"""Read-only official knowledge hints for the internal operator console (sandbox only)."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from app.config import AppSettings, get_settings
from app.corpus_planning.pgvector_sandbox_indexing import assert_sandbox_database_url
from app.embeddings import generate_embedding
from app.knowledge.domain_query_normalization import (
    build_domain_query_expansions,
    normalize_persian_support_query,
)
from app.knowledge.knowledge_models import KnowledgeDocumentType, KnowledgeSourceLane
from app.knowledge.knowledge_retrieval_tool import (
    ALLOWED_KNOWLEDGE_NAMESPACE,
    MAX_SNIPPET_CHARS,
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalResponse,
    execute_sandbox_knowledge_retrieval,
)
from app.operator_console.console_models import OperatorTicket
from app.rag.pgvector_store import PgVectorStore
from app.rag.vector_store import VectorStore

KnowledgeRetrievalFn = Callable[
    [KnowledgeRetrievalRequest, VectorStore, Callable[[str], list[float]]],
    KnowledgeRetrievalResponse,
]

_SAFE_QUERY_FIELD_NAMES = frozenset(
    {
        "original_vendor_issue_preview",
        "latest_vendor_message",
        "recent_context_preview",
        "ticket_label",
        "route_label",
    },
)

_FORBIDDEN_QUERY_INPUT_FIELDS = frozenset(
    {
        "ticket_text_preview",
        "open_ticket_preview",
        "room_id",
        "user_input",
        "messages",
        "conversation_transcript",
        "transcript",
        "draft_response",
        "final_response",
        "retrieved_context",
    },
)

_FORBIDDEN_MARKDOWN_TOKENS = (
    '"user_input"',
    '"messages"',
    '"conversation_transcript"',
    '"draft_response"',
    '"final_response"',
    "sk-",
    "begin private key",
    "postgresql://",
)

_OFFICIAL_DOCUMENT_TYPES = [
    document_type.value
    for document_type in KnowledgeDocumentType
    if document_type is not KnowledgeDocumentType.HISTORICAL_TICKET_MEMORY
]

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
_OPENAI_EMBED_PROVIDER = "openai"
_OPENAI_EMBED_MODEL = "text-embedding-3-small"
_HINTS_CANDIDATE_MULTIPLIER = 64
_FUND_ROUTE_BOOST = "تسویه حساب فروشنده شرایط تسویه واریز"


@dataclass(frozen=True)
class KnowledgeHint:
    """One safe official policy hint for operator review (snippet only)."""

    document_type: str
    section_title: str
    source_lane: str
    priority_rank: int
    snippet: str
    score: float


def _optional_line(label: str, value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return f"{label}: {text}"


def _is_fund_or_billing_ticket(ticket: OperatorTicket) -> bool:
    label = (ticket.ticket_label or "").strip().lower()
    route = (ticket.route_label or "").strip().lower()
    return label == "fund" or route == "billing_review"


def build_knowledge_hint_query(
    ticket: OperatorTicket,
    *,
    first_turn_only: bool = False,
) -> str:
    """Build a sandbox retrieval query from HITL-safe snapshot fields only."""
    parts: list[str] = []
    field_lines = (
        _optional_line("ticket_label", ticket.ticket_label),
        _optional_line("route_label", ticket.route_label),
        _optional_line("original_vendor_issue_preview", ticket.original_vendor_issue_preview),
    )
    if not first_turn_only:
        field_lines = (
            *field_lines,
            _optional_line("latest_vendor_message", ticket.latest_vendor_message),
            _optional_line("recent_context_preview", ticket.recent_context_preview),
        )
    for line in field_lines:
        if line:
            parts.append(line)
    base = "\n".join(parts).strip()
    if not base:
        return ""

    normalized = normalize_persian_support_query(base)
    query_parts = [normalized]
    expansions = build_domain_query_expansions(normalized)
    if expansions:
        query_parts.append(f"| intent: {' '.join(expansions)}")
    if _is_fund_or_billing_ticket(ticket):
        query_parts.append(f"| boost: {_FUND_ROUTE_BOOST}")
    return " ".join(query_parts).strip()


def sanitize_knowledge_hint(hit: KnowledgeRetrievalHit) -> KnowledgeHint:
    """Map a retrieval hit to a console-safe hint (official policy lane only)."""
    if hit.source_lane != KnowledgeSourceLane.OFFICIAL_POLICY.value:
        raise ValueError(f"hint must be official_policy (got {hit.source_lane!r})")
    snippet = hit.snippet.strip()
    if len(snippet) > MAX_SNIPPET_CHARS:
        snippet = snippet[: MAX_SNIPPET_CHARS - 1].rstrip() + "…"
    return KnowledgeHint(
        document_type=hit.document_type,
        section_title=hit.section_title,
        source_lane=hit.source_lane,
        priority_rank=hit.priority_rank,
        snippet=snippet,
        score=hit.score,
    )


def assert_knowledge_hints_markdown_safe(markdown: str) -> None:
    """Fail closed if hint rendering may leak forbidden fields."""
    lowered = markdown.lower()
    for token in _FORBIDDEN_MARKDOWN_TOKENS:
        if token in lowered:
            raise ValueError(f"knowledge hints preview must not contain forbidden token: {token}")


def render_knowledge_hints_markdown(hints: Sequence[KnowledgeHint]) -> str:
    """Render operator-console knowledge hints as Markdown (safe fields only)."""
    if not hints:
        body = "No policy hint found."
    else:
        lines: list[str] = []
        for index, hint in enumerate(hints, start=1):
            lines.extend(
                [
                    f"#### Hint {index}",
                    f"- **document_type:** {hint.document_type}",
                    f"- **section_title:** {hint.section_title}",
                    f"- **source_lane:** {hint.source_lane}",
                    f"- **snippet:** {hint.snippet}",
                    "",
                ],
            )
        body = "\n".join(lines).rstrip()
    markdown = "## Relevant official policy hints\n\n" + body + "\n"
    assert_knowledge_hints_markdown_safe(markdown)
    return markdown


def _openai_query_embedding_fn(text: str) -> list[float]:
    return list(
        generate_embedding(text, provider=_OPENAI_EMBED_PROVIDER, model=_OPENAI_EMBED_MODEL).vector,
    )


def _default_query_embedding_fn(settings: AppSettings) -> Callable[[str], list[float]]:
    index_version = settings.knowledge_retrieval_index_version.strip().lower()
    if (
        settings.embedding_provider.strip().lower() == _OPENAI_EMBED_PROVIDER
        or "openai" in index_version
    ):
        return _openai_query_embedding_fn
    from app.corpus_planning.embedding_dry_run import build_mock_embedding

    dims = settings.pgvector_dimensions

    def _mock_fn(text: str) -> list[float]:
        return build_mock_embedding(text, dims)

    return _mock_fn


def _default_vector_store(settings: AppSettings) -> PgVectorStore:
    env_url = os.environ.get("PGVECTOR_DATABASE_URL", "")
    database_url = (settings.pgvector_database_url or env_url).strip()
    if not database_url:
        database_url = _DEFAULT_DATABASE_URL
    assert_sandbox_database_url(database_url)
    return PgVectorStore(
        database_url,
        table_name=settings.pgvector_table,
        dimensions=settings.pgvector_dimensions,
    )


def _allowed_document_types_for_ticket(ticket: OperatorTicket) -> list[str]:
    """Prefer settlement policy chunks for fund / billing_review tickets."""
    if _is_fund_or_billing_ticket(ticket):
        return [
            KnowledgeDocumentType.SETTLEMENT_RULES.value,
            KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
            KnowledgeDocumentType.SUPPORT_FAQ.value,
        ]
    return _OFFICIAL_DOCUMENT_TYPES


def _build_retrieval_request(
    query: str,
    *,
    settings: AppSettings,
    ticket: OperatorTicket,
) -> KnowledgeRetrievalRequest:
    namespace = settings.knowledge_retrieval_namespace.strip()
    if namespace != ALLOWED_KNOWLEDGE_NAMESPACE:
        raise ValueError(
            f"knowledge_retrieval_namespace must be {ALLOWED_KNOWLEDGE_NAMESPACE!r}",
        )
    return KnowledgeRetrievalRequest(
        query=query,
        namespace=namespace,
        index_version=settings.knowledge_retrieval_index_version.strip(),
        top_k=settings.knowledge_hints_top_k,
        allowed_document_types=_allowed_document_types_for_ticket(ticket),
        prefer_official_policy=True,
    )


def fetch_knowledge_hints_for_ticket(
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
    store: VectorStore | None = None,
    query_embedding_fn: Callable[[str], list[float]] | None = None,
    retrieve_fn: KnowledgeRetrievalFn | None = None,
    first_turn_only: bool = False,
) -> tuple[KnowledgeHint, ...]:
    """Fetch read-only official policy hints when KNOWLEDGE_HINTS_ENABLED is true."""
    cfg = settings or get_settings()
    if not cfg.knowledge_hints_enabled:
        return ()

    query = build_knowledge_hint_query(ticket, first_turn_only=first_turn_only)
    if not query:
        return ()

    request = _build_retrieval_request(query, settings=cfg, ticket=ticket)
    _assert_request_query_uses_safe_fields_only(query)

    vector_store = store
    embed_fn = query_embedding_fn
    if vector_store is None or embed_fn is None:
        if vector_store is None:
            vector_store = _default_vector_store(cfg)
        if embed_fn is None:
            embed_fn = _default_query_embedding_fn(cfg)

    if retrieve_fn is not None:
        response = retrieve_fn(request, vector_store, embed_fn)
    else:
        response = execute_sandbox_knowledge_retrieval(
            request,
            vector_store,
            embed_fn,
            candidate_multiplier=_HINTS_CANDIDATE_MULTIPLIER,
        )
    hints: list[KnowledgeHint] = []
    for hit in response.hits:
        if hit.source_lane != KnowledgeSourceLane.OFFICIAL_POLICY.value:
            continue
        hints.append(sanitize_knowledge_hint(hit))
    return tuple(hints)


def _assert_request_query_uses_safe_fields_only(query: str) -> None:
    lowered = query.lower()
    for field_name in _FORBIDDEN_QUERY_INPUT_FIELDS:
        if field_name in lowered:
            raise ValueError(f"query must not reference forbidden field: {field_name}")
    for marker in ('"messages"', "conversation transcript", "user_input"):
        if marker in lowered:
            raise ValueError(f"query must not contain forbidden marker: {marker}")


def assert_query_built_from_safe_ticket_fields(
    ticket: OperatorTicket,
    query: str,
) -> None:
    """Test helper: ensure query text only reflects allowlisted snapshot fields."""
    unsafe_values = {
        key: value
        for key, value in (
            ("ticket_text_preview", ticket.ticket_text_preview),
            ("open_ticket_preview", ticket.open_ticket_preview),
            ("room_id", ticket.room_id),
        )
        if value and str(value).strip()
    }
    for field_name, value in unsafe_values.items():
        if str(value) in query:
            raise ValueError(f"query must not include unsafe field {field_name}")
    _assert_request_query_uses_safe_fields_only(query)


def ticket_safe_fields_for_query(ticket: OperatorTicket) -> Mapping[str, str | None]:
    """Expose allowlisted fields used for hint query construction."""
    return {field: getattr(ticket, field) for field in _SAFE_QUERY_FIELD_NAMES}

"""Shadow LangGraph node: sandbox retrieval chain metadata only (feature-flagged)."""

from __future__ import annotations

import os

from app.config import AppSettings, get_settings
from app.corpus_planning import sandbox_retrieval_chain_dry_run as _sandbox_chain
from app.embeddings import generate_embedding
from app.schemas.workflow import ToolError
from app.state.commerce_state import CommerceAIState
from app.state.retrieval_state import sanitize_retrieval_state_snapshot

from .common import _append_audit

_NODE_NAME = "sandbox_retrieve_pilot_shadow"
_PILOT_NAMESPACE = "vendor_ticket_real_pilot_balanced"
_PILOT_INDEX_VERSION = "pilot_balanced_v1"
_PROFILE = "semantic_pgvector"
_DEFAULT_TOP_K = 5
_MAX_QUERY_CHARS = 4000
_OPENAI_PROVIDER = "openai"
_OPENAI_MODEL = "text-embedding-3-small"


def _bounded_query_text(state: CommerceAIState) -> str:
    text = (state.get("user_input") or "").strip()
    if not text:
        text = (state.get("grounding_summary") or "").strip()
    if len(text) > _MAX_QUERY_CHARS:
        return text[:_MAX_QUERY_CHARS]
    return text


def _openai_query_embedding_fn(text: str) -> list[float]:
    embedding = generate_embedding(
        text,
        provider=_OPENAI_PROVIDER,
        model=_OPENAI_MODEL,
    )
    return embedding.vector


def _chain_config_from_state(
    state: CommerceAIState,
) -> _sandbox_chain.SandboxRetrievalChainDryRunConfig:
    return _sandbox_chain.SandboxRetrievalChainDryRunConfig(
        query=_bounded_query_text(state),
        ticket_label=state.get("ticket_label"),
        route_label=state.get("route_label"),
        review_priority=state.get("review_priority"),
        namespace=_PILOT_NAMESPACE,
        index_version=_PILOT_INDEX_VERSION,
        top_k=_DEFAULT_TOP_K,
        profile=_PROFILE,
        confirm_sandbox=True,
    )


def _database_url_from_settings(settings: AppSettings) -> str | None:
    url = settings.pgvector_database_url
    if url and url.strip():
        return url.strip()
    return os.environ.get("PGVECTOR_DATABASE_URL", "").strip() or None


def _apply_shadow_chain(state: CommerceAIState, settings: AppSettings) -> CommerceAIState:
    config = _chain_config_from_state(state)
    db_url = _database_url_from_settings(settings)
    result = _sandbox_chain.run_sandbox_retrieval_chain_on_state(
        state,
        config,
        database_url=db_url,
        table_name=settings.pgvector_table,
        dimensions=settings.pgvector_dimensions,
        query_embedding_fn=_openai_query_embedding_fn,
    )
    snapshot = sanitize_retrieval_state_snapshot(state)
    state["audit_log"] = _append_audit(
        state.get("audit_log") or [],
        node_name=_NODE_NAME,
        message="sandbox retrieval shadow chain completed",
        metadata={
            "executor_called": result.executor_called,
            "retrieval_snapshot": snapshot,
        },
    )
    return state


def sandbox_retrieve_pilot_shadow(state: CommerceAIState) -> CommerceAIState:
    """Run sandbox retrieval in shadow mode when LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true."""
    settings = get_settings()
    if not settings.langgraph_sandbox_retrieval_enabled:
        return state

    try:
        return _apply_shadow_chain(state, settings)
    except Exception as exc:  # noqa: BLE001 — fail closed; workflow continues
        reasons = list(state.get("retrieval_policy_reasons") or [])
        reasons.append(f"sandbox_retrieval_shadow_error: {exc!s}")
        state["retrieval_policy_reasons"] = reasons
        state["retrieval_sandbox_only"] = True
        state["retrieval_activated"] = False
        state["errors"] = [
            *(state.get("errors") or []),
            ToolError(
                tool_name=_NODE_NAME,
                error_type="sandbox_retrieval_shadow_failed",
                message="sandbox retrieval shadow failed; workflow continues",
            ),
        ]
        state["audit_log"] = _append_audit(
            state.get("audit_log") or [],
            node_name=_NODE_NAME,
            message="sandbox retrieval shadow failed",
            metadata={"error_type": type(exc).__name__},
        )
        return state

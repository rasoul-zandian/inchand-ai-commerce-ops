"""Export sanitized shadow replay JSONL from local ticket exports (offline; no raw content)."""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import AppSettings, get_settings
from app.corpus_planning.pgvector_sandbox_indexing import assert_sandbox_database_url
from app.corpus_planning.sandbox_retrieval_chain_dry_run import (
    SandboxRetrievalChainDryRunConfig,
    SandboxRetrievalChainDryRunResult,
    assert_safe_chain_output,
    run_sandbox_retrieval_chain_on_state,
)
from app.corpus_planning.shadow_replay_row_contract import (
    assert_shadow_replay_jsonl_line_safe,
    assert_shadow_replay_row_safe,
)
from app.corpus_planning.shadow_retrieval_metrics_dashboard import load_shadow_retrieval_rows
from app.nodes.vendor_ticket import build_review_queue_metadata
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState
from app.state.retrieval_state import default_retrieval_state_values
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)
from app.tickets.workflow_mapping import conversation_snapshot_to_workflow_input

_MAX_QUERY_CHARS = 4000
_DEFAULT_SANDBOX_DATABASE_URL = (
    "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
)

# Deterministic route labels for export (no vendor_ticket_node / LLM).
_EXPORT_ROUTE_BY_TICKET_LABEL: dict[str, str] = {
    "fund": "billing_review",
    "complaint": "escalation_review",
    "support": "general_vendor_support",
}


@dataclass(frozen=True)
class ShadowReplayExportConfig:
    """Operator inputs for shadow replay JSONL export."""

    namespace: str
    index_version: str
    profile: str
    top_k: int
    confirm_sandbox: bool


@dataclass
class LineError:
    line_number: int
    error_message: str


@dataclass
class ShadowReplayExportSummary:
    total_lines: int = 0
    empty_lines_ignored: int = 0
    valid_tickets: int = 0
    exported_rows: int = 0
    shadow_node_executed_count: int = 0
    invalid_lines: int = 0
    export_failures: int = 0
    label_counts: Counter[str] = field(default_factory=Counter)
    gate_decision_counts: Counter[str] = field(default_factory=Counter)
    parse_errors: list[LineError] = field(default_factory=list)
    export_errors: list[LineError] = field(default_factory=list)


def resolve_sandbox_export_database_url(
    settings: AppSettings,
    *,
    validate_sandbox: bool = True,
) -> str:
    """Resolve pgvector URL for shadow export (settings → env → local sandbox default)."""
    url = settings.pgvector_database_url
    if not url or not str(url).strip():
        url = os.environ.get("PGVECTOR_DATABASE_URL", "").strip() or None
    if not url:
        url = _DEFAULT_SANDBOX_DATABASE_URL
    resolved = str(url).strip()
    if validate_sandbox:
        assert_sandbox_database_url(resolved)
    return resolved


def configure_mock_workflow_runtime() -> None:
    """Force offline mock providers for routing-only graph steps (no OpenAI/Postgres)."""
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault("LLM_MODEL", "mock-vendor-ticket-drafter")
    os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
    os.environ.setdefault("EMBEDDING_MODEL", "mock-embedding-small")
    os.environ.setdefault("RAG_STRATEGY", "mock")
    os.environ.setdefault("RAG_PROFILE", "")
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("PGVECTOR_DATABASE_URL", _DEFAULT_SANDBOX_DATABASE_URL)
    get_settings.cache_clear()


def _bounded_query_text(state: CommerceAIState) -> str:
    text = (state.get("user_input") or "").strip()
    if not text:
        text = (state.get("grounding_summary") or "").strip()
    if len(text) > _MAX_QUERY_CHARS:
        return text[:_MAX_QUERY_CHARS]
    return text


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = str(err.get("msg", "validation error"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else "validation error"


def build_initial_state_from_snapshot(snapshot: ConversationTicketSnapshot) -> CommerceAIState:
    """Minimal CommerceAIState for routing + shadow chain (no vendor draft node)."""
    workflow_input = conversation_snapshot_to_workflow_input(snapshot)
    return {
        "request_id": f"shadow-export-{snapshot.room_id}",
        "session_id": None,
        "user_id": None,
        "user_role": None,
        "user_input": workflow_input["user_input"],
        "workflow_type": WorkflowType.UNKNOWN,
        "workflow_status": WorkflowStatus.STARTED,
        "entity_type": EntityType.UNKNOWN,
        "product_id": None,
        "vendor_id": None,
        "ticket_id": snapshot.room_id,
        "application_id": None,
        "room_id": workflow_input.get("room_id") or snapshot.room_id,
        "ticket_label": workflow_input.get("ticket_label"),
        "ticket_subtype": workflow_input.get("ticket_subtype"),
        "workflow_state_snapshot": dict(workflow_input.get("workflow_state_snapshot") or {}),
        "retrieved_context": {},
        "rag_sources": [],
        "tool_results": {},
        "specialist_output": {},
        "risk_score": None,
        "confidence_score": None,
        "detected_intent": None,
        "grounding_summary": None,
        "grounding_sources": [],
        "qa_passed": None,
        "qa_issues": [],
        "qa_warnings": [],
        "qa_summary": None,
        "qa_requires_human_attention": False,
        "route_label": None,
        "routing_reasons": [],
        "specialist_recommended_action": None,
        "review_category": None,
        "review_priority": None,
        "review_reason": None,
        "recommended_action": None,
        "human_approval_required": False,
        "approval_status": ApprovalStatus.NOT_REQUIRED,
        "final_response": None,
        "errors": [],
        "audit_log": [],
        **default_retrieval_state_values(),
    }


def resolve_shadow_export_route_label(ticket_label: str | None) -> str | None:
    """Map pilot ticket_label to operational route_label (deterministic; no LLM)."""
    if not ticket_label:
        return None
    norm = str(ticket_label).strip().lower()
    return _EXPORT_ROUTE_BY_TICKET_LABEL.get(norm)


def apply_shadow_export_route_label(state: CommerceAIState) -> CommerceAIState:
    """Promote route_label from ticket_label when not already set (export routing only)."""
    existing = state.get("route_label")
    if isinstance(existing, str) and existing.strip():
        return state
    route = resolve_shadow_export_route_label(state.get("ticket_label"))
    if route:
        state["route_label"] = route
    return state


def run_routing_pipeline(state: CommerceAIState) -> CommerceAIState:
    """Normalize + route only (no vendor draft, no retrieve_context consumption)."""
    from app.nodes.common import normalize_request, route_workflow

    state = normalize_request(state)
    state = route_workflow(state)
    return apply_shadow_export_route_label(state)


def _retrieval_fields_for_export_row(
    state: CommerceAIState,
    chain_result: SandboxRetrievalChainDryRunResult | None,
) -> dict[str, Any]:
    """Merge sanitized retrieval fields from chain snapshot and state."""
    snapshot: dict[str, Any] = dict(chain_result.snapshot) if chain_result is not None else {}
    executor_called = bool(chain_result.executor_called) if chain_result is not None else False

    def _pick(key: str) -> Any:
        if key in snapshot:
            return snapshot[key]
        return state.get(key)

    metadata_filter = _pick("retrieval_metadata_filter")
    if metadata_filter is None and chain_result is not None:
        gate_filter = chain_result.gate_result.required_metadata_filter
        if gate_filter is not None:
            metadata_filter = {
                k: v
                for k in ("ticket_label", "route_label")
                if (v := getattr(gate_filter, k, None)) is not None
            } or None

    return {
        "retrieval_gate_decision": _pick("retrieval_gate_decision"),
        "retrieval_scenario": _pick("retrieval_scenario"),
        "retrieval_policy_reasons": list(_pick("retrieval_policy_reasons") or []),
        "retrieval_query_hash": _pick("retrieval_query_hash"),
        "retrieval_result_count": _pick("retrieval_result_count"),
        "retrieval_metadata_filter": metadata_filter,
        "retrieval_sandbox_only": _pick("retrieval_sandbox_only")
        if _pick("retrieval_sandbox_only") is not None
        else True,
        "executor_called": executor_called,
    }


def _review_metadata_fields(
    state: CommerceAIState,
) -> tuple[str | None, str | None, list[str]]:
    errors: list[str] = []
    try:
        meta = build_review_queue_metadata(state)
    except Exception as exc:  # noqa: BLE001 — export must continue
        return None, None, [f"review_metadata_error: {exc}"]

    review_priority = meta.get("review_priority")
    priority = review_priority if isinstance(review_priority, str) else None
    department_route = meta.get("department_route") or {}
    assigned = department_route.get("assigned_department")
    assigned_department = assigned if isinstance(assigned, str) else None
    return priority, assigned_department, errors


def build_chain_config_from_state(
    state: CommerceAIState,
    export_config: ShadowReplayExportConfig,
) -> SandboxRetrievalChainDryRunConfig:
    """Build sandbox chain config for shadow export (ticket_label + route_label filter only).

    Omits review_priority from metadata_filter: export uses review-queue values
    (LOW/MEDIUM) that do not match pgvector index vocabulary (normal/high).
    """
    return SandboxRetrievalChainDryRunConfig(
        query=_bounded_query_text(state),
        ticket_label=state.get("ticket_label"),
        route_label=state.get("route_label"),
        review_priority=None,
        namespace=export_config.namespace,
        index_version=export_config.index_version,
        top_k=export_config.top_k,
        profile=export_config.profile,
        confirm_sandbox=export_config.confirm_sandbox,
    )


def build_shadow_replay_export_row(
    snapshot: ConversationTicketSnapshot,
    state: CommerceAIState,
    *,
    shadow_node_executed: bool,
    chain_result: SandboxRetrievalChainDryRunResult | None = None,
    export_errors: list[str] | None = None,
) -> dict[str, Any]:
    """One sanitized JSON object per ticket for Step 136 dashboard input."""
    row_errors = list(export_errors or [])
    priority, assigned_department, meta_errors = _review_metadata_fields(state)
    row_errors.extend(meta_errors)
    retrieval_fields = _retrieval_fields_for_export_row(state, chain_result)

    route_label = state.get("route_label")
    if not (isinstance(route_label, str) and route_label.strip()):
        route_label = resolve_shadow_export_route_label(snapshot.ticket_label)

    row: dict[str, Any] = {
        "room_id": snapshot.room_id,
        "ticket_label": snapshot.ticket_label,
        "route_label": route_label,
        "review_priority": priority,
        "assigned_department": assigned_department,
        "shadow_node_executed": shadow_node_executed,
        **retrieval_fields,
        "retrieval_activated": False,
        "downstream_consumed_retrieval": False,
        "errors": row_errors,
    }
    assert_shadow_replay_row_safe(row)
    return row


def _default_chain_runner(
    state: CommerceAIState,
    chain_config: SandboxRetrievalChainDryRunConfig,
    settings: AppSettings,
) -> SandboxRetrievalChainDryRunResult:
    from app.embeddings import generate_embedding

    db_url = resolve_sandbox_export_database_url(
        settings,
        validate_sandbox=chain_config.confirm_sandbox,
    )

    def _openai_query_embedding_fn(text: str) -> list[float]:
        embedding = generate_embedding(
            text,
            provider="openai",
            model="text-embedding-3-small",
        )
        return embedding.vector

    return run_sandbox_retrieval_chain_on_state(
        state,
        chain_config,
        database_url=db_url,
        table_name=settings.pgvector_table,
        dimensions=settings.pgvector_dimensions,
        query_embedding_fn=_openai_query_embedding_fn,
    )


def export_shadow_replay_row_for_snapshot(
    snapshot: ConversationTicketSnapshot,
    export_config: ShadowReplayExportConfig,
    *,
    settings: AppSettings | None = None,
    run_chain: Callable[
        [CommerceAIState, SandboxRetrievalChainDryRunConfig, AppSettings],
        SandboxRetrievalChainDryRunResult,
    ]
    | None = None,
) -> dict[str, Any]:
    """Route ticket and optionally run sandbox shadow chain; return sanitized export row."""
    settings = settings or get_settings()
    row_errors: list[str] = []
    state = build_initial_state_from_snapshot(snapshot)
    try:
        state = run_routing_pipeline(state)
    except Exception as exc:  # noqa: BLE001
        row_errors.append(f"routing_error: {exc}")

    shadow_executed = False
    chain_result: SandboxRetrievalChainDryRunResult | None = None
    if settings.langgraph_sandbox_retrieval_enabled:
        chain_config = build_chain_config_from_state(state, export_config)
        runner = run_chain or _default_chain_runner
        try:
            chain_result = runner(state, chain_config, settings)
            shadow_executed = True
            for key, value in chain_result.snapshot.items():
                state[key] = value
        except Exception as exc:  # noqa: BLE001
            row_errors.append(f"shadow_chain_error: {exc}")
            shadow_executed = True
    else:
        row_errors.append(
            "shadow_chain_skipped: LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false",
        )

    return build_shadow_replay_export_row(
        snapshot,
        state,
        shadow_node_executed=shadow_executed,
        chain_result=chain_result,
        export_errors=row_errors,
    )


def export_shadow_replay_jsonl_content(
    lines: list[str],
    export_config: ShadowReplayExportConfig,
    *,
    settings: AppSettings | None = None,
    run_chain: Callable[
        [CommerceAIState, SandboxRetrievalChainDryRunConfig, AppSettings],
        SandboxRetrievalChainDryRunResult,
    ]
    | None = None,
) -> tuple[list[dict[str, Any]], ShadowReplayExportSummary]:
    """Process ticket export JSONL lines into sanitized shadow replay rows."""
    if not export_config.confirm_sandbox:
        raise ValueError("confirm_sandbox must be true for shadow replay export")

    settings = settings or get_settings()
    summary = ShadowReplayExportSummary()
    rows: list[dict[str, Any]] = []
    physical_line = 0

    for raw_line in lines:
        physical_line += 1
        if not raw_line.strip():
            summary.empty_lines_ignored += 1
            continue

        summary.total_lines += 1
        try:
            snapshot = parse_conversation_ticket_snapshot(raw_line)
        except json.JSONDecodeError as exc:
            summary.invalid_lines += 1
            summary.parse_errors.append(
                LineError(
                    line_number=physical_line,
                    error_message=f"JSON decode error at column {exc.colno}: {exc.msg}",
                )
            )
            continue
        except ValidationError as exc:
            summary.invalid_lines += 1
            summary.parse_errors.append(
                LineError(
                    line_number=physical_line,
                    error_message=_format_validation_error(exc),
                )
            )
            continue
        except ValueError as exc:
            summary.invalid_lines += 1
            summary.parse_errors.append(
                LineError(line_number=physical_line, error_message=str(exc))
            )
            continue

        summary.valid_tickets += 1
        summary.label_counts[snapshot.ticket_label] += 1

        try:
            row = export_shadow_replay_row_for_snapshot(
                snapshot,
                export_config,
                settings=settings,
                run_chain=run_chain,
            )
        except ValueError as exc:
            summary.export_failures += 1
            summary.export_errors.append(
                LineError(line_number=physical_line, error_message=str(exc))
            )
            continue
        except Exception as exc:  # noqa: BLE001
            summary.export_failures += 1
            summary.export_errors.append(
                LineError(line_number=physical_line, error_message=str(exc))
            )
            continue

        rows.append(row)
        summary.exported_rows += 1
        if row.get("shadow_node_executed"):
            summary.shadow_node_executed_count += 1
        gate = row.get("retrieval_gate_decision")
        if isinstance(gate, str) and gate:
            summary.gate_decision_counts[gate] += 1

    return rows, summary


def write_shadow_replay_jsonl(
    rows: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write rows with per-line safety checks (fail closed on unsafe serialization)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            assert_shadow_replay_row_safe(row)
            line = json.dumps(row, ensure_ascii=False) + "\n"
            assert_shadow_replay_jsonl_line_safe(line)
            assert_safe_chain_output(line)
            handle.write(line)


def export_shadow_replay_jsonl_file(
    export_path: Path,
    output_path: Path,
    export_config: ShadowReplayExportConfig,
    *,
    settings: AppSettings | None = None,
    run_chain: Callable[
        [CommerceAIState, SandboxRetrievalChainDryRunConfig, AppSettings],
        SandboxRetrievalChainDryRunResult,
    ]
    | None = None,
) -> ShadowReplayExportSummary:
    """Read ticket JSONL, export shadow replay JSONL, validate output is dashboard-safe."""
    lines = export_path.read_text(encoding="utf-8").splitlines()
    rows, summary = export_shadow_replay_jsonl_content(
        lines,
        export_config,
        settings=settings,
        run_chain=run_chain,
    )
    write_shadow_replay_jsonl(rows, output_path)
    load_shadow_retrieval_rows(output_path)
    return summary


def format_export_summary(
    summary: ShadowReplayExportSummary,
    *,
    export_path: str | None = None,
    output_path: str | None = None,
) -> str:
    lines: list[str] = ["shadow_replay_jsonl_export: complete"]
    if export_path:
        lines.append(f"  input={export_path}")
    if output_path:
        lines.append(f"  output={output_path}")
    lines.extend(
        [
            f"  total_lines={summary.total_lines}",
            f"  valid_tickets={summary.valid_tickets}",
            f"  exported_rows={summary.exported_rows}",
            f"  shadow_node_executed_count={summary.shadow_node_executed_count}",
            f"  invalid_lines={summary.invalid_lines}",
            f"  export_failures={summary.export_failures}",
        ]
    )
    if summary.gate_decision_counts:
        lines.append("  gate_decision_counts:")
        for decision, count in sorted(summary.gate_decision_counts.items()):
            lines.append(f"    {decision}={count}")
    if summary.parse_errors:
        lines.append("  parse_errors:")
        for err in summary.parse_errors:
            lines.append(f"    line {err.line_number}: {err.error_message}")
    if summary.export_errors:
        lines.append("  export_errors:")
        for err in summary.export_errors:
            lines.append(f"    line {err.line_number}: {err.error_message}")
    return "\n".join(lines)

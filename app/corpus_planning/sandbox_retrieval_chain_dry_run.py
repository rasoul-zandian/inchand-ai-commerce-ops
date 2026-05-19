"""Dry-run sandbox retrieval chain: policy gate → executor → state snapshot (no LangGraph)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.corpus_planning.pgvector_sandbox_indexing import assert_sandbox_database_url
from app.corpus_planning.pilot_retrieval_eval import build_pilot_pgvector_store
from app.corpus_planning.retrieval_policy_gate import (
    RetrievalGateDecision,
    RetrievalPolicyGateInput,
    RetrievalPolicyGateResult,
    evaluate_retrieval_policy_gate,
)
from app.corpus_planning.retrieval_tool_models import (
    RetrievalToolRequest,
    RetrievalToolResponse,
)
from app.corpus_planning.retrieval_tool_validation import validate_allowed_metadata_filter
from app.corpus_planning.sandbox_retrieval_tool import (
    QueryEmbeddingFn,
    execute_sandbox_retrieval_tool,
)
from app.rag.vector_store import VectorStore
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState
from app.state.retrieval_state import (
    apply_retrieval_gate_result_to_state,
    apply_retrieval_tool_response_to_state,
    sanitize_retrieval_state_snapshot,
)

_FORBIDDEN_OUTPUT_TOKENS = (
    "conversation_transcript",
    "OPENAI_API_KEY",
    "sk-",
    "BEGIN PRIVATE KEY",
)

ExecuteToolFn = Callable[..., RetrievalToolResponse]


@dataclass(frozen=True)
class SandboxRetrievalChainDryRunConfig:
    """Operator inputs for the sandbox retrieval dry-run chain."""

    query: str
    namespace: str
    index_version: str
    top_k: int
    profile: str
    confirm_sandbox: bool
    ticket_label: str | None = None
    route_label: str | None = None
    review_priority: str | None = None
    sandbox_only: bool = True


@dataclass(frozen=True)
class SandboxRetrievalChainDryRunResult:
    """Outcome of a dry-run chain (safe snapshot only; no hit bodies)."""

    exit_code: int
    snapshot: dict[str, Any]
    gate_result: RetrievalPolicyGateResult
    executor_called: bool


def assert_safe_chain_output(text: str) -> None:
    """Reject serialized output that may leak secrets or raw query-adjacent payloads."""
    lowered = text.lower()
    for token in _FORBIDDEN_OUTPUT_TOKENS:
        if token.lower() in lowered:
            raise RuntimeError(f"unsafe dry-run output token detected: {token}")


def build_metadata_filter_from_config(
    config: SandboxRetrievalChainDryRunConfig,
) -> object | None:
    raw: dict[str, str] = {}
    if config.ticket_label:
        raw["ticket_label"] = config.ticket_label
    if config.route_label:
        raw["route_label"] = config.route_label
    if config.review_priority:
        raw["review_priority"] = config.review_priority
    if not raw:
        return None
    return validate_allowed_metadata_filter(raw)


def build_gate_input_from_config(
    config: SandboxRetrievalChainDryRunConfig,
) -> RetrievalPolicyGateInput:
    return RetrievalPolicyGateInput(
        ticket_label=config.ticket_label,
        route_label=config.route_label,
        namespace=config.namespace,
        index_version=config.index_version,
        requested_top_k=config.top_k,
        metadata_filter=build_metadata_filter_from_config(config),
        sandbox_only=config.sandbox_only,
    )


def minimal_dry_run_commerce_state() -> CommerceAIState:
    """Minimal CommerceAIState for dry-run snapshot helpers (not a full graph run)."""
    return {
        "request_id": "dry-run-sandbox-retrieval-chain",
        "session_id": None,
        "user_id": None,
        "user_role": None,
        "user_input": "",
        "workflow_type": WorkflowType.UNKNOWN,
        "workflow_status": WorkflowStatus.STARTED,
        "entity_type": EntityType.UNKNOWN,
        "product_id": None,
        "vendor_id": None,
        "ticket_id": None,
        "application_id": None,
        "room_id": None,
        "ticket_label": None,
        "ticket_subtype": None,
        "workflow_state_snapshot": {},
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
    }


def build_tool_request_from_gate(
    config: SandboxRetrievalChainDryRunConfig,
    gate_result: RetrievalPolicyGateResult,
) -> RetrievalToolRequest:
    if gate_result.required_metadata_filter is None:
        raise ValueError("allow gate result must include required_metadata_filter")
    return RetrievalToolRequest(
        query=config.query,
        top_k=config.top_k,
        namespace=config.namespace,
        index_version=config.index_version,
        metadata_filter=gate_result.required_metadata_filter,
        eval_mode="metadata_filtered",
    )


def run_sandbox_retrieval_chain_on_state(
    state: CommerceAIState,
    config: SandboxRetrievalChainDryRunConfig,
    *,
    database_url: str | None = None,
    table_name: str = "rag_vector_records",
    dimensions: int = 1536,
    store_factory: Callable[[str], VectorStore] | None = None,
    query_embedding_fn: QueryEmbeddingFn | None = None,
    execute_tool: ExecuteToolFn | None = None,
) -> SandboxRetrievalChainDryRunResult:
    """Run gate → optional executor on an existing state (injected deps for tests)."""
    if not config.confirm_sandbox:
        raise ValueError("confirm_sandbox must be true for sandbox retrieval chain")

    gate_input = build_gate_input_from_config(config)
    gate_result = evaluate_retrieval_policy_gate(gate_input)
    apply_retrieval_gate_result_to_state(state, gate_result)

    executor_called = False
    if gate_result.decision == RetrievalGateDecision.ALLOW:
        tool_fn = execute_tool or execute_sandbox_retrieval_tool
        if query_embedding_fn is None:
            raise ValueError("query_embedding_fn is required when executor runs")

        db_url = (database_url or "").strip()
        if tool_fn is execute_sandbox_retrieval_tool:
            if not db_url:
                raise ValueError("database_url is required when executor runs")
            assert_sandbox_database_url(db_url)

            def _default_store_factory(url: str) -> VectorStore:
                return build_pilot_pgvector_store(
                    url,
                    namespace=config.namespace,
                    index_version=config.index_version,
                    table_name=table_name,
                    dimensions=dimensions,
                )

            factory = store_factory or _default_store_factory
            store = factory(db_url)
        else:
            if store_factory is None:
                raise ValueError("store_factory is required when execute_tool is injected")
            if not db_url:
                db_url = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
            store = store_factory(db_url)

        request = build_tool_request_from_gate(config, gate_result)
        response = tool_fn(
            request,
            store,
            query_embedding_fn,
            profile=config.profile,
        )
        apply_retrieval_tool_response_to_state(state, response)
        executor_called = True

    snapshot = sanitize_retrieval_state_snapshot(state)
    exit_code = 2 if gate_result.decision == RetrievalGateDecision.DENY else 0
    return SandboxRetrievalChainDryRunResult(
        exit_code=exit_code,
        snapshot=snapshot,
        gate_result=gate_result,
        executor_called=executor_called,
    )


def run_sandbox_retrieval_chain_dry_run(
    config: SandboxRetrievalChainDryRunConfig,
    *,
    database_url: str | None = None,
    table_name: str = "rag_vector_records",
    dimensions: int = 1536,
    store_factory: Callable[[str], VectorStore] | None = None,
    query_embedding_fn: QueryEmbeddingFn | None = None,
    execute_tool: ExecuteToolFn | None = None,
) -> SandboxRetrievalChainDryRunResult:
    """Run gate → optional executor → state snapshot on a minimal dry-run state."""
    state = minimal_dry_run_commerce_state()
    return run_sandbox_retrieval_chain_on_state(
        state,
        config,
        database_url=database_url,
        table_name=table_name,
        dimensions=dimensions,
        store_factory=store_factory,
        query_embedding_fn=query_embedding_fn,
        execute_tool=execute_tool,
    )


def format_snapshot_json(snapshot: dict[str, Any]) -> str:
    serialized = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    assert_safe_chain_output(serialized)
    return serialized


def format_snapshot_summary(result: SandboxRetrievalChainDryRunResult) -> str:
    snap = result.snapshot
    lines = [
        "dry_run_sandbox_retrieval_chain: complete",
        f"  retrieval_gate_decision={snap.get('retrieval_gate_decision')}",
        f"  retrieval_scenario={snap.get('retrieval_scenario')}",
        f"  retrieval_policy_reasons={snap.get('retrieval_policy_reasons', [])}",
        f"  retrieval_query_hash={snap.get('retrieval_query_hash')}",
        f"  retrieval_result_count={snap.get('retrieval_result_count')}",
        f"  retrieval_metadata_filter={snap.get('retrieval_metadata_filter')}",
        f"  retrieval_sandbox_only={snap.get('retrieval_sandbox_only')}",
        f"  retrieval_activated={snap.get('retrieval_activated')}",
        f"  executor_called={result.executor_called}",
    ]
    text = "\n".join(lines) + "\n"
    assert_safe_chain_output(text)
    return text

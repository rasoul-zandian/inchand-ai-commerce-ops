"""Helpers for additive sandbox retrieval fields on CommerceAIState (no execution)."""

from __future__ import annotations

from typing import Any

from app.corpus_planning.retrieval_policy_gate import RetrievalPolicyGateResult
from app.corpus_planning.retrieval_tool_models import (
    RetrievalToolMetadataFilter,
    RetrievalToolResponse,
)
from app.state.commerce_state import CommerceAIState

RETRIEVAL_STATE_DEFAULTS: dict[str, Any] = {
    "retrieval_sandbox_only": True,
    "retrieval_activated": False,
    "retrieval_policy_reasons": [],
}

_RETRIEVAL_STATE_KEYS = frozenset(
    {
        "retrieval_gate_decision",
        "retrieval_scenario",
        "retrieval_policy_reasons",
        "retrieval_query_hash",
        "retrieval_result_count",
        "retrieval_metadata_filter",
        "retrieval_sandbox_only",
        "retrieval_activated",
    }
)

_ALLOWED_METADATA_FILTER_KEYS = frozenset(
    {"ticket_label", "route_label", "review_priority"},
)

_FORBIDDEN_SNAPSHOT_KEYS = frozenset(
    {
        "query",
        "content",
        "transcript",
        "conversation_transcript",
        "raw_text",
        "vector",
        "vectors",
        "embedding",
        "embeddings",
        "messages",
        "results",
        "retrieved_context",
        "draft_response",
        "final_response",
    }
)


def default_retrieval_state_values() -> dict[str, Any]:
    """Safe defaults for additive retrieval fields (does not mutate workflow state)."""
    return {
        "retrieval_gate_decision": None,
        "retrieval_scenario": None,
        "retrieval_policy_reasons": [],
        "retrieval_query_hash": None,
        "retrieval_result_count": None,
        "retrieval_metadata_filter": None,
        **RETRIEVAL_STATE_DEFAULTS,
    }


def _assert_retrieval_not_activated(flag: bool, *, source: str) -> None:
    if flag:
        raise ValueError(f"{source}: retrieval_activated must be false")


def _metadata_filter_to_dict(
    metadata_filter: RetrievalToolMetadataFilter | None,
) -> dict[str, str] | None:
    if metadata_filter is None:
        return None
    payload: dict[str, str] = {}
    for key in _ALLOWED_METADATA_FILTER_KEYS:
        value = getattr(metadata_filter, key, None)
        if value is not None:
            text = str(value).strip()
            if text:
                payload[key] = text
    return payload or None


def _reject_forbidden_keys(payload: dict[str, Any], *, label: str) -> None:
    forbidden = {str(key).lower() for key in payload.keys()}.intersection(_FORBIDDEN_SNAPSHOT_KEYS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(f"{label} contains forbidden keys: {joined}")


def apply_retrieval_gate_result_to_state(
    state: CommerceAIState,
    gate_result: RetrievalPolicyGateResult,
) -> CommerceAIState:
    """Write policy gate outcome into state (aggregate-safe; no retrieval execution)."""
    _assert_retrieval_not_activated(gate_result.retrieval_activated, source="gate_result")
    state["retrieval_gate_decision"] = gate_result.decision.value
    state["retrieval_scenario"] = gate_result.scenario.value
    state["retrieval_policy_reasons"] = list(gate_result.reasons)
    metadata = _metadata_filter_to_dict(gate_result.required_metadata_filter)
    state["retrieval_metadata_filter"] = metadata
    if metadata is not None:
        _reject_forbidden_keys(metadata, label="retrieval_metadata_filter")
    state["retrieval_sandbox_only"] = True
    state["retrieval_activated"] = False
    return state


def apply_retrieval_tool_response_to_state(
    state: CommerceAIState,
    response: RetrievalToolResponse,
) -> CommerceAIState:
    """Write aggregate-safe tool response fields into state (no hits, content, or vectors)."""
    _assert_retrieval_not_activated(response.retrieval_activated, source="tool_response")
    if not response.sandbox_only:
        raise ValueError("tool_response: sandbox_only must be true")
    state["retrieval_query_hash"] = response.query_hash
    state["retrieval_result_count"] = response.result_count
    state["retrieval_sandbox_only"] = True
    state["retrieval_activated"] = False
    return state


def sanitize_retrieval_state_snapshot(state: CommerceAIState) -> dict[str, Any]:
    """Build an audit-safe retrieval slice from state (no raw query, content, or vectors)."""
    snapshot: dict[str, Any] = {}
    for key in _RETRIEVAL_STATE_KEYS:
        if key not in state:
            continue
        value = state[key]
        if key == "retrieval_metadata_filter" and value is not None:
            if not isinstance(value, dict):
                raise ValueError("retrieval_metadata_filter must be a dict")
            filter_dict = {str(k): str(v) for k, v in value.items() if v is not None}
            unknown = set(filter_dict.keys()) - _ALLOWED_METADATA_FILTER_KEYS
            if unknown:
                joined = ", ".join(sorted(unknown))
                raise ValueError(f"retrieval_metadata_filter has unsupported keys: {joined}")
            _reject_forbidden_keys(filter_dict, label="retrieval_metadata_filter")
            snapshot[key] = filter_dict
            continue
        if key == "retrieval_policy_reasons":
            reasons = value if isinstance(value, list) else []
            snapshot[key] = [str(item) for item in reasons]
            continue
        snapshot[key] = value

    _reject_forbidden_keys(snapshot, label="retrieval_state_snapshot")
    activated = snapshot.get("retrieval_activated", False)
    _assert_retrieval_not_activated(bool(activated), source="state")
    snapshot["retrieval_activated"] = False
    snapshot["retrieval_sandbox_only"] = snapshot.get("retrieval_sandbox_only", True)
    return snapshot

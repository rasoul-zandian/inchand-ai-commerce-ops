"""Sanitized shadow replay JSONL row contract (export + dashboard)."""

from __future__ import annotations

from typing import Any

FORBIDDEN_SHADOW_REPLAY_KEYS = frozenset(
    {
        "query",
        "user_input",
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
        "rag_sources",
        "specialist_output",
        "tool_results",
        "audit_log",
    }
)

FORBIDDEN_SHADOW_REPLAY_SUBSTRINGS = (
    "sk-",
    "BEGIN PRIVATE KEY",
    "OPENAI_API_KEY",
)

ALLOWED_SHADOW_REPLAY_TOP_LEVEL_KEYS = frozenset(
    {
        "room_id",
        "request_id",
        "ticket_id",
        "shadow_node_executed",
        "retrieval_gate_decision",
        "retrieval_scenario",
        "retrieval_policy_reasons",
        "retrieval_query_hash",
        "retrieval_result_count",
        "retrieval_metadata_filter",
        "retrieval_sandbox_only",
        "retrieval_activated",
        "downstream_consumed_retrieval",
        "ticket_label",
        "route_label",
        "review_priority",
        "assigned_department",
        "retrieval_error",
        "executor_called",
        "errors",
    }
)


def _collect_json_keys(value: Any, keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).lower())
            _collect_json_keys(child, keys)
    elif isinstance(value, list):
        for item in value:
            _collect_json_keys(item, keys)


def assert_shadow_replay_row_safe(row: dict[str, Any], *, line_number: int | None = None) -> None:
    """Fail closed if a shadow replay row may leak raw content or unsafe flags."""
    prefix = f"line {line_number}: " if line_number is not None else ""

    keys: set[str] = set()
    _collect_json_keys(row, keys)
    forbidden = keys.intersection(FORBIDDEN_SHADOW_REPLAY_KEYS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(f"{prefix}forbidden keys in shadow replay row: {joined}")

    unknown = keys - FORBIDDEN_SHADOW_REPLAY_KEYS - ALLOWED_SHADOW_REPLAY_TOP_LEVEL_KEYS
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"{prefix}unsupported keys in shadow replay row: {joined}")

    if row.get("retrieval_activated") is True:
        raise ValueError(f"{prefix}retrieval_activated must be false")

    if row.get("downstream_consumed_retrieval") is True:
        raise ValueError(f"{prefix}downstream_consumed_retrieval must be false")


def assert_shadow_replay_jsonl_line_safe(line: str) -> None:
    """Reject serialized JSONL that may embed secrets or forbidden field names."""
    lowered = line.lower()
    for key in FORBIDDEN_SHADOW_REPLAY_KEYS:
        if f'"{key}"' in lowered:
            raise ValueError(f"shadow replay JSONL must not reference forbidden key: {key}")
    for token in FORBIDDEN_SHADOW_REPLAY_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"shadow replay JSONL must not contain forbidden token: {token}")

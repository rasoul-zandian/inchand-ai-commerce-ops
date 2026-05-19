"""Sanitized AI assist shadow replay JSONL row contract (export + dashboard)."""

from __future__ import annotations

from typing import Any

FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_KEYS = frozenset(
    {
        "query",
        "user_input",
        "messages",
        "content",
        "raw_text",
        "transcript",
        "conversation_transcript",
        "vector",
        "vectors",
        "embedding",
        "embeddings",
        "results",
        "retrieved_context",
        "draft_response",
        "final_response",
        "rag_sources",
        "specialist_output",
        "tool_results",
        "audit_log",
        "suggestions",
    }
)

FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_SUBSTRINGS = (
    "sk-",
    "BEGIN PRIVATE KEY",
    "OPENAI_API_KEY",
)

ALLOWED_AI_ASSIST_SHADOW_REPLAY_TOP_LEVEL_KEYS = frozenset(
    {
        "room_id",
        "ticket_label",
        "route_label",
        "review_priority",
        "assigned_department",
        "ai_assist_shadow_generated",
        "ai_assist_suggested_priority",
        "ai_assist_escalation_recommended",
        "ai_assist_duplicate_possible",
        "ai_assist_suggested_action",
        "ai_assist_confidence_band",
        "ai_assist_human_review_required",
        "ai_assist_shadow_only",
        "retrieval_activated",
        "downstream_consumed_retrieval",
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


def assert_ai_assist_shadow_replay_row_safe(
    row: dict[str, Any],
    *,
    line_number: int | None = None,
) -> None:
    """Fail closed if an AI assist shadow replay row may leak raw content or unsafe flags."""
    prefix = f"line {line_number}: " if line_number is not None else ""

    keys: set[str] = set()
    _collect_json_keys(row, keys)
    forbidden = keys.intersection(FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_KEYS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(f"{prefix}forbidden keys in AI assist shadow replay row: {joined}")

    unknown = (
        keys
        - FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_KEYS
        - ALLOWED_AI_ASSIST_SHADOW_REPLAY_TOP_LEVEL_KEYS
    )
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"{prefix}unsupported keys in AI assist shadow replay row: {joined}")

    if row.get("retrieval_activated") is True:
        raise ValueError(f"{prefix}retrieval_activated must be false")

    if row.get("downstream_consumed_retrieval") is True:
        raise ValueError(f"{prefix}downstream_consumed_retrieval must be false")

    if row.get("ai_assist_shadow_only") is False:
        raise ValueError(f"{prefix}ai_assist_shadow_only must not be false")


def assert_ai_assist_shadow_replay_jsonl_line_safe(line: str) -> None:
    """Reject serialized JSONL that may embed secrets or forbidden field names."""
    lowered = line.lower()
    for key in FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_KEYS:
        if f'"{key}"' in lowered:
            msg = f"AI assist shadow replay JSONL must not reference forbidden key: {key}"
            raise ValueError(msg)
    for token in FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(
                f"AI assist shadow replay JSONL must not contain forbidden token: {token}",
            )

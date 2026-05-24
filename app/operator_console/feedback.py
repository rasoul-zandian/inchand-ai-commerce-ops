"""Append-only local JSONL persistence for operator console feedback (no DB, no APIs)."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_OPERATOR_FEEDBACK_PATH = Path("reports/operator_feedback.jsonl")
INTERNAL_NOTE_MAX_CHARS = 500

ALLOWED_FEEDBACK_TYPES = frozenset(
    {
        "helpful",
        "noisy",
        "wrong_action",
        "wrong_priority",
        "needs_human_followup",
    },
)

_ALLOWED_RECORD_KEYS = frozenset(
    {
        "feedback_id",
        "room_id",
        "timestamp",
        "reviewer_id",
        "suggested_action",
        "ticket_label",
        "route_label",
        "feedback_type",
        "internal_note",
        "source",
        "persisted_to",
    },
)

_FORBIDDEN_NOTE_SUBSTRINGS = (
    "conversation transcript",
    '"messages"',
    "draft_response",
    "final_response",
    "retrieved_context",
    "user_input",
    "tool_results",
    "vector",
    "embedding",
)


def _utc_iso_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def _truncate_note(text: str, *, max_chars: int = INTERNAL_NOTE_MAX_CHARS) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def assert_internal_note_safe(note: str) -> None:
    """Reject notes that may embed transcript or forbidden payload patterns."""
    lowered = note.lower()
    for token in _FORBIDDEN_NOTE_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"internal_note must not contain forbidden pattern: {token}")


def build_operator_feedback_record(
    *,
    room_id: str,
    suggested_action: str | None,
    ticket_label: str | None,
    route_label: str | None,
    feedback_type: str,
    internal_note: str | None = None,
    reviewer_id: str | None = None,
) -> dict[str, Any]:
    """Build a single feedback record (aggregate fields only; no ticket body)."""
    if not room_id or not str(room_id).strip():
        raise ValueError("room_id is required")
    normalized_type = feedback_type.strip().lower()
    if normalized_type not in ALLOWED_FEEDBACK_TYPES:
        allowed = ", ".join(sorted(ALLOWED_FEEDBACK_TYPES))
        raise ValueError(f"feedback_type must be one of: {allowed}")

    note: str | None = None
    if internal_note is not None and str(internal_note).strip():
        note = _truncate_note(str(internal_note).strip())
        assert_internal_note_safe(note)

    suggested = (
        suggested_action.strip()
        if isinstance(suggested_action, str) and suggested_action.strip()
        else None
    )
    tlabel = (
        ticket_label.strip() if isinstance(ticket_label, str) and ticket_label.strip() else None
    )
    rlabel = route_label.strip() if isinstance(route_label, str) and route_label.strip() else None

    record: dict[str, Any] = {
        "feedback_id": str(uuid.uuid4()),
        "room_id": str(room_id).strip(),
        "timestamp": _utc_iso_timestamp(),
        "reviewer_id": (reviewer_id or "local_operator").strip() or "local_operator",
        "suggested_action": suggested,
        "ticket_label": tlabel,
        "route_label": rlabel,
        "feedback_type": normalized_type,
        "internal_note": note,
        "source": "operator_console",
        "persisted_to": "local_jsonl",
    }
    extra = set(record.keys()) - _ALLOWED_RECORD_KEYS
    if extra:
        raise ValueError(f"unexpected keys in feedback record: {extra}")
    return record


def append_operator_feedback(
    record: Mapping[str, Any],
    *,
    path: Path | str = DEFAULT_OPERATOR_FEEDBACK_PATH,
) -> Path:
    """Append one JSON line to local feedback log (create parent dirs if needed)."""
    keys = set(record.keys())
    if keys != _ALLOWED_RECORD_KEYS:
        missing = _ALLOWED_RECORD_KEYS - keys
        extra = keys - _ALLOWED_RECORD_KEYS
        msg_parts = []
        if missing:
            msg_parts.append(f"missing keys: {sorted(missing)}")
        if extra:
            msg_parts.append(f"extra keys: {sorted(extra)}")
        raise ValueError("feedback record keys must match contract: " + "; ".join(msg_parts))

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(record), ensure_ascii=False) + "\n"
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return file_path


@dataclass(frozen=True)
class OperatorFeedbackSummary:
    """Lightweight counts for sidebar display."""

    total_count: int
    helpful_count: int
    noisy_wrong_count: int
    by_type: dict[str, int]


def load_operator_feedback_summary(
    path: Path | str = DEFAULT_OPERATOR_FEEDBACK_PATH,
) -> OperatorFeedbackSummary:
    """Load append-only JSONL and aggregate feedback counts."""
    file_path = Path(path)
    if not file_path.is_file():
        return OperatorFeedbackSummary(
            total_count=0,
            helpful_count=0,
            noisy_wrong_count=0,
            by_type={},
        )

    types: Counter[str] = Counter()
    total = 0
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        fb_type = row.get("feedback_type")
        if not isinstance(fb_type, str):
            continue
        fb_type = fb_type.strip().lower()
        if fb_type not in ALLOWED_FEEDBACK_TYPES:
            continue
        types[fb_type] += 1
        total += 1

    helpful = types.get("helpful", 0)
    noisy_wrong = (
        types.get("noisy", 0)
        + types.get("wrong_action", 0)
        + types.get("wrong_priority", 0)
        + types.get("needs_human_followup", 0)
    )
    return OperatorFeedbackSummary(
        total_count=total,
        helpful_count=helpful,
        noisy_wrong_count=noisy_wrong,
        by_type=dict(sorted(types.items())),
    )

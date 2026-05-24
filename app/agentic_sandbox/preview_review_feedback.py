"""Structured HITL review feedback for operator-console agentic sandbox previews."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.hitl.ticket_text_preview import _contains_unredacted_pii

DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH = Path(
    "reports/agentic_preview_review_feedback.jsonl",
)
REVIEWER_NOTE_MAX_CHARS = 300

_FORBIDDEN_TEXT_SUBSTRINGS = (
    "conversation transcript",
    '"messages"',
    "messages[",
    "draft_response",
    "final_response",
    "draft_reply",
    "retrieved_context",
    "retrieval_results",
    "raw_prompt",
    "raw_snippets",
    "gold_reference_reply",
    "user_input",
    "tool_results",
    "sk-",
    "begin private key",
    "postgresql://",
    "openai_api_key",
)

_ALLOWED_RECORD_KEYS = frozenset(
    {
        "review_id",
        "room_id",
        "review_timestamp_utc",
        "graph_status_correct",
        "intent_correct",
        "action_correct",
        "actionability_correct",
        "entity_extraction_correct",
        "knowledge_hints_helpful",
        "safety_correct",
        "ready_for_human_review_correct",
        "draft_length_reasonable",
        "overall_preview_useful",
        "unnecessary_additional_details_requested",
        "reviewer_notes",
        "source",
        "persisted_to",
    },
)


@dataclass(frozen=True)
class AgenticPreviewReviewFeedback:
    """One structured operator review of an agentic sandbox preview run."""

    room_id: str
    review_timestamp_utc: str
    graph_status_correct: bool
    intent_correct: bool
    action_correct: bool
    actionability_correct: bool
    entity_extraction_correct: bool
    knowledge_hints_helpful: bool
    safety_correct: bool
    ready_for_human_review_correct: bool
    draft_length_reasonable: bool
    overall_preview_useful: bool
    unnecessary_additional_details_requested: bool = False
    review_id: str = ""
    reviewer_notes: str | None = None
    source: str = "operator_console"
    persisted_to: str = "local_jsonl"

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgenticPreviewReviewSummary:
    """Aggregated metrics from append-only sandbox preview review log."""

    total_reviews: int
    overall_preview_useful_count: int
    intent_correct_count: int
    action_correct_count: int
    knowledge_hints_helpful_count: int

    @property
    def preview_usefulness_percent(self) -> float:
        return _percent(self.overall_preview_useful_count, self.total_reviews)

    @property
    def intent_correctness_percent(self) -> float:
        return _percent(self.intent_correct_count, self.total_reviews)

    @property
    def action_correctness_percent(self) -> float:
        return _percent(self.action_correct_count, self.total_reviews)

    @property
    def knowledge_helpfulness_percent(self) -> float:
        return _percent(self.knowledge_hints_helpful_count, self.total_reviews)


def _percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(100.0 * numerator / denominator, 1)


def _utc_iso_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def _truncate_text(text: str, *, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def assert_preview_review_text_safe(text: str, *, field_name: str = "reviewer_notes") -> None:
    """Reject reviewer free text that may leak transcripts, prompts, or PII."""
    if not text.strip():
        return
    lowered = text.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"{field_name} must not contain forbidden pattern: {token}")
    if _contains_unredacted_pii(text):
        raise ValueError(f"{field_name} contains unredacted PII-like patterns")


def build_agentic_preview_review_record(
    *,
    room_id: str,
    graph_status_correct: bool,
    intent_correct: bool,
    action_correct: bool,
    actionability_correct: bool,
    entity_extraction_correct: bool,
    knowledge_hints_helpful: bool,
    safety_correct: bool,
    ready_for_human_review_correct: bool,
    draft_length_reasonable: bool,
    overall_preview_useful: bool,
    unnecessary_additional_details_requested: bool = False,
    reviewer_notes: str | None = None,
    review_timestamp_utc: str | None = None,
) -> dict[str, Any]:
    """Build one allowlisted JSONL record (no draft text or retrieval snippets)."""
    if not room_id or not str(room_id).strip():
        raise ValueError("room_id is required")

    note: str | None = None
    if reviewer_notes is not None and str(reviewer_notes).strip():
        note = _truncate_text(str(reviewer_notes).strip(), max_chars=REVIEWER_NOTE_MAX_CHARS)
        assert_preview_review_text_safe(note)

    feedback = AgenticPreviewReviewFeedback(
        review_id=str(uuid.uuid4()),
        room_id=str(room_id).strip(),
        review_timestamp_utc=review_timestamp_utc or _utc_iso_timestamp(),
        graph_status_correct=bool(graph_status_correct),
        intent_correct=bool(intent_correct),
        action_correct=bool(action_correct),
        actionability_correct=bool(actionability_correct),
        entity_extraction_correct=bool(entity_extraction_correct),
        knowledge_hints_helpful=bool(knowledge_hints_helpful),
        safety_correct=bool(safety_correct),
        ready_for_human_review_correct=bool(ready_for_human_review_correct),
        draft_length_reasonable=bool(draft_length_reasonable),
        overall_preview_useful=bool(overall_preview_useful),
        unnecessary_additional_details_requested=bool(
            unnecessary_additional_details_requested,
        ),
        reviewer_notes=note,
    )
    record = feedback.to_record()
    extra = set(record.keys()) - _ALLOWED_RECORD_KEYS
    if extra:
        raise ValueError(f"unexpected keys in agentic preview review record: {extra}")
    return record


def append_agentic_preview_review_feedback(
    record: Mapping[str, Any],
    *,
    path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
) -> Path:
    """Append one JSON line to local sandbox preview review log."""
    keys = set(record.keys())
    if keys != _ALLOWED_RECORD_KEYS:
        missing = _ALLOWED_RECORD_KEYS - keys
        extra = keys - _ALLOWED_RECORD_KEYS
        parts: list[str] = []
        if missing:
            parts.append(f"missing keys: {sorted(missing)}")
        if extra:
            parts.append(f"extra keys: {sorted(extra)}")
        raise ValueError(
            "agentic preview review record keys must match contract: " + "; ".join(parts),
        )

    payload = json.dumps(dict(record), ensure_ascii=False)
    assert_preview_review_record_safe(payload)

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
    return file_path


def assert_preview_review_record_safe(content: str) -> None:
    """Fail closed if persisted row may contain forbidden fields."""
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"preview review record must not contain forbidden token: {token}")


def parse_agentic_preview_review_row(row: Mapping[str, Any]) -> AgenticPreviewReviewFeedback | None:
    try:
        return AgenticPreviewReviewFeedback(
            review_id=str(row.get("review_id") or ""),
            room_id=str(row["room_id"]),
            review_timestamp_utc=str(row["review_timestamp_utc"]),
            graph_status_correct=bool(row.get("graph_status_correct")),
            intent_correct=bool(row.get("intent_correct")),
            action_correct=bool(row.get("action_correct")),
            actionability_correct=bool(row.get("actionability_correct")),
            entity_extraction_correct=bool(row.get("entity_extraction_correct")),
            knowledge_hints_helpful=bool(row.get("knowledge_hints_helpful")),
            safety_correct=bool(row.get("safety_correct")),
            ready_for_human_review_correct=bool(row.get("ready_for_human_review_correct")),
            draft_length_reasonable=bool(row.get("draft_length_reasonable")),
            overall_preview_useful=bool(row.get("overall_preview_useful")),
            unnecessary_additional_details_requested=bool(
                row.get("unnecessary_additional_details_requested"),
            ),
            reviewer_notes=_optional_str(row.get("reviewer_notes")),
            source=str(row.get("source") or "operator_console"),
            persisted_to=str(row.get("persisted_to") or "local_jsonl"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_agentic_preview_review_rows(
    path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
) -> list[AgenticPreviewReviewFeedback]:
    """Load all valid review rows from JSONL (missing file → empty list)."""
    file_path = Path(path)
    if not file_path.is_file():
        return []
    rows: list[AgenticPreviewReviewFeedback] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        parsed = parse_agentic_preview_review_row(raw)
        if parsed is not None:
            rows.append(parsed)
    return rows


def load_agentic_preview_review_summary(
    path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
) -> AgenticPreviewReviewSummary:
    """Aggregate append-only sandbox preview review JSONL for sidebar metrics."""
    rows = load_agentic_preview_review_rows(path)
    useful = sum(1 for row in rows if row.overall_preview_useful)
    intent_ok = sum(1 for row in rows if row.intent_correct)
    action_ok = sum(1 for row in rows if row.action_correct)
    hints_ok = sum(1 for row in rows if row.knowledge_hints_helpful)
    return AgenticPreviewReviewSummary(
        total_reviews=len(rows),
        overall_preview_useful_count=useful,
        intent_correct_count=intent_ok,
        action_correct_count=action_ok,
        knowledge_hints_helpful_count=hints_ok,
    )


def latest_agentic_preview_review_for_room(
    room_id: str,
    *,
    path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
) -> AgenticPreviewReviewFeedback | None:
    matches = [r for r in load_agentic_preview_review_rows(path) if r.room_id == room_id]
    if not matches:
        return None
    return max(matches, key=lambda item: item.review_timestamp_utc)

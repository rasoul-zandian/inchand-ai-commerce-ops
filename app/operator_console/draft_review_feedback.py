"""Structured human review feedback for internal draft suggestions (local JSONL only)."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.hitl.ticket_text_preview import _contains_unredacted_pii

DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH = Path("reports/draft_review_feedback.jsonl")
REVIEWER_NOTE_MAX_CHARS = 300
BETTER_REPLY_MAX_CHARS = 300

_FORBIDDEN_TEXT_SUBSTRINGS = (
    "conversation transcript",
    '"messages"',
    "messages[",
    "draft_response",
    "final_response",
    "retrieved_context",
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
        "timestamp_utc",
        "reviewer_id",
        "room_id",
        "case_id",
        "draft_generation_mode",
        "draft_style",
        "conceptual_intent_fa",
        "detected_intent",
        "suggested_action",
        "ticket_label",
        "intent_correct",
        "action_correct",
        "entities_applicable",
        "entities_correct",
        "draft_usable",
        "too_verbose",
        "hallucination_detected",
        "unnecessary_followup_detected",
        "reviewer_note",
        "suggested_better_reply",
        "source",
        "persisted_to",
    },
)


@dataclass(frozen=True)
class DraftReviewFeedback:
    """One structured operator review of an internal draft suggestion."""

    review_id: str
    timestamp_utc: str
    reviewer_id: str
    room_id: str
    case_id: str | None
    draft_generation_mode: str
    draft_style: str | None
    conceptual_intent_fa: str | None
    detected_intent: str | None
    suggested_action: str | None
    intent_correct: bool
    action_correct: bool
    draft_usable: bool
    too_verbose: bool
    hallucination_detected: bool
    unnecessary_followup_detected: bool = False
    entities_applicable: bool = True
    entities_correct: bool | None = True
    ticket_label: str | None = None
    reviewer_note: str | None = None
    suggested_better_reply: str | None = None
    source: str = "operator_console"
    persisted_to: str = "local_jsonl"

    def to_record(self) -> dict[str, Any]:
        """Serialize to allowlisted JSONL record."""
        return asdict(self)


@dataclass(frozen=True)
class DraftReviewFeedbackSummary:
    """Aggregated counts from append-only draft review log."""

    total_reviews: int
    usable_count: int
    hallucination_count: int
    verbose_count: int
    by_detected_intent: dict[str, int]
    by_suggested_action: dict[str, int]

    @property
    def usable_percent(self) -> float:
        if self.total_reviews == 0:
            return 0.0
        return round(100.0 * self.usable_count / self.total_reviews, 1)


def _utc_iso_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _truncate_text(text: str, *, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def assert_reviewer_text_safe(text: str, *, field_name: str) -> None:
    """Reject reviewer free text that may leak transcripts, prompts, or PII."""
    if not text.strip():
        return
    lowered = text.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"{field_name} must not contain forbidden pattern: {token}")
    if _contains_unredacted_pii(text):
        raise ValueError(f"{field_name} contains unredacted PII-like patterns")


ENTITY_REVIEW_EXTRACTED_OK = "extracted_ok"
ENTITY_REVIEW_EXTRACTED_FAIL = "extracted_fail"
ENTITY_REVIEW_NOT_APPLICABLE = "not_applicable"

ENTITY_REVIEW_UI_OPTIONS: tuple[tuple[str, str], ...] = (
    (ENTITY_REVIEW_EXTRACTED_OK, "نیاز به استخراج بوده و استخراج شده"),
    (ENTITY_REVIEW_EXTRACTED_FAIL, "نیاز به استخراج بوده ولی استخراج نکرده"),
    (ENTITY_REVIEW_NOT_APPLICABLE, "نیاز به استخراج نداشته"),
)

ENTITY_REVIEW_UI_CAPTION_FA = "برای شماره سفارش، شناسه کالا، کد رهگیری و سایر شناسه‌های عملیاتی"


def map_entity_review_ui_choice(choice: str) -> tuple[bool, bool | None]:
    """Map operator-console 3-state entity review to storage fields."""
    if choice == ENTITY_REVIEW_EXTRACTED_OK:
        return True, True
    if choice == ENTITY_REVIEW_EXTRACTED_FAIL:
        return True, False
    if choice == ENTITY_REVIEW_NOT_APPLICABLE:
        return False, None
    raise ValueError(f"unknown entity review choice: {choice!r}")


def entity_review_ui_label(choice: str) -> str:
    for key, label in ENTITY_REVIEW_UI_OPTIONS:
        if key == choice:
            return label
    raise ValueError(f"unknown entity review choice: {choice!r}")


def _normalize_entity_review_fields(
    *,
    entities_applicable: bool,
    entities_correct: bool | None,
) -> tuple[bool, bool | None]:
    if entities_applicable:
        if entities_correct is None:
            raise ValueError("entities_correct is required when entities_applicable is true")
        return True, bool(entities_correct)
    if entities_correct is not None:
        raise ValueError("entities_correct must be omitted when entities_applicable is false")
    return False, None


def build_draft_review_feedback_record(
    *,
    room_id: str,
    draft_generation_mode: str,
    intent_correct: bool,
    action_correct: bool,
    entities_applicable: bool = True,
    entities_correct: bool | None = True,
    draft_usable: bool,
    too_verbose: bool,
    hallucination_detected: bool,
    unnecessary_followup_detected: bool = False,
    preview: Any | None = None,
    case_id: str | None = None,
    draft_style: str | None = None,
    conceptual_intent_fa: str | None = None,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    ticket_label: str | None = None,
    reviewer_note: str | None = None,
    suggested_better_reply: str | None = None,
    reviewer_id: str | None = None,
) -> dict[str, Any]:
    """Build a single draft review record (aggregate metadata only)."""
    if not room_id or not str(room_id).strip():
        raise ValueError("room_id is required")
    mode = str(draft_generation_mode).strip()
    if not mode:
        raise ValueError("draft_generation_mode is required")

    note: str | None = None
    if reviewer_note is not None and str(reviewer_note).strip():
        note = _truncate_text(str(reviewer_note).strip(), max_chars=REVIEWER_NOTE_MAX_CHARS)
        assert_reviewer_text_safe(note, field_name="reviewer_note")

    better: str | None = None
    if suggested_better_reply is not None and str(suggested_better_reply).strip():
        better = _truncate_text(
            str(suggested_better_reply).strip(),
            max_chars=BETTER_REPLY_MAX_CHARS,
        )
        assert_reviewer_text_safe(better, field_name="suggested_better_reply")

    applicable, entity_correct = _normalize_entity_review_fields(
        entities_applicable=entities_applicable,
        entities_correct=entities_correct,
    )

    if preview is not None:
        case_id = case_id or getattr(preview, "case_id", None)
        draft_style = draft_style or getattr(preview, "draft_style", None)
        conceptual_intent_fa = conceptual_intent_fa or getattr(
            preview,
            "conceptual_intent_fa",
            None,
        )
        detected_intent = detected_intent or getattr(preview, "detected_intent", None)
        suggested_action = suggested_action or getattr(preview, "suggested_action", None)
        ticket_label = ticket_label or getattr(preview, "ticket_label", None)

    feedback = DraftReviewFeedback(
        review_id=str(uuid.uuid4()),
        timestamp_utc=_utc_iso_timestamp(),
        reviewer_id=(reviewer_id or "local_operator").strip() or "local_operator",
        room_id=str(room_id).strip(),
        case_id=_optional_str(case_id),
        draft_generation_mode=mode,
        draft_style=_optional_str(draft_style),
        conceptual_intent_fa=_optional_str(conceptual_intent_fa),
        detected_intent=_optional_str(detected_intent),
        suggested_action=_optional_str(suggested_action),
        ticket_label=_optional_str(ticket_label),
        intent_correct=bool(intent_correct),
        action_correct=bool(action_correct),
        entities_applicable=applicable,
        entities_correct=entity_correct,
        draft_usable=bool(draft_usable),
        too_verbose=bool(too_verbose),
        hallucination_detected=bool(hallucination_detected),
        unnecessary_followup_detected=bool(unnecessary_followup_detected),
        reviewer_note=note,
        suggested_better_reply=better,
    )
    record = feedback.to_record()
    extra = set(record.keys()) - _ALLOWED_RECORD_KEYS
    if extra:
        raise ValueError(f"unexpected keys in draft review record: {extra}")
    return record


def append_draft_review_feedback(
    record: Mapping[str, Any],
    *,
    path: Path | str = DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
) -> Path:
    """Append one JSON line to local draft review log."""
    keys = set(record.keys())
    if keys != _ALLOWED_RECORD_KEYS:
        missing = _ALLOWED_RECORD_KEYS - keys
        extra = keys - _ALLOWED_RECORD_KEYS
        parts: list[str] = []
        if missing:
            parts.append(f"missing keys: {sorted(missing)}")
        if extra:
            parts.append(f"extra keys: {sorted(extra)}")
        raise ValueError("draft review record keys must match contract: " + "; ".join(parts))

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), ensure_ascii=False) + "\n")
    return file_path


def _parse_entities_applicable(row: Mapping[str, Any]) -> bool:
    if "entities_applicable" in row:
        return bool(row.get("entities_applicable"))
    return True


def _parse_entities_correct(row: Mapping[str, Any]) -> bool | None:
    if "entities_applicable" in row and not bool(row.get("entities_applicable")):
        return None
    if "entities_correct" not in row:
        return None
    raw = row.get("entities_correct")
    if raw is None:
        return None
    return bool(raw)


def parse_draft_review_feedback_row(row: Mapping[str, Any]) -> DraftReviewFeedback | None:
    try:
        return DraftReviewFeedback(
            review_id=str(row["review_id"]),
            timestamp_utc=str(row["timestamp_utc"]),
            reviewer_id=str(row.get("reviewer_id") or "local_operator"),
            room_id=str(row["room_id"]),
            case_id=_optional_str(row.get("case_id")),
            draft_generation_mode=str(row.get("draft_generation_mode") or ""),
            draft_style=_optional_str(row.get("draft_style")),
            conceptual_intent_fa=_optional_str(row.get("conceptual_intent_fa")),
            detected_intent=_optional_str(row.get("detected_intent")),
            suggested_action=_optional_str(row.get("suggested_action")),
            ticket_label=_optional_str(row.get("ticket_label")),
            intent_correct=bool(row.get("intent_correct")),
            action_correct=bool(row.get("action_correct")),
            entities_applicable=_parse_entities_applicable(row),
            entities_correct=_parse_entities_correct(row),
            draft_usable=bool(row.get("draft_usable")),
            too_verbose=bool(row.get("too_verbose")),
            hallucination_detected=bool(row.get("hallucination_detected")),
            unnecessary_followup_detected=bool(row.get("unnecessary_followup_detected")),
            reviewer_note=_optional_str(row.get("reviewer_note")),
            suggested_better_reply=_optional_str(row.get("suggested_better_reply")),
            source=str(row.get("source") or "operator_console"),
            persisted_to=str(row.get("persisted_to") or "local_jsonl"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_draft_review_feedback_rows(
    path: Path | str = DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
) -> list[DraftReviewFeedback]:
    """Load all valid review rows from JSONL."""
    file_path = Path(path)
    if not file_path.is_file():
        return []
    rows: list[DraftReviewFeedback] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        parsed = parse_draft_review_feedback_row(raw)
        if parsed is not None:
            rows.append(parsed)
    return rows


def latest_draft_review_for_room(
    room_id: str,
    *,
    path: Path | str = DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
) -> DraftReviewFeedback | None:
    """Return the most recent review for a room_id, if any."""
    matches = [r for r in load_draft_review_feedback_rows(path) if r.room_id == room_id]
    if not matches:
        return None
    return max(matches, key=lambda item: item.timestamp_utc)


def draft_review_badge_lines(review: DraftReviewFeedback) -> list[str]:
    """Lightweight UI badges derived from a submitted review."""
    if review.draft_usable and not review.too_verbose and not review.hallucination_detected:
        return ["✅ good draft"]
    badges: list[str] = []
    if review.too_verbose:
        badges.append("⚠️ verbose")
    if review.hallucination_detected:
        badges.append("⚠️ hallucination risk")
    if not badges and review.draft_usable:
        badges.append("✅ good draft")
    return badges


def load_draft_review_feedback_summary(
    path: Path | str = DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
) -> DraftReviewFeedbackSummary:
    """Aggregate append-only draft review JSONL for sidebar metrics."""
    rows = load_draft_review_feedback_rows(path)
    by_intent: Counter[str] = Counter()
    by_action: Counter[str] = Counter()
    usable = 0
    hallucination = 0
    verbose = 0
    for row in rows:
        if row.draft_usable:
            usable += 1
        if row.hallucination_detected:
            hallucination += 1
        if row.too_verbose:
            verbose += 1
        intent_key = row.detected_intent or "(none)"
        action_key = row.suggested_action or "(none)"
        by_intent[intent_key] += 1
        by_action[action_key] += 1
    return DraftReviewFeedbackSummary(
        total_reviews=len(rows),
        usable_count=usable,
        hallucination_count=hallucination,
        verbose_count=verbose,
        by_detected_intent=dict(sorted(by_intent.items())),
        by_suggested_action=dict(sorted(by_action.items())),
    )

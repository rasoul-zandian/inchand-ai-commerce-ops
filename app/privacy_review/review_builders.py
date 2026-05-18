"""Build privacy-warning review records and summaries from offline validation signals."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from pydantic import ValidationError
from scripts.validate_ticket_export import count_suspicious_tokens

from app.privacy_review.models import (
    PrivacyReviewSummary,
    PrivacyWarningRecord,
    PrivacyWarningType,
)
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)

_PRIVACY_WARNING_KEYS = frozenset(t.value for t in PrivacyWarningType)


def _counter_to_warning_types(counts: Counter[str]) -> list[PrivacyWarningType]:
    types: list[PrivacyWarningType] = []
    for key in sorted(counts):
        if counts[key] <= 0:
            continue
        if key not in _PRIVACY_WARNING_KEYS:
            continue
        types.append(PrivacyWarningType(key))
    return types


def warning_types_for_snapshot(snapshot: ConversationTicketSnapshot) -> list[PrivacyWarningType]:
    """Return privacy warning categories for a ticket; never returns matched substrings."""
    combined = "\n".join(message.text for message in snapshot.messages)
    seller = snapshot.seller_id or ""
    counts = count_suspicious_tokens(f"{combined}\n{seller}")
    return _counter_to_warning_types(counts)


def build_privacy_warning_record(
    room_id: str,
    warning_types: list[PrivacyWarningType],
    *,
    notes: str | None = None,
) -> PrivacyWarningRecord:
    """Build a per-ticket warning record (warnings must be non-empty)."""
    distinct = list(dict.fromkeys(warning_types))
    if not distinct:
        raise ValueError("warning_types must be non-empty to build a warning record")
    return PrivacyWarningRecord(
        room_id=room_id.strip(),
        warning_types=distinct,
        warning_count=len(distinct),
        requires_manual_review=True,
        corpus_eligible=False,
        notes=notes,
    )


def build_privacy_warning_records_from_export_lines(
    lines: list[str],
) -> tuple[list[PrivacyWarningRecord], Counter[str]]:
    """Scan normalized export JSONL and return warning records plus type counts."""
    records: list[PrivacyWarningRecord] = []
    type_counts: Counter[str] = Counter()

    for raw_line in lines:
        if not raw_line.strip():
            continue
        try:
            snapshot = parse_conversation_ticket_snapshot(raw_line)
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue

        warning_types = warning_types_for_snapshot(snapshot)
        if not warning_types:
            continue

        for warning_type in warning_types:
            type_counts[warning_type.value] += 1

        records.append(
            build_privacy_warning_record(snapshot.room_id, warning_types),
        )

    return records, type_counts


def build_privacy_review_summary(
    *,
    total_tickets_reviewed: int,
    warning_records: list[PrivacyWarningRecord],
    warning_type_counts: dict[str, int] | Counter[str] | None = None,
) -> PrivacyReviewSummary:
    """Aggregate privacy review metrics from replay scope and warning records."""
    tickets_with_warnings = len(warning_records)
    counts = dict(warning_type_counts or {})
    if not counts and warning_records:
        merged: Counter[str] = Counter()
        for record in warning_records:
            for warning_type in record.warning_types:
                merged[warning_type.value] += 1
        counts = dict(merged)

    return PrivacyReviewSummary(
        total_tickets_reviewed=total_tickets_reviewed,
        tickets_with_warnings=tickets_with_warnings,
        warning_type_counts=counts,
        manual_review_required_count=tickets_with_warnings,
        corpus_eligible_count=total_tickets_reviewed - tickets_with_warnings,
        corpus_blocked_count=tickets_with_warnings,
    )


def corpus_eligible_for_warning_types(warning_types: list[PrivacyWarningType]) -> bool:
    """Deterministic corpus eligibility: blocked when any privacy warning is present."""
    return len(warning_types) == 0


def summary_to_json_dict(
    summary: PrivacyReviewSummary,
    *,
    warning_records: list[PrivacyWarningRecord],
    replay_path: str,
    export_path: str | None,
    generated_at: str,
) -> dict[str, Any]:
    """Serialize aggregate-safe privacy review payload (no raw text)."""
    return {
        "generated_at": generated_at,
        "sources": {
            "replay_report": replay_path,
            "normalized_export": export_path,
        },
        "summary": summary.model_dump(),
        "tickets_with_warnings": [
            {
                "room_id": record.room_id,
                "warning_types": [warning_type.value for warning_type in record.warning_types],
                "warning_count": record.warning_count,
                "requires_manual_review": record.requires_manual_review,
                "corpus_eligible": record.corpus_eligible,
                "notes": record.notes,
            }
            for record in warning_records
        ],
    }

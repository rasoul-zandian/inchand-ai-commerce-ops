"""Build historical reply benchmark cases from redacted vendor ticket JSONL (offline only)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.hitl.ticket_text_preview import (
    _contains_unredacted_pii,
    _truncate_preview,
)
from app.live_feed.open_ticket_snapshot import (
    build_open_ticket_snapshot,
    open_ticket_snapshot_to_payload,
)
from app.privacy_review.redaction import assert_redacted_export_safe, redact_pii_text
from app.tickets.conversation_models import (
    ConversationMessage,
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)

# Gold human reply: keep bounded for JSONL + future model comparison.
GOLD_REFERENCE_MAX_LENGTH = 500

_RESPONSE_SENDER_TYPES = frozenset({"support_agent", "finance_agent"})
_VENDOR_SENDER_TYPES = frozenset({"seller"})
_INTERNAL_SENDER_TYPES = frozenset({"system", "unknown"})

FIRST_VENDOR_TURN_CASE_ID_SUFFIX = "first_vendor_turn"


class BenchmarkCaseMode(StrEnum):
    """How to expand one ticket room into benchmark evaluation cases."""

    ALL_ADJACENT_PAIRS = "all_adjacent_pairs"
    FIRST_VENDOR_TURN = "first_vendor_turn"


_FULL_TRANSCRIPT_MARKERS = (
    "conversation transcript:",
    "messages[",
    '"messages"',
)


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        aware = dt.replace(tzinfo=UTC)
    else:
        aware = dt.astimezone(UTC)
    return aware.replace(microsecond=0).isoformat()


@dataclass
class HistoricalReplyBenchmarkStats:
    """Aggregate counts written to ``historical_reply_benchmark_summary.json``."""

    total_cases: int = 0
    cases_by_label: dict[str, int] = field(default_factory=dict)
    cases_by_responder_role: dict[str, int] = field(default_factory=dict)
    skipped_no_support_reply: int = 0
    skipped_unsafe: int = 0
    tickets_processed: int = 0
    source_path: str = ""
    output_jsonl_path: str = ""
    output_summary_path: str = ""
    generated_at_utc: str = ""
    case_mode: str = BenchmarkCaseMode.ALL_ADJACENT_PAIRS.value

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "case_mode": self.case_mode,
            "total_cases": self.total_cases,
            "cases_by_label": dict(sorted(self.cases_by_label.items())),
            "cases_by_responder_role": dict(sorted(self.cases_by_responder_role.items())),
            "skipped_no_support_reply": self.skipped_no_support_reply,
            "skipped_unsafe": self.skipped_unsafe,
            "tickets_processed": self.tickets_processed,
            "source_path": self.source_path,
            "output_jsonl_path": self.output_jsonl_path,
            "output_summary_path": self.output_summary_path,
            "generated_at_utc": self.generated_at_utc,
        }


def _room_has_vendor_responder_adjacency(snapshot: ConversationTicketSnapshot) -> bool:
    messages = snapshot.messages
    for i in range(len(messages) - 1):
        if messages[i].sender_type == "seller":
            if messages[i + 1].sender_type in _RESPONSE_SENDER_TYPES:
                return True
    return False


def _prepare_gold_reference_reply(raw: str) -> str | None:
    """Redact, reject lingering PII patterns, truncate. Returns None if unusable."""
    stripped = raw.strip()
    if not stripped:
        return None
    redacted = redact_pii_text(stripped).redacted_text.strip()
    if not redacted:
        return None
    lowered = redacted.lower()
    for marker in _FULL_TRANSCRIPT_MARKERS:
        if marker in lowered:
            return None
    if _contains_unredacted_pii(redacted):
        return None
    try:
        assert_redacted_export_safe(redacted)
    except ValueError:
        return None
    return _truncate_preview(redacted, max_length=GOLD_REFERENCE_MAX_LENGTH)


def _first_non_internal_index(messages: list[ConversationMessage]) -> int | None:
    for index, message in enumerate(messages):
        if message.sender_type not in _INTERNAL_SENDER_TYPES:
            return index
    return None


def _find_first_vendor_turn_indices(
    snapshot: ConversationTicketSnapshot,
) -> tuple[int, int] | None:
    """Return (first_vendor_index, first_support_finance_index) or None if room skipped."""
    messages = snapshot.messages
    first_idx = _first_non_internal_index(messages)
    if first_idx is None:
        return None
    if messages[first_idx].sender_type not in _VENDOR_SENDER_TYPES:
        return None
    vendor_index = first_idx
    for index in range(vendor_index + 1, len(messages)):
        if messages[index].sender_type in _RESPONSE_SENDER_TYPES:
            return vendor_index, index
    return None


def _room_has_first_vendor_turn_pattern(snapshot: ConversationTicketSnapshot) -> bool:
    return _find_first_vendor_turn_indices(snapshot) is not None


def _iter_vendor_responder_pairs(
    snapshot: ConversationTicketSnapshot,
) -> Iterator[tuple[int, str, str]]:
    """Yield (vendor_index, vendor_message_id, responder_message_id)."""
    messages = snapshot.messages
    for i in range(len(messages) - 1):
        if messages[i].sender_type != "seller":
            continue
        nxt = messages[i + 1]
        if nxt.sender_type not in _RESPONSE_SENDER_TYPES:
            continue
        yield (i, messages[i].message_id, nxt.message_id)


def _snapshot_truncated_to_vendor_turn(
    snapshot: ConversationTicketSnapshot,
    vendor_index_inclusive: int,
) -> ConversationTicketSnapshot:
    return snapshot.model_copy(
        deep=True,
        update={"messages": list(snapshot.messages[: vendor_index_inclusive + 1])},
    )


def build_benchmark_case(
    snapshot: ConversationTicketSnapshot,
    *,
    vendor_index: int,
    route_label: str | None,
    responder_index: int | None = None,
    case_id: str | None = None,
    snapshot_before_override: dict[str, str | None] | None = None,
) -> dict[str, Any] | None:
    """One benchmark row, or None if safety/context checks fail."""
    messages = snapshot.messages
    if responder_index is None:
        responder_index = vendor_index + 1
    if responder_index >= len(messages):
        return None

    truncated = _snapshot_truncated_to_vendor_turn(snapshot, vendor_index)
    vendor = messages[vendor_index]
    responder = messages[responder_index]
    if responder.sender_type not in _RESPONSE_SENDER_TYPES:
        return None

    if snapshot_before_override is not None:
        snapshot_before = snapshot_before_override
    else:
        try:
            built = build_open_ticket_snapshot(truncated)
        except ValueError:
            return None
        if not built.latest_vendor_message:
            return None
        snap_payload = open_ticket_snapshot_to_payload(built)
        snapshot_before = {
            "original_vendor_issue_preview": snap_payload.get("original_vendor_issue_preview"),
            "latest_vendor_message": snap_payload.get("latest_vendor_message"),
            "recent_context_preview": snap_payload.get("recent_context_preview"),
        }

    gold = _prepare_gold_reference_reply(responder.text)
    if gold is None:
        return None

    resolved_case_id = case_id or f"{snapshot.room_id}__{vendor.message_id}"

    sequence: dict[str, Any] = {
        "vendor_message_index": vendor_index,
        "vendor_message_id": vendor.message_id,
        "responder_message_id": responder.message_id,
        "responder_message_index": responder_index,
        "ticket_created_at": _iso_utc(snapshot.created_at),
        "case_mode": BenchmarkCaseMode.ALL_ADJACENT_PAIRS.value,
    }
    v_ts = _iso_utc(vendor.timestamp)
    if v_ts is not None:
        sequence["vendor_message_timestamp"] = v_ts
    r_ts = _iso_utc(responder.timestamp)
    if r_ts is not None:
        sequence["responder_message_timestamp"] = r_ts

    return {
        "case_id": resolved_case_id,
        "room_id": snapshot.room_id,
        "ticket_label": snapshot.ticket_label,
        "route_label": route_label,
        "snapshot_before_reply": snapshot_before,
        "gold_reference_reply": gold,
        "responder_role": responder.sender_type,
        "sequence": sequence,
    }


def _first_vendor_turn_snapshot_before(
    snapshot: ConversationTicketSnapshot,
    vendor_index: int,
) -> dict[str, str | None] | None:
    """Snapshot fields before the first human reply (first vendor message only)."""
    truncated = _snapshot_truncated_to_vendor_turn(snapshot, vendor_index)
    try:
        built = build_open_ticket_snapshot(truncated)
    except ValueError:
        return None
    vendor_preview = built.original_vendor_issue_preview or built.latest_vendor_message
    if not vendor_preview:
        return None
    return {
        "original_vendor_issue_preview": vendor_preview,
        "latest_vendor_message": vendor_preview,
        "recent_context_preview": None,
    }


def build_first_vendor_turn_case(
    snapshot: ConversationTicketSnapshot,
    *,
    route_label: str | None,
) -> dict[str, Any] | None:
    """One first-turn benchmark row per room, or None if skipped or unsafe."""
    indices = _find_first_vendor_turn_indices(snapshot)
    if indices is None:
        return None
    vendor_index, responder_index = indices
    snapshot_before = _first_vendor_turn_snapshot_before(snapshot, vendor_index)
    if snapshot_before is None:
        return None
    row = build_benchmark_case(
        snapshot,
        vendor_index=vendor_index,
        responder_index=responder_index,
        route_label=route_label,
        case_id=f"{snapshot.room_id}__{FIRST_VENDOR_TURN_CASE_ID_SUFFIX}",
        snapshot_before_override=snapshot_before,
    )
    if row is None:
        return None
    sequence = dict(row["sequence"])
    sequence["case_mode"] = BenchmarkCaseMode.FIRST_VENDOR_TURN.value
    row["sequence"] = sequence
    return row


def _normalize_route_label(raw: dict[str, Any]) -> str | None:
    route_label = raw.get("route_label")
    if route_label is not None and not isinstance(route_label, str):
        return str(route_label).strip() or None
    if isinstance(route_label, str):
        return route_label.strip() or None
    return None


def extract_cases_from_ticket_line(
    raw: dict[str, Any],
    *,
    case_mode: BenchmarkCaseMode | str = BenchmarkCaseMode.ALL_ADJACENT_PAIRS,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Parse one JSON object; return (cases, skipped_unsafe_count, had_eligible_pattern).

    ``had_eligible_pattern`` means the room matched the mode's inclusion rules before
    safety filtering (adjacent seller→support pairs, or first-vendor-turn pattern).
    """
    mode = BenchmarkCaseMode(case_mode)
    route_label = _normalize_route_label(raw)
    snapshot = parse_conversation_ticket_snapshot(raw)

    if mode == BenchmarkCaseMode.FIRST_VENDOR_TURN:
        had_pattern = _room_has_first_vendor_turn_pattern(snapshot)
        if not had_pattern:
            return [], 0, False
        row = build_first_vendor_turn_case(snapshot, route_label=route_label)
        if row is None:
            return [], 1, True
        return [row], 0, True

    had_adjacency = _room_has_vendor_responder_adjacency(snapshot)
    cases: list[dict[str, Any]] = []
    skipped_unsafe = 0

    for vendor_index, _vid, _rid in _iter_vendor_responder_pairs(snapshot):
        row = build_benchmark_case(snapshot, vendor_index=vendor_index, route_label=route_label)
        if row is None:
            skipped_unsafe += 1
            continue
        cases.append(row)

    return cases, skipped_unsafe, had_adjacency


def build_benchmark_from_jsonl(
    input_path: Path,
    *,
    output_jsonl_path: Path,
    output_summary_path: Path,
    case_mode: BenchmarkCaseMode | str = BenchmarkCaseMode.ALL_ADJACENT_PAIRS,
) -> HistoricalReplyBenchmarkStats:
    """Read redacted JSONL, write benchmark JSONL + summary JSON under ``reports/``."""
    if not input_path.is_file():
        raise FileNotFoundError(f"benchmark input not found: {input_path}")

    mode = BenchmarkCaseMode(case_mode)
    stats = HistoricalReplyBenchmarkStats(
        source_path=str(input_path.resolve()),
        output_jsonl_path=str(output_jsonl_path.resolve()),
        output_summary_path=str(output_summary_path.resolve()),
        generated_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
        case_mode=mode.value,
    )

    by_label: Counter[str] = Counter()
    by_role: Counter[str] = Counter()
    total_cases = 0
    skipped_unsafe_total = 0
    skipped_no_support = 0
    tickets_processed = 0

    output_jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    with (
        input_path.open(encoding="utf-8") as inp,
        output_jsonl_path.open("w", encoding="utf-8") as outp,
    ):
        for line_no, line in enumerate(inp, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {input_path}:{line_no}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"line {line_no} must be a JSON object")

            tickets_processed += 1
            cases, skipped_unsafe, had_pattern = extract_cases_from_ticket_line(
                raw,
                case_mode=mode,
            )
            skipped_unsafe_total += skipped_unsafe

            if not had_pattern:
                skipped_no_support += 1
            for case in cases:
                outp.write(json.dumps(case, ensure_ascii=False) + "\n")
                total_cases += 1
                by_label[str(case["ticket_label"])] += 1
                by_role[str(case["responder_role"])] += 1

    stats.total_cases = total_cases
    stats.cases_by_label = dict(by_label)
    stats.cases_by_responder_role = dict(by_role)
    stats.skipped_no_support_reply = skipped_no_support
    stats.skipped_unsafe = skipped_unsafe_total
    stats.tickets_processed = tickets_processed

    output_summary_path.parent.mkdir(parents=True, exist_ok=True)
    output_summary_path.write_text(
        json.dumps(stats.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return stats

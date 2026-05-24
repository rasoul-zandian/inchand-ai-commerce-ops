"""Deterministic investigation of agentic preview entity-extraction misses (advisory only)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.agentic_sandbox.agentic_readiness_analysis import BatchRunRecord, load_batch_run_records
from app.agentic_sandbox.preview_review_feedback import (
    DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    load_agentic_preview_review_rows,
)
from app.agentic_sandbox.report_paths import DEFAULT_BATCH_RUNS_JSONL
from app.evals.first_turn_draft_context import (
    ENTITY_SOURCE_FULL_FIRST_VENDOR,
    ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
    build_first_turn_draft_context_from_ticket,
)
from app.live_feed.open_ticket_snapshot import (
    OPEN_TICKET_ORIGINAL_MAX_CHARS,
    extract_latest_vendor_message,
    extract_original_vendor_issue,
)
from app.operator_console.console_loader import (
    DEFAULT_REDACTED_TICKETS_PATH,
    DEFAULT_REPLAY_PATH,
    load_operator_tickets,
)
from app.operator_console.draft_review_feedback import _FORBIDDEN_TEXT_SUBSTRINGS
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)
from app.workflows.operational_entity_extraction import (
    OperationalEntityExtractionResult,
    extract_operational_entities,
    normalize_digits,
)

DEFAULT_INVESTIGATION_SUMMARY_PATH = Path("reports/entity_extraction_investigation_summary.json")
DEFAULT_INVESTIGATION_REPORT_PATH = Path("reports/entity_extraction_investigation_report.md")

_ENTITY_KEY_ORDER = "order_ids"
_ENTITY_KEY_PRODUCT = "product_ids"
_ENTITY_KEY_TRACKING = "tracking_code"
_ENTITY_KEY_IBAN = "iban"


class EntityExtractionRootCause(StrEnum):
    UNSUPPORTED_PATTERN = "unsupported_pattern"
    FIRST_TURN_ISOLATION_GAP = "first_turn_isolation_gap"
    NORMALIZATION_GAP = "normalization_gap"
    AMBIGUOUS_NUMERIC_PATTERN = "ambiguous_numeric_pattern"
    EXTRACTION_RULE_GAP = "extraction_rule_gap"
    REVIEW_MISMATCH = "review_mismatch"
    NOT_REPRODUCIBLE = "not_reproducible"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EntitySnapshot:
    """Serializable entity bundle for investigation reports."""

    order_ids: tuple[str, ...] = ()
    product_ids: tuple[str, ...] = ()
    tracking_code: str | None = None
    iban: str | None = None
    iban_masked: str | None = None
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_extraction(cls, result: OperationalEntityExtractionResult) -> EntitySnapshot:
        return cls(
            order_ids=result.order_ids,
            product_ids=result.product_ids,
            tracking_code=result.primary_tracking_code,
            iban=result.primary_iban,
            iban_masked=result.primary_iban_masked,
            warnings=result.warnings,
        )

    @classmethod
    def from_replay_row(cls, row: dict[str, Any]) -> EntitySnapshot:
        order_ids = _split_csv(row.get("extracted_order_ids"))
        if not order_ids and row.get("extracted_order_id"):
            order_ids = (str(row["extracted_order_id"]).strip(),)
        return cls(
            order_ids=order_ids,
            product_ids=_split_csv(row.get("extracted_product_ids")),
            tracking_code=_optional_str(row.get("extracted_tracking_code")),
            iban=_optional_str(row.get("extracted_iban")),
            iban_masked=_optional_str(row.get("extracted_iban_masked")),
            warnings=_split_warnings(row.get("entity_warnings_summary")),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "order_ids": list(self.order_ids),
            "product_ids": list(self.product_ids),
            "tracking_code": self.tracking_code,
            "iban": self.iban,
            "iban_masked": self.iban_masked,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class EntityExtractionInvestigationResult:
    """Per-room deterministic entity miss investigation."""

    room_id: str
    detected_intent: str | None
    conceptual_intent_fa: str | None
    entity_source: str
    expected_entities: dict[str, Any]
    extracted_entities: dict[str, Any]
    missing_entities: dict[str, Any]
    unexpected_entities: dict[str, Any]
    likely_root_cause: str
    investigation_notes: str
    reproducible: bool = True
    later_thread_only_entities: dict[str, Any] = field(default_factory=dict)
    replay_entities: dict[str, Any] | None = None
    batch_order_id_count: int | None = None
    first_turn_preview_truncated: bool = False
    first_turn_full_char_count: int | None = None
    first_turn_preview_char_count: int | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "detected_intent": self.detected_intent,
            "conceptual_intent_fa": self.conceptual_intent_fa,
            "entity_source": self.entity_source,
            "expected_entities": self.expected_entities,
            "extracted_entities": self.extracted_entities,
            "missing_entities": self.missing_entities,
            "unexpected_entities": self.unexpected_entities,
            "likely_root_cause": self.likely_root_cause,
            "investigation_notes": self.investigation_notes,
            "reproducible": self.reproducible,
            "later_thread_only_entities": self.later_thread_only_entities,
            "replay_entities": self.replay_entities,
            "batch_order_id_count": self.batch_order_id_count,
            "first_turn_preview_truncated": self.first_turn_preview_truncated,
            "first_turn_full_char_count": self.first_turn_full_char_count,
            "first_turn_preview_char_count": self.first_turn_preview_char_count,
        }


@dataclass(frozen=True)
class EntityExtractionInvestigationSummary:
    """Aggregate investigation output."""

    generated_at_utc: str
    source_feedback_path: str
    source_batch_runs_path: str
    source_replay_path: str
    source_redacted_path: str | None
    investigated_room_count: int
    flagged_review_count: int
    root_cause_counts: dict[str, int]
    investigations: tuple[EntityExtractionInvestigationResult, ...]
    advisory_improvements: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_feedback_path": self.source_feedback_path,
            "source_batch_runs_path": self.source_batch_runs_path,
            "source_replay_path": self.source_replay_path,
            "source_redacted_path": self.source_redacted_path,
            "investigated_room_count": self.investigated_room_count,
            "flagged_review_count": self.flagged_review_count,
            "root_cause_counts": dict(self.root_cause_counts),
            "investigations": [item.to_json_dict() for item in self.investigations],
            "advisory_improvements": list(self.advisory_improvements),
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_csv(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    text = str(value).strip()
    if not text:
        return ()
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _split_warnings(value: Any) -> tuple[str, ...]:
    text = _optional_str(value)
    if not text:
        return ()
    return tuple(part.strip() for part in text.split(";") if part.strip())


def _first_vendor_message(snapshot: ConversationTicketSnapshot) -> str | None:
    for message in snapshot.messages:
        if message.sender_type == "seller":
            text = message.text.strip()
            if text:
                return text
    return None


def _entity_diff(
    reference: EntitySnapshot,
    observed: EntitySnapshot,
) -> tuple[dict[str, Any], dict[str, Any]]:
    missing: dict[str, Any] = {}
    unexpected: dict[str, Any] = {}

    ref_orders = set(reference.order_ids)
    obs_orders = set(observed.order_ids)
    if ref_orders - obs_orders:
        missing[_ENTITY_KEY_ORDER] = sorted(ref_orders - obs_orders)
    if obs_orders - ref_orders:
        unexpected[_ENTITY_KEY_ORDER] = sorted(obs_orders - ref_orders)

    ref_products = set(reference.product_ids)
    obs_products = set(observed.product_ids)
    if ref_products - obs_products:
        missing[_ENTITY_KEY_PRODUCT] = sorted(ref_products - obs_products)
    if obs_products - ref_products:
        unexpected[_ENTITY_KEY_PRODUCT] = sorted(obs_products - ref_products)

    if reference.tracking_code and reference.tracking_code != observed.tracking_code:
        missing[_ENTITY_KEY_TRACKING] = reference.tracking_code
    if observed.tracking_code and observed.tracking_code != reference.tracking_code:
        if _ENTITY_KEY_TRACKING not in missing:
            unexpected[_ENTITY_KEY_TRACKING] = observed.tracking_code

    if reference.iban and reference.iban != observed.iban:
        missing[_ENTITY_KEY_IBAN] = reference.iban_masked or "present"
    if observed.iban and observed.iban != reference.iban:
        if _ENTITY_KEY_IBAN not in missing:
            unexpected[_ENTITY_KEY_IBAN] = observed.iban_masked or "present"

    return missing, unexpected


def _later_thread_only(reference: EntitySnapshot, latest: EntitySnapshot) -> dict[str, Any]:
    later: dict[str, Any] = {}
    latest_orders = set(latest.order_ids) - set(reference.order_ids)
    if latest_orders:
        later[_ENTITY_KEY_ORDER] = sorted(latest_orders)
    latest_products = set(latest.product_ids) - set(reference.product_ids)
    if latest_products:
        later[_ENTITY_KEY_PRODUCT] = sorted(latest_products)
    if latest.tracking_code and latest.tracking_code != reference.tracking_code:
        later[_ENTITY_KEY_TRACKING] = latest.tracking_code
    if latest.iban and latest.iban != reference.iban:
        later[_ENTITY_KEY_IBAN] = latest.iban_masked or "present"
    return later


def _has_tracking_keyword(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "کد رهگیری",
        "شماره رهگیری",
        "رهگیری پست",
        "کد پیگیری",
        "tracking",
    )
    return any(marker in lowered for marker in markers)


def _preview_truncated(full_text: str, preview: str | None) -> bool:
    if not preview:
        return False
    if len(full_text) <= OPEN_TICKET_ORIGINAL_MAX_CHARS:
        return False
    return len(preview) >= OPEN_TICKET_ORIGINAL_MAX_CHARS - 3


def _inc_order_ids_in_text(text: str) -> tuple[str, ...]:
    normalized = normalize_digits(text)
    return tuple(
        dict.fromkeys(
            match.group(1)
            for match in re.finditer(r"INC\s*[-_:\s]*(\d{7})(?!\d)", normalized, re.I)
        ),
    )


def classify_entity_extraction_root_cause(
    *,
    missing: dict[str, Any],
    unexpected: dict[str, Any],
    later_thread_only: dict[str, Any],
    reference: EntitySnapshot,
    preview: EntitySnapshot,
    full_first_text: str,
    preview_text: str | None,
    preview_truncated: bool,
) -> EntityExtractionRootCause:
    """Classify likely miss cause from deterministic signals."""
    if not missing and not unexpected:
        if later_thread_only:
            return EntityExtractionRootCause.REVIEW_MISMATCH
        return EntityExtractionRootCause.NOT_REPRODUCIBLE

    if later_thread_only and not missing:
        return EntityExtractionRootCause.REVIEW_MISMATCH

    missing_orders = missing.get(_ENTITY_KEY_ORDER) or []
    full_inc_orders = _inc_order_ids_in_text(full_first_text)
    preview_inc_orders = _inc_order_ids_in_text(preview_text or "")

    if preview_truncated and missing_orders:
        truncated_missing = [oid for oid in missing_orders if oid in full_inc_orders]
        if truncated_missing and any(oid not in preview_inc_orders for oid in truncated_missing):
            return EntityExtractionRootCause.FIRST_TURN_ISOLATION_GAP

    if missing_orders and full_inc_orders:
        norm_full = normalize_digits(full_first_text)
        norm_preview = normalize_digits(preview_text or "")
        for order_id in missing_orders:
            if order_id in full_inc_orders and order_id not in preview_inc_orders:
                if f"INC-{order_id}" in norm_full.upper().replace(" ", "") and (
                    f"INC-{order_id}" not in norm_preview.upper().replace(" ", "")
                ):
                    return EntityExtractionRootCause.FIRST_TURN_ISOLATION_GAP

    if reference.warnings or preview.warnings:
        warning_blob = " ".join(reference.warnings + preview.warnings)
        if "ناقص" in warning_blob or "نامشخص" in warning_blob:
            return EntityExtractionRootCause.AMBIGUOUS_NUMERIC_PATTERN

    if _ENTITY_KEY_TRACKING in missing and _has_tracking_keyword(full_first_text):
        if not re.search(r"\d{15,25}", normalize_digits(full_first_text)):
            return EntityExtractionRootCause.UNSUPPORTED_PATTERN

    if normalize_digits(full_first_text) != normalize_digits(preview_text or "") and missing:
        return EntityExtractionRootCause.NORMALIZATION_GAP

    if missing or unexpected:
        return EntityExtractionRootCause.EXTRACTION_RULE_GAP

    return EntityExtractionRootCause.UNKNOWN


def _build_investigation_notes(
    *,
    root_cause: EntityExtractionRootCause,
    missing: dict[str, Any],
    unexpected: dict[str, Any],
    later_thread_only: dict[str, Any],
    preview_truncated: bool,
    full_chars: int | None,
    preview_chars: int | None,
) -> str:
    parts: list[str] = []
    if missing:
        parts.append(f"missing={json.dumps(missing, ensure_ascii=False)}")
    if unexpected:
        parts.append(f"unexpected={json.dumps(unexpected, ensure_ascii=False)}")
    if later_thread_only:
        parts.append("later_thread_only_entities_present=true")
    if preview_truncated:
        parts.append(
            f"first_turn_preview_truncated=true "
            f"(preview_chars={preview_chars}, full_chars={full_chars}, "
            f"limit={OPEN_TICKET_ORIGINAL_MAX_CHARS})",
        )
    parts.append(f"classified_root_cause={root_cause.value}")
    return "; ".join(parts)


def load_redacted_snapshot(
    room_id: str,
    path: Path | str = DEFAULT_REDACTED_TICKETS_PATH,
) -> ConversationTicketSnapshot | None:
    file_path = Path(path)
    if not file_path.is_file():
        return None
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            snapshot = parse_conversation_ticket_snapshot(line)
        except ValueError:
            continue
        if snapshot.room_id == room_id:
            return snapshot
    return None


def load_replay_row(room_id: str, path: Path | str = DEFAULT_REPLAY_PATH) -> dict[str, Any] | None:
    file_path = Path(path)
    if not file_path.is_file():
        return None
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and str(row.get("room_id")) == room_id:
            return row
    return None


def flagged_entity_review_room_ids(
    feedback_path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    *,
    room_id: str | None = None,
) -> list[str]:
    """Return room_ids with entity_extraction_correct=false (latest review per room)."""
    latest_by_room: dict[str, bool] = {}
    for review in load_agentic_preview_review_rows(feedback_path):
        latest_by_room[review.room_id] = review.entity_extraction_correct
    flagged = [rid for rid, ok in latest_by_room.items() if not ok]
    if room_id is not None:
        rid = str(room_id).strip()
        return [rid] if rid else []
    return sorted(flagged)


def investigate_room_entity_extraction(
    room_id: str,
    *,
    replay_path: Path | str = DEFAULT_REPLAY_PATH,
    redacted_path: Path | str | None = DEFAULT_REDACTED_TICKETS_PATH,
    batch_row: BatchRunRecord | None = None,
    replay_row: dict[str, Any] | None = None,
) -> EntityExtractionInvestigationResult | None:
    """Reconstruct first-turn extraction context and compare expected vs extracted."""
    replay_row = replay_row or load_replay_row(room_id, replay_path)
    snapshot = load_redacted_snapshot(room_id, redacted_path) if redacted_path else None

    full_first_text = ""
    if snapshot is not None:
        full_first_text = _first_vendor_message(snapshot) or ""
    elif replay_row and replay_row.get("original_vendor_issue_preview"):
        full_first_text = str(replay_row["original_vendor_issue_preview"])

    preview_text = None
    if snapshot is not None:
        preview_text = extract_original_vendor_issue(snapshot)
    elif replay_row:
        preview_text = _optional_str(replay_row.get("original_vendor_issue_preview"))

    if not full_first_text and not preview_text:
        return None

    reference = EntitySnapshot.from_extraction(
        extract_operational_entities(full_first_text or preview_text or ""),
    )
    preview_extracted = EntitySnapshot.from_extraction(
        extract_operational_entities(preview_text or full_first_text or ""),
    )

    tickets = load_operator_tickets(
        replay_path,
        redacted_tickets_path=redacted_path,
    )
    ticket = next((item for item in tickets if item.room_id == room_id), None)
    sandbox_entities = preview_extracted
    entity_source = ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    if ticket is not None:
        try:
            ctx = build_first_turn_draft_context_from_ticket(ticket)
            sandbox_entities = EntitySnapshot.from_extraction(ctx.first_turn_entities)
            entity_source = ctx.entity_extraction_source
        except ValueError:
            sandbox_entities = preview_extracted

    missing, unexpected = _entity_diff(reference, sandbox_entities)

    latest_text = ""
    if snapshot is not None:
        latest_text = extract_latest_vendor_message(snapshot) or ""
    elif ticket is not None and ticket.latest_vendor_message:
        latest_text = ticket.latest_vendor_message
    latest_entities = EntitySnapshot.from_extraction(extract_operational_entities(latest_text))
    later_only = _later_thread_only(reference, latest_entities)

    truncated = _preview_truncated(full_first_text, preview_text)
    root_cause = classify_entity_extraction_root_cause(
        missing=missing,
        unexpected=unexpected,
        later_thread_only=later_only,
        reference=reference,
        preview=sandbox_entities,
        full_first_text=full_first_text,
        preview_text=preview_text,
        preview_truncated=truncated,
    )

    replay_entities = EntitySnapshot.from_replay_row(replay_row) if replay_row else None
    detected_intent = batch_row.detected_intent if batch_row else None
    conceptual = batch_row.conceptual_intent_fa if batch_row else None
    if ticket and ticket.detected_intent:
        detected_intent = detected_intent or ticket.detected_intent

    notes = _build_investigation_notes(
        root_cause=root_cause,
        missing=missing,
        unexpected=unexpected,
        later_thread_only=later_only,
        preview_truncated=truncated,
        full_chars=len(full_first_text) if full_first_text else None,
        preview_chars=len(preview_text) if preview_text else None,
    )

    reproducible = bool(missing or unexpected)
    if root_cause == EntityExtractionRootCause.NOT_REPRODUCIBLE:
        reproducible = False

    return EntityExtractionInvestigationResult(
        room_id=room_id,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual,
        entity_source=entity_source,
        expected_entities=reference.to_json_dict(),
        extracted_entities=sandbox_entities.to_json_dict(),
        missing_entities=missing,
        unexpected_entities=unexpected,
        likely_root_cause=root_cause.value,
        investigation_notes=notes,
        reproducible=reproducible,
        later_thread_only_entities=later_only,
        replay_entities=replay_entities.to_json_dict() if replay_entities else None,
        batch_order_id_count=batch_row.order_id_count if batch_row else None,
        first_turn_preview_truncated=truncated,
        first_turn_full_char_count=len(full_first_text) if full_first_text else None,
        first_turn_preview_char_count=len(preview_text) if preview_text else None,
    )


def _advisory_improvements(
    investigations: list[EntityExtractionInvestigationResult],
) -> tuple[str, ...]:
    causes = {item.likely_root_cause for item in investigations}
    tips: list[str] = []
    if EntityExtractionRootCause.FIRST_TURN_ISOLATION_GAP.value in causes:
        tips.append(
            "Advisory: confirm operator tickets attach full_first_vendor_message_text "
            f"({ENTITY_SOURCE_FULL_FIRST_VENDOR}) from redacted export; UI/draft "
            "previews may stay truncated while extraction uses the full first seller message.",
        )
    if EntityExtractionRootCause.EXTRACTION_RULE_GAP.value in causes:
        tips.append(
            "Advisory: extend deterministic extractor patterns for missed INC/order "
            "variants after investigation sign-off.",
        )
    if EntityExtractionRootCause.UNSUPPORTED_PATTERN.value in causes:
        tips.append(
            "Advisory: tracking keywords without a complete numeric code may need "
            "incomplete-tracking candidate handling in a future step.",
        )
    if EntityExtractionRootCause.REVIEW_MISMATCH.value in causes:
        tips.append(
            "Advisory: confirm reviewer compared sandbox first-turn entities only, "
            "not later-thread or open-snapshot fields.",
        )
    return tuple(dict.fromkeys(tips))


def summarize_entity_extraction_investigations(
    investigations: list[EntityExtractionInvestigationResult],
    *,
    source_feedback_path: str,
    source_batch_runs_path: str,
    source_replay_path: str,
    source_redacted_path: str | None,
    flagged_review_count: int,
    generated_at_utc: str | None = None,
) -> EntityExtractionInvestigationSummary:
    root_cause_counts: dict[str, int] = {}
    for item in investigations:
        root_cause_counts[item.likely_root_cause] = (
            root_cause_counts.get(item.likely_root_cause, 0) + 1
        )
    return EntityExtractionInvestigationSummary(
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_feedback_path=source_feedback_path,
        source_batch_runs_path=source_batch_runs_path,
        source_replay_path=source_replay_path,
        source_redacted_path=source_redacted_path,
        investigated_room_count=len(investigations),
        flagged_review_count=flagged_review_count,
        root_cause_counts=root_cause_counts,
        investigations=tuple(investigations),
        advisory_improvements=_advisory_improvements(investigations),
    )


def render_entity_extraction_investigation_markdown(
    summary: EntityExtractionInvestigationSummary,
) -> str:
    """Render investigation markdown (safe fields only)."""
    lines = [
        "# Entity Extraction Investigation Report",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Feedback source:** `{summary.source_feedback_path}`  ",
        f"**Batch runs:** `{summary.source_batch_runs_path}`  ",
        "**Scope:** Diagnostics only — no extractor or graph behavior changes.",
        "",
        "## Summary",
        "",
        f"- **flagged_reviews:** {summary.flagged_review_count}",
        f"- **investigated_rooms:** {summary.investigated_room_count}",
        "",
        "## Root cause counts",
        "",
        "| Root cause | Rooms |",
        "|------------|------:|",
    ]
    if summary.root_cause_counts:
        for cause, count in sorted(summary.root_cause_counts.items()):
            lines.append(f"| `{cause}` | {count} |")
    else:
        lines.append("| *(none)* | 0 |")

    lines.extend(["", "## Investigated rooms", ""])
    if not summary.investigations:
        lines.append("*(No flagged rooms investigated.)*")
    else:
        for item in summary.investigations:
            lines.extend(
                [
                    f"### Room `{item.room_id}`",
                    "",
                    f"- **detected_intent:** `{item.detected_intent or '—'}`",
                    f"- **conceptual_intent_fa:** {item.conceptual_intent_fa or '—'}",
                    f"- **entity_source:** `{item.entity_source}`",
                    f"- **likely_root_cause:** `{item.likely_root_cause}`",
                    f"- **reproducible:** {item.reproducible}",
                    f"- **first_turn_preview_truncated:** {item.first_turn_preview_truncated}",
                    "",
                    "**Expected (full first vendor message):**",
                    f"- order_ids: `{item.expected_entities.get('order_ids', [])}`",
                    f"- product_ids: `{item.expected_entities.get('product_ids', [])}`",
                    f"- tracking_code: `{item.expected_entities.get('tracking_code') or '—'}`",
                    f"- iban_masked: `{item.expected_entities.get('iban_masked') or '—'}`",
                    "",
                    "**Extracted (sandbox first-turn path):**",
                    f"- order_ids: `{item.extracted_entities.get('order_ids', [])}`",
                    f"- product_ids: `{item.extracted_entities.get('product_ids', [])}`",
                    f"- tracking_code: `{item.extracted_entities.get('tracking_code') or '—'}`",
                    f"- iban_masked: `{item.extracted_entities.get('iban_masked') or '—'}`",
                    "",
                    f"- **missing_entities:** "
                    f"`{json.dumps(item.missing_entities, ensure_ascii=False)}`",
                    f"- **unexpected_entities:** "
                    f"`{json.dumps(item.unexpected_entities, ensure_ascii=False)}`",
                ],
            )
            if item.later_thread_only_entities:
                lines.append(
                    f"- **later_thread_only_entities:** "
                    f"`{json.dumps(item.later_thread_only_entities, ensure_ascii=False)}`",
                )
            if item.replay_entities:
                lines.append(
                    f"- **replay_open_snapshot_entities:** "
                    f"orders=`{item.replay_entities.get('order_ids', [])}` "
                    f"tracking=`{item.replay_entities.get('tracking_code') or '—'}`",
                )
            if item.batch_order_id_count is not None:
                lines.append(f"- **batch_order_id_count:** {item.batch_order_id_count}")
            lines.append(f"- **investigation_notes:** {item.investigation_notes}")
            lines.append("")

    lines.extend(["", "## Reproducibility", ""])
    reproducible = [item.room_id for item in summary.investigations if item.reproducible]
    if reproducible:
        lines.append(f"Reproducible misses: `{', '.join(reproducible)}`")
    else:
        lines.append("No reproducible entity miss pattern in investigated set.")

    lines.extend(["", "## Candidate future improvements (advisory only)", ""])
    if summary.advisory_improvements:
        for tip in summary.advisory_improvements:
            lines.append(f"- {tip}")
    else:
        lines.append("*(No advisory items — no flagged misses or all review mismatches.)*")

    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Investigation only — does not modify extraction rules or graph behavior.",
            "- No prompts, raw transcripts, secrets, or retrieval snippets in this report.",
            "",
        ],
    )
    return "\n".join(lines)


def assert_entity_extraction_investigation_output_safe(content: str) -> None:
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(
                f"entity extraction investigation output must not contain forbidden token: {token}",
            )
    for token in (
        "conversation transcript",
        "gold_reference_reply",
        '"messages"',
        "raw_prompt",
        "retrieved_context",
    ):
        if token in lowered:
            raise ValueError(
                f"entity extraction investigation output must not contain forbidden token: {token}",
            )
    if re.search(r"sk-[a-z0-9]{8,}", content, flags=re.IGNORECASE):
        raise ValueError("investigation output must not contain API key patterns")


def build_entity_extraction_investigation_report(
    *,
    feedback_path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    batch_runs_path: Path | str = DEFAULT_BATCH_RUNS_JSONL,
    replay_path: Path | str = DEFAULT_REPLAY_PATH,
    redacted_path: Path | str | None = DEFAULT_REDACTED_TICKETS_PATH,
    room_id: str | None = None,
    summary_output: Path = DEFAULT_INVESTIGATION_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_INVESTIGATION_REPORT_PATH,
    generated_at_utc: str | None = None,
) -> EntityExtractionInvestigationSummary:
    """Investigate flagged preview entity misses and write JSON + markdown reports."""
    flagged = flagged_entity_review_room_ids(feedback_path, room_id=room_id)
    batch_index = {row.room_id: row for row in load_batch_run_records(batch_runs_path)}

    investigations: list[EntityExtractionInvestigationResult] = []
    for rid in flagged:
        result = investigate_room_entity_extraction(
            rid,
            replay_path=replay_path,
            redacted_path=redacted_path,
            batch_row=batch_index.get(rid),
            replay_row=load_replay_row(rid, replay_path),
        )
        if result is not None:
            investigations.append(result)

    summary = summarize_entity_extraction_investigations(
        investigations,
        source_feedback_path=str(feedback_path),
        source_batch_runs_path=str(batch_runs_path),
        source_replay_path=str(replay_path),
        source_redacted_path=str(redacted_path) if redacted_path else None,
        flagged_review_count=len(flagged),
        generated_at_utc=generated_at_utc,
    )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_entity_extraction_investigation_markdown(summary)

    assert_entity_extraction_investigation_output_safe(json_text)
    assert_entity_extraction_investigation_output_safe(markdown)

    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary

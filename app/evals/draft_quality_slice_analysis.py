"""Slice-based draft quality analysis from operator review feedback (advisory only)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evals.draft_review_metrics import (
    _entity_applicable_rows,
    _rate,
    detect_failure_patterns,
)
from app.operator_console.draft_review_feedback import (
    _FORBIDDEN_TEXT_SUBSTRINGS,
    DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
    DraftReviewFeedback,
    load_draft_review_feedback_rows,
)

DEFAULT_SLICE_SUMMARY_PATH = Path("reports/draft_quality_slice_analysis_summary.json")
DEFAULT_SLICE_REPORT_PATH = Path("reports/draft_quality_slice_analysis_report.md")

DEFAULT_MIN_SLICE_REVIEWS = 3
DEFAULT_USABLE_WEAK_THRESHOLD = 0.6
DEFAULT_ACTION_ACCURACY_WEAK_THRESHOLD = 0.7
DEFAULT_ENTITY_ACCURACY_WEAK_THRESHOLD = 0.7
DEFAULT_MONITOR_USAGE_WEAK_THRESHOLD = 0.35

_ORDER_ACTIONS = frozenset(
    {
        "update_delivery_status",
        "check_order_status",
        "check_return_request",
        "human_followup",
        "record_update",
    },
)
_PRODUCT_ACTIONS = frozenset(
    {
        "check_product_approval",
        "review_product_edit",
    },
)

_SLICE_DIMENSIONS = (
    "detected_intent",
    "conceptual_intent_fa",
    "suggested_action",
    "ticket_label",
    "route_label",
    "entity_presence",
    "actionability",
)

_EXTRA_FAILURE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("weak_clarification", ("clarification", "واضح", "مبهم", "گنگ", "نامفهوم", "شناسه لازم")),
    (
        "incorrect_identifier_handling",
        ("شناسه", "شماره سفارش", "شناسه کالا", "کد رهگیری", "identifier", "order id"),
    ),
    ("unnecessary_followup", ("followup", "پیگیری اضاف", "جمله اضاف", "فالوآپ")),
)

_FAILURE_PATTERN_LABELS: dict[str, str] = {
    "action_mismatch": "wrong action",
    "wrong_intent": "wrong intent",
    "missing_entity": "missing entities",
    "verbose_draft": "verbose",
    "hallucination": "hallucination",
    "not_usable": "not usable",
    "unclear_reply": "weak clarification",
    "policy_misunderstanding": "policy misunderstanding",
    "weak_clarification": "weak clarification",
    "incorrect_identifier_handling": "incorrect identifier handling",
    "unnecessary_followup": "unnecessary followup",
}


@dataclass(frozen=True)
class DraftQualitySliceReport:
    """Quality metrics for one slice (dimension + key)."""

    slice_type: str
    slice_key: str
    total_reviews: int
    usable_rate: float
    hallucination_rate: float
    action_accuracy_rate: float
    intent_accuracy_rate: float
    entity_accuracy_rate: float
    unnecessary_followup_rate: float
    monitor_usage_rate: float
    common_failure_patterns: tuple[tuple[str, int], ...]
    is_weak: bool = False
    weakness_reasons: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "slice_type": self.slice_type,
            "slice_key": self.slice_key,
            "total_reviews": self.total_reviews,
            "usable_rate": self.usable_rate,
            "hallucination_rate": self.hallucination_rate,
            "action_accuracy_rate": self.action_accuracy_rate,
            "intent_accuracy_rate": self.intent_accuracy_rate,
            "entity_accuracy_rate": self.entity_accuracy_rate,
            "unnecessary_followup_rate": self.unnecessary_followup_rate,
            "monitor_usage_rate": self.monitor_usage_rate,
            "common_failure_patterns": [
                {"pattern_id": pattern_id, "count": count}
                for pattern_id, count in self.common_failure_patterns
            ],
            "is_weak": self.is_weak,
            "weakness_reasons": list(self.weakness_reasons),
        }


@dataclass(frozen=True)
class DraftQualitySliceSummary:
    """Aggregate slice analysis for draft calibration targeting."""

    total_reviews: int
    overall_usable_rate: float
    slice_reports: tuple[DraftQualitySliceReport, ...]
    weakest_slices: tuple[DraftQualitySliceReport, ...]
    strongest_slices: tuple[DraftQualitySliceReport, ...]
    recommended_calibration_targets: tuple[str, ...]
    generated_at_utc: str = ""
    source_feedback_path: str = ""
    enrichment_source_path: str | None = None
    min_slice_reviews: int = DEFAULT_MIN_SLICE_REVIEWS

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_feedback_path": self.source_feedback_path,
            "enrichment_source_path": self.enrichment_source_path,
            "min_slice_reviews": self.min_slice_reviews,
            "total_reviews": self.total_reviews,
            "overall_usable_rate": self.overall_usable_rate,
            "slice_reports": [report.to_json_dict() for report in self.slice_reports],
            "weakest_slices": [report.to_json_dict() for report in self.weakest_slices],
            "strongest_slices": [report.to_json_dict() for report in self.strongest_slices],
            "recommended_calibration_targets": list(self.recommended_calibration_targets),
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _dimension_key(value: str | None, *, default: str = "(none)") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _entity_accuracy_rate(rows: list[DraftReviewFeedback]) -> float:
    applicable = _entity_applicable_rows(rows)
    correct = sum(1 for row in applicable if row.entities_correct is True)
    return _rate(correct, len(applicable))


def _extended_failure_patterns(row: DraftReviewFeedback) -> list[str]:
    patterns = detect_failure_patterns(row)
    if row.unnecessary_followup_detected and "unnecessary_followup" not in patterns:
        patterns.append("unnecessary_followup")
    note = (row.reviewer_note or "").strip().lower()
    if note:
        for pattern_id, keywords in _EXTRA_FAILURE_PATTERNS:
            if any(keyword in note for keyword in keywords):
                if pattern_id not in patterns:
                    patterns.append(pattern_id)
    return patterns


def load_draft_enrichment_index(
    path: Path | str | None,
) -> dict[str, dict[str, Any]]:
    """Index offline draft JSONL rows by ``room_id`` (optional enrichment)."""
    if path is None:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    index: dict[str, dict[str, Any]] = {}
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        room_id = row.get("room_id")
        if not isinstance(room_id, str) or not room_id.strip():
            continue
        key = room_id.strip()
        candidate = {
            "route_label": row.get("route_label"),
            "draft_extracted_order_ids": row.get("draft_extracted_order_ids"),
            "draft_extracted_product_ids": row.get("draft_extracted_product_ids"),
            "draft_extracted_tracking_code": row.get("draft_extracted_tracking_code"),
            "actionability_actionable": row.get("actionability_actionable"),
            "requires_identifier_request": row.get("requires_identifier_request"),
            "actionability_missing_entities": row.get("actionability_missing_entities"),
        }
        existing = index.get(key)
        if (
            existing is None
            or bool(row.get("draft_generated"))
            and not bool(
                existing.get("draft_generated"),
            )
        ):
            index[key] = candidate
    return index


def _enrichment_for_row(
    row: DraftReviewFeedback,
    enrichment_index: Mapping[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return enrichment_index.get(row.room_id.strip())


def _has_csv_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text)


def entity_presence_slice_key(
    row: DraftReviewFeedback,
    enrichment: dict[str, Any] | None,
) -> str:
    """Single entity-presence bucket per review."""
    if enrichment:
        has_order = _has_csv_value(enrichment.get("draft_extracted_order_ids"))
        has_product = _has_csv_value(enrichment.get("draft_extracted_product_ids"))
        has_tracking = _has_csv_value(enrichment.get("draft_extracted_tracking_code"))
        if not has_order and not has_product and not has_tracking:
            return "no_entities"
        if has_tracking:
            return "has_tracking"
        if has_product:
            return "has_product_id"
        if has_order:
            return "has_order_id"
        return "no_entities"

    if not row.entities_applicable:
        return "no_entities"
    action = (row.suggested_action or "").strip().lower()
    if action in _PRODUCT_ACTIONS:
        return "has_product_id" if row.entities_correct is True else "no_entities"
    if action in _ORDER_ACTIONS:
        return "has_order_id" if row.entities_correct is True else "no_entities"
    if row.entities_correct is True:
        return "has_order_id"
    return "no_entities"


def actionability_slice_key(
    row: DraftReviewFeedback,
    enrichment: dict[str, Any] | None,
) -> str:
    if enrichment is not None:
        if enrichment.get("requires_identifier_request") is True:
            return "missing_identifiers"
        actionable = enrichment.get("actionability_actionable")
        if actionable is True:
            return "actionable"
        if actionable is False:
            return "missing_identifiers"
    action = (row.suggested_action or "").strip().lower()
    if action == "monitor":
        return "actionable"
    if action == "request_missing_info":
        return "missing_identifiers"
    if row.entities_applicable and row.entities_correct is False:
        return "missing_identifiers"
    if not row.entities_applicable and action in _ORDER_ACTIONS | _PRODUCT_ACTIONS:
        return "missing_identifiers"
    return "actionable"


def route_label_slice_key(
    row: DraftReviewFeedback,
    enrichment: dict[str, Any] | None,
) -> str:
    if enrichment and enrichment.get("route_label"):
        return _dimension_key(str(enrichment.get("route_label")))
    return "(unknown)"


def _slice_keys_for_row(
    row: DraftReviewFeedback,
    enrichment_index: Mapping[str, dict[str, Any]],
) -> dict[str, str]:
    enrichment = _enrichment_for_row(row, enrichment_index)
    return {
        "detected_intent": _dimension_key(row.detected_intent),
        "conceptual_intent_fa": _dimension_key(row.conceptual_intent_fa),
        "suggested_action": _dimension_key(row.suggested_action),
        "ticket_label": _dimension_key(row.ticket_label),
        "route_label": route_label_slice_key(row, enrichment),
        "entity_presence": entity_presence_slice_key(row, enrichment),
        "actionability": actionability_slice_key(row, enrichment),
    }


def _build_slice_report(
    slice_type: str,
    slice_key: str,
    rows: list[DraftReviewFeedback],
    *,
    min_slice_reviews: int,
    usable_weak: float,
    action_weak: float,
    entity_weak: float,
    monitor_weak: float,
) -> DraftQualitySliceReport:
    total = len(rows)
    failure_counter: Counter[str] = Counter()
    for row in rows:
        failure_counter.update(_extended_failure_patterns(row))

    monitor_count = sum(
        1 for row in rows if (row.suggested_action or "").strip().lower() == "monitor"
    )
    weakness_reasons: list[str] = []
    usable_rate = _rate(sum(1 for row in rows if row.draft_usable), total)
    action_accuracy = _rate(sum(1 for row in rows if row.action_correct), total)
    entity_accuracy = _entity_accuracy_rate(rows)
    hallucination_rate = _rate(sum(1 for row in rows if row.hallucination_detected), total)
    intent_accuracy = _rate(sum(1 for row in rows if row.intent_correct), total)
    followup_rate = _rate(
        sum(1 for row in rows if row.unnecessary_followup_detected),
        total,
    )
    monitor_usage = _rate(monitor_count, total)

    if total >= min_slice_reviews:
        if usable_rate < usable_weak:
            weakness_reasons.append("low_usable_rate")
        if action_accuracy < action_weak:
            weakness_reasons.append("low_action_accuracy")
        if entity_accuracy < entity_weak and any(row.entities_applicable for row in rows):
            weakness_reasons.append("low_entity_accuracy")
        if monitor_usage >= monitor_weak and slice_key != "monitor":
            weakness_reasons.append("high_monitor_usage")
        top_failures = [pid for pid, _ in failure_counter.most_common(2)]
        if failure_counter.get("not_usable", 0) >= max(2, total // 2):
            weakness_reasons.append("repeated_not_usable")
        if failure_counter.get("action_mismatch", 0) >= max(2, total // 3):
            weakness_reasons.append("repeated_action_mismatch")
        if failure_counter.get("missing_entity", 0) >= max(2, total // 3):
            weakness_reasons.append("repeated_missing_entity")
        if (
            failure_counter.get("incorrect_identifier_handling", 0) >= 2
            or failure_counter.get("weak_clarification", 0) >= 2
        ):
            weakness_reasons.append("identifier_or_clarification_issues")
        _ = top_failures

    common = tuple(
        (pattern_id, count) for pattern_id, count in failure_counter.most_common(5) if count > 0
    )

    return DraftQualitySliceReport(
        slice_type=slice_type,
        slice_key=slice_key,
        total_reviews=total,
        usable_rate=usable_rate,
        hallucination_rate=hallucination_rate,
        action_accuracy_rate=action_accuracy,
        intent_accuracy_rate=intent_accuracy,
        entity_accuracy_rate=entity_accuracy,
        unnecessary_followup_rate=followup_rate,
        monitor_usage_rate=monitor_usage,
        common_failure_patterns=common,
        is_weak=bool(weakness_reasons),
        weakness_reasons=tuple(dict.fromkeys(weakness_reasons)),
    )


def _rank_eligible_slices(
    reports: list[DraftQualitySliceReport],
    *,
    min_slice_reviews: int,
) -> list[DraftQualitySliceReport]:
    eligible = [
        report
        for report in reports
        if report.total_reviews >= min_slice_reviews and report.slice_key != "(none)"
    ]
    return eligible


def build_calibration_target(report: DraftQualitySliceReport) -> str | None:
    """Advisory-only calibration hint from a weak slice."""
    if not report.is_weak:
        return None
    label = report.slice_key
    usable_pct = f"{report.usable_rate:.0%}"
    if report.slice_type == "conceptual_intent_fa":
        return (
            f'"{label}" conceptual-intent slice has low usable rate ({usable_pct}) '
            "→ review prompts/phrasing for this operational intent family"
        )
    if report.slice_type == "detected_intent":
        return (
            f"`{label}` detected-intent slice is fragile (usable {usable_pct}, "
            f"intent accuracy {report.intent_accuracy_rate:.0%}) "
            "→ inspect intent detection + draft templates for this intent"
        )
    if report.slice_type == "suggested_action":
        if label == "monitor":
            return (
                f"`monitor` slice still weak (usable {usable_pct}) "
                "→ inspect fallback routing and monitor suppression boundaries"
            )
        if "entity" in report.weakness_reasons or report.entity_accuracy_rate < 0.7:
            return (
                f"`{label}` slice has low entity accuracy "
                f"({report.entity_accuracy_rate:.0%}) "
                "→ improve product/order/tracking extraction for this action"
            )
        return (
            f"`{label}` action slice underperforms (usable {usable_pct}, "
            f"action accuracy {report.action_accuracy_rate:.0%}) "
            "→ review action-specific draft guidance"
        )
    if report.slice_type == "entity_presence":
        if label == "no_entities":
            return (
                "Tickets without extracted entities show weak drafts "
                f"(usable {usable_pct}) → verify identifier-request drafts (Step 191)"
            )
        return (
            f"Entity slice `{label}` is weak (usable {usable_pct}) "
            "→ check drafts when this entity type is present"
        )
    if report.slice_type == "actionability":
        if label == "missing_identifiers":
            return (
                "Missing-identifier actionability slice is weak "
                f"(usable {usable_pct}) → calibrate identifier-request wording "
                "and block fake operational claims"
            )
        return (
            f"Actionable slice `{label}` usable rate {usable_pct} "
            "→ review operational closure language"
        )
    if report.slice_type == "ticket_label":
        return (
            f"Ticket label `{label}` category underperforms (usable {usable_pct}) "
            "→ review category-specific calibration"
        )
    if report.slice_type == "route_label":
        return (
            f"Route `{label}` underperforms (usable {usable_pct}) "
            "→ inspect routing + draft pairing for this route"
        )
    return (
        f"{report.slice_type}/{label} slice is weak (usable {usable_pct}) "
        "→ manual calibration review"
    )


def compute_draft_quality_slice_analysis(
    rows: list[DraftReviewFeedback],
    *,
    enrichment_index: Mapping[str, dict[str, Any]] | None = None,
    source_feedback_path: str = "",
    enrichment_source_path: str | None = None,
    generated_at_utc: str | None = None,
    min_slice_reviews: int = DEFAULT_MIN_SLICE_REVIEWS,
    usable_weak_threshold: float = DEFAULT_USABLE_WEAK_THRESHOLD,
    action_accuracy_weak_threshold: float = DEFAULT_ACTION_ACCURACY_WEAK_THRESHOLD,
    entity_accuracy_weak_threshold: float = DEFAULT_ENTITY_ACCURACY_WEAK_THRESHOLD,
    monitor_usage_weak_threshold: float = DEFAULT_MONITOR_USAGE_WEAK_THRESHOLD,
) -> DraftQualitySliceSummary:
    """Compute slice reports and weak/strong rankings from review feedback."""
    enrichment = enrichment_index or {}
    buckets: dict[tuple[str, str], list[DraftReviewFeedback]] = defaultdict(list)

    for row in rows:
        keys = _slice_keys_for_row(row, enrichment)
        for slice_type, slice_key in keys.items():
            buckets[(slice_type, slice_key)].append(row)

    reports: list[DraftQualitySliceReport] = []
    for (slice_type, slice_key), bucket in sorted(buckets.items()):
        reports.append(
            _build_slice_report(
                slice_type,
                slice_key,
                bucket,
                min_slice_reviews=min_slice_reviews,
                usable_weak=usable_weak_threshold,
                action_weak=action_accuracy_weak_threshold,
                entity_weak=entity_accuracy_weak_threshold,
                monitor_weak=monitor_usage_weak_threshold,
            ),
        )

    eligible = _rank_eligible_slices(reports, min_slice_reviews=min_slice_reviews)
    weakest = tuple(
        sorted(
            [report for report in eligible if report.is_weak],
            key=lambda report: (report.usable_rate, report.action_accuracy_rate),
        )[:10],
    )
    if not weakest:
        weakest = tuple(
            sorted(eligible, key=lambda report: report.usable_rate)[:5],
        )

    strongest = tuple(
        sorted(
            eligible,
            key=lambda report: (-report.usable_rate, -report.action_accuracy_rate),
        )[:5],
    )

    targets: list[str] = []
    seen_targets: set[str] = set()
    for report in sorted(
        [r for r in eligible if r.is_weak],
        key=lambda item: item.usable_rate,
    ):
        target = build_calibration_target(report)
        if target and target not in seen_targets:
            seen_targets.add(target)
            targets.append(target)
    if not targets and rows:
        targets.append(
            "No weak slices met thresholds with minimum review count — "
            "continue sampling operational tickets in the operator console.",
        )

    overall_usable = _rate(sum(1 for row in rows if row.draft_usable), len(rows))

    return DraftQualitySliceSummary(
        total_reviews=len(rows),
        overall_usable_rate=overall_usable,
        slice_reports=tuple(reports),
        weakest_slices=weakest,
        strongest_slices=strongest,
        recommended_calibration_targets=tuple(targets[:12]),
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_feedback_path=source_feedback_path,
        enrichment_source_path=enrichment_source_path,
        min_slice_reviews=min_slice_reviews,
    )


def _failure_pattern_display(pattern_id: str) -> str:
    return _FAILURE_PATTERN_LABELS.get(pattern_id, pattern_id)


def format_draft_quality_slice_markdown(summary: DraftQualitySliceSummary) -> str:
    """Render offline markdown slice report (metrics only; no ticket text)."""
    lines = [
        "# Draft Quality Slice Analysis",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Source:** `{summary.source_feedback_path}`  ",
    ]
    if summary.enrichment_source_path:
        lines.append(f"**Enrichment:** `{summary.enrichment_source_path}`  ")
    lines.extend(
        [
            f"**Min reviews per slice:** {summary.min_slice_reviews}  ",
            "**Scope:** Analytics only — no prompt/mapping/behavior changes.",
            "",
            "## Overall",
            "",
            f"- **total_reviews:** {summary.total_reviews}",
            f"- **overall_usable_rate:** {summary.overall_usable_rate:.1%}",
            "",
        ],
    )

    if summary.total_reviews == 0:
        lines.extend(
            [
                "*(No draft reviews in source file yet.)*",
                "",
                "## Governance",
                "",
                "- Slice analysis uses local `draft_review_feedback.jsonl` only.",
                "- No full ticket text, prompts, transcripts, or retrieval payloads.",
                "- Recommended targets are advisory — manual calibration only.",
                "",
            ],
        )
        return "\n".join(lines)

    lines.extend(["## Strongest slices (usable rate)", ""])
    if summary.strongest_slices:
        lines.extend(
            [
                "| Type | Slice | Reviews | Usable | Action acc. | Entity acc. |",
                "|------|-------|--------:|-------:|------------:|------------:|",
            ],
        )
        for report in summary.strongest_slices:
            lines.append(
                f"| {report.slice_type} | {report.slice_key[:48]} | "
                f"{report.total_reviews} | {report.usable_rate:.1%} | "
                f"{report.action_accuracy_rate:.1%} | {report.entity_accuracy_rate:.1%} |",
            )
    else:
        lines.append("*(No slices met minimum review count.)*")
    lines.append("")

    lines.extend(["## Weakest slices", ""])
    if summary.weakest_slices:
        lines.extend(
            [
                "| Type | Slice | Reviews | Usable | Weak reasons | Top failures |",
                "|------|-------|--------:|-------:|--------------|--------------|",
            ],
        )
        for report in summary.weakest_slices:
            reasons = ", ".join(report.weakness_reasons) or "—"
            failures = ", ".join(
                f"{_failure_pattern_display(pid)} ({count})"
                for pid, count in report.common_failure_patterns[:3]
            )
            lines.append(
                f"| {report.slice_type} | {report.slice_key[:40]} | "
                f"{report.total_reviews} | {report.usable_rate:.1%} | {reasons} | "
                f"{failures or '—'} |",
            )
    else:
        lines.append("*(No weak slices detected at current thresholds.)*")
    lines.append("")

    def _section_slices(slice_type: str, title: str) -> None:
        lines.extend([f"## {title}", ""])
        typed = [
            report
            for report in summary.slice_reports
            if report.slice_type == slice_type and report.total_reviews >= summary.min_slice_reviews
        ]
        typed.sort(key=lambda item: item.usable_rate)
        if not typed:
            lines.append("*(No slices with enough reviews.)*")
            lines.append("")
            return
        lines.extend(
            [
                "| Slice | Reviews | Usable | Halluc. | Action | Intent | Entity | Monitor % |",
                "|-------|--------:|-------:|--------:|-------:|-------:|-------:|----------:|",
            ],
        )
        for report in typed[:15]:
            lines.append(
                f"| {report.slice_key[:44]} | {report.total_reviews} | "
                f"{report.usable_rate:.1%} | {report.hallucination_rate:.1%} | "
                f"{report.action_accuracy_rate:.1%} | {report.intent_accuracy_rate:.1%} | "
                f"{report.entity_accuracy_rate:.1%} | {report.monitor_usage_rate:.1%} |",
            )
        lines.append("")

    _section_slices("detected_intent", "Quality by detected intent")
    _section_slices("conceptual_intent_fa", "Quality by conceptual intent (fa)")
    _section_slices("suggested_action", "Quality by suggested action")
    _section_slices("ticket_label", "Quality by ticket label")
    _section_slices("route_label", "Quality by route label")
    _section_slices("entity_presence", "Entity-related quality")
    _section_slices("actionability", "Actionable vs missing identifiers")

    lines.extend(["## Recommended calibration targets (advisory)", ""])
    for index, target in enumerate(summary.recommended_calibration_targets, start=1):
        lines.append(f"{index}. {target}")
    lines.append("")

    lines.extend(
        [
            "## Governance",
            "",
            "- Slice analysis identifies fragile intents/actions — **no** auto-calibration.",
            "- Pair with `build_draft_review_metrics_report.py` and "
            "`build_action_mismatch_analysis.py` for context.",
            "- No full drafts, prompts, transcripts, or retrieval snippets in this report.",
            "",
        ],
    )
    return "\n".join(lines)


def assert_slice_analysis_output_safe(content: str) -> None:
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"slice analysis output must not contain forbidden token: {token}")


def build_draft_quality_slice_analysis_report(
    feedback_path: Path | str = DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
    *,
    enrichment_path: Path | str | None = None,
    summary_output: Path = DEFAULT_SLICE_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_SLICE_REPORT_PATH,
    generated_at_utc: str | None = None,
    min_slice_reviews: int = DEFAULT_MIN_SLICE_REVIEWS,
) -> DraftQualitySliceSummary:
    """Load feedback JSONL and write slice analysis JSON + markdown."""
    source = Path(feedback_path)
    rows = load_draft_review_feedback_rows(source)
    enrichment_source: str | None = None
    enrichment_index: dict[str, dict[str, Any]] = {}
    if enrichment_path is not None:
        enrichment_index = load_draft_enrichment_index(enrichment_path)
        if Path(enrichment_path).is_file():
            enrichment_source = str(enrichment_path)

    summary = compute_draft_quality_slice_analysis(
        rows,
        enrichment_index=enrichment_index,
        source_feedback_path=str(source),
        enrichment_source_path=enrichment_source,
        generated_at_utc=generated_at_utc,
        min_slice_reviews=min_slice_reviews,
    )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = format_draft_quality_slice_markdown(summary)

    assert_slice_analysis_output_safe(json_text)
    assert_slice_analysis_output_safe(markdown)

    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary

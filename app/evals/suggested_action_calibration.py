"""Analyze suggested_action quality from draft review feedback (calibration only)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.operator_console.draft_review_feedback import (
    _FORBIDDEN_TEXT_SUBSTRINGS,
    DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
    DraftReviewFeedback,
    load_draft_review_feedback_rows,
)
from app.workflows.suggested_action_taxonomy import (
    _DELIVERY_CONCEPTUAL_MARKERS,
    _ORDER_STATUS_CONCEPTUAL_MARKERS,
    _PRODUCT_APPROVAL_CONCEPTUAL_MARKERS,
    _PRODUCT_EDIT_MARKERS,
    _RETURN_REFUND_MARKERS,
)

DEFAULT_CALIBRATION_SUMMARY_PATH = Path("reports/suggested_action_calibration_summary.json")
DEFAULT_CALIBRATION_REPORT_PATH = Path("reports/suggested_action_calibration_report.md")

_FALLBACK_ACTIONS = frozenset({"monitor", "human_followup"})

_OPERATIONAL_CONCEPTUAL_MARKERS = (
    *_DELIVERY_CONCEPTUAL_MARKERS,
    *_ORDER_STATUS_CONCEPTUAL_MARKERS,
    *_PRODUCT_APPROVAL_CONCEPTUAL_MARKERS,
    *_PRODUCT_EDIT_MARKERS,
    *_RETURN_REFUND_MARKERS,
    "ثبت تحویل سفارش",
    "درخواست تایید کالا",
    "تایید کالا",
    "پیگیری سفارش",
)

_INTENT_PREFERRED_ACTION_HINTS: tuple[tuple[str, str, str], ...] = (
    (
        "delivery_confirmation_request",
        "update_delivery_status",
        "delivery_confirmation_request should prefer update_delivery_status over monitor",
    ),
    (
        "settlement_status_inquiry",
        "check_settlement_status",
        "settlement_status_inquiry should prefer check_settlement_status over monitor",
    ),
    (
        "product_approval_review",
        "check_product_approval",
        "product approval tickets should avoid monitor; prefer check_product_approval",
    ),
    (
        "order_status_review",
        "check_order_status",
        "order_status_review should prefer check_order_status over monitor",
    ),
    (
        "complaint_escalation",
        "escalate",
        "complaint_escalation should prefer escalate over monitor or human_followup",
    ),
    (
        "seller_operational_request",
        "human_followup",
        "seller_operational_request may use human_followup but not monitor when seller asks action",
    ),
    (
        "prohibited_goods_question",
        "answer_policy_question",
        "policy questions should prefer answer_policy_question",
    ),
    (
        "product_publishing_question",
        "answer_policy_question",
        "publishing questions should prefer answer_policy_question",
    ),
)


@dataclass(frozen=True)
class SuggestedActionMismatch:
    """One human-flagged action mapping issue (aggregate metadata only)."""

    detected_intent: str
    conceptual_intent_fa: str | None
    predicted_action: str
    human_review_outcome: str
    ticket_label: str | None
    failure_pattern: str
    reviewer_note: str | None = None
    room_id: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "detected_intent": self.detected_intent,
            "conceptual_intent_fa": self.conceptual_intent_fa,
            "predicted_action": self.predicted_action,
            "human_review_outcome": self.human_review_outcome,
            "ticket_label": self.ticket_label,
            "failure_pattern": self.failure_pattern,
            "reviewer_note": self.reviewer_note,
            "room_id": self.room_id,
        }


@dataclass(frozen=True)
class ActionAccuracySlice:
    """Accuracy stats for one action or intent bucket."""

    key: str
    count: int
    correct_count: int
    accuracy_rate: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "count": self.count,
            "correct_count": self.correct_count,
            "accuracy_rate": self.accuracy_rate,
        }


@dataclass(frozen=True)
class MappingAdjustmentRecommendation:
    """Advisory taxonomy tweak (not applied automatically)."""

    detected_intent: str
    current_common_action: str
    suggested_preferred_action: str
    reason: str
    evidence_count: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "detected_intent": self.detected_intent,
            "current_common_action": self.current_common_action,
            "suggested_preferred_action": self.suggested_preferred_action,
            "reason": self.reason,
            "evidence_count": self.evidence_count,
        }


@dataclass(frozen=True)
class SuggestedActionCalibrationSummary:
    """Offline suggested_action calibration from draft review JSONL."""

    total_reviewed_actions: int
    action_accuracy_rate: float
    fallback_action_rate: float
    monitor_usage_rate: float
    human_followup_usage_rate: float
    fallback_overuse_count: int
    most_overused_actions: tuple[tuple[str, int], ...] = ()
    weakest_actions: tuple[ActionAccuracySlice, ...] = ()
    weakest_detected_intents: tuple[ActionAccuracySlice, ...] = ()
    top_mismatch_patterns: tuple[tuple[str, int], ...] = ()
    suggested_mapping_adjustments: tuple[MappingAdjustmentRecommendation, ...] = ()
    mismatches: tuple[SuggestedActionMismatch, ...] = ()
    generated_at_utc: str = ""
    source_feedback_path: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_feedback_path": self.source_feedback_path,
            "total_reviewed_actions": self.total_reviewed_actions,
            "action_accuracy_rate": self.action_accuracy_rate,
            "fallback_action_rate": self.fallback_action_rate,
            "monitor_usage_rate": self.monitor_usage_rate,
            "human_followup_usage_rate": self.human_followup_usage_rate,
            "fallback_overuse_count": self.fallback_overuse_count,
            "most_overused_actions": [
                {"action": action, "count": count} for action, count in self.most_overused_actions
            ],
            "weakest_actions": [s.to_json_dict() for s in self.weakest_actions],
            "weakest_detected_intents": [s.to_json_dict() for s in self.weakest_detected_intents],
            "top_mismatch_patterns": [
                {"pattern": pattern, "count": count}
                for pattern, count in self.top_mismatch_patterns
            ],
            "suggested_mapping_adjustments": [
                r.to_json_dict() for r in self.suggested_mapping_adjustments
            ],
            "mismatch_count": len(self.mismatches),
            "mismatches_sample": [m.to_json_dict() for m in self.mismatches[:25]],
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _dimension_key(value: str | None, *, default: str = "(none)") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _conceptual_blob(row: DraftReviewFeedback) -> str:
    parts = [
        row.conceptual_intent_fa or "",
        row.detected_intent or "",
    ]
    return " ".join(p.strip() for p in parts if p.strip())


def is_fallback_overuse_candidate(row: DraftReviewFeedback) -> bool:
    """True when monitor/human_followup is used but conceptual text implies operational work."""
    action = _dimension_key(row.suggested_action, default="").lower()
    if action not in _FALLBACK_ACTIONS:
        return False
    blob = _conceptual_blob(row)
    if not blob:
        return False
    return _has_any(blob, _OPERATIONAL_CONCEPTUAL_MARKERS)


def _human_review_outcome(row: DraftReviewFeedback) -> str:
    if not row.action_correct:
        return "action_incorrect"
    if not row.draft_usable:
        return "draft_not_usable"
    return "action_correct"


def _failure_pattern_for_row(row: DraftReviewFeedback) -> str | None:
    if is_fallback_overuse_candidate(row):
        return "fallback_overuse"
    if not row.action_correct:
        return "action_mismatch"
    if not row.draft_usable and not row.action_correct:
        return "usable_blocked_by_action"
    if not row.draft_usable and row.action_correct:
        return "draft_not_usable_other"
    return None


def collect_action_mismatches(rows: list[DraftReviewFeedback]) -> list[SuggestedActionMismatch]:
    """Build mismatch records for action_correct=false and related failure cases."""
    mismatches: list[SuggestedActionMismatch] = []
    for row in rows:
        pattern = _failure_pattern_for_row(row)
        if pattern is None:
            continue
        if pattern == "draft_not_usable_other":
            continue
        mismatches.append(
            SuggestedActionMismatch(
                detected_intent=_dimension_key(row.detected_intent),
                conceptual_intent_fa=row.conceptual_intent_fa,
                predicted_action=_dimension_key(row.suggested_action),
                human_review_outcome=_human_review_outcome(row),
                ticket_label=row.ticket_label,
                failure_pattern=pattern,
                reviewer_note=row.reviewer_note,
                room_id=row.room_id,
            ),
        )
    return mismatches


def _accuracy_slices(
    buckets: dict[str, list[bool]],
    *,
    limit: int = 8,
) -> tuple[ActionAccuracySlice, ...]:
    slices: list[ActionAccuracySlice] = []
    for key, outcomes in sorted(buckets.items()):
        total = len(outcomes)
        correct = sum(1 for ok in outcomes if ok)
        slices.append(
            ActionAccuracySlice(
                key=key,
                count=total,
                correct_count=correct,
                accuracy_rate=_rate(correct, total),
            ),
        )
    slices.sort(key=lambda item: (item.accuracy_rate, -item.count))
    return tuple(slices[:limit])


def generate_mapping_adjustments(
    mismatches: list[SuggestedActionMismatch],
    *,
    min_evidence: int = 1,
) -> tuple[MappingAdjustmentRecommendation, ...]:
    """Advisory remapping hints from mismatch evidence (not applied automatically)."""
    recommendations: list[MappingAdjustmentRecommendation] = []
    for intent, preferred, reason in _INTENT_PREFERRED_ACTION_HINTS:
        evidence = [
            m
            for m in mismatches
            if m.detected_intent == intent
            and m.predicted_action in _FALLBACK_ACTIONS
            and m.predicted_action != preferred
        ]
        if len(evidence) >= min_evidence:
            wrong_action = Counter(m.predicted_action for m in evidence).most_common(1)[0][0]
            recommendations.append(
                MappingAdjustmentRecommendation(
                    detected_intent=intent,
                    current_common_action=wrong_action,
                    suggested_preferred_action=preferred,
                    reason=reason,
                    evidence_count=len(evidence),
                ),
            )
    intent_action_wrong: Counter[tuple[str, str]] = Counter()
    for m in mismatches:
        if m.failure_pattern == "action_mismatch":
            intent_action_wrong[(m.detected_intent, m.predicted_action)] += 1
    for (intent, wrong_action), count in intent_action_wrong.most_common(5):
        if any(r.detected_intent == intent for r in recommendations):
            continue
        preferred = next(
            (p for i, p, _ in _INTENT_PREFERRED_ACTION_HINTS if i == intent),
            None,
        )
        if preferred and wrong_action != preferred and count >= min_evidence:
            reason = next(
                (r for i, _, r in _INTENT_PREFERRED_ACTION_HINTS if i == intent),
                f"Review mapping for {intent}",
            )
            recommendations.append(
                MappingAdjustmentRecommendation(
                    detected_intent=intent,
                    current_common_action=wrong_action,
                    suggested_preferred_action=preferred,
                    reason=reason,
                    evidence_count=count,
                ),
            )
    return tuple(recommendations)


def compute_suggested_action_calibration(
    rows: list[DraftReviewFeedback],
    *,
    source_feedback_path: str = "",
    generated_at_utc: str | None = None,
) -> SuggestedActionCalibrationSummary:
    """Aggregate suggested_action calibration metrics from review rows."""
    reviewed = [r for r in rows if r.suggested_action]
    total = len(reviewed)
    correct = sum(1 for r in reviewed if r.action_correct)

    action_buckets: dict[str, list[bool]] = defaultdict(list)
    intent_buckets: dict[str, list[bool]] = defaultdict(list)
    action_counts: Counter[str] = Counter()

    for row in reviewed:
        action = _dimension_key(row.suggested_action)
        intent = _dimension_key(row.detected_intent)
        action_counts[action] += 1
        action_buckets[action].append(row.action_correct)
        intent_buckets[intent].append(row.action_correct)

    monitor_count = action_counts.get("monitor", 0)
    human_followup_count = action_counts.get("human_followup", 0)
    fallback_count = monitor_count + human_followup_count

    mismatches = collect_action_mismatches(reviewed)
    fallback_overuse = sum(1 for r in reviewed if is_fallback_overuse_candidate(r))
    pattern_counts = Counter(m.failure_pattern for m in mismatches)

    weakest_actions = _accuracy_slices(action_buckets)
    weakest_intents = _accuracy_slices(intent_buckets)
    most_overused = tuple(action_counts.most_common(8))
    adjustments = generate_mapping_adjustments(mismatches)

    return SuggestedActionCalibrationSummary(
        total_reviewed_actions=total,
        action_accuracy_rate=_rate(correct, total),
        fallback_action_rate=_rate(fallback_count, total),
        monitor_usage_rate=_rate(monitor_count, total),
        human_followup_usage_rate=_rate(human_followup_count, total),
        fallback_overuse_count=fallback_overuse,
        most_overused_actions=most_overused,
        weakest_actions=weakest_actions,
        weakest_detected_intents=weakest_intents,
        top_mismatch_patterns=tuple(pattern_counts.most_common()),
        suggested_mapping_adjustments=adjustments,
        mismatches=tuple(mismatches),
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_feedback_path=source_feedback_path,
    )


def format_suggested_action_calibration_markdown(
    summary: SuggestedActionCalibrationSummary,
) -> str:
    """Render offline markdown calibration report."""
    lines = [
        "# Suggested Action Calibration Report",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Source:** `{summary.source_feedback_path}`  ",
        "**Scope:** Advisory taxonomy calibration from draft review feedback only — "
        "**no** automatic mapping changes or action execution.",
        "",
        "## Overall action accuracy",
        "",
        f"- **total_reviewed_actions:** {summary.total_reviewed_actions}",
        f"- **action_accuracy_rate:** {summary.action_accuracy_rate:.1%}",
        f"- **fallback_action_rate (monitor + human_followup):** "
        f"{summary.fallback_action_rate:.1%}",
        f"- **monitor_usage_rate:** {summary.monitor_usage_rate:.1%}",
        f"- **human_followup_usage_rate:** {summary.human_followup_usage_rate:.1%}",
        f"- **fallback_overuse_count:** {summary.fallback_overuse_count}",
        "",
    ]

    if summary.total_reviewed_actions == 0:
        lines.extend(
            [
                "*(No draft reviews with suggested_action yet.)*",
                "",
                "## Governance",
                "",
                "- Input: `reports/draft_review_feedback.jsonl` (gitignored).",
                "- Recommendations are manual review only — do not auto-apply.",
                "",
            ],
        )
        return "\n".join(lines)

    lines.extend(
        [
            "## Weakest suggested actions (lowest accuracy)",
            "",
            "| Action | Reviews | Accuracy |",
            "|--------|--------:|---------:|",
        ],
    )
    for slice_ in summary.weakest_actions[:6]:
        lines.append(
            f"| {slice_.key} | {slice_.count} | {slice_.accuracy_rate:.1%} |",
        )
    lines.append("")

    lines.extend(
        [
            "## Weakest detected intents (action accuracy)",
            "",
            "| Intent | Reviews | Accuracy |",
            "|--------|--------:|---------:|",
        ],
    )
    for slice_ in summary.weakest_detected_intents[:6]:
        lines.append(
            f"| {slice_.key} | {slice_.count} | {slice_.accuracy_rate:.1%} |",
        )
    lines.append("")

    lines.extend(
        [
            "## Most overused suggested actions",
            "",
            "| Action | Count |",
            "|--------|------:|",
        ],
    )
    for action, count in summary.most_overused_actions:
        lines.append(f"| {action} | {count} |")
    lines.append("")

    lines.extend(
        [
            "## Monitor / human_followup overuse",
            "",
            f"- **monitor_usage_rate:** {summary.monitor_usage_rate:.1%}",
            f"- **human_followup_usage_rate:** {summary.human_followup_usage_rate:.1%}",
            f"- **fallback_overuse_candidates:** {summary.fallback_overuse_count} "
            "(operational conceptual intent + monitor/human_followup)",
            "",
            "## Top mismatch patterns",
            "",
            "| Pattern | Count |",
            "|---------|------:|",
        ],
    )
    if summary.top_mismatch_patterns:
        for pattern, count in summary.top_mismatch_patterns:
            lines.append(f"| {pattern} | {count} |")
    else:
        lines.append("| *(none)* | 0 |")
    lines.append("")

    lines.extend(
        [
            "## Suggested calibration adjustments (manual only)",
            "",
        ],
    )
    if summary.suggested_mapping_adjustments:
        for rec in summary.suggested_mapping_adjustments:
            lines.append(
                f"- **{rec.detected_intent}:** `{rec.current_common_action}` → "
                f"`{rec.suggested_preferred_action}` "
                f"({rec.evidence_count} evidence) — {rec.reason}",
            )
    else:
        lines.append("*(No adjustment recommendations from current sample.)*")
    lines.append("")

    if summary.mismatches:
        lines.extend(
            [
                "## Sample mismatches (metadata only)",
                "",
            ],
        )
        for m in summary.mismatches[:10]:
            note = f" — note: {m.reviewer_note[:80]}…" if m.reviewer_note else ""
            lines.append(
                f"- `{m.detected_intent}` / `{m.predicted_action}` / {m.failure_pattern}{note}",
            )
        lines.append("")

    lines.extend(
        [
            "## Governance",
            "",
            "- **No** automatic taxonomy updates, prompt retraining, or action execution.",
            "- **No** transcripts, prompts, retrieval snippets, or gold replies in this report.",
            "- Iterate mappings in `app/workflows/suggested_action_taxonomy.py` after review.",
            "",
        ],
    )
    return "\n".join(lines)


def assert_calibration_output_safe(content: str) -> None:
    """Reject outputs that may embed prompts or transcripts."""
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"calibration output must not contain forbidden token: {token}")


def build_suggested_action_calibration_report(
    feedback_path: Path | str = DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
    *,
    summary_output: Path = DEFAULT_CALIBRATION_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_CALIBRATION_REPORT_PATH,
    generated_at_utc: str | None = None,
) -> SuggestedActionCalibrationSummary:
    """Load feedback JSONL and write JSON + markdown calibration reports."""
    source = Path(feedback_path)
    rows = load_draft_review_feedback_rows(source)
    summary = compute_suggested_action_calibration(
        rows,
        source_feedback_path=str(source),
        generated_at_utc=generated_at_utc,
    )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = format_suggested_action_calibration_markdown(summary)

    assert_calibration_output_safe(json_text)
    assert_calibration_output_safe(markdown)

    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary

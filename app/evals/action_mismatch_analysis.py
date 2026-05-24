"""Deep analysis of suggested_action mismatches from draft review feedback (advisory only)."""

from __future__ import annotations

import json
import re
from collections import Counter
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

DEFAULT_ANALYSIS_SUMMARY_PATH = Path("reports/action_mismatch_analysis_summary.json")
DEFAULT_ANALYSIS_REPORT_PATH = Path("reports/action_mismatch_analysis_report.md")

_ACTION_NOTE_MARKERS = (
    "action",
    "اقدام",
    "suggested_action",
    "monitor",
    "human_followup",
    "billing_review",
    "check_settlement",
    "update_delivery",
    "check_order",
    "check_product",
    "اشتباه",
    "غلط",
    "نادرست",
    "باید",
)

_COMPLAINT_RESOLUTION_MARKERS = (
    "شکایت رو بردارید",
    "شکایت را بردارید",
    "بردارید شکایت",
    "حل شد",
    "مشکل حل",
)

_POLICY_MARKERS = ("قوانین", "مقررات", "سیاست", "انتشار", "مجاز")
_SETTLEMENT_MARKERS = ("تسویه", "واریز", "پرداخت", "کیف پول", "پنل")
_RETURN_MARKERS = ("مرجوع", "بازگشت", "استرداد", "عودت")

_AMBIGUOUS_BOUNDARY_FAMILIES: tuple[tuple[str, str, str], ...] = (
    (
        "billing_review_vs_check_settlement_status",
        "billing_review",
        "check_settlement_status",
        "Fund route vs operational settlement payout language",
    ),
    (
        "record_update_vs_update_delivery_status",
        "record_update",
        "update_delivery_status",
        "Tracking notification vs delivery confirmation",
    ),
    (
        "human_followup_vs_check_order_status",
        "human_followup",
        "check_order_status",
        "Generic follow-up vs order status review",
    ),
    (
        "check_product_approval_vs_review_product_edit",
        "check_product_approval",
        "review_product_edit",
        "Approval status vs product edit request",
    ),
    (
        "monitor_vs_specific_action",
        "monitor",
        "specific_operational",
        "Passive monitor vs operational-specific action",
    ),
)

_NOTE_EXPECTED_HINTS: tuple[tuple[str, str], ...] = (
    ("update_delivery", "update_delivery_status"),
    ("ثبت تحویل", "update_delivery_status"),
    ("delivery", "update_delivery_status"),
    ("check_product", "check_product_approval"),
    ("تایید کالا", "check_product_approval"),
    ("review_product", "review_product_edit"),
    ("ویرایش کالا", "review_product_edit"),
    ("check_settlement", "check_settlement_status"),
    ("تسویه", "check_settlement_status"),
    ("billing_review", "billing_review"),
    ("check_order", "check_order_status"),
    ("return", "check_return_request"),
    ("مرجوع", "check_return_request"),
    ("policy", "answer_policy_question"),
    ("قوانین", "answer_policy_question"),
    ("human_followup", "human_followup"),
    ("monitor", "monitor"),
    ("escalate", "escalate"),
    ("record_update", "record_update"),
)


@dataclass(frozen=True)
class ActionMismatchExample:
    """Safe metadata example for a single mismatch (no draft/transcript text)."""

    room_id: str
    case_id: str | None
    detected_intent: str
    conceptual_intent_fa: str | None
    predicted_action: str
    inferred_expected_action: str | None
    reviewer_note: str | None
    failure_reason: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "case_id": self.case_id,
            "detected_intent": self.detected_intent,
            "conceptual_intent_fa": self.conceptual_intent_fa,
            "predicted_action": self.predicted_action,
            "inferred_expected_action": self.inferred_expected_action,
            "reviewer_note": self.reviewer_note,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class ActionConfusionPair:
    """Predicted vs likely expected action from reviewer signals."""

    predicted_action: str
    reviewer_expected_action: str | None
    count: int
    examples_count: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "predicted_action": self.predicted_action,
            "reviewer_expected_action": self.reviewer_expected_action,
            "count": self.count,
            "examples_count": self.examples_count,
        }


@dataclass(frozen=True)
class IntentMismatchSlice:
    """Wrong-action rate for a detected_intent or conceptual bucket."""

    key: str
    total_reviews: int
    mismatch_count: int
    mismatch_rate: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "total_reviews": self.total_reviews,
            "mismatch_count": self.mismatch_count,
            "mismatch_rate": self.mismatch_rate,
        }


@dataclass(frozen=True)
class AmbiguousBoundaryHit:
    """Overlapping action family observed in mismatches."""

    boundary_id: str
    action_a: str
    action_b: str
    description: str
    count: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "boundary_id": self.boundary_id,
            "action_a": self.action_a,
            "action_b": self.action_b,
            "description": self.description,
            "count": self.count,
        }


@dataclass(frozen=True)
class ActionMismatchAnalysisSummary:
    """Deep mismatch analysis for post-refinement calibration review."""

    total_reviews: int
    total_action_mismatches: int
    action_accuracy_rate: float
    mismatch_rate: float
    top_predicted_wrong_actions: tuple[tuple[str, int], ...] = ()
    top_intents_with_mismatch: tuple[IntentMismatchSlice, ...] = ()
    top_conceptual_intents_with_mismatch: tuple[IntentMismatchSlice, ...] = ()
    confusion_pairs: tuple[ActionConfusionPair, ...] = ()
    ambiguous_action_boundaries: tuple[AmbiguousBoundaryHit, ...] = ()
    recommended_next_calibration_focus: str = ""
    sample_examples: tuple[ActionMismatchExample, ...] = ()
    generated_at_utc: str = ""
    source_feedback_path: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_feedback_path": self.source_feedback_path,
            "total_reviews": self.total_reviews,
            "total_action_mismatches": self.total_action_mismatches,
            "action_accuracy_rate": self.action_accuracy_rate,
            "mismatch_rate": self.mismatch_rate,
            "top_predicted_wrong_actions": [
                {"action": action, "count": count}
                for action, count in self.top_predicted_wrong_actions
            ],
            "top_intents_with_mismatch": [s.to_json_dict() for s in self.top_intents_with_mismatch],
            "top_conceptual_intents_with_mismatch": [
                s.to_json_dict() for s in self.top_conceptual_intents_with_mismatch
            ],
            "confusion_pairs": [p.to_json_dict() for p in self.confusion_pairs],
            "ambiguous_action_boundaries": [
                b.to_json_dict() for b in self.ambiguous_action_boundaries
            ],
            "recommended_next_calibration_focus": self.recommended_next_calibration_focus,
            "sample_examples": [e.to_json_dict() for e in self.sample_examples],
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _dimension_key(value: str | None, *, default: str = "(none)") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _analysis_blob(row: DraftReviewFeedback) -> str:
    parts = [
        row.conceptual_intent_fa or "",
        row.detected_intent or "",
        row.reviewer_note or "",
    ]
    return " ".join(p.strip() for p in parts if p.strip()).lower()


def _reviewer_note_indicates_action_issue(note: str | None) -> bool:
    if not note or not note.strip():
        return False
    lowered = note.strip().lower()
    return any(marker in lowered for marker in _ACTION_NOTE_MARKERS)


def is_action_mismatch_row(row: DraftReviewFeedback) -> bool:
    """True when review flags action mapping as wrong or action-related usability failure."""
    if not row.suggested_action:
        return False
    if not row.action_correct:
        return True
    if not row.draft_usable and _reviewer_note_indicates_action_issue(row.reviewer_note):
        return True
    if not row.draft_usable and not row.intent_correct and row.action_correct:
        return False
    if not row.draft_usable and not row.action_correct:
        return True
    return False


def _failure_reason(row: DraftReviewFeedback) -> str:
    if not row.action_correct:
        return "action_incorrect"
    if not row.draft_usable:
        return "draft_not_usable_action_related"
    return "action_related"


def infer_expected_action(
    row: DraftReviewFeedback,
    *,
    predicted_action: str,
) -> str | None:
    """Infer likely reviewer-expected action from note, conceptual intent, and detected intent."""
    blob = _analysis_blob(row)
    note = (row.reviewer_note or "").lower()
    intent = _dimension_key(row.detected_intent).lower()

    for marker, action in _NOTE_EXPECTED_HINTS:
        if marker in note:
            return action

    if _has_any(blob, _COMPLAINT_RESOLUTION_MARKERS) or (
        "شکایت" in blob and ("بردار" in blob or "حل" in blob)
    ):
        return "human_followup"

    if _has_any(blob, _DELIVERY_CONCEPTUAL_MARKERS) or intent == "delivery_confirmation_request":
        return "update_delivery_status"

    if _has_any(blob, _PRODUCT_EDIT_MARKERS):
        return "review_product_edit"

    if _has_any(blob, _PRODUCT_APPROVAL_CONCEPTUAL_MARKERS) or intent == "product_approval_review":
        return "check_product_approval"

    if _has_any(blob, _RETURN_REFUND_MARKERS) or _has_any(blob, _RETURN_MARKERS):
        return "check_return_request"

    if _has_any(blob, _ORDER_STATUS_CONCEPTUAL_MARKERS) or intent == "order_status_review":
        return "check_order_status"

    if intent == "complaint_escalation":
        return "escalate"

    if _has_any(blob, _POLICY_MARKERS) or intent in (
        "prohibited_goods_question",
        "product_publishing_question",
    ):
        return "answer_policy_question"

    if intent == "tracking_code_notification" or intent == "seller_notification":
        return "record_update"

    if _has_any(blob, _SETTLEMENT_MARKERS) or intent in (
        "settlement_status_inquiry",
        "settlement_panel_access_issue",
    ):
        if row.ticket_label == "fund" or (row.reviewer_note and "billing" in note):
            return "billing_review"
        if "واریز نشده" in blob or "پنل" in blob or "پرداخت نشده" in blob:
            return "check_settlement_status"
        return "check_settlement_status"

    if intent == "seller_operational_request":
        return "human_followup"

    if re.search(r"(بررسی|ثبت|تایید|پیگیری)", blob):
        return "human_followup"

    if predicted_action in ("monitor", "human_followup"):
        return None

    return None


def _mismatch_examples(
    rows: list[DraftReviewFeedback],
    *,
    limit: int = 12,
) -> tuple[ActionMismatchExample, ...]:
    examples: list[ActionMismatchExample] = []
    for row in rows:
        if not is_action_mismatch_row(row):
            continue
        predicted = _dimension_key(row.suggested_action)
        inferred = infer_expected_action(row, predicted_action=predicted)
        note = row.reviewer_note
        if note and len(note) > 120:
            note = note[:119].rstrip() + "…"
        examples.append(
            ActionMismatchExample(
                room_id=row.room_id,
                case_id=row.case_id,
                detected_intent=_dimension_key(row.detected_intent),
                conceptual_intent_fa=row.conceptual_intent_fa,
                predicted_action=predicted,
                inferred_expected_action=inferred,
                reviewer_note=note,
                failure_reason=_failure_reason(row),
            ),
        )
    return tuple(examples[:limit])


def _intent_mismatch_slices(
    rows: list[DraftReviewFeedback],
    *,
    key_fn: Any,
    limit: int = 8,
) -> tuple[IntentMismatchSlice, ...]:
    totals: Counter[str] = Counter()
    mismatches: Counter[str] = Counter()
    for row in rows:
        if not row.suggested_action:
            continue
        key = key_fn(row)
        totals[key] += 1
        if is_action_mismatch_row(row):
            mismatches[key] += 1
    slices: list[IntentMismatchSlice] = []
    for key, total in totals.items():
        wrong = mismatches.get(key, 0)
        if wrong == 0:
            continue
        slices.append(
            IntentMismatchSlice(
                key=key,
                total_reviews=total,
                mismatch_count=wrong,
                mismatch_rate=_rate(wrong, total),
            ),
        )
    slices.sort(key=lambda item: (-item.mismatch_count, -item.mismatch_rate))
    return tuple(slices[:limit])


def build_confusion_pairs(
    mismatch_rows: list[DraftReviewFeedback],
    *,
    limit: int = 12,
) -> tuple[ActionConfusionPair, ...]:
    """Aggregate predicted vs inferred expected action pairs."""
    pair_counts: Counter[tuple[str, str | None]] = Counter()
    for row in mismatch_rows:
        predicted = _dimension_key(row.suggested_action)
        expected = infer_expected_action(row, predicted_action=predicted)
        pair_counts[(predicted, expected)] += 1

    pairs: list[ActionConfusionPair] = []
    for (predicted, expected), count in pair_counts.most_common(limit):
        if expected is None:
            continue
        if predicted == expected:
            continue
        pairs.append(
            ActionConfusionPair(
                predicted_action=predicted,
                reviewer_expected_action=expected,
                count=count,
                examples_count=count,
            ),
        )
    unknown_predicted = [
        (pred, cnt) for (pred, exp), cnt in pair_counts.most_common() if exp is None and cnt > 0
    ]
    for predicted, count in unknown_predicted[:3]:
        pairs.append(
            ActionConfusionPair(
                predicted_action=predicted,
                reviewer_expected_action=None,
                count=count,
                examples_count=count,
            ),
        )
    return tuple(pairs)


def detect_ambiguous_boundaries(
    mismatch_rows: list[DraftReviewFeedback],
) -> tuple[AmbiguousBoundaryHit, ...]:
    """Count mismatches that span overlapping action families."""
    hits: Counter[str] = Counter()
    meta = {item[0]: item for item in _AMBIGUOUS_BOUNDARY_FAMILIES}

    for row in mismatch_rows:
        predicted = _dimension_key(row.suggested_action)
        expected = infer_expected_action(row, predicted_action=predicted)
        if not expected or predicted == expected:
            continue

        for boundary_id, action_a, action_b, _description in _AMBIGUOUS_BOUNDARY_FAMILIES:
            if boundary_id == "monitor_vs_specific_action":
                if predicted == "monitor" and expected not in ("monitor", "human_followup"):
                    hits[boundary_id] += 1
                continue
            if {predicted, expected} == {action_a, action_b}:
                hits[boundary_id] += 1
            elif predicted == action_a and expected == action_b:
                hits[boundary_id] += 1
            elif predicted == action_b and expected == action_a:
                hits[boundary_id] += 1

    results: list[AmbiguousBoundaryHit] = []
    for boundary_id, count in hits.most_common():
        if count <= 0:
            continue
        _id, action_a, action_b, description = meta[boundary_id]
        results.append(
            AmbiguousBoundaryHit(
                boundary_id=boundary_id,
                action_a=action_a,
                action_b=action_b,
                description=description,
                count=count,
            ),
        )
    return tuple(results)


def recommend_next_calibration_focus(
    *,
    confusion_pairs: tuple[ActionConfusionPair, ...],
    ambiguous_boundaries: tuple[AmbiguousBoundaryHit, ...],
    top_wrong_actions: tuple[tuple[str, int], ...],
    top_intents: tuple[IntentMismatchSlice, ...],
) -> str:
    """Single advisory sentence for the next taxonomy refinement pass."""
    if confusion_pairs:
        top = confusion_pairs[0]
        if top.reviewer_expected_action and top.predicted_action != top.reviewer_expected_action:
            return (
                f"Refine mapping boundary: `{top.predicted_action}` was predicted but "
                f"`{top.reviewer_expected_action}` was inferred from reviewer signals "
                f"({top.count} mismatches). Check whether Step 186 over-corrected this family."
            )
    if ambiguous_boundaries:
        boundary = ambiguous_boundaries[0]
        return (
            f"Clarify ambiguous boundary `{boundary.boundary_id}` "
            f"({boundary.action_a} vs {boundary.action_b}) — {boundary.count} mismatch hits. "
            f"{boundary.description}."
        )
    if top_intents:
        intent = top_intents[0]
        return (
            f"Review detected_intent `{intent.key}` — "
            f"{intent.mismatch_count}/{intent.total_reviews} action mismatches "
            f"({intent.mismatch_rate:.0%})."
        )
    if top_wrong_actions:
        action, count = top_wrong_actions[0]
        return (
            f"Review over-predicted wrong action `{action}` ({count} mismatches). "
            "Likely taxonomy boundary issue after specificity increase."
        )
    return "No action mismatches in feedback sample — collect more draft reviews before remapping."


def compute_action_mismatch_analysis(
    rows: list[DraftReviewFeedback],
    *,
    source_feedback_path: str = "",
    generated_at_utc: str | None = None,
) -> ActionMismatchAnalysisSummary:
    """Run deep mismatch analysis on draft review feedback rows."""
    reviewed = [r for r in rows if r.suggested_action]
    total = len(reviewed)
    mismatch_rows = [r for r in reviewed if is_action_mismatch_row(r)]
    mismatch_count = len(mismatch_rows)
    correct = sum(1 for r in reviewed if r.action_correct)

    wrong_action_counter = Counter(_dimension_key(r.suggested_action) for r in mismatch_rows)

    confusion = build_confusion_pairs(mismatch_rows)
    boundaries = detect_ambiguous_boundaries(mismatch_rows)
    focus = recommend_next_calibration_focus(
        confusion_pairs=confusion,
        ambiguous_boundaries=boundaries,
        top_wrong_actions=tuple(wrong_action_counter.most_common(8)),
        top_intents=_intent_mismatch_slices(
            reviewed, key_fn=lambda r: _dimension_key(r.detected_intent)
        ),
    )

    return ActionMismatchAnalysisSummary(
        total_reviews=total,
        total_action_mismatches=mismatch_count,
        action_accuracy_rate=_rate(correct, total),
        mismatch_rate=_rate(mismatch_count, total),
        top_predicted_wrong_actions=tuple(wrong_action_counter.most_common(8)),
        top_intents_with_mismatch=_intent_mismatch_slices(
            reviewed,
            key_fn=lambda r: _dimension_key(r.detected_intent),
        ),
        top_conceptual_intents_with_mismatch=_intent_mismatch_slices(
            reviewed,
            key_fn=lambda r: _dimension_key(r.conceptual_intent_fa),
        ),
        confusion_pairs=confusion,
        ambiguous_action_boundaries=boundaries,
        recommended_next_calibration_focus=focus,
        sample_examples=_mismatch_examples(mismatch_rows),
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_feedback_path=source_feedback_path,
    )


def format_action_mismatch_markdown(summary: ActionMismatchAnalysisSummary) -> str:
    """Render offline markdown deep-dive report."""
    lines = [
        "# Action Mismatch Deep Analysis",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Source:** `{summary.source_feedback_path}`  ",
        "**Scope:** Post–Step 186 advisory analysis — **no** taxonomy changes applied.",
        "",
        "## Overall mismatch rate",
        "",
        f"- **total_reviews:** {summary.total_reviews}",
        f"- **total_action_mismatches:** {summary.total_action_mismatches}",
        f"- **action_accuracy_rate:** {summary.action_accuracy_rate:.1%}",
        f"- **mismatch_rate:** {summary.mismatch_rate:.1%}",
        "",
        f"**Recommended next calibration focus:** {summary.recommended_next_calibration_focus}",
        "",
    ]

    if summary.total_action_mismatches == 0:
        lines.extend(
            [
                "*(No action mismatches in feedback — sample may be small.)*",
                "",
                "## Governance",
                "",
                "- Analysis only — do not auto-apply mapping changes.",
                "- No full drafts, prompts, or transcripts in this report.",
                "",
            ],
        )
        return "\n".join(lines)

    lines.extend(
        [
            "## Top wrong predicted actions",
            "",
            "| Predicted action | Mismatch count |",
            "|------------------|---------------:|",
        ],
    )
    for action, count in summary.top_predicted_wrong_actions:
        lines.append(f"| {action} | {count} |")
    lines.append("")

    lines.extend(
        [
            "## Top failing detected intents",
            "",
            "| Intent | Reviews | Mismatches | Mismatch rate |",
            "|--------|--------:|-----------:|--------------:|",
        ],
    )
    for slice_ in summary.top_intents_with_mismatch:
        lines.append(
            f"| {slice_.key} | {slice_.total_reviews} | {slice_.mismatch_count} | "
            f"{slice_.mismatch_rate:.1%} |",
        )
    lines.append("")

    lines.extend(
        [
            "## Top failing conceptual intents",
            "",
            "| Conceptual (fa) | Reviews | Mismatches | Mismatch rate |",
            "|-----------------|--------:|-----------:|--------------:|",
        ],
    )
    for slice_ in summary.top_conceptual_intents_with_mismatch:
        key = (slice_.key or "(none)")[:60]
        lines.append(
            f"| {key} | {slice_.total_reviews} | {slice_.mismatch_count} | "
            f"{slice_.mismatch_rate:.1%} |",
        )
    lines.append("")

    lines.extend(
        [
            "## Confusion pairs (predicted → inferred expected)",
            "",
            "| Predicted | Inferred expected | Count |",
            "|-----------|-------------------|------:|",
        ],
    )
    for pair in summary.confusion_pairs:
        expected = pair.reviewer_expected_action or "(unknown)"
        lines.append(f"| {pair.predicted_action} | {expected} | {pair.count} |")
    lines.append("")

    lines.extend(
        [
            "## Ambiguous action boundaries",
            "",
        ],
    )
    if summary.ambiguous_action_boundaries:
        for hit in summary.ambiguous_action_boundaries:
            lines.append(
                f"- **{hit.boundary_id}** (`{hit.action_a}` vs `{hit.action_b}`): "
                f"{hit.count} hits — {hit.description}",
            )
    else:
        lines.append("*(No cross-family boundary hits in current sample.)*")
    lines.append("")

    if summary.sample_examples:
        lines.extend(["## Sample mismatch examples (metadata only)", ""])
        for ex in summary.sample_examples:
            note = f" — note: {ex.reviewer_note}" if ex.reviewer_note else ""
            lines.append(
                f"- `{ex.room_id}` / `{ex.case_id or '—'}`: "
                f"intent=`{ex.detected_intent}`, "
                f"conceptual=`{ex.conceptual_intent_fa or '—'}`, "
                f"predicted=`{ex.predicted_action}` → "
                f"expected=`{ex.inferred_expected_action or '?'}` "
                f"({ex.failure_reason}){note}",
            )
        lines.append("")

    lines.extend(
        [
            "## Governance",
            "",
            "- Intended to explain action_accuracy drops after Step 186 specificity increases.",
            "- **No** automatic mapping updates, action execution, or LLM analysis.",
            "- Pair with `build_suggested_action_calibration_report.py` for context.",
            "",
        ],
    )
    return "\n".join(lines)


def assert_analysis_output_safe(content: str) -> None:
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"analysis output must not contain forbidden token: {token}")


def build_action_mismatch_analysis_report(
    feedback_path: Path | str = DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
    *,
    summary_output: Path = DEFAULT_ANALYSIS_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_ANALYSIS_REPORT_PATH,
    generated_at_utc: str | None = None,
) -> ActionMismatchAnalysisSummary:
    """Load feedback JSONL and write JSON + markdown analysis reports."""
    source = Path(feedback_path)
    rows = load_draft_review_feedback_rows(source)
    summary = compute_action_mismatch_analysis(
        rows,
        source_feedback_path=str(source),
        generated_at_utc=generated_at_utc,
    )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = format_action_mismatch_markdown(summary)

    assert_analysis_output_safe(json_text)
    assert_analysis_output_safe(markdown)

    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary

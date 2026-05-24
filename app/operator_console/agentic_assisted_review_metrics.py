"""Aggregate metrics for operator-assisted agentic mode reviews (analytics only)."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agentic_sandbox.preview_review_feedback import (
    DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    AgenticPreviewReviewFeedback,
    parse_agentic_preview_review_row,
)
from app.agentic_sandbox.preview_review_metrics import (
    PreviewReviewRecordWithContext,
    _compute_slice_metrics,
    _optional_str,
    _rate,
    _recommended_inspection_targets,
    load_preview_review_records_with_context,
)
from app.agentic_sandbox.report_paths import DEFAULT_BATCH_RUNS_JSONL
from app.operator_console.draft_review_feedback import _FORBIDDEN_TEXT_SUBSTRINGS

DEFAULT_OPERATOR_ASSISTED_REVIEW_FEEDBACK_PATH = Path(
    "reports/operator_assisted_review_feedback.jsonl",
)
DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_SUMMARY_PATH = Path(
    "reports/operator_assisted_review_metrics_summary.json",
)
DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_REPORT_PATH = Path(
    "reports/operator_assisted_review_metrics_report.md",
)

_ASSISTED_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("intent_correct", "intent"),
    ("action_correct", "action"),
    ("actionability_correct", "actionability"),
    ("entity_extraction_correct", "entity_extraction"),
    ("knowledge_hints_helpful", "knowledge_hints"),
    ("draft_length_reasonable", "draft"),
    ("safety_correct", "safety"),
    ("graph_status_correct", "graph_status"),
)

_ISSUE_FIELDS: tuple[tuple[str, str], ...] = (
    ("intent_correct", "wrong_intent"),
    ("action_correct", "wrong_action"),
    ("actionability_correct", "wrong_actionability"),
    ("entity_extraction_correct", "wrong_entity_extraction"),
    ("knowledge_hints_helpful", "unhelpful_knowledge"),
    ("draft_length_reasonable", "draft_not_helpful"),
    ("safety_correct", "safety_issue"),
    ("overall_preview_useful", "not_useful_for_assisted_workflow"),
)


@dataclass(frozen=True)
class OperatorAssistedReviewRecord:
    """One assisted-mode review row (preview schema + optional extension fields)."""

    review: AgenticPreviewReviewFeedback
    detected_intent: str | None = None
    suggested_action: str | None = None
    assisted_mode_useful: bool | None = None
    operator_trust_confident: bool | None = None
    draft_helpful: bool | None = None
    review_context: str | None = None

    @property
    def resolved_assisted_mode_useful(self) -> bool:
        if self.assisted_mode_useful is not None:
            return self.assisted_mode_useful
        return self.review.overall_preview_useful

    @property
    def resolved_operator_trust(self) -> bool:
        if self.operator_trust_confident is not None:
            return self.operator_trust_confident
        return self.review.safety_correct and self.review.ready_for_human_review_correct

    @property
    def resolved_draft_helpful(self) -> bool:
        if self.draft_helpful is not None:
            return self.draft_helpful
        return self.review.draft_length_reasonable


@dataclass(frozen=True)
class OperatorAssistedMetricsSummary:
    """Aggregate operator-assisted mode review metrics."""

    generated_at_utc: str
    source_preview_feedback_path: str
    source_assisted_extension_path: str | None
    total_reviews: int
    skipped_malformed_rows: int
    assisted_mode_usefulness_rate: float
    operator_trust_rate: float
    intent_accuracy_rate: float
    action_accuracy_rate: float
    actionability_accuracy_rate: float
    entity_accuracy_rate: float
    knowledge_helpfulness_rate: float
    draft_helpfulness_rate: float
    safety_confidence_rate: float
    overall_assisted_quality_rate: float
    by_detected_intent: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_suggested_action: dict[str, dict[str, Any]] = field(default_factory=dict)
    weakest_dimensions: tuple[str, ...] = ()
    top_review_issues: dict[str, int] = field(default_factory=dict)
    recommended_inspection_targets: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_preview_feedback_path": self.source_preview_feedback_path,
            "source_assisted_extension_path": self.source_assisted_extension_path,
            "total_reviews": self.total_reviews,
            "skipped_malformed_rows": self.skipped_malformed_rows,
            "assisted_mode_usefulness_rate": self.assisted_mode_usefulness_rate,
            "operator_trust_rate": self.operator_trust_rate,
            "intent_accuracy_rate": self.intent_accuracy_rate,
            "action_accuracy_rate": self.action_accuracy_rate,
            "actionability_accuracy_rate": self.actionability_accuracy_rate,
            "entity_accuracy_rate": self.entity_accuracy_rate,
            "knowledge_helpfulness_rate": self.knowledge_helpfulness_rate,
            "draft_helpfulness_rate": self.draft_helpfulness_rate,
            "safety_confidence_rate": self.safety_confidence_rate,
            "overall_assisted_quality_rate": self.overall_assisted_quality_rate,
            "by_detected_intent": self.by_detected_intent,
            "by_suggested_action": self.by_suggested_action,
            "weakest_dimensions": list(self.weakest_dimensions),
            "top_review_issues": dict(self.top_review_issues),
            "recommended_inspection_targets": list(self.recommended_inspection_targets),
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _parse_assisted_extension_row(raw: dict[str, Any]) -> OperatorAssistedReviewRecord | None:
    parsed = parse_agentic_preview_review_row(raw)
    if parsed is None:
        return None
    return OperatorAssistedReviewRecord(
        review=parsed,
        detected_intent=_optional_str(raw.get("detected_intent")),
        suggested_action=_optional_str(raw.get("suggested_action")),
        assisted_mode_useful=(
            bool(raw["assisted_mode_useful"]) if "assisted_mode_useful" in raw else None
        ),
        operator_trust_confident=(
            bool(raw["operator_trust_confident"]) if "operator_trust_confident" in raw else None
        ),
        draft_helpful=bool(raw["draft_helpful"]) if "draft_helpful" in raw else None,
        review_context=_optional_str(raw.get("review_context")),
    )


def _preview_context_to_assisted(
    row: PreviewReviewRecordWithContext,
) -> OperatorAssistedReviewRecord:
    return OperatorAssistedReviewRecord(
        review=row.review,
        detected_intent=row.detected_intent,
        suggested_action=row.suggested_action,
    )


def load_operator_assisted_review_records(
    preview_feedback_path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    *,
    assisted_extension_path: Path | str | None = DEFAULT_OPERATOR_ASSISTED_REVIEW_FEEDBACK_PATH,
    batch_runs_path: Path | str = DEFAULT_BATCH_RUNS_JSONL,
) -> tuple[list[OperatorAssistedReviewRecord], int]:
    """Load preview reviews and optional assisted extension JSONL (extension wins on review_id)."""
    preview_rows, skipped = load_preview_review_records_with_context(
        preview_feedback_path,
        batch_runs_path=batch_runs_path,
    )
    by_review_id: dict[str, OperatorAssistedReviewRecord] = {}
    for row in preview_rows:
        assisted = _preview_context_to_assisted(row)
        review_id = assisted.review.review_id or (
            f"{assisted.review.room_id}:{assisted.review.review_timestamp_utc}"
        )
        by_review_id[review_id] = assisted

    extension_path = Path(assisted_extension_path) if assisted_extension_path is not None else None
    if extension_path is not None and extension_path.is_file():
        for line in extension_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(raw, dict):
                skipped += 1
                continue
            parsed = _parse_assisted_extension_row(raw)
            if parsed is None:
                skipped += 1
                continue
            review_id = parsed.review.review_id or (
                f"{parsed.review.room_id}:{parsed.review.review_timestamp_utc}"
            )
            by_review_id[review_id] = parsed

    return list(by_review_id.values()), skipped


def _assisted_slice_metrics(rows: list[OperatorAssistedReviewRecord]) -> dict[str, Any]:
    total = len(rows)
    if total == 0:
        return {
            "total_reviews": 0,
            "assisted_mode_usefulness_rate": 0.0,
            "operator_trust_rate": 0.0,
            "intent_accuracy_rate": 0.0,
            "action_accuracy_rate": 0.0,
            "actionability_accuracy_rate": 0.0,
            "entity_accuracy_rate": 0.0,
            "knowledge_helpfulness_rate": 0.0,
            "draft_helpfulness_rate": 0.0,
            "safety_confidence_rate": 0.0,
            "overall_assisted_quality_rate": 0.0,
        }

    preview_rows = [
        PreviewReviewRecordWithContext(
            review=row.review,
            detected_intent=row.detected_intent,
            suggested_action=row.suggested_action,
        )
        for row in rows
    ]
    base = _compute_slice_metrics(preview_rows)

    assisted_useful = _rate(
        sum(1 for row in rows if row.resolved_assisted_mode_useful),
        total,
    )
    operator_trust = _rate(
        sum(1 for row in rows if row.resolved_operator_trust),
        total,
    )
    draft_helpful = _rate(
        sum(1 for row in rows if row.resolved_draft_helpful),
        total,
    )
    quality_components = (
        assisted_useful,
        operator_trust,
        base.intent_accuracy_rate,
        base.action_accuracy_rate,
        base.actionability_accuracy_rate,
        base.entity_accuracy_rate,
        base.knowledge_helpfulness_rate,
        draft_helpful,
        base.safety_correctness_rate,
    )
    overall_quality = round(sum(quality_components) / len(quality_components), 4)

    return {
        "total_reviews": total,
        "assisted_mode_usefulness_rate": assisted_useful,
        "operator_trust_rate": operator_trust,
        "intent_accuracy_rate": base.intent_accuracy_rate,
        "action_accuracy_rate": base.action_accuracy_rate,
        "actionability_accuracy_rate": base.actionability_accuracy_rate,
        "entity_accuracy_rate": base.entity_accuracy_rate,
        "knowledge_helpfulness_rate": base.knowledge_helpfulness_rate,
        "draft_helpfulness_rate": draft_helpful,
        "safety_confidence_rate": base.safety_correctness_rate,
        "overall_assisted_quality_rate": overall_quality,
    }


def detect_weakest_assisted_dimensions(rows: list[OperatorAssistedReviewRecord]) -> tuple[str, ...]:
    if not rows:
        return ()
    total = len(rows)
    scored: list[tuple[float, str]] = []
    for field_name, label in _ASSISTED_DIMENSIONS:
        count = sum(1 for row in rows if bool(getattr(row.review, field_name)))
        scored.append((_rate(count, total), label))
    scored.append(
        (
            _rate(sum(1 for row in rows if row.resolved_draft_helpful), total),
            "draft_helpfulness",
        ),
    )
    scored.append(
        (
            _rate(sum(1 for row in rows if row.resolved_operator_trust), total),
            "operator_trust",
        ),
    )
    scored.sort(key=lambda item: (item[0], item[1]))
    return tuple(label for _, label in scored)


def _top_review_issues(rows: list[OperatorAssistedReviewRecord]) -> dict[str, int]:
    total = len(rows)
    issues: dict[str, int] = {}
    for field_name, issue_name in _ISSUE_FIELDS:
        if field_name == "overall_preview_useful":
            issues[issue_name] = total - sum(1 for row in rows if row.resolved_assisted_mode_useful)
        else:
            issues[issue_name] = total - sum(
                1 for row in rows if bool(getattr(row.review, field_name))
            )
    return {key: value for key, value in issues.items() if value > 0}


def summarize_operator_assisted_review_metrics(
    records: list[OperatorAssistedReviewRecord],
    *,
    source_preview_feedback_path: str,
    source_assisted_extension_path: str | None,
    skipped_malformed_rows: int = 0,
    generated_at_utc: str | None = None,
) -> OperatorAssistedMetricsSummary:
    overall = _assisted_slice_metrics(records)
    preview_rows = [
        PreviewReviewRecordWithContext(
            review=row.review,
            detected_intent=row.detected_intent,
            suggested_action=row.suggested_action,
        )
        for row in records
    ]
    weakest = detect_weakest_assisted_dimensions(records)
    top_issues = _top_review_issues(records)

    by_intent: dict[str, dict[str, Any]] = {}
    intent_groups: dict[str, list[OperatorAssistedReviewRecord]] = defaultdict(list)
    for row in records:
        if row.detected_intent:
            intent_groups[row.detected_intent].append(row)
    for intent, group in sorted(intent_groups.items()):
        by_intent[intent] = _assisted_slice_metrics(group)

    by_action: dict[str, dict[str, Any]] = {}
    action_groups: dict[str, list[OperatorAssistedReviewRecord]] = defaultdict(list)
    for row in records:
        if row.suggested_action:
            action_groups[row.suggested_action].append(row)
    for action, group in sorted(action_groups.items()):
        by_action[action] = _assisted_slice_metrics(group)

    inspection_targets = _recommended_inspection_targets(
        preview_rows,
        weakest_dimensions=tuple(
            label.replace("_helpfulness", "").replace("operator_trust", "safety")
            for label in weakest[:3]
        ),
        top_issues={
            "wrong_intent_count": top_issues.get("wrong_intent", 0),
            "wrong_action_count": top_issues.get("wrong_action", 0),
            "wrong_actionability_count": top_issues.get("wrong_actionability", 0),
            "unhelpful_knowledge_count": top_issues.get("unhelpful_knowledge", 0),
            "safety_issue_count": top_issues.get("safety_issue", 0),
            "draft_length_issue_count": top_issues.get("draft_not_helpful", 0),
        },
    )
    assisted_targets = tuple(
        target.replace("sandbox preview", "operator-assisted package")
        for target in inspection_targets
    )

    return OperatorAssistedMetricsSummary(
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_preview_feedback_path=source_preview_feedback_path,
        source_assisted_extension_path=source_assisted_extension_path,
        total_reviews=int(overall["total_reviews"]),
        skipped_malformed_rows=skipped_malformed_rows,
        assisted_mode_usefulness_rate=float(overall["assisted_mode_usefulness_rate"]),
        operator_trust_rate=float(overall["operator_trust_rate"]),
        intent_accuracy_rate=float(overall["intent_accuracy_rate"]),
        action_accuracy_rate=float(overall["action_accuracy_rate"]),
        actionability_accuracy_rate=float(overall["actionability_accuracy_rate"]),
        entity_accuracy_rate=float(overall["entity_accuracy_rate"]),
        knowledge_helpfulness_rate=float(overall["knowledge_helpfulness_rate"]),
        draft_helpfulness_rate=float(overall["draft_helpfulness_rate"]),
        safety_confidence_rate=float(overall["safety_confidence_rate"]),
        overall_assisted_quality_rate=float(overall["overall_assisted_quality_rate"]),
        by_detected_intent=by_intent,
        by_suggested_action=by_action,
        weakest_dimensions=weakest,
        top_review_issues=top_issues,
        recommended_inspection_targets=assisted_targets,
    )


def render_operator_assisted_review_metrics_markdown(
    summary: OperatorAssistedMetricsSummary,
) -> str:
    lines = [
        "# Operator-Assisted Review Metrics Report",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Preview feedback:** `{summary.source_preview_feedback_path}`  ",
    ]
    if summary.source_assisted_extension_path:
        lines.append(
            f"**Assisted extension:** `{summary.source_assisted_extension_path}`  ",
        )
    lines.extend(
        [
            "**Scope:** Analytics-only — measures operator-assisted workflow quality "
            "from structured HITL reviews (no prompts, transcripts, or draft bodies).",
            "",
            "## Overall metrics",
            "",
            f"- **total_reviews:** {summary.total_reviews}",
            f"- **skipped_malformed_rows:** {summary.skipped_malformed_rows}",
            f"- **assisted_mode_usefulness_rate:** {summary.assisted_mode_usefulness_rate:.1%}",
            f"- **operator_trust_rate:** {summary.operator_trust_rate:.1%}",
            f"- **overall_assisted_quality_rate:** {summary.overall_assisted_quality_rate:.1%}",
            f"- **intent_accuracy_rate:** {summary.intent_accuracy_rate:.1%}",
            f"- **action_accuracy_rate:** {summary.action_accuracy_rate:.1%}",
            f"- **actionability_accuracy_rate:** {summary.actionability_accuracy_rate:.1%}",
            f"- **entity_accuracy_rate:** {summary.entity_accuracy_rate:.1%}",
            f"- **knowledge_helpfulness_rate:** {summary.knowledge_helpfulness_rate:.1%}",
            f"- **draft_helpfulness_rate:** {summary.draft_helpfulness_rate:.1%}",
            f"- **safety_confidence_rate:** {summary.safety_confidence_rate:.1%}",
            "",
            "## Weakest dimensions",
            "",
        ],
    )
    if summary.weakest_dimensions:
        for index, dimension in enumerate(summary.weakest_dimensions, start=1):
            lines.append(f"{index}. `{dimension}`")
    else:
        lines.append("*(No reviews yet.)*")

    lines.extend(["", "## Top review issues", "", "| Issue | Count |", "|-------|------:|"])
    if summary.top_review_issues:
        for issue, count in sorted(
            summary.top_review_issues.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"| {issue} | {count} |")
    else:
        lines.append("| *(none)* | 0 |")

    if summary.by_detected_intent:
        lines.extend(["", "## Breakdown by detected_intent", ""])
        lines.extend(_render_assisted_breakdown_table(summary.by_detected_intent))

    if summary.by_suggested_action:
        lines.extend(["", "## Breakdown by suggested_action", ""])
        lines.extend(_render_assisted_breakdown_table(summary.by_suggested_action))

    lines.extend(["", "## Recommended inspection targets", ""])
    if summary.recommended_inspection_targets:
        for target in summary.recommended_inspection_targets:
            lines.append(f"- {target}")
    else:
        lines.append("*(Submit assisted-mode / sandbox preview reviews to populate metrics.)*")

    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Analytics only — does not enable send, execution, or auto-approval.",
            "- Reuses sandbox preview review schema; optional assisted extension JSONL.",
            "- Safe output only: no transcripts, prompts, retrieval snippets, or draft text.",
            "",
        ],
    )
    return "\n".join(lines)


def _render_assisted_breakdown_table(slices: dict[str, dict[str, Any]]) -> list[str]:
    lines = [
        "| Slice | Reviews | Useful | Trust | Quality | Draft helpful |",
        "|-------|--------:|-------:|------:|--------:|--------------:|",
    ]
    for key, stats in sorted(slices.items()):
        lines.append(
            f"| `{key}` | {stats['total_reviews']} | "
            f"{stats['assisted_mode_usefulness_rate']:.1%} | "
            f"{stats['operator_trust_rate']:.1%} | "
            f"{stats['overall_assisted_quality_rate']:.1%} | "
            f"{stats['draft_helpfulness_rate']:.1%} |",
        )
    return lines


def assert_operator_assisted_review_metrics_output_safe(content: str) -> None:
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(
                "operator assisted review metrics output must not contain "
                f"forbidden token: {token}",
            )
    for token in (
        "conversation transcript",
        "gold_reference_reply",
        '"messages"',
        "reviewer_notes",
    ):
        if token in lowered:
            raise ValueError(
                "operator assisted review metrics output must not contain "
                f"forbidden token: {token}",
            )
    if re.search(r"sk-[a-z0-9]{8,}", content, flags=re.IGNORECASE):
        raise ValueError(
            "operator assisted review metrics output must not contain API key patterns",
        )


def build_operator_assisted_review_metrics_report(
    preview_feedback_path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    *,
    assisted_extension_path: Path | str | None = DEFAULT_OPERATOR_ASSISTED_REVIEW_FEEDBACK_PATH,
    batch_runs_path: Path | str = DEFAULT_BATCH_RUNS_JSONL,
    summary_output: Path = DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_REPORT_PATH,
    generated_at_utc: str | None = None,
) -> OperatorAssistedMetricsSummary:
    preview_source = Path(preview_feedback_path)
    extension_source = (
        Path(assisted_extension_path) if assisted_extension_path is not None else None
    )
    extension_label = None
    if extension_source is not None and extension_source.is_file():
        extension_label = str(extension_source)

    records, skipped = load_operator_assisted_review_records(
        preview_source,
        assisted_extension_path=assisted_extension_path,
        batch_runs_path=batch_runs_path,
    )
    summary = summarize_operator_assisted_review_metrics(
        records,
        source_preview_feedback_path=str(preview_source),
        source_assisted_extension_path=extension_label,
        skipped_malformed_rows=skipped,
        generated_at_utc=generated_at_utc,
    )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_operator_assisted_review_metrics_markdown(summary)

    assert_operator_assisted_review_metrics_output_safe(json_text)
    assert_operator_assisted_review_metrics_output_safe(markdown)

    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary

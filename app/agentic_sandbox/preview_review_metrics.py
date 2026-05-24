"""Aggregate metrics from operator agentic sandbox preview review feedback (analytics only)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agentic_sandbox.agentic_readiness_analysis import load_batch_run_records
from app.agentic_sandbox.preview_review_feedback import (
    DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    AgenticPreviewReviewFeedback,
    parse_agentic_preview_review_row,
)
from app.agentic_sandbox.report_paths import (
    DEFAULT_BATCH_RUNS_JSONL,
    DEFAULT_PREVIEW_REVIEW_METRICS_REPORT_PATH,
    DEFAULT_PREVIEW_REVIEW_METRICS_SUMMARY_PATH,
)
from app.operator_console.draft_review_feedback import _FORBIDDEN_TEXT_SUBSTRINGS

_GRAPH_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("graph_status_correct", "graph_status"),
    ("intent_correct", "intent"),
    ("action_correct", "action"),
    ("actionability_correct", "actionability"),
    ("entity_extraction_correct", "entity_extraction"),
)

_RATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("overall_preview_useful", "preview_usefulness_rate"),
    ("graph_status_correct", "graph_status_accuracy_rate"),
    ("intent_correct", "intent_accuracy_rate"),
    ("action_correct", "action_accuracy_rate"),
    ("actionability_correct", "actionability_accuracy_rate"),
    ("entity_extraction_correct", "entity_accuracy_rate"),
    ("knowledge_hints_helpful", "knowledge_helpfulness_rate"),
    ("safety_correct", "safety_correctness_rate"),
    ("ready_for_human_review_correct", "human_review_readiness_accuracy_rate"),
    ("draft_length_reasonable", "draft_length_reasonable_rate"),
)

_ISSUE_FIELDS: tuple[tuple[str, str], ...] = (
    ("intent_correct", "wrong_intent_count"),
    ("action_correct", "wrong_action_count"),
    ("actionability_correct", "wrong_actionability_count"),
    ("knowledge_hints_helpful", "unhelpful_knowledge_count"),
    ("safety_correct", "safety_issue_count"),
    ("draft_length_reasonable", "draft_length_issue_count"),
)


@dataclass(frozen=True)
class PreviewReviewRecordWithContext:
    """One parsed review row with optional intent/action context for breakdowns."""

    review: AgenticPreviewReviewFeedback
    detected_intent: str | None = None
    suggested_action: str | None = None


@dataclass(frozen=True)
class PreviewReviewSliceMetrics:
    """Rates and issue counts for one breakdown slice."""

    total_reviews: int
    preview_usefulness_rate: float
    graph_status_accuracy_rate: float
    intent_accuracy_rate: float
    action_accuracy_rate: float
    actionability_accuracy_rate: float
    entity_accuracy_rate: float
    knowledge_helpfulness_rate: float
    safety_correctness_rate: float
    human_review_readiness_accuracy_rate: float
    draft_length_reasonable_rate: float
    wrong_intent_count: int
    wrong_action_count: int
    wrong_actionability_count: int
    unhelpful_knowledge_count: int
    safety_issue_count: int
    draft_length_issue_count: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "total_reviews": self.total_reviews,
            "preview_usefulness_rate": self.preview_usefulness_rate,
            "graph_status_accuracy_rate": self.graph_status_accuracy_rate,
            "intent_accuracy_rate": self.intent_accuracy_rate,
            "action_accuracy_rate": self.action_accuracy_rate,
            "actionability_accuracy_rate": self.actionability_accuracy_rate,
            "entity_accuracy_rate": self.entity_accuracy_rate,
            "knowledge_helpfulness_rate": self.knowledge_helpfulness_rate,
            "safety_correctness_rate": self.safety_correctness_rate,
            "human_review_readiness_accuracy_rate": self.human_review_readiness_accuracy_rate,
            "draft_length_reasonable_rate": self.draft_length_reasonable_rate,
            "wrong_intent_count": self.wrong_intent_count,
            "wrong_action_count": self.wrong_action_count,
            "wrong_actionability_count": self.wrong_actionability_count,
            "unhelpful_knowledge_count": self.unhelpful_knowledge_count,
            "safety_issue_count": self.safety_issue_count,
            "draft_length_issue_count": self.draft_length_issue_count,
        }


@dataclass(frozen=True)
class AgenticPreviewReviewMetricsSummary:
    """Aggregate metrics from append-only sandbox preview review JSONL."""

    generated_at_utc: str
    source_feedback_path: str
    total_reviews: int
    skipped_malformed_rows: int
    preview_usefulness_rate: float
    graph_status_accuracy_rate: float
    intent_accuracy_rate: float
    action_accuracy_rate: float
    actionability_accuracy_rate: float
    entity_accuracy_rate: float
    knowledge_helpfulness_rate: float
    safety_correctness_rate: float
    human_review_readiness_accuracy_rate: float
    draft_length_reasonable_rate: float
    wrong_intent_count: int
    wrong_action_count: int
    wrong_actionability_count: int
    unhelpful_knowledge_count: int
    safety_issue_count: int
    draft_length_issue_count: int
    weakest_graph_dimensions: tuple[str, ...] = ()
    by_room_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_detected_intent: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_suggested_action: dict[str, dict[str, Any]] = field(default_factory=dict)
    reviews_with_notes_count: int = 0
    operator_notes_summary: str | None = None
    recommended_inspection_targets: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_feedback_path": self.source_feedback_path,
            "total_reviews": self.total_reviews,
            "skipped_malformed_rows": self.skipped_malformed_rows,
            "preview_usefulness_rate": self.preview_usefulness_rate,
            "graph_status_accuracy_rate": self.graph_status_accuracy_rate,
            "intent_accuracy_rate": self.intent_accuracy_rate,
            "action_accuracy_rate": self.action_accuracy_rate,
            "actionability_accuracy_rate": self.actionability_accuracy_rate,
            "entity_accuracy_rate": self.entity_accuracy_rate,
            "knowledge_helpfulness_rate": self.knowledge_helpfulness_rate,
            "safety_correctness_rate": self.safety_correctness_rate,
            "human_review_readiness_accuracy_rate": self.human_review_readiness_accuracy_rate,
            "draft_length_reasonable_rate": self.draft_length_reasonable_rate,
            "top_issues": {
                "wrong_intent_count": self.wrong_intent_count,
                "wrong_action_count": self.wrong_action_count,
                "wrong_actionability_count": self.wrong_actionability_count,
                "unhelpful_knowledge_count": self.unhelpful_knowledge_count,
                "safety_issue_count": self.safety_issue_count,
                "draft_length_issue_count": self.draft_length_issue_count,
            },
            "weakest_graph_dimensions": list(self.weakest_graph_dimensions),
            "by_room_id": self.by_room_id,
            "by_detected_intent": self.by_detected_intent,
            "by_suggested_action": self.by_suggested_action,
            "reviews_with_notes_count": self.reviews_with_notes_count,
            "operator_notes_summary": self.operator_notes_summary,
            "recommended_inspection_targets": list(self.recommended_inspection_targets),
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _batch_context_by_room(
    batch_runs_path: Path | str = DEFAULT_BATCH_RUNS_JSONL,
) -> dict[str, tuple[str | None, str | None]]:
    """Latest batch run intent/action per room_id (analytics join only)."""
    path = Path(batch_runs_path)
    if not path.is_file():
        return {}
    index: dict[str, tuple[str | None, str | None]] = {}
    for record in load_batch_run_records(path):
        index[record.room_id] = (record.detected_intent, record.suggested_action)
    return index


def load_preview_review_records_with_context(
    path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    *,
    batch_runs_path: Path | str = DEFAULT_BATCH_RUNS_JSONL,
) -> tuple[list[PreviewReviewRecordWithContext], int]:
    """Load feedback JSONL rows; return parsed records and skipped malformed line count."""
    file_path = Path(path)
    if not file_path.is_file():
        return [], 0

    batch_index = _batch_context_by_room(batch_runs_path)
    records: list[PreviewReviewRecordWithContext] = []
    skipped = 0

    for line in file_path.read_text(encoding="utf-8").splitlines():
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
        parsed = parse_agentic_preview_review_row(raw)
        if parsed is None:
            skipped += 1
            continue

        intent = _optional_str(raw.get("detected_intent"))
        action = _optional_str(raw.get("suggested_action"))
        if intent is None or action is None:
            batch_ctx = batch_index.get(parsed.room_id)
            if batch_ctx is not None:
                if intent is None:
                    intent = batch_ctx[0]
                if action is None:
                    action = batch_ctx[1]

        records.append(
            PreviewReviewRecordWithContext(
                review=parsed,
                detected_intent=intent,
                suggested_action=action,
            ),
        )
    return records, skipped


def _count_true(rows: list[PreviewReviewRecordWithContext], field_name: str) -> int:
    return sum(1 for row in rows if bool(getattr(row.review, field_name)))


def _compute_slice_metrics(rows: list[PreviewReviewRecordWithContext]) -> PreviewReviewSliceMetrics:
    total = len(rows)
    rates = {
        rate_name: _rate(_count_true(rows, field_name), total)
        for field_name, rate_name in _RATE_FIELDS
    }
    issues = {
        issue_name: total - _count_true(rows, field_name)
        for field_name, issue_name in _ISSUE_FIELDS
    }
    return PreviewReviewSliceMetrics(
        total_reviews=total,
        **rates,
        **issues,
    )


def detect_weakest_graph_dimensions(rows: list[PreviewReviewRecordWithContext]) -> tuple[str, ...]:
    """Return graph dimension labels sorted from lowest to highest accuracy rate."""
    if not rows:
        return ()
    total = len(rows)
    scored: list[tuple[float, str]] = []
    for field_name, label in _GRAPH_DIMENSIONS:
        rate = _rate(_count_true(rows, field_name), total)
        scored.append((rate, label))
    scored.sort(key=lambda item: (item[0], item[1]))
    return tuple(label for _, label in scored)


def _build_notes_summary(rows: list[PreviewReviewRecordWithContext]) -> tuple[int, str | None]:
    with_notes = [row for row in rows if row.review.reviewer_notes]
    count = len(with_notes)
    if count == 0:
        return 0, None
    return (
        count,
        f"{count} review(s) include operator notes (note text omitted from analytics report).",
    )


def _recommended_inspection_targets(
    rows: list[PreviewReviewRecordWithContext],
    *,
    weakest_dimensions: tuple[str, ...],
    top_issues: dict[str, int],
) -> tuple[str, ...]:
    if not rows:
        return ()

    targets: list[str] = []
    if weakest_dimensions:
        targets.append(
            f"Re-inspect sandbox graph `{weakest_dimensions[0]}` accuracy "
            f"(lowest-rated graph dimension).",
        )

    issue_ranking = sorted(top_issues.items(), key=lambda item: (-item[1], item[0]))
    for issue_name, count in issue_ranking[:3]:
        if count > 0:
            targets.append(f"Address `{issue_name}` ({count} flagged review(s)).")

    room_issue_counts: Counter[str] = Counter()
    for row in rows:
        review = row.review
        issues = sum(
            1
            for flag in (
                not review.intent_correct,
                not review.action_correct,
                not review.actionability_correct,
                not review.entity_extraction_correct,
                not review.knowledge_hints_helpful,
                not review.safety_correct,
                not review.overall_preview_useful,
            )
            if flag
        )
        if issues:
            room_issue_counts[review.room_id] += issues

    for room_id, _ in room_issue_counts.most_common(5):
        targets.append(f"Replay agentic sandbox preview for room `{room_id}`.")

    intent_slices: dict[str, list[PreviewReviewRecordWithContext]] = defaultdict(list)
    for row in rows:
        if row.detected_intent:
            intent_slices[row.detected_intent].append(row)
    for intent, slice_rows in sorted(
        intent_slices.items(),
        key=lambda item: _rate(_count_true(item[1], "overall_preview_useful"), len(item[1])),
    ):
        if len(slice_rows) >= 2:
            rate = _rate(_count_true(slice_rows, "overall_preview_useful"), len(slice_rows))
            if rate < 0.5:
                targets.append(
                    f"Inspect intent `{intent}` preview usefulness ({rate:.0%} useful, "
                    f"n={len(slice_rows)}).",
                )
                break

    deduped: list[str] = []
    seen: set[str] = set()
    for target in targets:
        if target not in seen:
            seen.add(target)
            deduped.append(target)
    return tuple(deduped[:12])


def summarize_preview_review_metrics(
    records: list[PreviewReviewRecordWithContext],
    *,
    source_feedback_path: str,
    skipped_malformed_rows: int = 0,
    generated_at_utc: str | None = None,
) -> AgenticPreviewReviewMetricsSummary:
    """Aggregate preview review feedback into summary metrics."""
    overall = _compute_slice_metrics(records)
    weakest = detect_weakest_graph_dimensions(records)
    notes_count, notes_summary = _build_notes_summary(records)

    by_room: dict[str, dict[str, Any]] = {}
    room_groups: dict[str, list[PreviewReviewRecordWithContext]] = defaultdict(list)
    for row in records:
        room_groups[row.review.room_id].append(row)
    for room_id, group in sorted(room_groups.items()):
        by_room[room_id] = _compute_slice_metrics(group).to_json_dict()

    by_intent: dict[str, dict[str, Any]] = {}
    intent_groups: dict[str, list[PreviewReviewRecordWithContext]] = defaultdict(list)
    for row in records:
        if row.detected_intent:
            intent_groups[row.detected_intent].append(row)
    for intent, group in sorted(intent_groups.items()):
        by_intent[intent] = _compute_slice_metrics(group).to_json_dict()

    by_action: dict[str, dict[str, Any]] = {}
    action_groups: dict[str, list[PreviewReviewRecordWithContext]] = defaultdict(list)
    for row in records:
        if row.suggested_action:
            action_groups[row.suggested_action].append(row)
    for action, group in sorted(action_groups.items()):
        by_action[action] = _compute_slice_metrics(group).to_json_dict()

    top_issues = {
        "wrong_intent_count": overall.wrong_intent_count,
        "wrong_action_count": overall.wrong_action_count,
        "wrong_actionability_count": overall.wrong_actionability_count,
        "unhelpful_knowledge_count": overall.unhelpful_knowledge_count,
        "safety_issue_count": overall.safety_issue_count,
        "draft_length_issue_count": overall.draft_length_issue_count,
    }
    inspection_targets = _recommended_inspection_targets(
        records,
        weakest_dimensions=weakest,
        top_issues=top_issues,
    )

    return AgenticPreviewReviewMetricsSummary(
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_feedback_path=source_feedback_path,
        total_reviews=overall.total_reviews,
        skipped_malformed_rows=skipped_malformed_rows,
        preview_usefulness_rate=overall.preview_usefulness_rate,
        graph_status_accuracy_rate=overall.graph_status_accuracy_rate,
        intent_accuracy_rate=overall.intent_accuracy_rate,
        action_accuracy_rate=overall.action_accuracy_rate,
        actionability_accuracy_rate=overall.actionability_accuracy_rate,
        entity_accuracy_rate=overall.entity_accuracy_rate,
        knowledge_helpfulness_rate=overall.knowledge_helpfulness_rate,
        safety_correctness_rate=overall.safety_correctness_rate,
        human_review_readiness_accuracy_rate=overall.human_review_readiness_accuracy_rate,
        draft_length_reasonable_rate=overall.draft_length_reasonable_rate,
        wrong_intent_count=overall.wrong_intent_count,
        wrong_action_count=overall.wrong_action_count,
        wrong_actionability_count=overall.wrong_actionability_count,
        unhelpful_knowledge_count=overall.unhelpful_knowledge_count,
        safety_issue_count=overall.safety_issue_count,
        draft_length_issue_count=overall.draft_length_issue_count,
        weakest_graph_dimensions=weakest,
        by_room_id=by_room,
        by_detected_intent=by_intent,
        by_suggested_action=by_action,
        reviews_with_notes_count=notes_count,
        operator_notes_summary=notes_summary,
        recommended_inspection_targets=inspection_targets,
    )


def render_preview_review_metrics_markdown(
    summary: AgenticPreviewReviewMetricsSummary,
) -> str:
    """Render metrics markdown (no transcripts, prompts, drafts, or raw notes)."""
    lines = [
        "# Agentic Preview Review Metrics Report",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Source:** `{summary.source_feedback_path}`  ",
        "**Scope:** Analytics-only aggregation of operator sandbox preview reviews.",
        "",
        "## Overall metrics",
        "",
        f"- **total_reviews:** {summary.total_reviews}",
        f"- **skipped_malformed_rows:** {summary.skipped_malformed_rows}",
        f"- **preview_usefulness_rate:** {summary.preview_usefulness_rate:.1%}",
        f"- **graph_status_accuracy_rate:** {summary.graph_status_accuracy_rate:.1%}",
        f"- **intent_accuracy_rate:** {summary.intent_accuracy_rate:.1%}",
        f"- **action_accuracy_rate:** {summary.action_accuracy_rate:.1%}",
        f"- **actionability_accuracy_rate:** {summary.actionability_accuracy_rate:.1%}",
        f"- **entity_accuracy_rate:** {summary.entity_accuracy_rate:.1%}",
        f"- **knowledge_helpfulness_rate:** {summary.knowledge_helpfulness_rate:.1%}",
        f"- **safety_correctness_rate:** {summary.safety_correctness_rate:.1%}",
        f"- **human_review_readiness_accuracy_rate:** "
        f"{summary.human_review_readiness_accuracy_rate:.1%}",
        f"- **draft_length_reasonable_rate:** {summary.draft_length_reasonable_rate:.1%}",
        "",
        "## Weakest graph dimensions",
        "",
    ]
    if summary.weakest_graph_dimensions:
        for index, dimension in enumerate(summary.weakest_graph_dimensions, start=1):
            lines.append(f"{index}. `{dimension}`")
    else:
        lines.append("*(No reviews yet.)*")

    lines.extend(
        [
            "",
            "## Knowledge usefulness",
            "",
            f"- **knowledge_helpfulness_rate:** {summary.knowledge_helpfulness_rate:.1%}",
            f"- **unhelpful_knowledge_count:** {summary.unhelpful_knowledge_count}",
            "",
            "## Safety / readiness confidence",
            "",
            f"- **safety_correctness_rate:** {summary.safety_correctness_rate:.1%}",
            f"- **safety_issue_count:** {summary.safety_issue_count}",
            f"- **human_review_readiness_accuracy_rate:** "
            f"{summary.human_review_readiness_accuracy_rate:.1%}",
            f"- **draft_length_reasonable_rate:** {summary.draft_length_reasonable_rate:.1%}",
            f"- **draft_length_issue_count:** {summary.draft_length_issue_count}",
            "",
            "## Top issues (counts)",
            "",
            "| Issue | Count |",
            "|-------|------:|",
            f"| wrong_intent | {summary.wrong_intent_count} |",
            f"| wrong_action | {summary.wrong_action_count} |",
            f"| wrong_actionability | {summary.wrong_actionability_count} |",
            f"| unhelpful_knowledge | {summary.unhelpful_knowledge_count} |",
            f"| safety_issue | {summary.safety_issue_count} |",
            f"| draft_length_issue | {summary.draft_length_issue_count} |",
            "",
        ],
    )

    if summary.operator_notes_summary:
        lines.extend(
            [
                "## Operator notes (safe summary)",
                "",
                f"- **reviews_with_notes_count:** {summary.reviews_with_notes_count}",
                f"- {summary.operator_notes_summary}",
                "",
            ],
        )

    lines.extend(["## Recommended next inspection targets", ""])
    if summary.recommended_inspection_targets:
        for target in summary.recommended_inspection_targets:
            lines.append(f"- {target}")
    else:
        lines.append("*(No targets — submit preview reviews to populate metrics.)*")

    if summary.by_detected_intent:
        lines.extend(["", "## Breakdown by detected_intent", ""])
        lines.extend(_render_breakdown_table(summary.by_detected_intent))

    if summary.by_suggested_action:
        lines.extend(["", "## Breakdown by suggested_action", ""])
        lines.extend(_render_breakdown_table(summary.by_suggested_action))

    if summary.by_room_id and len(summary.by_room_id) <= 20:
        lines.extend(["", "## Breakdown by room_id", ""])
        lines.extend(_render_breakdown_table(summary.by_room_id))

    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Analytics only — does not change graph logic, mappings, or retrieval.",
            "- No auto-learning from operator feedback.",
            "- Safe output only: no transcripts, prompts, retrieval snippets, or draft text.",
            "",
        ],
    )
    return "\n".join(lines)


def _render_breakdown_table(slices: dict[str, dict[str, Any]]) -> list[str]:
    lines = [
        "| Slice | Reviews | Useful rate | Intent rate | Action rate | Knowledge rate |",
        "|-------|--------:|------------:|------------:|------------:|---------------:|",
    ]
    for key, stats in sorted(slices.items()):
        lines.append(
            f"| `{key}` | {stats['total_reviews']} | "
            f"{stats['preview_usefulness_rate']:.1%} | "
            f"{stats['intent_accuracy_rate']:.1%} | "
            f"{stats['action_accuracy_rate']:.1%} | "
            f"{stats['knowledge_helpfulness_rate']:.1%} |",
        )
    return lines


def assert_preview_review_metrics_output_safe(content: str) -> None:
    """Fail closed if report output may contain forbidden content."""
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(
                f"preview review metrics output must not contain forbidden token: {token}",
            )
    for token in (
        "conversation transcript",
        "gold_reference_reply",
        '"messages"',
        "original_vendor",
        "reviewer_notes",
    ):
        if token in lowered:
            raise ValueError(
                f"preview review metrics output must not contain forbidden token: {token}",
            )
    if re.search(r"sk-[a-z0-9]{8,}", content, flags=re.IGNORECASE):
        raise ValueError("preview review metrics output must not contain API key patterns")


def build_agentic_preview_review_metrics_report(
    feedback_path: Path | str = DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    *,
    batch_runs_path: Path | str = DEFAULT_BATCH_RUNS_JSONL,
    summary_output: Path = DEFAULT_PREVIEW_REVIEW_METRICS_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_PREVIEW_REVIEW_METRICS_REPORT_PATH,
    generated_at_utc: str | None = None,
) -> AgenticPreviewReviewMetricsSummary:
    """Load preview review JSONL and write JSON + markdown metrics reports."""
    source = Path(feedback_path)
    records, skipped = load_preview_review_records_with_context(
        source,
        batch_runs_path=batch_runs_path,
    )
    summary = summarize_preview_review_metrics(
        records,
        source_feedback_path=str(source),
        skipped_malformed_rows=skipped,
        generated_at_utc=generated_at_utc,
    )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_preview_review_metrics_markdown(summary)

    assert_preview_review_metrics_output_safe(json_text)
    assert_preview_review_metrics_output_safe(markdown)

    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary

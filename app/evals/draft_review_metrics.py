"""Aggregate draft review feedback into offline calibration metrics (no auto-learning)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.operator_console.draft_review_feedback import (
    _FORBIDDEN_TEXT_SUBSTRINGS,
    DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
    DraftReviewFeedback,
    load_draft_review_feedback_rows,
)

DEFAULT_METRICS_SUMMARY_PATH = Path("reports/draft_review_metrics_summary.json")
DEFAULT_METRICS_REPORT_PATH = Path("reports/draft_review_metrics_report.md")

_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "messages",
        "user_input",
        "gold_reference_reply",
        "retrieved_context",
        "prompt",
        "prompt_body",
        "draft_response",
        "final_response",
        "conversation_transcript",
        "open_ticket_preview",
        "suggested_better_reply",
    },
)

_FAILURE_PATTERN_DEFS: tuple[tuple[str, str, str], ...] = (
    ("action_mismatch", "Suggested action mismatch", "checkbox"),
    ("wrong_intent", "Wrong detected intent", "checkbox"),
    ("missing_entity", "Missing or wrong entities", "checkbox"),
    ("verbose_draft", "Too verbose", "checkbox"),
    ("hallucination", "Hallucination / unsupported claim", "checkbox"),
    ("not_usable", "Draft not usable", "checkbox"),
    ("unclear_reply", "Unclear reply (note heuristic)", "note"),
    ("policy_misunderstanding", "Policy misunderstanding (note heuristic)", "note"),
)

_NOTE_HEURISTICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("unclear_reply", ("unclear", "نامشخص", "مبهم", "گنگ", "نامفهوم")),
    (
        "policy_misunderstanding",
        ("policy", "قانون", "سیاست", "مقررات", "خط‌مشی", "خط مشی"),
    ),
)


@dataclass(frozen=True)
class GroupMetricRates:
    """Per-dimension rates over a slice of reviews."""

    count: int
    usable_rate: float
    hallucination_rate: float
    verbosity_rate: float
    intent_accuracy_rate: float
    action_accuracy_rate: float
    entity_accuracy_rate: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "usable_rate": self.usable_rate,
            "hallucination_rate": self.hallucination_rate,
            "verbosity_rate": self.verbosity_rate,
            "intent_accuracy_rate": self.intent_accuracy_rate,
            "action_accuracy_rate": self.action_accuracy_rate,
            "entity_accuracy_rate": self.entity_accuracy_rate,
        }


@dataclass(frozen=True)
class DraftReviewMetricsSummary:
    """Offline aggregate metrics from local draft review JSONL."""

    total_reviews: int
    usable_rate: float
    hallucination_rate: float
    verbosity_rate: float
    intent_accuracy_rate: float
    action_accuracy_rate: float
    entity_accuracy_rate: float
    entity_applicable_count: int = 0
    entity_not_applicable_count: int = 0
    unnecessary_followup_rate: float = 0.0
    by_detected_intent: dict[str, GroupMetricRates] = field(default_factory=dict)
    by_conceptual_intent_fa: dict[str, GroupMetricRates] = field(default_factory=dict)
    by_suggested_action: dict[str, GroupMetricRates] = field(default_factory=dict)
    by_ticket_label: dict[str, GroupMetricRates] = field(default_factory=dict)
    most_common_reviewer_notes: tuple[tuple[str, int], ...] = ()
    most_common_failure_patterns: tuple[tuple[str, int], ...] = ()
    generated_at_utc: str = ""
    source_feedback_path: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_feedback_path": self.source_feedback_path,
            "total_reviews": self.total_reviews,
            "usable_rate": self.usable_rate,
            "hallucination_rate": self.hallucination_rate,
            "verbosity_rate": self.verbosity_rate,
            "intent_accuracy_rate": self.intent_accuracy_rate,
            "action_accuracy_rate": self.action_accuracy_rate,
            "entity_accuracy_rate": self.entity_accuracy_rate,
            "entity_applicable_count": self.entity_applicable_count,
            "entity_not_applicable_count": self.entity_not_applicable_count,
            "unnecessary_followup_rate": self.unnecessary_followup_rate,
            "by_detected_intent": {
                key: value.to_json_dict() for key, value in self.by_detected_intent.items()
            },
            "by_conceptual_intent_fa": {
                key: value.to_json_dict() for key, value in self.by_conceptual_intent_fa.items()
            },
            "by_suggested_action": {
                key: value.to_json_dict() for key, value in self.by_suggested_action.items()
            },
            "by_ticket_label": {
                key: value.to_json_dict() for key, value in self.by_ticket_label.items()
            },
            "most_common_reviewer_notes": [
                {"note": note, "count": count} for note, count in self.most_common_reviewer_notes
            ],
            "most_common_failure_patterns": [
                {"pattern_id": pattern_id, "count": count}
                for pattern_id, count in self.most_common_failure_patterns
            ],
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


def _entity_applicable_rows(rows: list[DraftReviewFeedback]) -> list[DraftReviewFeedback]:
    return [row for row in rows if row.entities_applicable]


def _entity_accuracy_counts(rows: list[DraftReviewFeedback]) -> tuple[int, int, int]:
    """Return (correct, applicable_count, not_applicable_count)."""
    applicable = _entity_applicable_rows(rows)
    correct = sum(1 for row in applicable if row.entities_correct is True)
    not_applicable = len(rows) - len(applicable)
    return correct, len(applicable), not_applicable


def _entity_accuracy_rate(rows: list[DraftReviewFeedback]) -> float:
    correct, applicable_count, _ = _entity_accuracy_counts(rows)
    return _rate(correct, applicable_count)


def _group_metric_rates(rows: list[DraftReviewFeedback]) -> GroupMetricRates:
    total = len(rows)
    return GroupMetricRates(
        count=total,
        usable_rate=_rate(sum(1 for row in rows if row.draft_usable), total),
        hallucination_rate=_rate(
            sum(1 for row in rows if row.hallucination_detected),
            total,
        ),
        verbosity_rate=_rate(sum(1 for row in rows if row.too_verbose), total),
        intent_accuracy_rate=_rate(sum(1 for row in rows if row.intent_correct), total),
        action_accuracy_rate=_rate(sum(1 for row in rows if row.action_correct), total),
        entity_accuracy_rate=_entity_accuracy_rate(rows),
    )


def _group_breakdown(
    rows: list[DraftReviewFeedback],
    key_fn: Any,
) -> dict[str, GroupMetricRates]:
    buckets: dict[str, list[DraftReviewFeedback]] = defaultdict(list)
    for row in rows:
        buckets[key_fn(row)].append(row)
    return {key: _group_metric_rates(bucket) for key, bucket in sorted(buckets.items())}


def _checkbox_failure_patterns(row: DraftReviewFeedback) -> list[str]:
    patterns: list[str] = []
    if not row.action_correct:
        patterns.append("action_mismatch")
    if not row.intent_correct:
        patterns.append("wrong_intent")
    if row.entities_applicable and row.entities_correct is False:
        patterns.append("missing_entity")
    if row.too_verbose:
        patterns.append("verbose_draft")
    if row.hallucination_detected:
        patterns.append("hallucination")
    if not row.draft_usable:
        patterns.append("not_usable")
    return patterns


def _note_failure_patterns(note: str | None) -> list[str]:
    if not note or not note.strip():
        return []
    lowered = note.strip().lower()
    found: list[str] = []
    for pattern_id, keywords in _NOTE_HEURISTICS:
        if any(keyword in lowered for keyword in keywords):
            found.append(pattern_id)
    return found


def detect_failure_patterns(row: DraftReviewFeedback) -> list[str]:
    """Lightweight failure tags from checkboxes and reviewer-note heuristics."""
    seen: set[str] = set()
    ordered: list[str] = []
    for pattern_id in _checkbox_failure_patterns(row):
        if pattern_id not in seen:
            seen.add(pattern_id)
            ordered.append(pattern_id)
    for pattern_id in _note_failure_patterns(row.reviewer_note):
        if pattern_id not in seen:
            seen.add(pattern_id)
            ordered.append(pattern_id)
    return ordered


def aggregate_failure_pattern_counts(
    rows: list[DraftReviewFeedback],
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(detect_failure_patterns(row))
    return counter


def compute_draft_review_metrics(
    rows: list[DraftReviewFeedback],
    *,
    source_feedback_path: str = "",
    generated_at_utc: str | None = None,
) -> DraftReviewMetricsSummary:
    """Compute summary rates and breakdowns from parsed feedback rows."""
    total = len(rows)
    overall = _group_metric_rates(rows)

    note_counter: Counter[str] = Counter()
    for row in rows:
        if row.reviewer_note:
            normalized = re.sub(r"\s+", " ", row.reviewer_note.strip())
            if normalized:
                note_counter[normalized] += 1

    failure_counts = aggregate_failure_pattern_counts(rows)

    unnecessary_followup = sum(1 for row in rows if row.unnecessary_followup_detected)
    _, entity_applicable_count, entity_not_applicable_count = _entity_accuracy_counts(rows)

    return DraftReviewMetricsSummary(
        total_reviews=total,
        usable_rate=overall.usable_rate,
        hallucination_rate=overall.hallucination_rate,
        verbosity_rate=overall.verbosity_rate,
        intent_accuracy_rate=overall.intent_accuracy_rate,
        action_accuracy_rate=overall.action_accuracy_rate,
        entity_accuracy_rate=overall.entity_accuracy_rate,
        entity_applicable_count=entity_applicable_count,
        entity_not_applicable_count=entity_not_applicable_count,
        unnecessary_followup_rate=_rate(unnecessary_followup, total),
        by_detected_intent=_group_breakdown(
            rows,
            lambda row: _dimension_key(row.detected_intent),
        ),
        by_conceptual_intent_fa=_group_breakdown(
            rows,
            lambda row: _dimension_key(row.conceptual_intent_fa),
        ),
        by_suggested_action=_group_breakdown(
            rows,
            lambda row: _dimension_key(row.suggested_action),
        ),
        by_ticket_label=_group_breakdown(
            rows,
            lambda row: _dimension_key(getattr(row, "ticket_label", None)),
        ),
        most_common_reviewer_notes=tuple(note_counter.most_common(10)),
        most_common_failure_patterns=tuple(failure_counts.most_common()),
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_feedback_path=source_feedback_path,
    )


def _weak_slices(
    breakdown: dict[str, GroupMetricRates],
    *,
    rate_attr: str,
    min_count: int = 1,
    limit: int = 5,
) -> list[tuple[str, GroupMetricRates]]:
    items = [
        (key, stats)
        for key, stats in breakdown.items()
        if stats.count >= min_count and key != "(none)"
    ]
    items.sort(key=lambda item: getattr(item[1], rate_attr))
    return items[:limit]


def _failure_pattern_label(pattern_id: str) -> str:
    for pid, label, _source in _FAILURE_PATTERN_DEFS:
        if pid == pattern_id:
            return label
    return pattern_id


def format_draft_review_metrics_markdown(summary: DraftReviewMetricsSummary) -> str:
    """Render offline markdown report (aggregate metrics only)."""
    lines = [
        "# Draft Review Metrics Report",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Source:** `{summary.source_feedback_path}`  ",
        "**Scope:** Local operator draft review feedback only — evaluation/calibration; "
        "no auto-learning, prompts, or transcripts.",
        "",
        "## Overall metrics",
        "",
        f"- **total_reviews:** {summary.total_reviews}",
        f"- **usable_rate:** {summary.usable_rate:.1%}",
        f"- **hallucination_rate:** {summary.hallucination_rate:.1%}",
        f"- **verbosity_rate:** {summary.verbosity_rate:.1%}",
        f"- **intent_accuracy_rate:** {summary.intent_accuracy_rate:.1%}",
        f"- **action_accuracy_rate:** {summary.action_accuracy_rate:.1%}",
        f"- **entity_accuracy_rate:** {summary.entity_accuracy_rate:.1%} "
        f"({summary.entity_applicable_count} applicable reviews)",
        f"- **entity_applicable_count:** {summary.entity_applicable_count}",
        f"- **entity_not_applicable_count:** {summary.entity_not_applicable_count}",
        f"- **unnecessary_followup_rate:** {summary.unnecessary_followup_rate:.1%}",
        "",
    ]

    if summary.total_reviews == 0:
        lines.extend(
            [
                "*(No draft reviews in source file yet.)*",
                "",
                "## Governance",
                "",
                "- Metrics are computed from `reports/draft_review_feedback.jsonl` only.",
                "- No full prompts, transcripts, gold replies, or retrieval snippets.",
                "- No automatic prompt, taxonomy, or model updates.",
                "",
            ],
        )
        return "\n".join(lines)

    weak_intents = _weak_slices(summary.by_detected_intent, rate_attr="intent_accuracy_rate")
    weak_actions = _weak_slices(summary.by_suggested_action, rate_attr="action_accuracy_rate")

    lines.extend(
        [
            "## Top weak intents (lowest intent accuracy)",
            "",
            "| Intent | Count | Intent accuracy |",
            "|--------|------:|----------------:|",
        ],
    )
    if weak_intents:
        for intent, stats in weak_intents:
            lines.append(
                f"| {intent} | {stats.count} | {stats.intent_accuracy_rate:.1%} |",
            )
    else:
        lines.append("| *(none)* | 0 | — |")
    lines.append("")

    lines.extend(
        [
            "## Top weak suggested actions (lowest action accuracy)",
            "",
            "| Action | Count | Action accuracy |",
            "|--------|------:|----------------:|",
        ],
    )
    if weak_actions:
        for action, stats in weak_actions:
            lines.append(
                f"| {action} | {stats.count} | {stats.action_accuracy_rate:.1%} |",
            )
    else:
        lines.append("| *(none)* | 0 | — |")
    lines.append("")

    lines.extend(
        [
            "## Verbosity observations",
            "",
            f"- **verbosity_rate (overall):** {summary.verbosity_rate:.1%}",
        ],
    )
    verbose_by_intent = sorted(
        summary.by_detected_intent.items(),
        key=lambda item: item[1].verbosity_rate,
        reverse=True,
    )[:5]
    if verbose_by_intent:
        lines.append("- **Highest verbosity by detected_intent:**")
        for intent, stats in verbose_by_intent:
            if stats.verbosity_rate > 0:
                lines.append(f"  - `{intent}`: {stats.verbosity_rate:.1%} ({stats.count} reviews)")
    lines.append("")

    lines.extend(
        [
            "## Hallucination observations",
            "",
            f"- **hallucination_rate (overall):** {summary.hallucination_rate:.1%}",
        ],
    )
    hall_by_action = sorted(
        summary.by_suggested_action.items(),
        key=lambda item: item[1].hallucination_rate,
        reverse=True,
    )[:5]
    if hall_by_action:
        lines.append("- **Highest hallucination flags by suggested_action:**")
        for action, stats in hall_by_action:
            if stats.hallucination_rate > 0:
                lines.append(
                    f"  - `{action}`: {stats.hallucination_rate:.1%} ({stats.count} reviews)",
                )
    lines.append("")

    lines.extend(
        [
            "## Most common failure patterns",
            "",
            "| Pattern | Count |",
            "|---------|------:|",
        ],
    )
    if summary.most_common_failure_patterns:
        for pattern_id, count in summary.most_common_failure_patterns[:10]:
            label = _failure_pattern_label(pattern_id)
            lines.append(f"| {label} (`{pattern_id}`) | {count} |")
    else:
        lines.append("| *(none)* | 0 |")
    lines.append("")

    lines.extend(["## Reviewer note themes (exact short notes, top 10)", ""])
    if summary.most_common_reviewer_notes:
        for note, count in summary.most_common_reviewer_notes:
            escaped = note.replace("|", "\\|")
            lines.append(f"- ({count}×) {escaped}")
    else:
        lines.append("*(no reviewer notes yet)*")
    lines.append("")

    lines.extend(
        [
            "## Breakdown by ticket_label",
            "",
            "| Label | Reviews | Usable | Hallucination | Verbose |",
            "|-------|--------:|-------:|--------------:|--------:|",
        ],
    )
    for label, stats in summary.by_ticket_label.items():
        lines.append(
            f"| {label} | {stats.count} | {stats.usable_rate:.1%} | "
            f"{stats.hallucination_rate:.1%} | {stats.verbosity_rate:.1%} |",
        )
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Input: append-only `reports/draft_review_feedback.jsonl` (gitignored).",
            "- Outputs: aggregate rates and short reviewer-note counts only.",
            "- **No** automatic prompt mutation, taxonomy changes, model retraining, "
            "or customer send.",
            "",
        ],
    )
    return "\n".join(lines)


def assert_metrics_output_safe(content: str) -> None:
    """Reject outputs that may embed prompts, transcripts, or forbidden keys."""
    lowered = content.lower()
    for key in _FORBIDDEN_OUTPUT_KEYS:
        if f'"{key}"' in content:
            raise ValueError(f"metrics output must not reference forbidden key: {key}")
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"metrics output must not contain forbidden token: {token}")


def build_draft_review_metrics_report(
    feedback_path: Path | str = DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
    *,
    summary_output: Path = DEFAULT_METRICS_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_METRICS_REPORT_PATH,
    generated_at_utc: str | None = None,
) -> DraftReviewMetricsSummary:
    """Load feedback JSONL, write JSON summary + markdown report."""
    source = Path(feedback_path)
    rows = load_draft_review_feedback_rows(source)
    summary = compute_draft_review_metrics(
        rows,
        source_feedback_path=str(source),
        generated_at_utc=generated_at_utc,
    )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = format_draft_review_metrics_markdown(summary)

    assert_metrics_output_safe(json_text)
    assert_metrics_output_safe(markdown)

    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary

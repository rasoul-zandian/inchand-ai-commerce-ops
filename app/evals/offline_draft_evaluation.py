"""Offline evaluation of draft suggestions vs historical gold human replies (deterministic v1)."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evals.offline_draft_generation import assert_draft_reply_safe, gold_reference_reply_hash
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits

LOW_OVERLAP_THRESHOLD = 0.15

_PUNCTUATION_RE = re.compile(
    r"[^\w\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+",
    re.UNICODE,
)


@dataclass(frozen=True)
class DraftGoldCaseResult:
    """Per-case metrics only (no draft or gold body text)."""

    case_id: str
    room_id: str | None
    ticket_label: str | None
    route_label: str | None
    detected_intent: str | None
    suggested_action: str | None
    draft_generated: bool
    missing_draft: bool
    unsafe_draft: bool
    draft_length: int
    gold_length: int
    lexical_overlap_score: float | None
    low_overlap: bool
    gold_hash_match: bool | None


@dataclass
class OfflineDraftEvaluationSummary:
    """Aggregate offline draft vs gold evaluation (v1)."""

    total_cases: int = 0
    evaluated_cases: int = 0
    missing_draft_count: int = 0
    unsafe_draft_count: int = 0
    average_draft_length: float = 0.0
    average_gold_length: float = 0.0
    lexical_overlap_score_avg: float = 0.0
    intent_counts: dict[str, int] = field(default_factory=dict)
    suggested_action_counts: dict[str, int] = field(default_factory=dict)
    cases_by_ticket_label: dict[str, int] = field(default_factory=dict)
    cases_with_low_overlap: list[dict[str, Any]] = field(default_factory=list)
    draft_suggestions_path: str = ""
    benchmark_path: str = ""
    output_json_path: str = ""
    output_markdown_path: str = ""
    generated_at_utc: str = ""
    low_overlap_threshold: float = LOW_OVERLAP_THRESHOLD

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "evaluated_cases": self.evaluated_cases,
            "missing_draft_count": self.missing_draft_count,
            "unsafe_draft_count": self.unsafe_draft_count,
            "average_draft_length": round(self.average_draft_length, 2),
            "average_gold_length": round(self.average_gold_length, 2),
            "lexical_overlap_score_avg": round(self.lexical_overlap_score_avg, 4),
            "intent_counts": dict(sorted(self.intent_counts.items())),
            "suggested_action_counts": dict(sorted(self.suggested_action_counts.items())),
            "cases_by_ticket_label": dict(sorted(self.cases_by_ticket_label.items())),
            "cases_with_low_overlap": self.cases_with_low_overlap,
            "draft_suggestions_path": self.draft_suggestions_path,
            "benchmark_path": self.benchmark_path,
            "output_json_path": self.output_json_path,
            "output_markdown_path": self.output_markdown_path,
            "generated_at_utc": self.generated_at_utc,
            "low_overlap_threshold": self.low_overlap_threshold,
        }


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"JSONL not found: {path}")
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path}:{line_no}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"line {line_no} must be a JSON object")
        rows.append(row)
    return rows


def load_draft_suggestions(path: Path | str) -> dict[str, dict[str, Any]]:
    """Index draft suggestion rows by ``case_id``."""
    index: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl_rows(Path(path)):
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            continue
        index[case_id.strip()] = row
    return index


def load_benchmark_gold(path: Path | str) -> dict[str, dict[str, Any]]:
    """Index benchmark rows by ``case_id`` (includes ``gold_reference_reply`` for local eval)."""
    index: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl_rows(Path(path)):
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            continue
        index[case_id.strip()] = row
    return index


def normalize_text_for_overlap(text: str) -> str:
    """Normalize Persian/Latin text for simple lexical overlap (v1)."""
    cleaned = normalize_persian_arabic_digits(text.strip())
    cleaned = _PUNCTUATION_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def tokenize_for_overlap(text: str) -> set[str]:
    """Whitespace tokens after normalization; drops single-character noise."""
    normalized = normalize_text_for_overlap(text)
    if not normalized:
        return set()
    return {token for token in normalized.split() if len(token) > 1}


def lexical_overlap_score(draft: str, gold: str) -> float:
    """Jaccard similarity over normalized token sets (0.0–1.0)."""
    draft_tokens = tokenize_for_overlap(draft)
    gold_tokens = tokenize_for_overlap(gold)
    if not draft_tokens and not gold_tokens:
        return 0.0
    if not draft_tokens or not gold_tokens:
        return 0.0
    intersection = draft_tokens & gold_tokens
    union = draft_tokens | gold_tokens
    return len(intersection) / len(union)


def is_draft_unsafe(draft: str) -> bool:
    """Return True if draft fails Step 171 safety checks."""
    try:
        assert_draft_reply_safe(draft)
    except ValueError:
        return True
    return False


def evaluate_draft_against_gold(
    case_id: str,
    draft_row: Mapping[str, Any] | None,
    gold_row: Mapping[str, Any],
    *,
    low_overlap_threshold: float = LOW_OVERLAP_THRESHOLD,
) -> DraftGoldCaseResult:
    """Compare one draft suggestion row to benchmark gold (metrics only in result)."""
    gold_text = gold_row.get("gold_reference_reply")
    gold = gold_text.strip() if isinstance(gold_text, str) else ""
    gold_length = len(gold)

    draft_generated = False
    draft = ""
    if draft_row is not None:
        draft_generated = bool(draft_row.get("draft_generated"))
        raw_draft = draft_row.get("draft_reply")
        if isinstance(raw_draft, str):
            draft = raw_draft.strip()

    missing_draft = not draft_generated or not draft
    unsafe_draft = bool(draft) and is_draft_unsafe(draft)
    draft_length = len(draft)

    overlap: float | None = None
    low_overlap = False
    if draft and gold and not unsafe_draft:
        overlap = lexical_overlap_score(draft, gold)
        low_overlap = overlap < low_overlap_threshold

    gold_hash_match: bool | None = None
    if draft_row is not None and gold:
        expected_hash = gold_reference_reply_hash(gold)
        actual_hash = draft_row.get("gold_reference_reply_hash")
        if isinstance(actual_hash, str) and actual_hash.strip():
            gold_hash_match = actual_hash.strip() == expected_hash

    ticket_label = gold_row.get("ticket_label")
    if draft_row is not None and draft_row.get("ticket_label") is not None:
        ticket_label = draft_row.get("ticket_label")

    return DraftGoldCaseResult(
        case_id=case_id,
        room_id=_optional_str(gold_row.get("room_id") or (draft_row or {}).get("room_id")),
        ticket_label=_optional_str(ticket_label),
        route_label=_optional_str(
            (draft_row or {}).get("route_label") or gold_row.get("route_label"),
        ),
        detected_intent=_optional_str((draft_row or {}).get("detected_intent")),
        suggested_action=_optional_str((draft_row or {}).get("suggested_action")),
        draft_generated=draft_generated,
        missing_draft=missing_draft,
        unsafe_draft=unsafe_draft,
        draft_length=draft_length,
        gold_length=gold_length,
        lexical_overlap_score=overlap,
        low_overlap=low_overlap,
        gold_hash_match=gold_hash_match,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def summarize_draft_evaluation(
    case_results: Sequence[DraftGoldCaseResult],
    *,
    draft_suggestions_path: Path | str,
    benchmark_path: Path | str,
    output_json_path: Path | str,
    output_markdown_path: Path | str,
    low_overlap_threshold: float = LOW_OVERLAP_THRESHOLD,
) -> OfflineDraftEvaluationSummary:
    """Aggregate per-case results into summary metrics."""
    summary = OfflineDraftEvaluationSummary(
        total_cases=len(case_results),
        draft_suggestions_path=str(Path(draft_suggestions_path).resolve()),
        benchmark_path=str(Path(benchmark_path).resolve()),
        output_json_path=str(Path(output_json_path).resolve()),
        output_markdown_path=str(Path(output_markdown_path).resolve()),
        generated_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
        low_overlap_threshold=low_overlap_threshold,
    )

    intent_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    overlap_scores: list[float] = []
    draft_lengths: list[int] = []
    gold_lengths: list[int] = []
    low_overlap_cases: list[dict[str, Any]] = []

    for result in case_results:
        label = result.ticket_label or "(none)"
        label_counts[label] += 1
        if result.detected_intent:
            intent_counts[result.detected_intent] += 1
        if result.suggested_action:
            action_counts[result.suggested_action] += 1
        if result.missing_draft:
            summary.missing_draft_count += 1
        if result.unsafe_draft:
            summary.unsafe_draft_count += 1
        if result.gold_length > 0:
            gold_lengths.append(result.gold_length)
        if result.draft_length > 0 and not result.unsafe_draft:
            draft_lengths.append(result.draft_length)
        if result.lexical_overlap_score is not None:
            summary.evaluated_cases += 1
            overlap_scores.append(result.lexical_overlap_score)
        if result.low_overlap and result.lexical_overlap_score is not None:
            low_overlap_cases.append(
                {
                    "case_id": result.case_id,
                    "lexical_overlap_score": round(result.lexical_overlap_score, 4),
                    "draft_length": result.draft_length,
                    "gold_length": result.gold_length,
                    "detected_intent": result.detected_intent,
                    "suggested_action": result.suggested_action,
                },
            )

    if draft_lengths:
        summary.average_draft_length = sum(draft_lengths) / len(draft_lengths)
    if gold_lengths:
        summary.average_gold_length = sum(gold_lengths) / len(gold_lengths)
    if overlap_scores:
        summary.lexical_overlap_score_avg = sum(overlap_scores) / len(overlap_scores)

    summary.intent_counts = dict(intent_counts)
    summary.suggested_action_counts = dict(action_counts)
    summary.cases_by_ticket_label = dict(label_counts)
    summary.cases_with_low_overlap = sorted(
        low_overlap_cases,
        key=lambda item: (item["lexical_overlap_score"], item["case_id"]),
    )
    return summary


def render_draft_evaluation_markdown(summary: OfflineDraftEvaluationSummary) -> str:
    """Render a safe markdown report (aggregate metrics + case ids only; no reply bodies)."""
    lines = [
        "# Offline draft vs gold evaluation (v1)",
        "",
        "Deterministic first-pass evaluation for internal offline review only. "
        "**Not** production quality approval; drafts are **not** customer-facing.",
        "",
        "## Inputs",
        f"- Draft suggestions: `{summary.draft_suggestions_path}`",
        f"- Benchmark gold: `{summary.benchmark_path}`",
        "",
        f"Generated at (UTC): `{summary.generated_at_utc}`",
        "",
        "## Aggregate metrics",
        f"- total_cases: {summary.total_cases}",
        f"- evaluated_cases: {summary.evaluated_cases}",
        f"- missing_draft_count: {summary.missing_draft_count}",
        f"- unsafe_draft_count: {summary.unsafe_draft_count}",
        f"- average_draft_length: {summary.average_draft_length:.2f}",
        f"- average_gold_length: {summary.average_gold_length:.2f}",
        f"- lexical_overlap_score_avg: {summary.lexical_overlap_score_avg:.4f}",
        f"- low_overlap_threshold: {summary.low_overlap_threshold}",
        "",
        "## Intent counts",
    ]
    if summary.intent_counts:
        for intent, count in sorted(summary.intent_counts.items()):
            lines.append(f"- {intent}: {count}")
    else:
        lines.append("- (none)")

    lines.extend(["", "## Suggested action counts"])
    if summary.suggested_action_counts:
        for action, count in sorted(summary.suggested_action_counts.items()):
            lines.append(f"- {action}: {count}")
    else:
        lines.append("- (none)")

    lines.extend(["", "## Cases by ticket_label"])
    for label, count in sorted(summary.cases_by_ticket_label.items()):
        lines.append(f"- {label}: {count}")

    lines.extend(
        [
            "",
            "## Cases with low overlap (case_id + metrics only)",
            "",
            "| case_id | overlap | draft_len | gold_len | intent | action |",
            "| --- | ---: | ---: | ---: | --- | --- |",
        ],
    )
    if summary.cases_with_low_overlap:
        for row in summary.cases_with_low_overlap:
            lines.append(
                f"| {row['case_id']} | {row['lexical_overlap_score']:.4f} | "
                f"{row['draft_length']} | {row['gold_length']} | "
                f"{row.get('detected_intent') or '—'} | {row.get('suggested_action') or '—'} |",
            )
    else:
        lines.append("| (none) | — | — | — | — | — |")

    lines.append("")
    assert_markdown_excludes_raw_replies("\n".join(lines))
    return "\n".join(lines) + "\n"


def assert_markdown_excludes_raw_replies(markdown: str) -> None:
    """Fail closed if markdown may contain full draft/gold reply bodies."""
    forbidden_markers = (
        "gold_reference_reply",
        "draft_reply",
        "سلام — واحد مالی",
        "conversation transcript",
    )
    lowered = markdown.lower()
    for marker in forbidden_markers:
        if marker.lower() in lowered:
            raise ValueError(f"markdown must not contain raw reply marker: {marker}")


def case_result_to_public_dict(result: DraftGoldCaseResult) -> dict[str, Any]:
    """Serialize per-case metrics without draft or gold text."""
    return {
        "case_id": result.case_id,
        "room_id": result.room_id,
        "ticket_label": result.ticket_label,
        "route_label": result.route_label,
        "detected_intent": result.detected_intent,
        "suggested_action": result.suggested_action,
        "draft_generated": result.draft_generated,
        "missing_draft": result.missing_draft,
        "unsafe_draft": result.unsafe_draft,
        "draft_length": result.draft_length,
        "gold_length": result.gold_length,
        "lexical_overlap_score": (
            round(result.lexical_overlap_score, 4)
            if result.lexical_overlap_score is not None
            else None
        ),
        "low_overlap": result.low_overlap,
        "gold_hash_match": result.gold_hash_match,
    }


def run_offline_draft_evaluation(
    draft_suggestions_path: Path | str,
    benchmark_path: Path | str,
    *,
    output_json_path: Path | str,
    output_markdown_path: Path | str,
    low_overlap_threshold: float = LOW_OVERLAP_THRESHOLD,
) -> OfflineDraftEvaluationSummary:
    """Load inputs, evaluate all benchmark cases, write JSON + markdown under ``reports/``."""
    drafts = load_draft_suggestions(draft_suggestions_path)
    gold_index = load_benchmark_gold(benchmark_path)

    case_results: list[DraftGoldCaseResult] = []
    for case_id in sorted(gold_index.keys()):
        case_results.append(
            evaluate_draft_against_gold(
                case_id,
                drafts.get(case_id),
                gold_index[case_id],
                low_overlap_threshold=low_overlap_threshold,
            ),
        )

    summary = summarize_draft_evaluation(
        case_results,
        draft_suggestions_path=draft_suggestions_path,
        benchmark_path=benchmark_path,
        output_json_path=output_json_path,
        output_markdown_path=output_markdown_path,
        low_overlap_threshold=low_overlap_threshold,
    )

    payload = {
        "summary": summary.to_json_dict(),
        "per_case": [case_result_to_public_dict(result) for result in case_results],
    }

    json_path = Path(output_json_path)
    md_path = Path(output_markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_draft_evaluation_markdown(summary), encoding="utf-8")
    return summary

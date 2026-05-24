"""Knowledge hint coverage diagnostics for agentic sandbox batch runs (analytics only)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agentic_sandbox.agentic_readiness_analysis import BatchRunRecord, load_batch_run_records
from app.agentic_sandbox.policy_relevance import is_policy_relevant_signals
from app.agentic_sandbox.report_paths import (
    DEFAULT_BATCH_RUNS_JSONL,
    DEFAULT_COVERAGE_REPORT_PATH,
    DEFAULT_COVERAGE_SUMMARY_PATH,
)
from app.operator_console.draft_review_feedback import _FORBIDDEN_TEXT_SUBSTRINGS

GAP_MISSING_QUERY_TERMS = "missing_query_terms"
GAP_KNOWLEDGE_INDEX_GAP = "knowledge_index_gap"
GAP_RETRIEVAL_FILTER_TOO_STRICT = "retrieval_filter_too_strict"
GAP_QUERY_NORMALIZATION_GAP = "query_normalization_gap"
GAP_ACTION_INTENT_MISMATCH = "action_intent_mismatch"
GAP_UNKNOWN = "unknown"

GAP_REASONS = (
    GAP_MISSING_QUERY_TERMS,
    GAP_KNOWLEDGE_INDEX_GAP,
    GAP_RETRIEVAL_FILTER_TOO_STRICT,
    GAP_QUERY_NORMALIZATION_GAP,
    GAP_ACTION_INTENT_MISMATCH,
    GAP_UNKNOWN,
)

_POLICY_KEYWORDS = (
    "settlement",
    "تسویه",
    "واریز",
    "محصول",
    "کالا",
    "approval",
    "publishing",
    "publish",
    "قوانین",
    "ممنوع",
    "مرجوع",
    "return",
    "refund",
    "shipping",
    "delivery",
    "prohibited_goods",
    "product_publishing_rules",
    "settlement_rules",
    "refund_return_rules",
    "shipping_delivery_rules",
    "prohibited",
    "billing_review",
    "check_settlement_status",
    "answer_policy_question",
)

_POLICY_INTENTS = frozenset(
    {
        "settlement_status_inquiry",
        "settlement_panel_access_issue",
        "product_publishing_question",
        "prohibited_goods_question",
        "product_approval_review",
    },
)

_POLICY_ACTIONS = frozenset(
    {
        "check_settlement_status",
        "billing_review",
        "answer_policy_question",
        "check_product_approval",
        "check_return_request",
        "review_product_edit",
    },
)

_POLICY_ROUTES = frozenset({"billing_review"})
_POLICY_LABELS = frozenset({"fund"})

_GENERIC_CONCEPTUAL_PHRASES = (
    "پشتیبانی عمومی فروشنده",
    "اطلاع فروشنده",
    "پیگیری شکایت",
    "اطلاع کد رهگیری",
)

_SETTLEMENT_SIGNALS = (
    "settlement",
    "تسویه",
    "واریز",
    "billing_review",
    "check_settlement_status",
    "settlement_rules",
)

_PRODUCT_POLICY_SIGNALS = (
    "product_publishing",
    "prohibited_goods",
    "product_approval",
    "محصول",
    "کالا",
    "ممنوع",
    "approval",
    "publishing",
)

_RETURN_POLICY_SIGNALS = (
    "return",
    "refund",
    "مرجوع",
    "refund_return_rules",
)

_SHIPPING_POLICY_SIGNALS = (
    "shipping",
    "delivery",
    "shipping_delivery_rules",
)


@dataclass(frozen=True)
class ZeroHintRun:
    """One policy-relevant run with zero knowledge hints."""

    room_id: str
    ticket_label: str | None
    route_label: str | None
    detected_intent: str | None
    conceptual_intent_fa: str | None
    suggested_action: str | None
    knowledge_hint_count: int
    reason_hint: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "ticket_label": self.ticket_label,
            "route_label": self.route_label,
            "detected_intent": self.detected_intent,
            "conceptual_intent_fa": self.conceptual_intent_fa,
            "suggested_action": self.suggested_action,
            "knowledge_hint_count": self.knowledge_hint_count,
            "reason_hint": self.reason_hint,
        }


@dataclass
class SliceCoverageStats:
    """Hint coverage counts for one slice key (intent, action, or label)."""

    total: int = 0
    policy_relevant: int = 0
    with_hints: int = 0
    zero_hint_policy: int = 0

    def to_json_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "policy_relevant": self.policy_relevant,
            "with_hints": self.with_hints,
            "zero_hint_policy": self.zero_hint_policy,
        }


@dataclass
class KnowledgeHintCoverageSummary:
    """Aggregate knowledge hint coverage metrics."""

    generated_at_utc: str
    source_batch_runs_path: str
    total_runs: int
    policy_relevant_runs: int
    runs_with_hints: int
    runs_without_hints: int
    coverage_rate: float
    zero_hint_policy_runs: tuple[ZeroHintRun, ...]
    by_detected_intent: dict[str, dict[str, int]] = field(default_factory=dict)
    by_suggested_action: dict[str, dict[str, int]] = field(default_factory=dict)
    by_ticket_label: dict[str, dict[str, int]] = field(default_factory=dict)
    likely_gap_reasons: dict[str, int] = field(default_factory=dict)
    recommended_inspection_targets: tuple[ZeroHintRun, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_batch_runs_path": self.source_batch_runs_path,
            "total_runs": self.total_runs,
            "policy_relevant_runs": self.policy_relevant_runs,
            "runs_with_hints": self.runs_with_hints,
            "runs_without_hints": self.runs_without_hints,
            "coverage_rate": self.coverage_rate,
            "zero_hint_policy_runs": [item.to_json_dict() for item in self.zero_hint_policy_runs],
            "by_detected_intent": self.by_detected_intent,
            "by_suggested_action": self.by_suggested_action,
            "by_ticket_label": self.by_ticket_label,
            "likely_gap_reasons": dict(self.likely_gap_reasons),
            "recommended_inspection_targets": [
                item.to_json_dict() for item in self.recommended_inspection_targets
            ],
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _signal_blob_from_parts(
    *,
    detected_intent: str | None,
    conceptual_intent_fa: str | None,
    suggested_action: str | None,
    ticket_label: str | None,
    route_label: str | None,
) -> str:
    parts = (
        detected_intent,
        conceptual_intent_fa,
        suggested_action,
        ticket_label,
        route_label,
    )
    return " ".join(part.strip().lower() for part in parts if part and str(part).strip())


def _signal_blob(row: BatchRunRecord) -> str:
    return _signal_blob_from_parts(
        detected_intent=row.detected_intent,
        conceptual_intent_fa=row.conceptual_intent_fa,
        suggested_action=row.suggested_action,
        ticket_label=row.ticket_label,
        route_label=row.route_label,
    )


def is_policy_relevant_run(row: BatchRunRecord) -> bool:
    return is_policy_relevant_signals(
        detected_intent=row.detected_intent,
        conceptual_intent_fa=row.conceptual_intent_fa,
        suggested_action=row.suggested_action,
        ticket_label=row.ticket_label,
        route_label=row.route_label,
    )


def _action_implies_policy(action: str) -> bool:
    return action in _POLICY_ACTIONS or any(
        keyword in action
        for keyword in (
            "settlement",
            "billing",
            "policy",
            "approval",
            "return",
            "refund",
            "publish",
        )
    )


def _intent_implies_policy(intent: str) -> bool:
    return intent in _POLICY_INTENTS or any(
        keyword in intent
        for keyword in ("settlement", "publish", "prohibited", "approval", "return", "refund")
    )


def _conceptual_has_policy_terms(conceptual: str | None) -> bool:
    if not conceptual or not conceptual.strip():
        return False
    text = conceptual.strip()
    if any(phrase in text for phrase in _GENERIC_CONCEPTUAL_PHRASES):
        return False
    lowered = text.lower()
    return any(
        keyword in lowered
        for keyword in _POLICY_KEYWORDS
        if not keyword.isascii() or len(keyword) > 3
    )


def _has_normalization_variant(conceptual: str | None) -> bool:
    if not conceptual:
        return False
    return "تصفیه" in conceptual and "تسویه" not in conceptual


def _is_settlement_context(row: BatchRunRecord) -> bool:
    blob = _signal_blob(row)
    return any(signal in blob for signal in _SETTLEMENT_SIGNALS)


def _is_fund_or_billing(row: BatchRunRecord) -> bool:
    label = (row.ticket_label or "").strip().lower()
    route = (row.route_label or "").strip().lower()
    return label in _POLICY_LABELS or route in _POLICY_ROUTES


def _expected_document_types(row: BatchRunRecord) -> tuple[str, ...]:
    blob = _signal_blob(row)
    expected: list[str] = []
    if any(signal in blob for signal in _SETTLEMENT_SIGNALS):
        expected.append("settlement_rules")
    if any(signal in blob for signal in _PRODUCT_POLICY_SIGNALS):
        expected.extend(["product_publishing_rules", "prohibited_goods"])
    if any(signal in blob for signal in _RETURN_POLICY_SIGNALS):
        expected.append("refund_return_rules")
    if any(signal in blob for signal in _SHIPPING_POLICY_SIGNALS):
        expected.append("shipping_delivery_rules")
    if not expected:
        expected.append("vendor_general_policy")
    return tuple(dict.fromkeys(expected))


def infer_gap_reason(row: BatchRunRecord) -> str:
    """Infer likely reason for zero hints on a policy-relevant run (heuristic only)."""
    intent = (row.detected_intent or "").strip().lower()
    action = (row.suggested_action or "").strip().lower()

    if _action_implies_policy(action) and not _intent_implies_policy(intent):
        if not _is_settlement_context(row) and not _is_fund_or_billing(row):
            return GAP_ACTION_INTENT_MISMATCH

    if _has_normalization_variant(row.conceptual_intent_fa):
        return GAP_QUERY_NORMALIZATION_GAP

    if not _conceptual_has_policy_terms(row.conceptual_intent_fa):
        if not _is_fund_or_billing(row):
            return GAP_MISSING_QUERY_TERMS

    if _is_fund_or_billing(row) and _is_settlement_context(row):
        return GAP_RETRIEVAL_FILTER_TOO_STRICT

    expected = _expected_document_types(row)
    if expected:
        return GAP_KNOWLEDGE_INDEX_GAP

    return GAP_UNKNOWN


def build_zero_hint_run(row: BatchRunRecord) -> ZeroHintRun:
    return ZeroHintRun(
        room_id=row.room_id,
        ticket_label=row.ticket_label,
        route_label=row.route_label,
        detected_intent=row.detected_intent,
        conceptual_intent_fa=row.conceptual_intent_fa,
        suggested_action=row.suggested_action,
        knowledge_hint_count=row.knowledge_hint_count,
        reason_hint=infer_gap_reason(row),
    )


def _update_slice(stats: SliceCoverageStats, *, policy: bool, hints: int) -> None:
    stats.total += 1
    if policy:
        stats.policy_relevant += 1
        if hints <= 0:
            stats.zero_hint_policy += 1
    if hints > 0:
        stats.with_hints += 1


def summarize_knowledge_hint_coverage(
    records: list[BatchRunRecord],
    *,
    source_batch_runs_path: str = "",
    generated_at_utc: str | None = None,
) -> KnowledgeHintCoverageSummary:
    """Compute knowledge hint coverage summary from batch run records."""
    total = len(records)
    policy_relevant = 0
    with_hints = 0
    without_hints = 0
    policy_with_hints = 0

    intent_slices: dict[str, SliceCoverageStats] = defaultdict(SliceCoverageStats)
    action_slices: dict[str, SliceCoverageStats] = defaultdict(SliceCoverageStats)
    label_slices: dict[str, SliceCoverageStats] = defaultdict(SliceCoverageStats)
    gap_reasons: Counter[str] = Counter()
    zero_hint_runs: list[ZeroHintRun] = []

    for row in records:
        hints = row.knowledge_hint_count
        policy = is_policy_relevant_run(row)

        if hints > 0:
            with_hints += 1
        else:
            without_hints += 1

        if policy:
            policy_relevant += 1
            if hints > 0:
                policy_with_hints += 1
            else:
                zero = build_zero_hint_run(row)
                zero_hint_runs.append(zero)
                gap_reasons[zero.reason_hint] += 1

        intent_key = row.detected_intent or "(none)"
        action_key = row.suggested_action or "(none)"
        label_key = row.ticket_label or "(none)"

        _update_slice(intent_slices[intent_key], policy=policy, hints=hints)
        _update_slice(action_slices[action_key], policy=policy, hints=hints)
        _update_slice(label_slices[label_key], policy=policy, hints=hints)

    inspection_targets = sorted(
        zero_hint_runs,
        key=lambda item: (
            0 if item.reason_hint == GAP_KNOWLEDGE_INDEX_GAP else 1,
            0 if item.reason_hint == GAP_RETRIEVAL_FILTER_TOO_STRICT else 1,
            item.room_id,
        ),
    )[:20]

    return KnowledgeHintCoverageSummary(
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_batch_runs_path=source_batch_runs_path,
        total_runs=total,
        policy_relevant_runs=policy_relevant,
        runs_with_hints=with_hints,
        runs_without_hints=without_hints,
        coverage_rate=_rate(policy_with_hints, policy_relevant),
        zero_hint_policy_runs=tuple(zero_hint_runs),
        by_detected_intent={
            key: stats.to_json_dict() for key, stats in sorted(intent_slices.items())
        },
        by_suggested_action={
            key: stats.to_json_dict() for key, stats in sorted(action_slices.items())
        },
        by_ticket_label={key: stats.to_json_dict() for key, stats in sorted(label_slices.items())},
        likely_gap_reasons={reason: gap_reasons.get(reason, 0) for reason in GAP_REASONS},
        recommended_inspection_targets=tuple(inspection_targets),
    )


def render_knowledge_hint_coverage_markdown(summary: KnowledgeHintCoverageSummary) -> str:
    """Render coverage markdown report (metrics only)."""
    lines = [
        "# Agentic Knowledge Hint Coverage Report",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Source:** `{summary.source_batch_runs_path}`  ",
        "**Scope:** Knowledge hint coverage diagnostics — no retrieval behavior changes.",
        "",
        "## Overall coverage",
        "",
        f"- **total_runs:** {summary.total_runs}",
        f"- **runs_with_hints:** {summary.runs_with_hints}",
        f"- **runs_without_hints:** {summary.runs_without_hints}",
        "",
        "## Policy-relevant runs",
        "",
        f"- **policy_relevant_runs:** {summary.policy_relevant_runs}",
        f"- **coverage_rate (policy runs with hints):** {summary.coverage_rate:.1%}",
        "",
        "## Zero-hint policy runs",
        "",
    ]
    if summary.zero_hint_policy_runs:
        lines.extend(
            [
                "| room_id | intent | action | label | route | reason_hint |",
                "|---------|--------|--------|-------|-------|-------------|",
            ],
        )
        for item in summary.zero_hint_policy_runs:
            lines.append(
                f"| `{item.room_id}` | `{item.detected_intent or '—'}` | "
                f"`{item.suggested_action or '—'}` | `{item.ticket_label or '—'}` | "
                f"`{item.route_label or '—'}` | {item.reason_hint} |",
            )
    else:
        lines.append("*(No zero-hint policy runs.)*")

    lines.extend(["", "## Breakdown by detected_intent", ""])
    lines.extend(_render_slice_table(summary.by_detected_intent))

    lines.extend(["", "## Breakdown by suggested_action", ""])
    lines.extend(_render_slice_table(summary.by_suggested_action))

    lines.extend(["", "## Breakdown by ticket_label", ""])
    lines.extend(_render_slice_table(summary.by_ticket_label))

    lines.extend(
        [
            "",
            "## Likely gap reasons",
            "",
            "| Reason | Count |",
            "|--------|------:|",
        ],
    )
    for reason in GAP_REASONS:
        count = summary.likely_gap_reasons.get(reason, 0)
        if count:
            lines.append(f"| `{reason}` | {count} |")
    if not any(summary.likely_gap_reasons.values()):
        lines.append("| *(none)* | 0 |")

    lines.extend(["", "## Recommended inspection targets", ""])
    if summary.recommended_inspection_targets:
        lines.extend(
            [
                "| room_id | intent | action | reason_hint |",
                "|---------|--------|--------|-------------|",
            ],
        )
        for item in summary.recommended_inspection_targets[:15]:
            lines.append(
                f"| `{item.room_id}` | `{item.detected_intent or '—'}` | "
                f"`{item.suggested_action or '—'}` | {item.reason_hint} |",
            )
    else:
        lines.append("*(No inspection targets — policy runs have hints.)*")

    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Diagnostics only — does not change retrieval ranking, embeddings, or index.",
            "- Run after `run_agentic_sandbox_batch_report.py` to explain zero-hint policy runs.",
            "- Safe output only: no ticket text, prompts, or retrieval snippets.",
            "",
        ],
    )
    return "\n".join(lines)


def _render_slice_table(slices: dict[str, dict[str, int]]) -> list[str]:
    if not slices:
        return ["*(none)*"]
    lines = [
        "| Slice | Total | Policy | With hints | Zero-hint policy |",
        "|-------|------:|-------:|-----------:|-----------------:|",
    ]
    for key, stats in sorted(slices.items()):
        lines.append(
            f"| `{key}` | {stats['total']} | {stats['policy_relevant']} | "
            f"{stats['with_hints']} | {stats['zero_hint_policy']} |",
        )
    return lines


def assert_coverage_output_safe(content: str) -> None:
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"coverage output must not contain forbidden token: {token}")
    for token in (
        "conversation transcript",
        "gold_reference_reply",
        '"messages"',
        "original_vendor",
    ):
        if token in lowered:
            raise ValueError(f"coverage output must not contain forbidden token: {token}")
    if re.search(r"sk-[a-z0-9]{8,}", content, flags=re.IGNORECASE):
        raise ValueError("coverage output must not contain API key patterns")


def build_knowledge_hint_coverage_report(
    batch_runs_path: Path | str = DEFAULT_BATCH_RUNS_JSONL,
    *,
    summary_output: Path = DEFAULT_COVERAGE_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_COVERAGE_REPORT_PATH,
    generated_at_utc: str | None = None,
) -> KnowledgeHintCoverageSummary:
    """Load batch JSONL and write knowledge hint coverage JSON + markdown reports."""
    source = Path(batch_runs_path)
    records = load_batch_run_records(source)
    summary = summarize_knowledge_hint_coverage(
        records,
        source_batch_runs_path=str(source),
        generated_at_utc=generated_at_utc,
    )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_knowledge_hint_coverage_markdown(summary)

    assert_coverage_output_safe(json_text)
    assert_coverage_output_safe(markdown)

    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary

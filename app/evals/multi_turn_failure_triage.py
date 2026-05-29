"""Multi-turn eval failure triage — classify, cluster, and prioritize without prompt changes."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.evals.multi_turn_eval_runner import (
    DEFAULT_RESULTS_JSONL,
    assert_report_safe,
    load_eval_scenarios,
    normalize_eval_text,
    text_contains_marker,
)
from app.operator_console.manual_chat_models import ManualChatMessage

DEFAULT_TRIAGE_SUMMARY_JSON = Path("reports/multi_turn_failure_triage_summary.json")
DEFAULT_TRIAGE_REPORT_MD = Path("reports/multi_turn_failure_triage_report.md")
DEFAULT_TRIAGE_CLUSTERS_JSON = Path("reports/multi_turn_failure_clusters.json")

_FORBIDDEN_REPORT_SUBSTRINGS = (
    "raw_prompt",
    "chain_of_thought",
    "hidden_reasoning",
    "reviewer_thoughts",
    "knowledge_hints_for_prompt",
)

_SEVERITY_WEIGHT = {
    "critical": 100,
    "high": 70,
    "medium": 40,
    "low": 15,
    "cosmetic": 5,
}

_OPERATIONAL_IMPACT = {
    "critical": 10,
    "high": 8,
    "medium": 5,
    "low": 2,
    "cosmetic": 1,
}


class EvalFailureCategory(StrEnum):
    """Normalized failure taxonomy for triage."""

    REPEATED_IDENTIFIER_REQUEST = "repeated_identifier_request"
    OVER_QUESTIONING = "over_questioning"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    POLICY_GROUNDING_FAILURE = "policy_grounding_failure"
    WEAK_ACKNOWLEDGMENT = "weak_acknowledgment"
    INCORRECT_INTENT = "incorrect_intent"
    INCORRECT_ACTION = "incorrect_action"
    MISSING_REQUIRED_IDENTIFIER_REQUEST = "missing_required_identifier_request"
    PHOTO_REQUEST_LEAKAGE = "photo_request_leakage"
    PANEL_ISSUE_HANDLING_FAILURE = "panel_issue_handling_failure"
    MULTI_TURN_CONTEXT_FAILURE = "multi_turn_context_failure"
    REFLECTION_MISSED_ISSUE = "reflection_missed_issue"
    REFLECTION_OVERWRITE_FAILURE = "reflection_overwrite_failure"
    PROVIDER_VARIANCE = "provider_variance"
    ACCEPTABLE_VARIANCE = "acceptable_variance"
    LOW_QUALITY_WORDING = "low_quality_wording"
    VERBOSITY = "verbosity"
    ROUTING_FAILURE = "routing_failure"
    EXTRACTION_FAILURE = "extraction_failure"
    KNOWLEDGE_RETRIEVAL_FAILURE = "knowledge_retrieval_failure"
    GRAPH_ERROR = "graph_error"
    GENERIC_ASSERTION_FAILURE = "generic_assertion_failure"


class EvalFailureSeverity(StrEnum):
    """Operational severity for prioritization."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    COSMETIC = "cosmetic"


class SuggestedFixArea(StrEnum):
    """Likely subsystem to investigate (not a prompt dump)."""

    OPERATIONAL_SUFFICIENCY = "operational_sufficiency"
    REFLECTION = "reflection"
    EXTRACTION = "extraction"
    ROUTING = "routing"
    RETRIEVAL = "retrieval"
    POLICY_GROUNDING = "policy_grounding"
    PROMPT_CALIBRATION = "prompt_calibration"
    MULTI_TURN_CONTEXT = "multi_turn_context"
    ACTIONABILITY = "actionability"
    MOCK_TEMPLATE_QUALITY = "mock_template_quality"
    PROVIDER_VARIANCE = "provider_variance"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvalFailureTriageItem:
    """One classified failure (typically one failed assertion)."""

    scenario_id: str
    scenario_category: str
    failure_type: EvalFailureCategory
    severity: EvalFailureSeverity
    provider: str
    ticket_label: str | None
    expected_assertion: str
    actual_output_summary: str
    conversation_summary: str
    draft_reply: str | None
    reflection_applied: bool
    reflection_saved: bool
    reflection_issue_types: tuple[str, ...]
    root_cause_hypothesis: str
    suggested_fix_area: SuggestedFixArea
    regression_risk: str
    priority_score: float
    acceptable_variance: bool = False
    detected_intent: str | None = None
    suggested_action: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_category": self.scenario_category,
            "failure_type": self.failure_type.value,
            "severity": self.severity.value,
            "provider": self.provider,
            "ticket_label": self.ticket_label,
            "expected_assertion": self.expected_assertion,
            "actual_output_summary": self.actual_output_summary,
            "conversation_summary": self.conversation_summary,
            "draft_reply": self.draft_reply,
            "reflection_applied": self.reflection_applied,
            "reflection_saved": self.reflection_saved,
            "reflection_issue_types": list(self.reflection_issue_types),
            "root_cause_hypothesis": self.root_cause_hypothesis,
            "suggested_fix_area": self.suggested_fix_area.value,
            "regression_risk": self.regression_risk,
            "priority_score": self.priority_score,
            "acceptable_variance": self.acceptable_variance,
            "detected_intent": self.detected_intent,
            "suggested_action": self.suggested_action,
        }


@dataclass(frozen=True)
class EvalFailureCluster:
    """Grouped failures sharing the same underlying pattern."""

    cluster_id: str
    failure_type: EvalFailureCategory
    severity: EvalFailureSeverity
    pattern_summary: str
    suggested_fix_area: SuggestedFixArea
    scenario_ids: tuple[str, ...]
    occurrence_count: int
    priority_score: float
    example_scenario_id: str
    example_assertion: str
    regression_risk: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "failure_type": self.failure_type.value,
            "severity": self.severity.value,
            "pattern_summary": self.pattern_summary,
            "suggested_fix_area": self.suggested_fix_area.value,
            "scenario_ids": list(self.scenario_ids),
            "occurrence_count": self.occurrence_count,
            "priority_score": self.priority_score,
            "example_scenario_id": self.example_scenario_id,
            "example_assertion": self.example_assertion,
            "regression_risk": self.regression_risk,
        }


@dataclass
class ReflectionEffectivenessMetrics:
    """Reflection save/miss rates across the eval run."""

    scenarios_with_reflection: int = 0
    reflection_rewrite_count: int = 0
    failures_prevented_by_reflection: int = 0
    failures_missed_by_reflection: int = 0
    rewrites_improved_result: int = 0
    rewrites_still_failed: int = 0
    reflection_save_rate: float = 0.0
    reflection_miss_rate: float = 0.0
    reflection_false_rewrite_rate: float = 0.0
    rewrite_by_category: dict[str, int] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "scenarios_with_reflection": self.scenarios_with_reflection,
            "reflection_rewrite_count": self.reflection_rewrite_count,
            "failures_prevented_by_reflection": self.failures_prevented_by_reflection,
            "failures_missed_by_reflection": self.failures_missed_by_reflection,
            "rewrites_improved_result": self.rewrites_improved_result,
            "rewrites_still_failed": self.rewrites_still_failed,
            "reflection_save_rate": self.reflection_save_rate,
            "reflection_miss_rate": self.reflection_miss_rate,
            "reflection_false_rewrite_rate": self.reflection_false_rewrite_rate,
            "rewrite_by_category": dict(self.rewrite_by_category),
        }


@dataclass(frozen=True)
class EvalFailureTriageSummary:
    """Aggregate triage output."""

    generated_at_utc: str
    source_results_path: str
    provider: str
    total_scenarios: int
    failed_scenarios: int
    triaged_failure_count: int
    acceptable_variance_count: int
    real_failure_count: int
    by_failure_type: dict[str, int]
    by_severity: dict[str, int]
    by_fix_area: dict[str, int]
    reflection_metrics: ReflectionEffectivenessMetrics
    clusters: tuple[EvalFailureCluster, ...]
    items: tuple[EvalFailureTriageItem, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_results_path": self.source_results_path,
            "provider": self.provider,
            "total_scenarios": self.total_scenarios,
            "failed_scenarios": self.failed_scenarios,
            "triaged_failure_count": self.triaged_failure_count,
            "acceptable_variance_count": self.acceptable_variance_count,
            "real_failure_count": self.real_failure_count,
            "by_failure_type": self.by_failure_type,
            "by_severity": self.by_severity,
            "by_fix_area": self.by_fix_area,
            "reflection_metrics": self.reflection_metrics.to_json_dict(),
            "top_clusters": [cluster.to_json_dict() for cluster in self.clusters[:15]],
            "top_priority_items": [
                item.to_json_dict()
                for item in sorted(self.items, key=lambda x: -x.priority_score)[:20]
                if not item.acceptable_variance
            ],
        }


_ACK_EQUIVALENCE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("دریافت شد", "ثبت شد", "دریافت گردید", "دریافت کردیم"),
    ("در دست بررسی", "بررسی می‌شود", "بررسی قرار گرفت", "ارجاع شد"),
    ("ثبت شد", "ثبت گردید", "ثبت شده"),
)

_REPEATED_ASK_MARKERS = (
    "کد رهگیری را ارسال",
    "شماره سفارش را ارسال",
    "شناسه سفارش را ارسال",
    "شناسه کالا را ارسال",
    "شماره شبا را ارسال",
    "شماره شبای صحیح",
    "لطفاً کد رهگیری",
)

_PHOTO_MARKERS = ("عکس", "اسکرین‌شات", "اسکرین شات", "فایل تصویر", "screenshot")

_PANEL_ID_MARKERS = ("شناسه پنل", "کد پنل", "شناسه فروشگاه", "shop_id")

_POLICY_MARKERS = ("کیف پول", "۳ روز", "بانک سامان", "نهایی شدن", "اولین بازه")

_UNSUPPORTED_CLAIM_MARKERS = (
    "پنل شما فعال می‌شود",
    "پنل فعال میشود",
    "واریز شد",
    "انجام شد",
    "ثبت قطعی",
)


def load_eval_results_jsonl(path: Path = DEFAULT_RESULTS_JSONL) -> list[dict[str, Any]]:
    """Load per-scenario eval rows from JSONL."""
    if not path.is_file():
        raise FileNotFoundError(f"eval results not found: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def _summarize_draft(draft: str | None, *, max_chars: int = 160) -> str:
    text = (draft or "").strip()
    if not text:
        return "—"
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _conversation_summary_from_messages(messages: Sequence[ManualChatMessage]) -> str:
    parts: list[str] = []
    for message in messages[-4:]:
        role = message.sender_type
        snippet = message.text.strip()
        if len(snippet) > 80:
            snippet = snippet[:79] + "…"
        parts.append(f"{role}: {snippet}")
    return " | ".join(parts) if parts else "—"


def _conversation_summary_from_row(
    row: Mapping[str, Any],
    scenarios_by_id: Mapping[str, Any],
) -> str:
    scenario_id = str(row.get("scenario_id") or "")
    scenario = scenarios_by_id.get(scenario_id)
    if scenario is not None and hasattr(scenario, "messages"):
        return _conversation_summary_from_messages(scenario.messages)
    return "—"


def _marker_from_assertion_name(name: str) -> str:
    for prefix in ("must_contain:", "must_not_contain:", "regex_match:"):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def _draft_has_ack_equivalent(draft: str, expected_marker: str) -> bool:
    """True when draft conveys equivalent operational acknowledgment."""
    for group in _ACK_EQUIVALENCE_GROUPS:
        normalized_group = {normalize_eval_text(item) for item in group}
        expected_norm = normalize_eval_text(expected_marker)
        if expected_norm not in normalized_group:
            continue
        for phrase in group:
            if text_contains_marker(draft, phrase):
                return True
    return False


def _is_acceptable_variance(
    row: Mapping[str, Any],
    *,
    assertion_name: str,
    assertion_message: str,
    draft: str,
) -> bool:
    """Downgrade linguistic-only mismatches when operational meaning is preserved."""
    failed = row.get("failed_assertions") or []
    if not isinstance(failed, list):
        return False

    has_must_not_failure = any(
        str(item.get("name", "")).startswith("must_not_contain")
        for item in failed
        if isinstance(item, dict)
    )
    if has_must_not_failure:
        return False

    has_intent_action_failure = any(
        str(item.get("name", "")) in {"expected_intent", "expected_action"}
        for item in failed
        if isinstance(item, dict)
    )
    if has_intent_action_failure:
        return False

    if assertion_name.startswith("must_contain:"):
        marker = _marker_from_assertion_name(assertion_name)
        if _draft_has_ack_equivalent(draft, marker):
            return True
        soft_markers = ("دریافت", "ثبت", "بررسی", "ارجاع", "ناظر")
        if any(text_contains_marker(draft, soft) for soft in soft_markers):
            if marker in ("دریافت شد", "ثبت شد") or "دریافت" in marker:
                return True

    if assertion_name == "reflection_rewrite_expected":
        if "missing marker" not in assertion_message:
            return False

    return False


def _severity_for_category(
    category: EvalFailureCategory,
    *,
    regression_risk: str,
) -> EvalFailureSeverity:
    if category == EvalFailureCategory.ACCEPTABLE_VARIANCE:
        return EvalFailureSeverity.COSMETIC
    if category in {
        EvalFailureCategory.UNSUPPORTED_CLAIM,
        EvalFailureCategory.REPEATED_IDENTIFIER_REQUEST,
    }:
        return EvalFailureSeverity.CRITICAL
    if category in {
        EvalFailureCategory.POLICY_GROUNDING_FAILURE,
        EvalFailureCategory.MISSING_REQUIRED_IDENTIFIER_REQUEST,
        EvalFailureCategory.PANEL_ISSUE_HANDLING_FAILURE,
        EvalFailureCategory.REFLECTION_MISSED_ISSUE,
    }:
        return EvalFailureSeverity.HIGH
    if category in {
        EvalFailureCategory.INCORRECT_INTENT,
        EvalFailureCategory.INCORRECT_ACTION,
        EvalFailureCategory.MULTI_TURN_CONTEXT_FAILURE,
        EvalFailureCategory.WEAK_ACKNOWLEDGMENT,
        EvalFailureCategory.ROUTING_FAILURE,
    }:
        return EvalFailureSeverity.MEDIUM
    if category in {
        EvalFailureCategory.LOW_QUALITY_WORDING,
        EvalFailureCategory.VERBOSITY,
        EvalFailureCategory.PROVIDER_VARIANCE,
    }:
        return EvalFailureSeverity.LOW
    if category == EvalFailureCategory.GRAPH_ERROR:
        return EvalFailureSeverity.CRITICAL
    return EvalFailureSeverity.MEDIUM


def _regression_risk_for_category(category: EvalFailureCategory) -> str:
    if category in {
        EvalFailureCategory.UNSUPPORTED_CLAIM,
        EvalFailureCategory.REPEATED_IDENTIFIER_REQUEST,
        EvalFailureCategory.POLICY_GROUNDING_FAILURE,
    }:
        return "high"
    if category == EvalFailureCategory.ACCEPTABLE_VARIANCE:
        return "low"
    if category in {EvalFailureCategory.PROVIDER_VARIANCE, EvalFailureCategory.LOW_QUALITY_WORDING}:
        return "low"
    return "medium"


def _classify_assertion_failure(
    row: Mapping[str, Any],
    *,
    assertion_name: str,
    assertion_message: str,
    scenario_category: str,
    draft: str,
    provider: str,
) -> tuple[EvalFailureCategory, str, SuggestedFixArea]:
    """Return failure type, hypothesis, and suggested fix area."""
    reflection_issues = tuple(str(x) for x in row.get("reflection_issue_types") or ())
    rewrite_applied = bool(row.get("reflection_rewrite_applied"))
    policy_q = str(row.get("policy_question_type") or "none")

    if assertion_name == "expected_intent":
        return (
            EvalFailureCategory.INCORRECT_INTENT,
            f"Intent mismatch: {assertion_message}",
            SuggestedFixArea.ROUTING,
        )

    if assertion_name == "expected_action":
        return (
            EvalFailureCategory.INCORRECT_ACTION,
            f"Action mismatch: {assertion_message}",
            SuggestedFixArea.ACTIONABILITY,
        )

    if assertion_name == "reflection_rewrite_expected":
        return (
            EvalFailureCategory.REFLECTION_MISSED_ISSUE,
            "Reflection expected to rewrite draft but rewrite_applied=false",
            SuggestedFixArea.REFLECTION,
        )

    if assertion_name.startswith("must_not_contain:"):
        marker = _marker_from_assertion_name(assertion_name)
        if any(text_contains_marker(marker, ask) for ask in _REPEATED_ASK_MARKERS) or any(
            text_contains_marker(draft, ask) for ask in _REPEATED_ASK_MARKERS
        ):
            return (
                EvalFailureCategory.REPEATED_IDENTIFIER_REQUEST,
                f"Draft still asks for identifier after fulfillment: {marker}",
                SuggestedFixArea.MULTI_TURN_CONTEXT,
            )
        if any(text_contains_marker(draft, panel) for panel in _PANEL_ID_MARKERS):
            return (
                EvalFailureCategory.PANEL_ISSUE_HANDLING_FAILURE,
                "Draft requests panel/shop ID on panel scenario",
                SuggestedFixArea.OPERATIONAL_SUFFICIENCY,
            )
        if any(text_contains_marker(draft, photo) for photo in _PHOTO_MARKERS):
            if scenario_category != "photo_request_gating":
                return (
                    EvalFailureCategory.PHOTO_REQUEST_LEAKAGE,
                    "Unnecessary photo/screenshot request in draft",
                    SuggestedFixArea.OPERATIONAL_SUFFICIENCY,
                )
        if "بستگی دارد" in marker or "قوانین" in marker:
            return (
                EvalFailureCategory.POLICY_GROUNDING_FAILURE,
                "Vague policy referral instead of grounded answer",
                SuggestedFixArea.POLICY_GROUNDING,
            )
        return (
            EvalFailureCategory.OVER_QUESTIONING,
            f"Forbidden phrase present: {marker}",
            SuggestedFixArea.PROMPT_CALIBRATION,
        )

    if assertion_name.startswith("must_contain:"):
        marker = _marker_from_assertion_name(assertion_name)
        if scenario_category == "settlement_policy" or policy_q.startswith("settlement"):
            if not any(text_contains_marker(draft, pol) for pol in _POLICY_MARKERS):
                return (
                    EvalFailureCategory.POLICY_GROUNDING_FAILURE,
                    f"Settlement policy fact missing from draft: {marker}",
                    SuggestedFixArea.POLICY_GROUNDING,
                )
        fulfillment_categories = {
            "tracking_fulfillment",
            "order_id_fulfillment",
            "repeated_ask_prevention",
        }
        if scenario_category in fulfillment_categories:
            if "repeated_identifier_request" in reflection_issues and not rewrite_applied:
                return (
                    EvalFailureCategory.REFLECTION_MISSED_ISSUE,
                    "Reflection detected repeated ask but did not rewrite",
                    SuggestedFixArea.REFLECTION,
                )
            if provider == "mock":
                return (
                    EvalFailureCategory.PROVIDER_VARIANCE,
                    f"Mock draft missing expected acknowledgment: {marker}",
                    SuggestedFixArea.MOCK_TEMPLATE_QUALITY,
                )
            return (
                EvalFailureCategory.WEAK_ACKNOWLEDGMENT,
                f"Draft missing expected acknowledgment marker: {marker}",
                SuggestedFixArea.OPERATIONAL_SUFFICIENCY,
            )
        if scenario_category == "missing_identifier":
            return (
                EvalFailureCategory.MISSING_REQUIRED_IDENTIFIER_REQUEST,
                f"Draft did not request required identifier: {marker}",
                SuggestedFixArea.ACTIONABILITY,
            )
        if provider == "mock":
            return (
                EvalFailureCategory.PROVIDER_VARIANCE,
                f"Provider/mock wording variance for: {marker}",
                SuggestedFixArea.MOCK_TEMPLATE_QUALITY,
            )
        return (
            EvalFailureCategory.WEAK_ACKNOWLEDGMENT,
            f"Expected phrase missing: {marker}",
            SuggestedFixArea.PROMPT_CALIBRATION,
        )

    if assertion_name == "should_generate_draft":
        return (
            EvalFailureCategory.MULTI_TURN_CONTEXT_FAILURE,
            f"Draft generation gating mismatch: {assertion_message}",
            SuggestedFixArea.MULTI_TURN_CONTEXT,
        )

    if assertion_name == "golden_regression" or assertion_name.startswith("golden"):
        return (
            EvalFailureCategory.PROVIDER_VARIANCE,
            "Draft fingerprint drift vs golden baseline",
            SuggestedFixArea.PROVIDER_VARIANCE,
        )

    return (
        EvalFailureCategory.GENERIC_ASSERTION_FAILURE,
        assertion_message or assertion_name,
        SuggestedFixArea.UNKNOWN,
    )


def _compute_priority_score(
    severity: EvalFailureSeverity,
    *,
    cluster_frequency: int = 1,
    reflection_missed: bool = False,
    regression_risk: str,
) -> float:
    base = float(_SEVERITY_WEIGHT.get(severity.value, 40))
    impact = float(_OPERATIONAL_IMPACT.get(severity.value, 5))
    freq_bonus = min(cluster_frequency * 3.0, 30.0)
    reflection_bonus = 12.0 if reflection_missed else 0.0
    risk_bonus = {"high": 15.0, "medium": 8.0, "low": 0.0}.get(regression_risk, 8.0)
    return base + impact + freq_bonus + reflection_bonus + risk_bonus


def triage_eval_row(
    row: Mapping[str, Any],
    *,
    scenarios_by_id: Mapping[str, Any],
    provider: str | None = None,
) -> list[EvalFailureTriageItem]:
    """Classify all failed assertions for one eval result row."""
    if row.get("passed") is True:
        return []

    scenario_id = str(row.get("scenario_id") or "")
    scenario_category = str(row.get("category") or "uncategorized")
    draft = str(row.get("draft_reply") or "")
    provider_name = provider or str(row.get("provider") or "unknown")
    scenario = scenarios_by_id.get(scenario_id)
    ticket_label_str = None
    if scenario is not None and getattr(scenario, "ticket_label", None):
        ticket_label_str = str(scenario.ticket_label).strip() or None
    if not ticket_label_str and row.get("ticket_label"):
        ticket_label_str = str(row.get("ticket_label")).strip() or None

    if row.get("error"):
        severity = EvalFailureSeverity.CRITICAL
        category = EvalFailureCategory.GRAPH_ERROR
        item = EvalFailureTriageItem(
            scenario_id=scenario_id,
            scenario_category=scenario_category,
            failure_type=category,
            severity=severity,
            provider=provider_name,
            ticket_label=ticket_label_str,
            expected_assertion="graph_run",
            actual_output_summary=str(row.get("error"))[:160],
            conversation_summary=_conversation_summary_from_row(row, scenarios_by_id),
            draft_reply=None,
            reflection_applied=False,
            reflection_saved=False,
            reflection_issue_types=(),
            root_cause_hypothesis="Graph run raised an exception",
            suggested_fix_area=SuggestedFixArea.UNKNOWN,
            regression_risk="high",
            priority_score=_compute_priority_score(
                severity,
                regression_risk="high",
            ),
            detected_intent=row.get("detected_intent"),
            suggested_action=row.get("suggested_action"),
        )
        return [item]

    failed_assertions = row.get("failed_assertions") or []
    if not isinstance(failed_assertions, list) or not failed_assertions:
        return []

    conversation = _conversation_summary_from_row(row, scenarios_by_id)
    reflection_applied = bool(row.get("reflection_rewrite_applied"))
    reflection_issues = tuple(str(x) for x in row.get("reflection_issue_types") or ())
    reflection_saved = reflection_applied and bool(reflection_issues)

    items: list[EvalFailureTriageItem] = []
    for raw_assertion in failed_assertions:
        if not isinstance(raw_assertion, dict):
            continue
        assertion_name = str(raw_assertion.get("name") or "")
        assertion_message = str(raw_assertion.get("message") or "")

        category, hypothesis, fix_area = _classify_assertion_failure(
            row,
            assertion_name=assertion_name,
            assertion_message=assertion_message,
            scenario_category=scenario_category,
            draft=draft,
            provider=provider_name,
        )

        acceptable = _is_acceptable_variance(
            row,
            assertion_name=assertion_name,
            assertion_message=assertion_message,
            draft=draft,
        )
        if acceptable:
            category = EvalFailureCategory.ACCEPTABLE_VARIANCE
            hypothesis = (
                "Operational meaning likely preserved; wording differs from eval phrase only"
            )
            fix_area = SuggestedFixArea.PROVIDER_VARIANCE

        regression_risk = _regression_risk_for_category(category)
        severity = _severity_for_category(category, regression_risk=regression_risk)
        reflection_missed = category == EvalFailureCategory.REFLECTION_MISSED_ISSUE

        items.append(
            EvalFailureTriageItem(
                scenario_id=scenario_id,
                scenario_category=scenario_category,
                failure_type=category,
                severity=severity,
                provider=provider_name,
                ticket_label=ticket_label_str,
                expected_assertion=assertion_name,
                actual_output_summary=_summarize_draft(draft),
                conversation_summary=conversation,
                draft_reply=draft or None,
                reflection_applied=reflection_applied,
                reflection_saved=reflection_saved,
                reflection_issue_types=reflection_issues,
                root_cause_hypothesis=hypothesis,
                suggested_fix_area=fix_area,
                regression_risk=regression_risk,
                priority_score=_compute_priority_score(
                    severity,
                    reflection_missed=reflection_missed,
                    regression_risk=regression_risk,
                ),
                acceptable_variance=acceptable,
                detected_intent=row.get("detected_intent"),
                suggested_action=row.get("suggested_action"),
            ),
        )
    return items


def cluster_triage_items(
    items: Sequence[EvalFailureTriageItem],
) -> tuple[EvalFailureCluster, ...]:
    """Group triage items by failure type + assertion pattern."""
    buckets: dict[str, list[EvalFailureTriageItem]] = defaultdict(list)
    for item in items:
        if item.acceptable_variance:
            continue
        marker = _marker_from_assertion_name(item.expected_assertion)
        bucket_key = (
            f"{item.failure_type.value}|{item.expected_assertion}|"
            f"{normalize_eval_text(marker)[:40]}"
        )
        buckets[bucket_key].append(item)

    clusters: list[EvalFailureCluster] = []
    for index, (_key, group) in enumerate(
        sorted(buckets.items(), key=lambda pair: -len(pair[1])),
    ):
        first = group[0]
        scenario_ids = tuple(dict.fromkeys(item.scenario_id for item in group))
        count = len(group)
        severity = first.severity
        if any(item.severity == EvalFailureSeverity.CRITICAL for item in group):
            severity = EvalFailureSeverity.CRITICAL
        elif any(item.severity == EvalFailureSeverity.HIGH for item in group):
            severity = EvalFailureSeverity.HIGH

        pattern = first.root_cause_hypothesis
        if count > 1:
            pattern = f"{pattern} ({count} scenarios)"

        cluster_id = f"cluster_{index + 1:03d}_{first.failure_type.value}"
        clusters.append(
            EvalFailureCluster(
                cluster_id=cluster_id,
                failure_type=first.failure_type,
                severity=severity,
                pattern_summary=pattern,
                suggested_fix_area=first.suggested_fix_area,
                scenario_ids=scenario_ids,
                occurrence_count=count,
                priority_score=_compute_priority_score(
                    severity,
                    cluster_frequency=count,
                    reflection_missed=first.failure_type
                    == EvalFailureCategory.REFLECTION_MISSED_ISSUE,
                    regression_risk=first.regression_risk,
                ),
                example_scenario_id=first.scenario_id,
                example_assertion=first.expected_assertion,
                regression_risk=first.regression_risk,
            ),
        )

    return tuple(sorted(clusters, key=lambda c: -c.priority_score))


def _update_cluster_priority_scores(
    items: list[EvalFailureTriageItem],
    clusters: Sequence[EvalFailureCluster],
) -> list[EvalFailureTriageItem]:
    """Boost item priority scores using cluster recurrence frequency."""
    freq_by_scenario: dict[str, int] = defaultdict(int)
    for cluster in clusters:
        for sid in cluster.scenario_ids:
            freq_by_scenario[sid] = max(freq_by_scenario[sid], cluster.occurrence_count)

    updated: list[EvalFailureTriageItem] = []
    for item in items:
        freq = freq_by_scenario.get(item.scenario_id, 1)
        new_score = _compute_priority_score(
            item.severity,
            cluster_frequency=freq,
            reflection_missed=item.failure_type == EvalFailureCategory.REFLECTION_MISSED_ISSUE,
            regression_risk=item.regression_risk,
        )
        updated.append(
            EvalFailureTriageItem(
                scenario_id=item.scenario_id,
                scenario_category=item.scenario_category,
                failure_type=item.failure_type,
                severity=item.severity,
                provider=item.provider,
                ticket_label=item.ticket_label,
                expected_assertion=item.expected_assertion,
                actual_output_summary=item.actual_output_summary,
                conversation_summary=item.conversation_summary,
                draft_reply=item.draft_reply,
                reflection_applied=item.reflection_applied,
                reflection_saved=item.reflection_saved,
                reflection_issue_types=item.reflection_issue_types,
                root_cause_hypothesis=item.root_cause_hypothesis,
                suggested_fix_area=item.suggested_fix_area,
                regression_risk=item.regression_risk,
                priority_score=new_score,
                acceptable_variance=item.acceptable_variance,
                detected_intent=item.detected_intent,
                suggested_action=item.suggested_action,
            ),
        )
    return updated


def compute_reflection_effectiveness(
    rows: Sequence[Mapping[str, Any]],
    items: Sequence[EvalFailureTriageItem],
) -> ReflectionEffectivenessMetrics:
    """Compute reflection save/miss/false-rewrite rates."""
    metrics = ReflectionEffectivenessMetrics()
    failed_scenario_ids = {
        str(row.get("scenario_id")) for row in rows if row.get("passed") is not True
    }

    for row in rows:
        if not row.get("reflection_reviewed"):
            continue
        metrics.scenarios_with_reflection += 1
        if row.get("reflection_rewrite_applied"):
            metrics.reflection_rewrite_count += 1
            cat = str(row.get("category") or "unknown")
            metrics.rewrite_by_category[cat] = metrics.rewrite_by_category.get(cat, 0) + 1

        scenario_id = str(row.get("scenario_id") or "")
        passed = row.get("passed") is True
        rewrite = bool(row.get("reflection_rewrite_applied"))
        issues = row.get("reflection_issue_types") or []

        if passed and rewrite and issues:
            metrics.failures_prevented_by_reflection += 1
            metrics.rewrites_improved_result += 1
        elif not passed and rewrite:
            metrics.rewrites_still_failed += 1
            if issues:
                metrics.reflection_false_rewrite_rate += 0  # counted below
        elif not passed and not rewrite:
            missed = any(
                item.scenario_id == scenario_id
                and item.failure_type == EvalFailureCategory.REFLECTION_MISSED_ISSUE
                for item in items
            )
            if missed or (issues and not rewrite):
                metrics.failures_missed_by_reflection += 1

    missed_items = [
        item
        for item in items
        if item.failure_type == EvalFailureCategory.REFLECTION_MISSED_ISSUE
        and not item.acceptable_variance
    ]
    metrics.failures_missed_by_reflection = max(
        metrics.failures_missed_by_reflection,
        len({item.scenario_id for item in missed_items}),
    )

    failed_count = len(failed_scenario_ids)
    if metrics.scenarios_with_reflection:
        metrics.reflection_save_rate = (
            metrics.failures_prevented_by_reflection / metrics.scenarios_with_reflection
        )
    if failed_count:
        metrics.reflection_miss_rate = metrics.failures_missed_by_reflection / failed_count
    if metrics.reflection_rewrite_count:
        metrics.reflection_false_rewrite_rate = (
            metrics.rewrites_still_failed / metrics.reflection_rewrite_count
        )

    return metrics


def run_failure_triage(
    rows: Sequence[Mapping[str, Any]],
    *,
    scenarios_by_id: Mapping[str, Any] | None = None,
    source_path: str = "",
) -> EvalFailureTriageSummary:
    """Triage all failed scenarios from eval JSONL rows."""
    scenario_index: dict[str, Any] = dict(scenarios_by_id or {})
    if not scenario_index:
        try:
            for scenario in load_eval_scenarios():
                scenario_index[scenario.scenario_id] = scenario
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            scenario_index = {}

    providers = [str(row.get("provider") or "unknown") for row in rows]
    provider = Counter(providers).most_common(1)[0][0] if providers else "unknown"

    all_items: list[EvalFailureTriageItem] = []
    for row in rows:
        all_items.extend(triage_eval_row(row, scenarios_by_id=scenario_index, provider=provider))

    clusters = cluster_triage_items(all_items)
    all_items = _update_cluster_priority_scores(all_items, clusters)

    real_items = [item for item in all_items if not item.acceptable_variance]
    acceptable_count = sum(1 for item in all_items if item.acceptable_variance)

    by_failure_type = Counter(item.failure_type.value for item in real_items)
    by_severity = Counter(item.severity.value for item in real_items)
    by_fix_area = Counter(item.suggested_fix_area.value for item in real_items)

    failed_scenarios = sum(1 for row in rows if row.get("passed") is not True)
    reflection_metrics = compute_reflection_effectiveness(rows, all_items)

    return EvalFailureTriageSummary(
        generated_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
        source_results_path=source_path,
        provider=provider,
        total_scenarios=len(rows),
        failed_scenarios=failed_scenarios,
        triaged_failure_count=len(all_items),
        acceptable_variance_count=acceptable_count,
        real_failure_count=len(real_items),
        by_failure_type=dict(by_failure_type),
        by_severity=dict(by_severity),
        by_fix_area=dict(by_fix_area),
        reflection_metrics=reflection_metrics,
        clusters=clusters,
        items=tuple(sorted(all_items, key=lambda item: -item.priority_score)),
    )


def render_triage_report_markdown(summary: EvalFailureTriageSummary) -> str:
    """Grouped markdown report (no hidden prompts)."""
    real_items = [item for item in summary.items if not item.acceptable_variance]

    def _section(
        title: str,
        items: Sequence[EvalFailureTriageItem],
        *,
        limit: int = 12,
    ) -> list[str]:
        lines = [f"## {title}", ""]
        if not items:
            lines.append("_None._")
            lines.append("")
            return lines
        for item in items[:limit]:
            lines.append(f"### `{item.scenario_id}` ({item.severity.value})")
            lines.append("")
            lines.append(f"- **failure_type:** {item.failure_type.value}")
            lines.append(f"- **scenario_category:** {item.scenario_category}")
            lines.append(f"- **assertion:** `{item.expected_assertion}`")
            lines.append(f"- **priority_score:** {item.priority_score:.1f}")
            lines.append(f"- **conversation:** {item.conversation_summary}")
            lines.append(f"- **root_cause:** {item.root_cause_hypothesis}")
            lines.append(f"- **fix_area:** {item.suggested_fix_area.value}")
            lines.append(
                f"- **reflection:** applied={item.reflection_applied} "
                f"saved={item.reflection_saved}",
            )
            if item.draft_reply:
                lines.append("")
                lines.append("**Final draft:**")
                lines.append("")
                lines.append(f"> {item.draft_reply}")
            lines.append("")
        if len(items) > limit:
            lines.append(f"_… and {len(items) - limit} more._")
            lines.append("")
        return lines

    critical = [i for i in real_items if i.severity == EvalFailureSeverity.CRITICAL]
    high = [i for i in real_items if i.severity == EvalFailureSeverity.HIGH]
    reflection_misses = [
        i for i in real_items if i.failure_type == EvalFailureCategory.REFLECTION_MISSED_ISSUE
    ]
    policy_issues = [
        i for i in real_items if i.failure_type == EvalFailureCategory.POLICY_GROUNDING_FAILURE
    ]
    multi_turn = [
        i
        for i in real_items
        if i.failure_type
        in {
            EvalFailureCategory.MULTI_TURN_CONTEXT_FAILURE,
            EvalFailureCategory.REPEATED_IDENTIFIER_REQUEST,
        }
    ]
    cosmetic = [i for i in summary.items if i.acceptable_variance]

    lines = [
        "# Multi-turn failure triage report",
        "",
        f"**Generated:** {summary.generated_at_utc}",
        f"**Source:** {summary.source_results_path}",
        f"**Provider:** {summary.provider}",
        "",
        "## Overview",
        "",
        f"- total_scenarios: {summary.total_scenarios}",
        f"- failed_scenarios: {summary.failed_scenarios}",
        f"- real_failures: {summary.real_failure_count}",
        f"- acceptable_variance: {summary.acceptable_variance_count}",
        "",
        "## Reflection effectiveness",
        "",
        f"- reflection_save_rate: {summary.reflection_metrics.reflection_save_rate:.1%}",
        f"- reflection_miss_rate: {summary.reflection_metrics.reflection_miss_rate:.1%}",
        f"- reflection_false_rewrite_rate: "
        f"{summary.reflection_metrics.reflection_false_rewrite_rate:.1%}",
        f"- failures_prevented_by_reflection: "
        f"{summary.reflection_metrics.failures_prevented_by_reflection}",
        "- failures_missed_by_reflection: "
        f"{summary.reflection_metrics.failures_missed_by_reflection}",
        "",
        "## Top recurring clusters",
        "",
    ]
    if not summary.clusters:
        lines.append("_No clusters._")
        lines.append("")
    else:
        for cluster in summary.clusters[:10]:
            lines.append(
                f"- **{cluster.cluster_id}** ({cluster.occurrence_count}×): "
                f"{cluster.failure_type.value} — {cluster.pattern_summary} "
                f"[{cluster.suggested_fix_area.value}]",
            )
        lines.append("")

    lines.extend(_section("Critical failures", critical))
    lines.extend(_section("High-impact regressions", high))
    lines.extend(_section("Reflection misses", reflection_misses))
    lines.extend(_section("Policy / retrieval grounding issues", policy_issues))
    lines.extend(_section("Multi-turn / repeated-ask issues", multi_turn))
    lines.extend(_section("Acceptable variance (downgraded)", cosmetic, limit=8))

    lines.append("_Analysis only — no prompt changes in this step._")
    lines.append("")
    text = "\n".join(lines)
    assert_report_safe(text)
    return text


def write_failure_triage_reports(
    summary: EvalFailureTriageSummary,
    *,
    summary_json: Path = DEFAULT_TRIAGE_SUMMARY_JSON,
    report_md: Path = DEFAULT_TRIAGE_REPORT_MD,
    clusters_json: Path = DEFAULT_TRIAGE_CLUSTERS_JSON,
    overwrite: bool = False,
) -> None:
    """Write triage summary, clusters, and markdown report."""
    for path in (summary_json, report_md, clusters_json):
        if path.exists() and not overwrite:
            raise FileExistsError(f"output exists: {path} (use --overwrite)")

    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_payload = summary.to_json_dict()
    summary_text = json.dumps(summary_payload, ensure_ascii=False, indent=2)
    assert_report_safe(summary_text)
    summary_json.write_text(summary_text + "\n", encoding="utf-8")

    clusters_payload = {
        "generated_at_utc": summary.generated_at_utc,
        "clusters": [cluster.to_json_dict() for cluster in summary.clusters],
    }
    clusters_text = json.dumps(clusters_payload, ensure_ascii=False, indent=2)
    assert_report_safe(clusters_text)
    clusters_json.write_text(clusters_text + "\n", encoding="utf-8")

    report_md.write_text(render_triage_report_markdown(summary), encoding="utf-8")

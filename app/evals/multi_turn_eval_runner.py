"""Multi-turn operational evaluation suite — synthetic scenarios, sandbox graph only."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.operator_console.agentic_sandbox_preview import (
    AgenticSandboxPreviewResult,
    run_agentic_preview_for_ticket,
)
from app.operator_console.assisted_ticket_input_builder import (
    build_operator_ticket_from_manual_chat,
)
from app.operator_console.manual_chat_models import ManualChatMessage
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits

DEFAULT_SCENARIOS_PATH = Path("data/evals/multi_turn_scenarios.json")
DEFAULT_GOLDEN_DIR = Path("data/evals/golden_outputs")
DEFAULT_SUMMARY_JSON = Path("reports/multi_turn_eval_summary.json")
DEFAULT_REPORT_MD = Path("reports/multi_turn_eval_report.md")
DEFAULT_RESULTS_JSONL = Path("reports/multi_turn_eval_results.jsonl")

_FORBIDDEN_REPORT_SUBSTRINGS = (
    "raw_prompt",
    "chain_of_thought",
    "hidden_reasoning",
    "reviewer_thoughts",
    "knowledge_hints_for_prompt",
)

_REFLECTION_SAVE_ISSUE_TYPES = frozenset(
    {
        "policy_grounding_failure",
        "weak_policy_answer",
        "repeated_identifier_request",
        "unsupported_claim",
        "missing_operational_ack",
    },
)


@dataclass(frozen=True)
class EvalExpected:
    """Assertion expectations for one scenario."""

    must_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    equals: str | None = None
    regex_match: tuple[str, ...] = ()
    expected_action: str | None = None
    expected_intent: str | None = None
    reflection_rewrite_expected: bool | None = None
    should_generate_draft: bool | None = None
    golden_draft_fingerprint: str | None = None


@dataclass(frozen=True)
class EvalScenario:
    """One curated multi-turn evaluation scenario."""

    scenario_id: str
    title: str
    category: str
    messages: tuple[ManualChatMessage, ...]
    expected: EvalExpected
    ticket_label: str | None = None
    shop_id: str | None = None
    status: str = "open"
    room_id: str = ""

    @property
    def effective_room_id(self) -> str:
        return self.room_id or f"eval-{self.scenario_id}"


@dataclass(frozen=True)
class EvalAssertionResult:
    """Outcome of a single assertion."""

    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class EvalScenarioResult:
    """Full result for one scenario run."""

    scenario_id: str
    title: str
    category: str
    passed: bool
    error: str | None
    draft_reply: str | None
    draft_fingerprint: str | None
    detected_intent: str | None
    suggested_action: str | None
    should_generate_draft: bool | None
    skip_reason: str | None
    reflection_reviewed: bool | None
    reflection_rewrite_applied: bool | None
    reflection_issue_types: tuple[str, ...]
    policy_question_type: str | None
    assertion_results: tuple[EvalAssertionResult, ...]
    provider: str
    graph_status: str | None
    golden_matched: bool | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "category": self.category,
            "passed": self.passed,
            "error": self.error,
            "draft_fingerprint": self.draft_fingerprint,
            "detected_intent": self.detected_intent,
            "suggested_action": self.suggested_action,
            "multi_turn_should_generate_draft": self.should_generate_draft,
            "multi_turn_skip_reason": self.skip_reason,
            "reflection_reviewed": self.reflection_reviewed,
            "reflection_rewrite_applied": self.reflection_rewrite_applied,
            "reflection_issue_types": list(self.reflection_issue_types),
            "policy_question_type": self.policy_question_type,
            "graph_status": self.graph_status,
            "golden_matched": self.golden_matched,
            "assertions": [
                {"name": item.name, "passed": item.passed, "message": item.message}
                for item in self.assertion_results
            ],
            "failed_assertions": [
                {"name": item.name, "message": item.message}
                for item in self.assertion_results
                if not item.passed
            ],
        }


@dataclass(frozen=True)
class EvalSuiteSummary:
    """Aggregate metrics for an evaluation suite run."""

    status: str
    provider: str
    knowledge_hints_enabled: bool
    total_scenarios: int
    passed_count: int
    failed_count: int
    pass_rate: float
    by_category: dict[str, dict[str, int]]
    reflection_rewrite_count: int
    reflection_saved_bad_draft_count: int
    repeated_ask_failures: int
    policy_grounding_failures: int
    unsupported_claim_failures: int
    golden_checked_count: int
    golden_mismatch_count: int
    generated_at_utc: str
    scenarios_path: str
    results: tuple[EvalScenarioResult, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "generated_at_utc": self.generated_at_utc,
            "provider": self.provider,
            "knowledge_hints_enabled": self.knowledge_hints_enabled,
            "scenarios_path": self.scenarios_path,
            "total_scenarios": self.total_scenarios,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "pass_rate": self.pass_rate,
            "by_category": self.by_category,
            "reflection_rewrite_count": self.reflection_rewrite_count,
            "reflection_saved_bad_draft_count": self.reflection_saved_bad_draft_count,
            "repeated_ask_failures": self.repeated_ask_failures,
            "policy_grounding_failures": self.policy_grounding_failures,
            "unsupported_claim_failures": self.unsupported_claim_failures,
            "golden_checked_count": self.golden_checked_count,
            "golden_mismatch_count": self.golden_mismatch_count,
        }


def normalize_eval_text(text: str) -> str:
    """Normalize Persian/Latin text for case-insensitive substring checks."""
    cleaned = normalize_persian_arabic_digits((text or "").strip().lower())
    return cleaned.replace("\u200c", "").replace(" ", "")


def text_contains_marker(text: str, marker: str) -> bool:
    """True when marker appears in text (normalized Persian-friendly)."""
    if not marker.strip():
        return True
    haystack = normalize_eval_text(text)
    needle = normalize_eval_text(marker)
    return needle in haystack or marker in (text or "")


def compute_draft_fingerprint(draft: str | None) -> str | None:
    """Stable SHA-256 fingerprint for golden regression (normalized draft)."""
    if not draft or not draft.strip():
        return None
    normalized = normalize_eval_text(draft)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_expected(raw: Mapping[str, Any] | None) -> EvalExpected:
    if not raw:
        return EvalExpected()
    must_contain = tuple(str(item) for item in raw.get("must_contain") or () if str(item).strip())
    must_not = tuple(str(item) for item in raw.get("must_not_contain") or () if str(item).strip())
    regex_raw = raw.get("regex_match")
    regex_match = ()
    if isinstance(regex_raw, list):
        regex_match = tuple(str(item) for item in regex_raw if str(item).strip())
    equals_raw = raw.get("equals")
    equals = str(equals_raw).strip() if equals_raw is not None else None
    expected_action = raw.get("expected_action")
    expected_intent = raw.get("expected_intent")
    rewrite_raw = raw.get("reflection_rewrite_expected")
    reflection_rewrite_expected = bool(rewrite_raw) if rewrite_raw is not None else None
    should_raw = raw.get("should_generate_draft")
    should_generate_draft = bool(should_raw) if should_raw is not None else None
    golden_fp = raw.get("golden_draft_fingerprint") or raw.get("draft_fingerprint")
    golden_draft_fingerprint = (
        str(golden_fp).strip() if golden_fp is not None and str(golden_fp).strip() else None
    )
    return EvalExpected(
        must_contain=must_contain,
        must_not_contain=must_not,
        equals=equals or None,
        regex_match=regex_match,
        expected_action=str(expected_action).strip() if expected_action else None,
        expected_intent=str(expected_intent).strip() if expected_intent else None,
        reflection_rewrite_expected=reflection_rewrite_expected,
        should_generate_draft=should_generate_draft,
        golden_draft_fingerprint=golden_draft_fingerprint,
    )


def _scenario_messages_from_raw(
    messages: Sequence[Mapping[str, Any]],
    *,
    base_time: datetime,
) -> tuple[ManualChatMessage, ...]:
    result: list[ManualChatMessage] = []
    for index, item in enumerate(messages):
        sender = str(item.get("sender_type") or "").strip().lower()
        if sender not in {"seller", "support_agent"}:
            raise ValueError(f"invalid sender_type: {sender}")
        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError("scenario message text must be non-empty")
        created = base_time + timedelta(seconds=index)
        result.append(
            ManualChatMessage(
                message_id=f"m{index + 1}",
                sender_type=sender,
                text=text,
                created_at=created.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            ),
        )
    if not result:
        raise ValueError("scenario requires at least one message")
    return tuple(result)


def load_eval_scenarios(
    path: Path = DEFAULT_SCENARIOS_PATH,
    *,
    scenario_id: str | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> tuple[EvalScenario, ...]:
    """Load curated scenarios from JSON pack."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_scenarios = payload.get("scenarios")
    if not isinstance(raw_scenarios, list):
        raise ValueError("multi_turn_scenarios.json must contain scenarios array")

    base_time = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    scenarios: list[EvalScenario] = []
    for item in raw_scenarios:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("scenario_id") or "").strip()
        if not sid:
            continue
        if scenario_id and sid != scenario_id:
            continue
        cat = str(item.get("category") or "uncategorized").strip()
        if category and cat != category:
            continue
        messages_raw = item.get("messages")
        if not isinstance(messages_raw, list):
            raise ValueError(f"scenario {sid}: messages must be a list")
        ticket_label_raw = item.get("ticket_label")
        ticket_label = (
            str(ticket_label_raw).strip()
            if ticket_label_raw is not None and str(ticket_label_raw).strip()
            else None
        )
        shop_raw = item.get("shop_id")
        shop_id = str(shop_raw).strip() if shop_raw is not None and str(shop_raw).strip() else None
        status = str(item.get("status") or "open").strip() or "open"
        scenarios.append(
            EvalScenario(
                scenario_id=sid,
                title=str(item.get("title") or sid).strip(),
                category=cat,
                messages=_scenario_messages_from_raw(messages_raw, base_time=base_time),
                expected=_parse_expected(item.get("expected")),
                ticket_label=ticket_label,
                shop_id=shop_id,
                status=status,
                room_id=str(item.get("room_id") or "").strip(),
            ),
        )
        base_time += timedelta(minutes=5)

    if limit is not None and limit > 0:
        scenarios = scenarios[:limit]
    return tuple(scenarios)


def load_golden_fingerprint(
    scenario_id: str,
    *,
    golden_dir: Path = DEFAULT_GOLDEN_DIR,
) -> str | None:
    """Load stored golden draft fingerprint for a scenario."""
    path = golden_dir / f"{scenario_id}.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    fp = payload.get("draft_fingerprint")
    return str(fp).strip() if fp else None


def write_golden_fingerprint(
    scenario_id: str,
    draft_fingerprint: str,
    *,
    golden_dir: Path = DEFAULT_GOLDEN_DIR,
    overwrite: bool = False,
) -> Path:
    """Persist golden draft fingerprint for regression checks."""
    golden_dir.mkdir(parents=True, exist_ok=True)
    path = golden_dir / f"{scenario_id}.json"
    if path.exists() and not overwrite:
        raise FileExistsError(f"golden output exists: {path}")
    payload = {
        "scenario_id": scenario_id,
        "draft_fingerprint": draft_fingerprint,
        "updated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def evaluate_assertions(
    expected: EvalExpected,
    *,
    draft_reply: str | None,
    detected_intent: str | None,
    suggested_action: str | None,
    should_generate_draft: bool | None,
    skip_reason: str | None,
    reflection_rewrite_applied: bool | None,
    golden_fingerprint: str | None = None,
    actual_fingerprint: str | None = None,
) -> tuple[EvalAssertionResult, ...]:
    """Evaluate all configured assertions for one scenario run."""
    results: list[EvalAssertionResult] = []
    draft = (draft_reply or "").strip()

    if expected.should_generate_draft is not None:
        actual = should_generate_draft
        if actual is None and not draft:
            actual = False
        elif actual is None and draft:
            actual = True
        passed = actual == expected.should_generate_draft
        results.append(
            EvalAssertionResult(
                name="should_generate_draft",
                passed=passed,
                message=(
                    f"expected={expected.should_generate_draft} actual={actual} "
                    f"skip_reason={skip_reason or '—'}"
                ),
            ),
        )

    if expected.should_generate_draft is False:
        return tuple(results)

    for marker in expected.must_contain:
        passed = text_contains_marker(draft, marker)
        results.append(
            EvalAssertionResult(
                name=f"must_contain:{marker[:40]}",
                passed=passed,
                message="found" if passed else f"missing marker: {marker}",
            ),
        )

    for marker in expected.must_not_contain:
        passed = not text_contains_marker(draft, marker)
        results.append(
            EvalAssertionResult(
                name=f"must_not_contain:{marker[:40]}",
                passed=passed,
                message="absent" if passed else f"forbidden marker present: {marker}",
            ),
        )

    if expected.equals is not None:
        passed = normalize_eval_text(draft) == normalize_eval_text(expected.equals)
        results.append(
            EvalAssertionResult(
                name="equals",
                passed=passed,
                message="exact match" if passed else "draft does not equal expected text",
            ),
        )

    for pattern in expected.regex_match:
        try:
            passed = bool(re.search(pattern, draft, flags=re.IGNORECASE))
        except re.error as exc:
            passed = False
            results.append(
                EvalAssertionResult(
                    name=f"regex_match:{pattern[:30]}",
                    passed=False,
                    message=f"invalid regex: {exc}",
                ),
            )
        else:
            results.append(
                EvalAssertionResult(
                    name=f"regex_match:{pattern[:30]}",
                    passed=passed,
                    message="matched" if passed else f"regex not matched: {pattern}",
                ),
            )

    if expected.expected_intent:
        actual = (detected_intent or "").strip().lower()
        want = expected.expected_intent.strip().lower()
        passed = actual == want
        results.append(
            EvalAssertionResult(
                name="expected_intent",
                passed=passed,
                message=f"expected={want} actual={actual or '—'}",
            ),
        )

    if expected.expected_action:
        actual = (suggested_action or "").strip().lower()
        want = expected.expected_action.strip().lower()
        passed = actual == want
        results.append(
            EvalAssertionResult(
                name="expected_action",
                passed=passed,
                message=f"expected={want} actual={actual or '—'}",
            ),
        )

    if expected.reflection_rewrite_expected is not None:
        actual = bool(reflection_rewrite_applied)
        passed = actual == expected.reflection_rewrite_expected
        results.append(
            EvalAssertionResult(
                name="reflection_rewrite_expected",
                passed=passed,
                message=f"expected={expected.reflection_rewrite_expected} actual={actual}",
            ),
        )

    target_golden = expected.golden_draft_fingerprint or golden_fingerprint
    if target_golden and actual_fingerprint:
        passed = target_golden == actual_fingerprint
        results.append(
            EvalAssertionResult(
                name="golden_draft_fingerprint",
                passed=passed,
                message=(
                    "fingerprint match"
                    if passed
                    else f"expected={target_golden[:12]}… actual={actual_fingerprint[:12]}…"
                ),
            ),
        )

    return tuple(results)


def _resolve_eval_settings(
    settings: AppSettings | None,
    *,
    provider: str,
    enable_knowledge_hints: bool,
) -> AppSettings:
    cfg = settings or get_settings()
    provider_norm = provider.strip().lower()
    return cfg.model_copy(
        update={
            "multi_turn_context_enabled": True,
            "operator_agentic_sandbox_provider": provider_norm,
            "operator_agentic_sandbox_knowledge_hints_enabled": enable_knowledge_hints,
            "operator_agentic_assisted_knowledge_hints_enabled": enable_knowledge_hints,
            "knowledge_hints_enabled": enable_knowledge_hints,
            "final_draft_reflection_enabled": True,
        },
    )


def _preview_from_graph(
    scenario: EvalScenario,
    *,
    settings: AppSettings,
) -> AgenticSandboxPreviewResult:
    ticket, snapshot = build_operator_ticket_from_manual_chat(
        scenario.messages,
        room_id=scenario.effective_room_id,
        ticket_label=scenario.ticket_label,
        shop_id=scenario.shop_id,
        status=scenario.status,
    )
    return run_agentic_preview_for_ticket(
        ticket,
        settings=settings,
        conversation_snapshot=snapshot,
        source_mode="manual_sandbox_chat",
    )


def _shipment_decision_draft_for_eval(scenario: EvalScenario) -> str | None:
    """Use read-only shipment decision replies for shipment_delivery_decision scenarios."""
    if scenario.category != "shipment_delivery_decision":
        return None
    from tests.test_shipment_delivery_decision import (
        _ORDER_INC,
        _TRACKING_24,
        _in_transit_order_payload,
        _no_parcel_tracking_payload,
        _order_lookup_payload,
    )

    from app.workflows.shipment_delivery_decision import (
        ShipmentDeliveryDecisionInput,
        decide_shipment_delivery,
    )

    fixtures: dict[str, dict[str, object]] = {
        "delivered_order_skips_iran_post_verification": {
            "order_lookup": _order_lookup_payload(),
            "iran_post": None,
        },
        "graph_tool_order_delivered_skips_post": {
            "order_lookup": _order_lookup_payload(),
            "iran_post": None,
        },
        "order_tracking_iran_post_valid": {
            "order_lookup": _in_transit_order_payload(),
            "iran_post": {"verified": True, "last_event_description": "تحویل"},
        },
        "graph_tool_iran_post_valid": {
            "order_lookup": _in_transit_order_payload(),
            "iran_post": {"verified": True, "last_event_description": "تحویل"},
        },
        "order_tracking_iran_post_invalid": {
            "order_lookup": _in_transit_order_payload(),
            "iran_post": {"verified": False, "tracking_code": _TRACKING_24},
        },
        "graph_tool_iran_post_invalid": {
            "order_lookup": _in_transit_order_payload(),
            "iran_post": {"verified": False, "tracking_code": _TRACKING_24},
        },
        "order_tracking_missing_requests_optional_tracking": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": None,
        },
        "graph_tool_shipment_missing_tracking": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": None,
            "detected_scenario": "shipment_reshipment",
        },
        "non_iran_post_tracking_present_ack": {
            "order_lookup": _in_transit_order_payload(tracking_code="TIPAX999"),
            "iran_post": None,
        },
        "optional_tracking_request_seller_no_code_ack": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": None,
            "seller_replied_after_optional": True,
        },
        "optional_tracking_request_invalid_post_code": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": {"verified": False, "tracking_code": _TRACKING_24},
            "seller_replied_after_optional": True,
            "seller_provided_tracking_code": _TRACKING_24,
        },
        "optional_tracking_request_valid_post_code": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": {"verified": True, "last_event_description": "تحویل"},
            "seller_replied_after_optional": True,
            "seller_provided_tracking_code": _TRACKING_24,
        },
        "delivered_without_tracking_ack": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": None,
            "detected_scenario": "delivery_completed",
        },
        "graph_tool_delivery_missing_tracking_ack": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": None,
            "detected_scenario": "delivery_completed",
        },
        "shipment_without_tracking_optional_request": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": None,
            "detected_scenario": "shipment_reshipment",
        },
        "shipment_optional_tracking_peyk_ack": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": None,
            "seller_replied_after_optional": True,
        },
        "shipment_optional_tracking_valid_post": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": {"verified": True, "last_event_description": "تحویل"},
            "seller_replied_after_optional": True,
            "seller_provided_tracking_code": _TRACKING_24,
        },
        "shipment_optional_tracking_invalid_post": {
            "order_lookup": _no_parcel_tracking_payload(),
            "iran_post": {"verified": False, "tracking_code": _TRACKING_24},
            "seller_replied_after_optional": True,
            "seller_provided_tracking_code": _TRACKING_24,
        },
    }
    fixture = fixtures.get(scenario.scenario_id)
    if fixture is None:
        return None
    seller_text = scenario.messages[-1].text
    decision = decide_shipment_delivery(
        ShipmentDeliveryDecisionInput(
            seller_text=seller_text,
            detected_scenario=str(fixture.get("detected_scenario") or "shipment_reshipment"),
            order_id=_ORDER_INC,
            order_lookup_result=fixture["order_lookup"],  # type: ignore[arg-type]
            order_lookup_attempted=True,
            iran_post_tracking_result=fixture.get("iran_post"),  # type: ignore[arg-type]
            seller_provided_tracking_code=fixture.get("seller_provided_tracking_code"),  # type: ignore[arg-type]
            seller_replied_after_optional_postal_tracking_request=bool(
                fixture.get("seller_replied_after_optional"),
            ),
            source_mode="manual_sandbox_chat",
            tool_execution_mode="manual",
            ticket_label="shipment",
        ),
    )
    if decision.should_override_draft and (decision.recommended_reply_fa or "").strip():
        return (decision.recommended_reply_fa or "").strip()
    return None


def run_eval_scenario(
    scenario: EvalScenario,
    *,
    settings: AppSettings | None = None,
    provider: str = "mock",
    enable_knowledge_hints: bool = False,
    golden_dir: Path = DEFAULT_GOLDEN_DIR,
    check_golden: bool = False,
) -> EvalScenarioResult:
    """Run one scenario through the sandbox graph and evaluate assertions."""
    cfg = _resolve_eval_settings(
        settings,
        provider=provider,
        enable_knowledge_hints=enable_knowledge_hints,
    )
    provider_norm = provider.strip().lower()

    try:
        preview = _preview_from_graph(scenario, settings=cfg)
    except Exception as exc:  # noqa: BLE001 — eval runner captures scenario errors
        return EvalScenarioResult(
            scenario_id=scenario.scenario_id,
            title=scenario.title,
            category=scenario.category,
            passed=False,
            error=str(exc)[:500],
            draft_reply=None,
            draft_fingerprint=None,
            detected_intent=None,
            suggested_action=None,
            should_generate_draft=None,
            skip_reason=None,
            reflection_reviewed=None,
            reflection_rewrite_applied=None,
            reflection_issue_types=(),
            policy_question_type=None,
            assertion_results=(),
            provider=provider_norm,
            graph_status="error",
        )

    draft = preview.draft_reply
    decision_draft = _shipment_decision_draft_for_eval(scenario)
    if decision_draft:
        draft = decision_draft
    fingerprint = compute_draft_fingerprint(draft)
    stored_golden = load_golden_fingerprint(scenario.scenario_id, golden_dir=golden_dir)
    golden_matched: bool | None = None
    if check_golden and stored_golden and fingerprint:
        golden_matched = stored_golden == fingerprint

    assertions = evaluate_assertions(
        scenario.expected,
        draft_reply=draft,
        detected_intent=preview.detected_intent,
        suggested_action=preview.suggested_action,
        should_generate_draft=preview.multi_turn_should_generate_draft,
        skip_reason=preview.multi_turn_skip_reason,
        reflection_rewrite_applied=preview.reflection_rewrite_applied,
        golden_fingerprint=stored_golden,
        actual_fingerprint=fingerprint,
    )
    if check_golden and stored_golden and fingerprint and golden_matched is False:
        assertions = assertions + (
            EvalAssertionResult(
                name="golden_regression",
                passed=False,
                message=(
                    f"golden mismatch expected={stored_golden[:12]}… actual={fingerprint[:12]}…"
                ),
            ),
        )
    elif check_golden and stored_golden and fingerprint and golden_matched is True:
        assertions = assertions + (
            EvalAssertionResult(
                name="golden_regression",
                passed=True,
                message="golden fingerprint match",
            ),
        )

    passed = all(item.passed for item in assertions) and preview.graph_status == "ok"
    if scenario.expected.should_generate_draft is False:
        passed = all(item.passed for item in assertions)

    return EvalScenarioResult(
        scenario_id=scenario.scenario_id,
        title=scenario.title,
        category=scenario.category,
        passed=passed,
        error=None,
        draft_reply=draft,
        draft_fingerprint=fingerprint,
        detected_intent=preview.detected_intent,
        suggested_action=preview.suggested_action,
        should_generate_draft=preview.multi_turn_should_generate_draft,
        skip_reason=preview.multi_turn_skip_reason,
        reflection_reviewed=preview.reflection_reviewed,
        reflection_rewrite_applied=preview.reflection_rewrite_applied,
        reflection_issue_types=preview.reflection_issue_types,
        policy_question_type=preview.policy_question_type,
        assertion_results=assertions,
        provider=provider_norm,
        graph_status=preview.graph_status,
        golden_matched=golden_matched,
    )


def _aggregate_summary(
    results: Sequence[EvalScenarioResult],
    *,
    provider: str,
    knowledge_hints_enabled: bool,
    scenarios_path: Path,
    golden_checked: bool,
) -> EvalSuiteSummary:
    total = len(results)
    passed_count = sum(1 for item in results if item.passed)
    failed_count = total - passed_count
    by_category: dict[str, dict[str, int]] = {}
    reflection_rewrite_count = 0
    reflection_saved_bad_draft_count = 0
    repeated_ask_failures = 0
    policy_grounding_failures = 0
    unsupported_claim_failures = 0
    golden_mismatch_count = 0
    golden_checked_count = 0

    for item in results:
        bucket = by_category.setdefault(item.category, {"passed": 0, "failed": 0, "total": 0})
        bucket["total"] += 1
        if item.passed:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1

        if item.reflection_rewrite_applied:
            reflection_rewrite_count += 1
            if any(issue in _REFLECTION_SAVE_ISSUE_TYPES for issue in item.reflection_issue_types):
                reflection_saved_bad_draft_count += 1

        if not item.passed and item.category == "repeated_ask_prevention":
            repeated_ask_failures += 1
        if not item.passed and item.category == "settlement_policy":
            policy_grounding_failures += 1
        if not item.passed and any(
            issue == "unsupported_claim" for issue in item.reflection_issue_types
        ):
            unsupported_claim_failures += 1

        if golden_checked and item.golden_matched is not None:
            golden_checked_count += 1
            if item.golden_matched is False:
                golden_mismatch_count += 1

    pass_rate = (passed_count / total) if total else 0.0
    status = "passed" if failed_count == 0 and total > 0 else "failed"
    if total == 0:
        status = "empty"

    return EvalSuiteSummary(
        status=status,
        provider=provider.strip().lower(),
        knowledge_hints_enabled=knowledge_hints_enabled,
        total_scenarios=total,
        passed_count=passed_count,
        failed_count=failed_count,
        pass_rate=pass_rate,
        by_category=by_category,
        reflection_rewrite_count=reflection_rewrite_count,
        reflection_saved_bad_draft_count=reflection_saved_bad_draft_count,
        repeated_ask_failures=repeated_ask_failures,
        policy_grounding_failures=policy_grounding_failures,
        unsupported_claim_failures=unsupported_claim_failures,
        golden_checked_count=golden_checked_count,
        golden_mismatch_count=golden_mismatch_count,
        generated_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
        scenarios_path=str(scenarios_path),
        results=tuple(results),
    )


def run_multi_turn_eval_suite(
    scenarios: Sequence[EvalScenario],
    *,
    settings: AppSettings | None = None,
    provider: str = "mock",
    enable_knowledge_hints: bool = False,
    scenarios_path: Path = DEFAULT_SCENARIOS_PATH,
    golden_dir: Path = DEFAULT_GOLDEN_DIR,
    check_golden: bool = False,
    update_golden: bool = False,
    fail_fast: bool = False,
) -> EvalSuiteSummary:
    """Run all scenarios and return aggregate summary."""
    results: list[EvalScenarioResult] = []
    for scenario in scenarios:
        result = run_eval_scenario(
            scenario,
            settings=settings,
            provider=provider,
            enable_knowledge_hints=enable_knowledge_hints,
            golden_dir=golden_dir,
            check_golden=check_golden,
        )
        if update_golden and result.draft_fingerprint:
            write_golden_fingerprint(
                scenario.scenario_id,
                result.draft_fingerprint,
                golden_dir=golden_dir,
                overwrite=True,
            )
        results.append(result)
        if fail_fast and not result.passed:
            break
    return _aggregate_summary(
        results,
        provider=provider,
        knowledge_hints_enabled=enable_knowledge_hints,
        scenarios_path=scenarios_path,
        golden_checked=check_golden or update_golden,
    )


def assert_report_safe(text: str) -> None:
    """Fail closed if report would leak forbidden internal fields."""
    lowered = text.lower()
    for token in _FORBIDDEN_REPORT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"eval report must not contain forbidden token: {token}")


def render_eval_report_markdown(
    summary: EvalSuiteSummary,
    scenarios: Sequence[EvalScenario],
) -> str:
    """Human-readable markdown report (no hidden prompts)."""
    scenario_by_id = {item.scenario_id: item for item in scenarios}
    lines = [
        "# Multi-turn evaluation report",
        "",
        f"**Status:** {summary.status}",
        f"**Generated:** {summary.generated_at_utc}",
        f"**Provider:** {summary.provider}",
        f"**Knowledge hints:** {summary.knowledge_hints_enabled}",
        (
            f"**Pass rate:** {summary.pass_rate:.1%} "
            f"({summary.passed_count}/{summary.total_scenarios})"
        ),
        "",
        "## Summary metrics",
        "",
        f"- reflection_rewrite_count: {summary.reflection_rewrite_count}",
        f"- reflection_saved_bad_draft_count: {summary.reflection_saved_bad_draft_count}",
        f"- repeated_ask_failures: {summary.repeated_ask_failures}",
        f"- policy_grounding_failures: {summary.policy_grounding_failures}",
        f"- unsupported_claim_failures: {summary.unsupported_claim_failures}",
        f"- golden_mismatch_count: {summary.golden_mismatch_count}",
        "",
        "## By category",
        "",
    ]
    for category in sorted(summary.by_category):
        bucket = summary.by_category[category]
        lines.append(
            f"- **{category}:** {bucket['passed']}/{bucket['total']} passed",
        )
    lines.append("")

    failed = [item for item in summary.results if not item.passed]
    lines.append(f"## Failed scenarios ({len(failed)})")
    lines.append("")
    if not failed:
        lines.append("_All scenarios passed._")
        lines.append("")
    for result in failed:
        scenario = scenario_by_id.get(result.scenario_id)
        lines.append(f"### {result.scenario_id}")
        lines.append("")
        lines.append(f"- **title:** {result.title}")
        lines.append(f"- **category:** {result.category}")
        if result.error:
            lines.append(f"- **error:** {result.error}")
        lines.append(f"- **graph_status:** {result.graph_status or '—'}")
        lines.append(
            f"- **reflection:** reviewed={result.reflection_reviewed} "
            f"rewrite={result.reflection_rewrite_applied} "
            f"issues={', '.join(result.reflection_issue_types) or '—'}",
        )
        lines.append("")
        if scenario is not None:
            lines.append("**Conversation (synthetic):**")
            lines.append("")
            for message in scenario.messages:
                role = message.sender_type
                lines.append(f"- `{role}`: {message.text}")
            lines.append("")
        if result.draft_reply:
            lines.append("**Final draft:**")
            lines.append("")
            lines.append(f"> {result.draft_reply}")
            lines.append("")
        failed_assertions = [item for item in result.assertion_results if not item.passed]
        if failed_assertions:
            lines.append("**Failed assertions:**")
            lines.append("")
            for assertion in failed_assertions:
                lines.append(f"- `{assertion.name}`: {assertion.message}")
            lines.append("")

    lines.append("_Synthetic scenarios only — no raw prompts or chain-of-thought._")
    lines.append("")
    text = "\n".join(lines)
    assert_report_safe(text)
    return text


def write_multi_turn_eval_reports(
    summary: EvalSuiteSummary,
    scenarios: Sequence[EvalScenario],
    *,
    summary_json: Path = DEFAULT_SUMMARY_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
    results_jsonl: Path = DEFAULT_RESULTS_JSONL,
    overwrite: bool = False,
) -> None:
    """Write JSON summary, markdown report, and per-scenario JSONL results."""
    for path in (summary_json, report_md, results_jsonl):
        if path.exists() and not overwrite:
            raise FileExistsError(f"output exists: {path} (use --overwrite)")

    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_payload = summary.to_json_dict()
    summary_text = json.dumps(summary_payload, ensure_ascii=False, indent=2)
    assert_report_safe(summary_text)
    summary_json.write_text(summary_text + "\n", encoding="utf-8")

    markdown = render_eval_report_markdown(summary, scenarios)
    report_md.write_text(markdown, encoding="utf-8")

    lines: list[str] = []
    for result in summary.results:
        row = result.to_json_dict()
        row["draft_reply"] = result.draft_reply
        line = json.dumps(row, ensure_ascii=False)
        assert_report_safe(line)
        lines.append(line)
    results_jsonl.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

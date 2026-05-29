"""Read-only multi-order shipment/delivery orchestration for manual sandbox."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.config import AppSettings, get_settings
from app.tools.inchand.order_lookup import lookup_inchand_order, normalize_inchand_order_id
from app.tools.operational_actions_registry import (
    OperationalToolId,
    build_inchand_eligibility_context,
    evaluate_tool_eligibility,
)
from app.workflows.operational_information_sufficiency import detect_operational_scenario
from app.workflows.shipment_delivery_decision import (
    ShipmentDeliveryDecisionInput,
    ShipmentDeliveryDecisionType,
    decide_shipment_delivery,
)

_INC_ORDER_RE = re.compile(r"\binc\s*[-_:\s]*(\d{7})\b", re.IGNORECASE)
_DIGIT_7_RE = re.compile(r"(?<!\d)(\d{7})(?!\d)")
_DIGIT_24_RE = re.compile(r"(?<!\d)(\d{24})(?!\d)")
_LONG_DIGIT_RE = re.compile(r"(?<!\d)(\d{8,})(?!\d)")
_ORDER_CONTEXT_MARKERS = ("سفارش", "order", "orders", "شماره")


@dataclass(frozen=True)
class MultiOrderExtractionDiagnostics:
    candidates_found: tuple[str, ...]
    normalized_order_ids: tuple[str, ...]
    rejected_candidates: tuple[str, ...]
    duplicate_count: int


@dataclass(frozen=True)
class PerOrderShipmentDecision:
    order_id: str
    found: bool | None
    order_status: str | None
    provider_status: str | None
    parcel_status: str | None
    has_tracking: bool
    delivered_in_inchand: bool
    lookup_error_type: str | None
    decision_type: str
    category: str

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "found": self.found,
            "order_status": self.order_status,
            "provider_status": self.provider_status,
            "parcel_status": self.parcel_status,
            "has_tracking": self.has_tracking,
            "delivered_in_inchand": self.delivered_in_inchand,
            "lookup_error_type": self.lookup_error_type,
            "decision_type": self.decision_type,
            "category": self.category,
        }


@dataclass(frozen=True)
class MultiOrderBatchSummary:
    batch_count: int
    executed_count: int
    skipped_count: int
    limit_exceeded: bool

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "batch_count": self.batch_count,
            "executed_count": self.executed_count,
            "skipped_count": self.skipped_count,
            "limit_exceeded": self.limit_exceeded,
        }


@dataclass(frozen=True)
class MultiOrderShipmentDecision:
    decision_type: str
    recommended_reply_fa: str
    should_override_draft: bool = True
    per_order: tuple[PerOrderShipmentDecision, ...] = ()
    summary: MultiOrderBatchSummary = field(
        default_factory=lambda: MultiOrderBatchSummary(0, 0, 0, False),
    )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type,
            "recommended_reply_fa": self.recommended_reply_fa,
            "should_override_draft": self.should_override_draft,
            "per_order": [row.to_safe_dict() for row in self.per_order],
            "summary": self.summary.to_safe_dict(),
        }


@dataclass(frozen=True)
class MultiOrderShipmentInput:
    seller_text: str
    source_mode: str
    graph_tools_enabled: bool
    detected_intent: str | None = None
    suggested_action: str | None = None
    conceptual_intent_fa: str | None = None
    preloaded_lookup_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    settings: AppSettings | None = None


def extract_all_inchand_order_ids_with_diagnostics(text: str) -> MultiOrderExtractionDiagnostics:
    normalized = text or ""
    candidates: list[str] = []
    rejected: list[str] = []
    accepted: list[str] = []
    seen: set[str] = set()
    duplicate_count = 0

    inc_spans: list[tuple[int, int]] = []
    for match in _INC_ORDER_RE.finditer(normalized):
        candidates.append(match.group(0))
        inc_spans.append(match.span())
        order_id = f"INC-{match.group(1)}"
        if order_id in seen:
            duplicate_count += 1
            continue
        accepted.append(order_id)
        seen.add(order_id)

    for match in _DIGIT_24_RE.finditer(normalized):
        candidates.append(match.group(1))
        rejected.append(match.group(1))

    has_order_context = any(marker in normalized.lower() for marker in _ORDER_CONTEXT_MARKERS) or (
        "INC-" in normalized.upper()
    )
    for match in _DIGIT_7_RE.finditer(normalized):
        raw = match.group(1)
        span = match.span()
        if any(span[0] >= inc_start and span[1] <= inc_end for inc_start, inc_end in inc_spans):
            continue
        candidates.append(raw)
        if not has_order_context:
            rejected.append(raw)
            continue
        order_id = f"INC-{raw}"
        if order_id in seen:
            duplicate_count += 1
            continue
        accepted.append(order_id)
        seen.add(order_id)

    for match in _LONG_DIGIT_RE.finditer(normalized):
        raw = match.group(1)
        if len(raw) == 24 or len(raw) == 7:
            continue
        candidates.append(raw)
        rejected.append(raw)

    normalized_ids = tuple(
        normalized_id for raw in accepted if (normalized_id := normalize_inchand_order_id(raw))
    )
    return MultiOrderExtractionDiagnostics(
        candidates_found=tuple(candidates),
        normalized_order_ids=normalized_ids,
        rejected_candidates=tuple(rejected),
        duplicate_count=duplicate_count,
    )


def extract_all_inchand_order_ids(text: str) -> list[str]:
    return list(extract_all_inchand_order_ids_with_diagnostics(text).normalized_order_ids)


def _category_from_decision(decision_type: str) -> str:
    mapping = {
        ShipmentDeliveryDecisionType.ORDER_ALREADY_DELIVERED_IN_INCHAND.value: (
            "delivered_in_inchand"
        ),
        ShipmentDeliveryDecisionType.ORDER_LOOKUP_FAILED.value: "lookup_failed",
        ShipmentDeliveryDecisionType.DELIVERY_COMPLETED_WITHOUT_TRACKING_ACK.value: (
            "delivery_completed_without_tracking_ack"
        ),
        ShipmentDeliveryDecisionType.TRACKING_MISSING_REQUEST_REQUIRED.value: (
            "no_tracking_shipment_needs_optional_tracking"
        ),
        ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_VALID.value: "iran_post_tracking_valid",
        ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_INVALID.value: "iran_post_tracking_invalid",
        ShipmentDeliveryDecisionType.NON_IRAN_POST_TRACKING_PRESENT.value: (
            "non_iran_post_tracking_present"
        ),
    }
    return mapping.get(decision_type, "unknown_requires_review")


def _build_aggregate_reply(
    rows: tuple[PerOrderShipmentDecision, ...], *, limit_exceeded: bool
) -> tuple[str, str]:
    if limit_exceeded:
        return (
            "multi_order_limit_exceeded",
            "درخواست شما برای بررسی سفارش‌های اعلام‌شده ثبت شد و در دست بررسی قرار گرفت.",
        )
    if not rows:
        return (
            "multi_order_mixed_review",
            (
                "وضعیت سفارش‌های اعلام‌شده بررسی شد. برخی سفارش‌ها نیاز به بررسی بیشتر "
                "دارند و درخواست شما ثبت شد و در دست بررسی قرار گرفت."
            ),
        )
    has_not_found = any(row.category == "not_found" for row in rows)
    if has_not_found:
        return (
            "multi_order_not_found_present",
            (
                "برخی از شماره سفارش‌های اعلام‌شده در سیستم یافت نشدند. "
                "درخواست شما ثبت شد و در دست بررسی قرار گرفت."
            ),
        )
    all_delivered = all(row.category == "delivered_in_inchand" for row in rows)
    if all_delivered:
        return (
            "multi_order_all_delivered",
            (
                "وضعیت سفارش‌های اعلام‌شده بررسی شد. وضعیت مرسوله برای همه سفارش‌ها "
                "تحویل شده است و درخواست شما ثبت و در دست بررسی قرار گرفت."
            ),
        )
    has_shipment_tracking_missing = any(
        row.category == "no_tracking_shipment_needs_optional_tracking" for row in rows
    )
    if has_shipment_tracking_missing:
        return (
            "multi_order_shipment_tracking_missing",
            (
                "لطفاً روش ارسال و کد رهگیری پستی را در صورت وجود برای سفارش‌های "
                "فاقد کد رهگیری ارسال کنید."
            ),
        )
    return (
        "multi_order_mixed_review",
        (
            "وضعیت سفارش‌های اعلام‌شده بررسی شد. برخی سفارش‌ها نیاز به بررسی بیشتر "
            "دارند و درخواست شما ثبت شد و در دست بررسی قرار گرفت."
        ),
    )


def decide_multi_order_shipment(inp: MultiOrderShipmentInput) -> MultiOrderShipmentDecision:
    cfg = inp.settings or get_settings()
    diagnostics = extract_all_inchand_order_ids_with_diagnostics(inp.seller_text)
    order_ids = diagnostics.normalized_order_ids
    count = len(order_ids)
    max_auto = int(cfg.multi_order_batch_max_auto_lookup)
    if count > max_auto:
        summary = MultiOrderBatchSummary(
            batch_count=count,
            executed_count=0,
            skipped_count=count,
            limit_exceeded=True,
        )
        decision_type, reply = _build_aggregate_reply((), limit_exceeded=True)
        return MultiOrderShipmentDecision(
            decision_type=decision_type, recommended_reply_fa=reply, summary=summary
        )

    scenario = detect_operational_scenario(
        seller_text=inp.seller_text,
        detected_intent=inp.detected_intent,
        suggested_action=inp.suggested_action,
        conceptual_intent_fa=inp.conceptual_intent_fa,
    )
    rows: list[PerOrderShipmentDecision] = []
    executed = 0
    for order_id in order_ids:
        safe_lookup = inp.preloaded_lookup_results.get(order_id)
        if safe_lookup is None:
            eligibility = evaluate_tool_eligibility(
                OperationalToolId.INCHAND_ORDER_LOOKUP,
                build_inchand_eligibility_context(
                    cfg,
                    source_mode=inp.source_mode,
                    order_id_present=True,
                    sandbox_auto_enabled=inp.graph_tools_enabled
                    and cfg.agentic_graph_order_lookup_enabled,
                    detected_scenario=scenario,
                    scenario_auto_eligible=True,
                ),
            )
            if eligibility.sandbox_auto_allowed:
                safe_lookup = lookup_inchand_order(order_id, settings=cfg).to_safe_dict()
                executed += 1
        found = bool(safe_lookup.get("found")) if isinstance(safe_lookup, dict) else None
        if isinstance(safe_lookup, dict):
            per_decision = decide_shipment_delivery(
                ShipmentDeliveryDecisionInput(
                    seller_text=inp.seller_text,
                    detected_scenario=scenario,
                    order_id=order_id,
                    order_lookup_result=safe_lookup,
                    order_lookup_attempted=True,
                    source_mode=inp.source_mode,
                    tool_execution_mode="sandbox_auto" if inp.graph_tools_enabled else "disabled",
                ),
            ).to_safe_dict()
            decision_type = str(per_decision.get("decision_type") or "unknown_requires_review")
            category = "not_found" if found is False else _category_from_decision(decision_type)
            rows.append(
                PerOrderShipmentDecision(
                    order_id=order_id,
                    found=found,
                    order_status=safe_lookup.get("order_status"),
                    provider_status=safe_lookup.get("primary_provider_status"),
                    parcel_status=safe_lookup.get("primary_parcel_status_name"),
                    has_tracking=bool(safe_lookup.get("primary_parcel_tracking_code")),
                    delivered_in_inchand=bool(safe_lookup.get("is_delivered_in_inchand")),
                    lookup_error_type=safe_lookup.get("error_type"),
                    decision_type=decision_type,
                    category=category,
                ),
            )
        else:
            rows.append(
                PerOrderShipmentDecision(
                    order_id=order_id,
                    found=None,
                    order_status=None,
                    provider_status=None,
                    parcel_status=None,
                    has_tracking=False,
                    delivered_in_inchand=False,
                    lookup_error_type="eligibility_blocked",
                    decision_type="order_lookup_failed",
                    category="lookup_failed",
                ),
            )

    summary = MultiOrderBatchSummary(
        batch_count=count,
        executed_count=executed,
        skipped_count=max(count - executed, 0),
        limit_exceeded=False,
    )
    rows_tuple = tuple(rows[: int(cfg.multi_order_batch_max_reply_items)])
    decision_type, reply = _build_aggregate_reply(rows_tuple, limit_exceeded=False)
    return MultiOrderShipmentDecision(
        decision_type=decision_type,
        recommended_reply_fa=reply,
        per_order=rows_tuple,
        summary=summary,
    )

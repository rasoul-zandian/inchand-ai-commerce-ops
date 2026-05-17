"""Department-aware review routing contract (metadata only; no assignment)."""

from __future__ import annotations

from pydantic import BaseModel, Field

ALLOWED_DEPARTMENTS = frozenset({"finance", "support", "complaint", "qa_review", "general"})
ALLOWED_REVIEWER_ROLES = frozenset(
    {
        "finance_operator",
        "support_operator",
        "complaint_operator",
        "senior_reviewer",
        "general_operator",
    }
)

_FINANCE_KEYWORDS = (
    "fund",
    "financial",
    "finance",
    "billing",
    "مالی",
    "تسویه",
    "فاکتور",
    "invoice",
    "settlement",
)
_COMPLAINT_KEYWORDS = ("complaint", "شکایت", "اعتراض")
_SUPPORT_KEYWORDS = ("support", "پشتیبانی", "escalation", "ارجاع")


class DepartmentReviewRoute(BaseModel):
    assigned_department: str
    reviewer_role: str
    routing_source: str
    routing_reasons: list[str] = Field(default_factory=list)
    requires_senior_review: bool = False


def _normalized(value: str | None) -> str:
    return (value or "").strip().lower()


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    if not haystack:
        return False
    return any(needle in haystack for needle in needles)


def _is_finance_signal(*, ticket_label: str, route_label: str) -> bool:
    if route_label == "billing_review":
        return True
    return _contains_any(ticket_label, _FINANCE_KEYWORDS)


def _is_complaint_signal(ticket_label: str) -> bool:
    return _contains_any(ticket_label, _COMPLAINT_KEYWORDS)


def _is_support_signal(*, ticket_label: str, route_label: str) -> bool:
    if route_label == "escalation_review":
        return True
    return _contains_any(ticket_label, _SUPPORT_KEYWORDS)


def build_department_review_route(
    *,
    ticket_label: str | None,
    route_label: str | None,
    qa_requires_human_attention: bool,
    risk_score: float | None,
    detected_intent: str | None = None,
) -> DepartmentReviewRoute:
    """Deterministic department/role recommendation for human review queues."""
    label_norm = _normalized(ticket_label)
    route_norm = _normalized(route_label)
    intent_norm = _normalized(detected_intent)
    reasons: list[str] = []
    sources: list[str] = []

    if not label_norm and intent_norm == "billing_discrepancy":
        label_norm = "financial"
        reasons.append("detected_intent_billing_discrepancy")
        sources.append("detected_intent")

    high_risk = risk_score is not None and risk_score >= 0.65
    if qa_requires_human_attention or high_risk:
        if qa_requires_human_attention:
            reasons.append("qa_requires_human_attention")
        if high_risk:
            reasons.append("risk_score_high")
        routing_source = "+".join(sources) if sources else "qa_or_risk"
        if route_norm:
            routing_source = f"{routing_source}+route_label" if routing_source else "route_label"
        if label_norm:
            routing_source = f"{routing_source}+ticket_label" if routing_source else "ticket_label"
        return DepartmentReviewRoute(
            assigned_department="qa_review",
            reviewer_role="senior_reviewer",
            routing_source=routing_source or "qa_or_risk",
            routing_reasons=reasons or ["qa_or_high_risk"],
            requires_senior_review=True,
        )

    if _is_complaint_signal(label_norm):
        return DepartmentReviewRoute(
            assigned_department="complaint",
            reviewer_role="complaint_operator",
            routing_source="ticket_label",
            routing_reasons=["ticket_label_complaint"],
        )

    if route_norm == "escalation_review":
        return DepartmentReviewRoute(
            assigned_department="support",
            reviewer_role="support_operator",
            routing_source="route_label",
            routing_reasons=["route_label_escalation_review"],
        )

    if _contains_any(label_norm, _SUPPORT_KEYWORDS) and not _contains_any(
        label_norm, _FINANCE_KEYWORDS
    ):
        return DepartmentReviewRoute(
            assigned_department="support",
            reviewer_role="support_operator",
            routing_source="ticket_label",
            routing_reasons=["ticket_label_support"],
        )

    if _is_finance_signal(ticket_label=label_norm, route_label=route_norm):
        if route_norm == "billing_review":
            reasons.append("route_label_billing_review")
        if label_norm:
            reasons.append("ticket_label_finance")
        return DepartmentReviewRoute(
            assigned_department="finance",
            reviewer_role="finance_operator",
            routing_source="route_label" if route_norm == "billing_review" else "ticket_label",
            routing_reasons=reasons or ["finance_topic"],
        )

    if _is_support_signal(ticket_label=label_norm, route_label=route_norm):
        source = "route_label" if route_norm else "ticket_label"
        return DepartmentReviewRoute(
            assigned_department="support",
            reviewer_role="support_operator",
            routing_source=source,
            routing_reasons=["support_topic"],
        )

    return DepartmentReviewRoute(
        assigned_department="general",
        reviewer_role="general_operator",
        routing_source="default",
        routing_reasons=["default_general_routing"],
    )

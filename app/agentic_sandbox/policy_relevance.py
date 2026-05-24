"""Policy relevance signals for agentic sandbox analytics."""

from __future__ import annotations

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


def is_policy_relevant_signals(
    *,
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
    ticket_label: str | None = None,
    route_label: str | None = None,
) -> bool:
    """True when any sandbox signal implies official policy knowledge would help."""
    intent = (detected_intent or "").strip().lower()
    action = (suggested_action or "").strip().lower()
    if intent in _POLICY_INTENTS or action in _POLICY_ACTIONS:
        return True
    label = (ticket_label or "").strip().lower()
    route = (route_label or "").strip().lower()
    if label in _POLICY_LABELS or route in _POLICY_ROUTES:
        return True
    blob = _signal_blob_from_parts(
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
        ticket_label=ticket_label,
        route_label=route_label,
    )
    return any(keyword in blob for keyword in _POLICY_KEYWORDS)

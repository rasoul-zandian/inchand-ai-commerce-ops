"""Vendor ticket specialist node: draft via provider-agnostic LLM layer (no outbound send)."""

from __future__ import annotations

from typing import Any, cast

from app.config import get_settings
from app.llm import generate_text
from app.llm.types import LLMResponse
from app.prompts.vendor_ticket import build_vendor_ticket_prompt
from app.state.commerce_state import CommerceAIState

from .common import _append_audit, _state_dict


def _policy_summary_text(retrieved_context: dict[str, Any]) -> str:
    policy_ctx = retrieved_context.get("policy_context")
    if isinstance(policy_ctx, dict):
        summary = policy_ctx.get("summary")
        if summary:
            return str(summary)
        title = policy_ctx.get("title")
        if title:
            return str(title)
        return ""
    if policy_ctx is None:
        return ""
    return str(policy_ctx)


def _llm_evidence(response: LLMResponse) -> list[str]:
    """Build LLM-related evidence lines; omit empty or None-valued fields."""
    lines: list[str] = [
        f"llm_provider={response.provider}",
        f"llm_model={response.model}",
    ]
    digest = response.metadata.get("digest")
    if digest:
        lines.append(f"llm_digest={digest}")
    response_id = response.metadata.get("response_id")
    if response_id:
        lines.append(f"llm_response_id={response_id}")
    return lines


def vendor_ticket_node(state: CommerceAIState) -> CommerceAIState:
    """Draft vendor reply text through app.llm; does not send any ticket reply."""
    data = _state_dict(state)
    ctx = data.get("retrieved_context") or {}
    ticket = ctx.get("ticket") or {}
    vendor = ctx.get("vendor") or {}

    ticket_subject = str(ticket.get("subject") or "بدون عنوان")
    ticket_body = str(ticket.get("body") or "")
    vendor_name = str(vendor.get("name") or "فروشنده")
    policy_summary = _policy_summary_text(ctx)
    previous_cases = ctx.get("previous_cases") or []
    previous_cases_count = len(previous_cases) if isinstance(previous_cases, list) else 0

    messages = build_vendor_ticket_prompt(
        ticket_subject=ticket_subject,
        ticket_body=ticket_body,
        vendor_name=vendor_name,
        policy_summary=policy_summary,
        previous_cases_count=previous_cases_count,
    )

    settings = get_settings()
    response = generate_text(
        messages,
        provider=settings.llm_provider,
        model=settings.llm_model,
    )

    confidence = 0.82
    risk = 0.34

    data["specialist_output"] = {
        "draft_response": response.content,
        "detected_intent": "billing_discrepancy",
        "confidence_score": confidence,
        "risk_score": risk,
        "evidence": [
            f"ticket_subject={ticket_subject}",
            f"vendor_name={vendor_name}",
            "policy_context_used=true",
            *_llm_evidence(response),
        ],
        "llm_provider": response.provider,
        "llm_model": response.model,
        "llm_metadata": response.metadata,
    }

    data["confidence_score"] = confidence
    data["risk_score"] = risk

    data["final_response"] = (
        "پیش‌نویس پاسخ برای تیکت فروشنده آماده شد و برای جلوگیری از ارسال خودکار، "
        "نیازمند تأیید انسانی است. لطفاً متن را در کنسول ادمین بازبینی و پس از تأیید ارسال کنید."
    )

    audit_metadata: dict[str, Any] = {
        "detected_intent": "billing_discrepancy",
        "llm_provider": response.provider,
        "llm_model": response.model,
    }
    response_id = response.metadata.get("response_id")
    if response_id:
        audit_metadata["llm_response_id"] = response_id

    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name="vendor_ticket_node",
        message="Generated vendor ticket draft via LLM layer (not sent).",
        metadata=audit_metadata,
    )
    return cast(CommerceAIState, data)

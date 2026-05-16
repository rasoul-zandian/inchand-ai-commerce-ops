"""Vendor ticket specialist node: draft via provider-agnostic LLM layer (no outbound send)."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm import generate_text
from app.llm.types import LLMResponse
from app.prompts.vendor_ticket import build_vendor_ticket_prompt
from app.rag.types import RAGDocument
from app.state.commerce_state import CommerceAIState
from app.tickets.workflow_mapping import resolve_ticket_context_from_state

from .common import _append_audit, _state_dict


class TicketIntentResult(BaseModel):
    """Normalized ticket intent from rule-based intent agent."""

    detected_intent: str


class PolicyGroundingResult(BaseModel):
    """Summary of retrieved policy/RAG context (no new retrieval)."""

    grounding_summary: str
    grounding_sources: list[str] = Field(default_factory=list)
    rag_document_count: int = 0
    policy_summary: str = ""


class DraftingResult(BaseModel):
    """LLM draft output and provider metadata."""

    draft_response: str
    llm_provider: str
    llm_model: str
    llm_metadata: dict[str, Any] = Field(default_factory=dict)


class QACheckResult(BaseModel):
    """Rule-based post-draft QA (does not block workflow or human approval)."""

    qa_passed: bool
    qa_issues: list[str] = Field(default_factory=list)
    qa_warnings: list[str] = Field(default_factory=list)
    qa_summary: str = ""


class SupervisorRoutingResult(BaseModel):
    """Deterministic operational route label (does not change LangGraph edges)."""

    route_label: str
    recommended_action: str
    routing_reasons: list[str] = Field(default_factory=list)
    requires_human_review: bool = True


class RiskReviewResult(BaseModel):
    """Deterministic risk/confidence for human approval gating."""

    confidence_score: float
    risk_score: float


_QA_SUMMARY_TOP_N = 3

_BILLING_KEYWORDS = ("تسویه", "فاکتور", "صورتحساب", "مغایرت", "billing", "invoice", "settlement")
_ESCALATION_KEYWORDS = ("ارجاع", "فوری", "escalat", "urgent")
_RISKY_PROMISE_TERMS = (
    "واریز قطعی",
    "بازپرداخت قطعی",
    "مبلغ قطعی",
    "تضمین می‌کنیم",
    "تضمین می کنیم",
    "حتماً پرداخت",
    "حتما پرداخت",
)
_BILLING_CLARIFICATION_TERMS = (
    "شماره فاکتور",
    "بازه زمانی",
    "تیم مالی",
    "بررسی مالی",
    "مدارک",
)
_UNPROFESSIONAL_TERMS = ("احمق", "بی‌ادب", "حق ندارید", "مقصر شما")


_REVIEW_CATEGORY_BY_ROUTE: dict[str, str] = {
    "qa_attention": "qa_attention",
    "escalation_review": "escalation",
    "billing_review": "billing",
    "style_guidance": "style_review",
    "general_vendor_support": "general_support",
}

_REVIEW_REASON_BY_CATEGORY: dict[str, str] = {
    "qa_attention": "QA issues require manual review.",
    "escalation": "Escalation workflow requires operator review.",
    "billing": "Billing discrepancy response awaiting approval.",
    "style_review": "Style and tone guidance review required.",
    "general_support": "General vendor support approval required.",
}


def _review_category_from_route(route_label: str | None) -> str:
    if not route_label:
        return "general_support"
    return _REVIEW_CATEGORY_BY_ROUTE.get(route_label, "general_support")


def _review_priority(
    *,
    route_label: str | None,
    qa_requires_human_attention: bool,
    risk_score: float | None,
    confidence_score: float | None,
) -> str:
    if qa_requires_human_attention or (risk_score is not None and risk_score >= 0.65):
        return "HIGH"
    if route_label == "escalation_review" or (
        confidence_score is not None and confidence_score < 0.75
    ):
        return "MEDIUM"
    return "LOW"


def build_review_queue_metadata(state: CommerceAIState) -> dict[str, Any]:
    """Lightweight review-queue fields for operator tooling (no persistence)."""
    data = _state_dict(state)
    route_label = data.get("route_label")
    category = _review_category_from_route(route_label if isinstance(route_label, str) else None)
    qa_requires = bool(data.get("qa_requires_human_attention"))
    risk_score = data.get("risk_score")
    confidence_score = data.get("confidence_score")
    priority = _review_priority(
        route_label=route_label if isinstance(route_label, str) else None,
        qa_requires_human_attention=qa_requires,
        risk_score=risk_score if isinstance(risk_score, (int, float)) else None,
        confidence_score=confidence_score if isinstance(confidence_score, (int, float)) else None,
    )
    from app.review_queue.department_routing import build_department_review_route

    ticket_context = resolve_ticket_context_from_state(data)
    ticket_label = ticket_context.get("ticket_label")
    detected_intent = data.get("detected_intent")
    department_route = build_department_review_route(
        ticket_label=ticket_label,
        route_label=route_label if isinstance(route_label, str) else None,
        qa_requires_human_attention=qa_requires,
        risk_score=risk_score if isinstance(risk_score, (int, float)) else None,
        detected_intent=detected_intent if isinstance(detected_intent, str) else None,
    )
    return {
        "review_category": category,
        "review_priority": priority,
        "review_reason": _REVIEW_REASON_BY_CATEGORY.get(
            category, _REVIEW_REASON_BY_CATEGORY["general_support"]
        ),
        "requires_human_approval": bool(data.get("human_approval_required")),
        "route_label": route_label,
        "qa_requires_attention": qa_requires,
        "qa_issue_count": len(data.get("qa_issues") or []),
        "risk_score": risk_score,
        "confidence_score": confidence_score,
        "department_route": department_route.model_dump(mode="json"),
    }


def apply_review_queue_metadata_to_state(state: CommerceAIState) -> CommerceAIState:
    """Promote review metadata onto state after approval gates are known."""
    data = _state_dict(state)
    meta = build_review_queue_metadata(cast(CommerceAIState, data))
    data["review_category"] = meta["review_category"]
    data["review_priority"] = meta["review_priority"]
    data["review_reason"] = meta["review_reason"]
    return cast(CommerceAIState, data)


def build_qa_attention_summary(state: CommerceAIState) -> dict[str, Any]:
    """Operator-facing QA rollup for API responses (no draft text or secrets)."""
    data = _state_dict(state)
    qa_issues = list(data.get("qa_issues") or [])
    qa_warnings = list(data.get("qa_warnings") or [])
    return {
        "requires_attention": bool(data.get("qa_requires_human_attention")) or bool(qa_issues),
        "qa_passed": data.get("qa_passed"),
        "issue_count": len(qa_issues),
        "warning_count": len(qa_warnings),
        "top_issues": qa_issues[:_QA_SUMMARY_TOP_N],
        "top_warnings": qa_warnings[:_QA_SUMMARY_TOP_N],
        "summary": data.get("qa_summary"),
        "route_label": data.get("route_label"),
    }


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


def _parse_rag_documents(raw: Any) -> list[RAGDocument]:
    """Coerce ``retrieved_context['rag_documents']`` entries to ``RAGDocument``."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[RAGDocument] = []
    for item in raw:
        if isinstance(item, RAGDocument):
            out.append(item)
            continue
        if isinstance(item, dict):
            try:
                out.append(RAGDocument.model_validate(item))
            except Exception:
                continue
    return out


def _combined_ticket_text(
    *,
    ticket_subject: str,
    ticket_body: str,
    user_input: str,
) -> str:
    return f"{ticket_subject}\n{ticket_body}\n{user_input}".lower()


def _ticket_intent_agent(
    *,
    ticket_subject: str,
    ticket_body: str,
    user_input: str,
) -> TicketIntentResult:
    """Rule-based intent normalization (placeholder for future LLM classifier)."""
    text = _combined_ticket_text(
        ticket_subject=ticket_subject,
        ticket_body=ticket_body,
        user_input=user_input,
    )
    if any(kw in text for kw in _ESCALATION_KEYWORDS):
        return TicketIntentResult(detected_intent="escalation_sla")
    if any(kw in text for kw in _BILLING_KEYWORDS):
        return TicketIntentResult(detected_intent="billing_discrepancy")
    return TicketIntentResult(detected_intent="billing_discrepancy")


def _policy_grounding_agent(
    *,
    retrieved_context: dict[str, Any],
    rag_documents: list[RAGDocument],
) -> PolicyGroundingResult:
    """Summarize existing retrieved context; does not call retrieval."""
    policy_summary = _policy_summary_text(retrieved_context)
    rag_count = len(rag_documents)
    grounding_sources = sorted({doc.source_type for doc in rag_documents})

    parts: list[str] = []
    if policy_summary:
        parts.append(f"policy: {policy_summary[:120]}")
    if rag_count:
        parts.append(f"rag_documents={rag_count}")
    if grounding_sources:
        parts.append(f"sources={','.join(grounding_sources)}")
    grounding_summary = "; ".join(parts) if parts else "no_policy_or_rag_context"

    return PolicyGroundingResult(
        grounding_summary=grounding_summary,
        grounding_sources=grounding_sources,
        rag_document_count=rag_count,
        policy_summary=policy_summary,
    )


def _drafting_agent(
    *,
    ticket_subject: str,
    ticket_body: str,
    vendor_name: str,
    policy_summary: str,
    previous_cases_count: int,
    rag_documents: list[RAGDocument],
) -> DraftingResult:
    """Build prompt and call LLM (single draft specialist)."""
    messages = build_vendor_ticket_prompt(
        ticket_subject=ticket_subject,
        ticket_body=ticket_body,
        vendor_name=vendor_name,
        policy_summary=policy_summary,
        previous_cases_count=previous_cases_count,
        rag_documents=rag_documents,
    )
    settings = get_settings()
    response = generate_text(
        messages,
        provider=settings.llm_provider,
        model=settings.llm_model,
    )
    return DraftingResult(
        draft_response=response.content,
        llm_provider=response.provider,
        llm_model=response.model,
        llm_metadata=response.metadata,
    )


def _qa_check_agent(
    *,
    draft_response: str,
    grounding: PolicyGroundingResult,
    intent: TicketIntentResult,
) -> QACheckResult:
    """Rule-based post-draft checks; warnings do not fail qa_passed."""
    draft = draft_response.strip()
    issues: list[str] = []
    warnings: list[str] = []

    if not draft:
        issues.append("empty_draft")

    for term in _RISKY_PROMISE_TERMS:
        if term in draft:
            issues.append(f"risky_promise_language:{term}")

    for term in _UNPROFESSIONAL_TERMS:
        if term in draft:
            issues.append(f"unprofessional_tone:{term}")

    if intent.detected_intent == "billing_discrepancy":
        if not any(term in draft for term in _BILLING_CLARIFICATION_TERMS):
            warnings.append("billing_missing_clarification_request")

    if grounding.grounding_summary == "no_policy_or_rag_context":
        warnings.append("weak_policy_grounding")
    elif grounding.rag_document_count == 0 and not grounding.policy_summary:
        warnings.append("weak_policy_grounding")

    qa_passed = len(issues) == 0
    if issues:
        qa_summary = f"failed:{len(issues)} issue(s), {len(warnings)} warning(s)"
    elif warnings:
        qa_summary = f"passed_with_warnings:{len(warnings)}"
    else:
        qa_summary = "passed"

    return QACheckResult(
        qa_passed=qa_passed,
        qa_issues=issues,
        qa_warnings=warnings,
        qa_summary=qa_summary,
    )


def _is_style_only_grounding(grounding: PolicyGroundingResult) -> bool:
    sources = grounding.grounding_sources
    return bool(sources) and set(sources) == {"style_guide"}


def _supervisor_router_agent(
    *,
    intent: TicketIntentResult,
    grounding: PolicyGroundingResult,
    qa: QACheckResult,
) -> SupervisorRoutingResult:
    """Classify internal operational route; human review always required."""
    reasons: list[str] = []

    if qa.qa_issues:
        reasons.append("qa_issues_present")
        return SupervisorRoutingResult(
            route_label="qa_attention",
            recommended_action="review_qa_issues_before_reply",
            routing_reasons=reasons,
        )

    if intent.detected_intent == "escalation_sla":
        reasons.append("intent_escalation_sla")
        return SupervisorRoutingResult(
            route_label="escalation_review",
            recommended_action="review_escalation_context",
            routing_reasons=reasons,
        )

    if intent.detected_intent == "billing_discrepancy":
        reasons.append("intent_billing_discrepancy")
        return SupervisorRoutingResult(
            route_label="billing_review",
            recommended_action="review_billing_reply_draft",
            routing_reasons=reasons,
        )

    if _is_style_only_grounding(grounding):
        reasons.append("grounding_style_guide_only")
        return SupervisorRoutingResult(
            route_label="style_guidance",
            recommended_action="review_tone_guidance",
            routing_reasons=reasons,
        )

    reasons.append("default_vendor_support")
    return SupervisorRoutingResult(
        route_label="general_vendor_support",
        recommended_action="review_ticket_reply_draft",
        routing_reasons=reasons,
    )


def _risk_review_agent(
    *,
    detected_intent: str,
    qa_result: QACheckResult | None = None,
    routing: SupervisorRoutingResult | None = None,
) -> RiskReviewResult:
    """Deterministic risk/confidence; adjusts slightly when QA issues exist."""
    _ = detected_intent
    _ = routing
    confidence = 0.82
    risk = 0.34
    if qa_result is not None and qa_result.qa_issues:
        confidence = min(confidence, 0.65)
        risk = max(risk, 0.65)
    return RiskReviewResult(confidence_score=confidence, risk_score=risk)


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


def _build_vendor_ticket_evidence(
    *,
    ticket_subject: str,
    vendor_name: str,
    grounding: PolicyGroundingResult,
    drafting: DraftingResult,
    qa: QACheckResult,
    routing: SupervisorRoutingResult,
) -> list[str]:
    """Assemble consistent evidence lines for specialist output."""
    evidence_lines: list[str] = [
        f"ticket_subject={ticket_subject}",
        f"vendor_name={vendor_name}",
        "policy_context_used=true",
        f"rag_document_count={grounding.rag_document_count}",
        f"qa_passed={'true' if qa.qa_passed else 'false'}",
        f"qa_issue_count={len(qa.qa_issues)}",
        f"qa_warning_count={len(qa.qa_warnings)}",
        f"route_label={routing.route_label}",
    ]
    if routing.routing_reasons:
        evidence_lines.append(f"route_reasons={','.join(routing.routing_reasons)}")
    if grounding.grounding_sources:
        evidence_lines.append(f"rag_sources={','.join(grounding.grounding_sources)}")
    if routing.route_label == "qa_attention":
        evidence_lines.append("qa_attention_required=true")
    evidence_lines.extend(
        _llm_evidence(
            LLMResponse(
                content=drafting.draft_response,
                provider=drafting.llm_provider,
                model=drafting.llm_model,
                metadata=drafting.llm_metadata,
            )
        )
    )
    return evidence_lines


def vendor_ticket_node(state: CommerceAIState) -> CommerceAIState:
    """Draft vendor reply text through internal specialist agents; does not send."""
    data = _state_dict(state)
    ctx = data.get("retrieved_context") or {}
    ticket = ctx.get("ticket") or {}
    vendor = ctx.get("vendor") or {}

    ticket_subject = str(ticket.get("subject") or "بدون عنوان")
    ticket_body = str(ticket.get("body") or "")
    vendor_name = str(vendor.get("name") or "فروشنده")
    user_input = str(data.get("user_input") or "")

    previous_cases = ctx.get("previous_cases") or []
    previous_cases_count = len(previous_cases) if isinstance(previous_cases, list) else 0
    rag_documents = _parse_rag_documents(ctx.get("rag_documents"))

    intent = _ticket_intent_agent(
        ticket_subject=ticket_subject,
        ticket_body=ticket_body,
        user_input=user_input,
    )
    grounding = _policy_grounding_agent(
        retrieved_context=ctx,
        rag_documents=rag_documents,
    )
    draft = _drafting_agent(
        ticket_subject=ticket_subject,
        ticket_body=ticket_body,
        vendor_name=vendor_name,
        policy_summary=grounding.policy_summary,
        previous_cases_count=previous_cases_count,
        rag_documents=rag_documents,
    )
    qa = _qa_check_agent(
        draft_response=draft.draft_response,
        grounding=grounding,
        intent=intent,
    )
    routing = _supervisor_router_agent(intent=intent, grounding=grounding, qa=qa)
    risk = _risk_review_agent(
        detected_intent=intent.detected_intent,
        qa_result=qa,
        routing=routing,
    )
    evidence_lines = _build_vendor_ticket_evidence(
        ticket_subject=ticket_subject,
        vendor_name=vendor_name,
        grounding=grounding,
        drafting=draft,
        qa=qa,
        routing=routing,
    )

    data["specialist_output"] = {
        "draft_response": draft.draft_response,
        "detected_intent": intent.detected_intent,
        "confidence_score": risk.confidence_score,
        "risk_score": risk.risk_score,
        "evidence": evidence_lines,
        "llm_provider": draft.llm_provider,
        "llm_model": draft.llm_model,
        "llm_metadata": draft.llm_metadata,
        "qa_passed": qa.qa_passed,
        "qa_issues": qa.qa_issues,
        "qa_warnings": qa.qa_warnings,
        "qa_summary": qa.qa_summary,
        "route_label": routing.route_label,
        "routing_reasons": routing.routing_reasons,
        "recommended_action": routing.recommended_action,
    }

    data["detected_intent"] = intent.detected_intent
    data["grounding_summary"] = grounding.grounding_summary
    data["grounding_sources"] = grounding.grounding_sources
    data["qa_passed"] = qa.qa_passed
    data["qa_issues"] = qa.qa_issues
    data["qa_warnings"] = qa.qa_warnings
    data["qa_summary"] = qa.qa_summary
    data["route_label"] = routing.route_label
    data["routing_reasons"] = routing.routing_reasons
    data["specialist_recommended_action"] = routing.recommended_action
    data["qa_requires_human_attention"] = False

    data["confidence_score"] = risk.confidence_score
    data["risk_score"] = risk.risk_score

    data["final_response"] = (
        "پیش‌نویس پاسخ برای تیکت فروشنده آماده شد و برای جلوگیری از ارسال خودکار، "
        "نیازمند تأیید انسانی است. لطفاً متن را در کنسول ادمین بازبینی و پس از تأیید ارسال کنید."
    )

    audit_metadata: dict[str, Any] = {
        "detected_intent": data["detected_intent"],
        "llm_provider": draft.llm_provider,
        "llm_model": draft.llm_model,
        "rag_document_count": grounding.rag_document_count,
        "grounding_summary": data["grounding_summary"],
        "qa_passed": data["qa_passed"],
        "qa_issue_count": len(data["qa_issues"]),
        "qa_warning_count": len(data["qa_warnings"]),
        "route_label": data["route_label"],
        "routing_reason_count": len(data["routing_reasons"]),
        "specialist_recommended_action": data["specialist_recommended_action"],
    }
    response_id = draft.llm_metadata.get("response_id")
    if response_id:
        audit_metadata["llm_response_id"] = response_id

    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name="vendor_ticket_node",
        message="Generated vendor ticket draft via LLM layer (not sent).",
        metadata=audit_metadata,
    )
    return cast(CommerceAIState, data)

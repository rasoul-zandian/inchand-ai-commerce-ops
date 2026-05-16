"""Controlled operator redraft execution (single draft regeneration; no send/approve)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm import generate_text
from app.nodes.vendor_ticket import (
    PolicyGroundingResult,
    TicketIntentResult,
    _parse_rag_documents,
    _policy_summary_text,
    _qa_check_agent,
)
from app.prompts.vendor_ticket import build_controlled_redraft_prompt
from app.rag.types import RAGDocument
from app.review_queue.redraft_models import RedraftResult, build_redraft_result


class ControlledRedraftValidationError(ValueError):
    """Raised when redraft input snapshot or operator guidance is invalid."""


class ControlledRedraftExecutionError(RuntimeError):
    """Raised when controlled redraft generation fails."""


class ControlledRedraftResult(BaseModel):
    redraft_response: str
    redraft_summary: dict[str, Any] = Field(default_factory=dict)
    redraft_result: RedraftResult | None = None


@dataclass(frozen=True)
class _RedraftExecutionContext:
    user_input: str
    previous_draft: str
    ticket_subject: str
    ticket_body: str
    vendor_name: str
    policy_summary: str
    detected_intent: str
    grounding_summary: str
    rag_documents: list[RAGDocument]
    previous_cases_count: int


def validate_workflow_state_snapshot(snapshot: dict[str, Any]) -> _RedraftExecutionContext:
    """Validate compact workflow snapshot required for controlled redraft."""
    if not snapshot:
        raise ControlledRedraftValidationError(
            "Controlled redraft requires workflow_state_snapshot in this version."
        )
    user_input = snapshot.get("user_input")
    if not isinstance(user_input, str) or not user_input.strip():
        raise ControlledRedraftValidationError(
            "workflow_state_snapshot.user_input is required for controlled redraft."
        )
    specialist_output = snapshot.get("specialist_output")
    if not isinstance(specialist_output, dict):
        raise ControlledRedraftValidationError(
            "workflow_state_snapshot.specialist_output.draft_response is required."
        )
    previous_draft = specialist_output.get("draft_response")
    if not isinstance(previous_draft, str) or not previous_draft.strip():
        raise ControlledRedraftValidationError(
            "workflow_state_snapshot.specialist_output.draft_response is required."
        )

    retrieved_context = snapshot.get("retrieved_context")
    ctx = retrieved_context if isinstance(retrieved_context, dict) else {}
    ticket = ctx.get("ticket") if isinstance(ctx.get("ticket"), dict) else {}
    vendor = ctx.get("vendor") if isinstance(ctx.get("vendor"), dict) else {}
    ticket_subject = str(ticket.get("subject") or "بدون عنوان")
    ticket_body = str(ticket.get("body") or user_input.strip())
    vendor_name = str(vendor.get("name") or "فروشنده")
    policy_summary = _policy_summary_text(ctx)
    grounding_summary = snapshot.get("grounding_summary")
    if not isinstance(grounding_summary, str) or not grounding_summary.strip():
        grounding_summary = policy_summary or "no_policy_or_rag_context"
    detected_intent = snapshot.get("detected_intent")
    if not isinstance(detected_intent, str) or not detected_intent.strip():
        detected_intent = str(specialist_output.get("detected_intent") or "general_inquiry")
    previous_cases = ctx.get("previous_cases")
    previous_cases_count = len(previous_cases) if isinstance(previous_cases, list) else 0
    rag_documents = _parse_rag_documents(ctx.get("rag_documents"))

    return _RedraftExecutionContext(
        user_input=user_input.strip(),
        previous_draft=previous_draft.strip(),
        ticket_subject=ticket_subject,
        ticket_body=ticket_body,
        vendor_name=vendor_name,
        policy_summary=policy_summary,
        detected_intent=detected_intent.strip(),
        grounding_summary=grounding_summary.strip(),
        rag_documents=rag_documents,
        previous_cases_count=previous_cases_count,
    )


def execute_controlled_redraft(
    *,
    operator_comment: str,
    workflow_state_snapshot: dict[str, Any],
    review_item_id: str,
    action_id: str,
    operator_id: str | None,
) -> ControlledRedraftResult:
    """Regenerate draft from operator guidance; does not mutate workflow state or send."""
    comment = operator_comment.strip()
    if not comment:
        raise ControlledRedraftValidationError(
            "Controlled redraft execution requires a non-empty operator comment."
        )

    ctx = validate_workflow_state_snapshot(workflow_state_snapshot)
    messages = build_controlled_redraft_prompt(
        ticket_subject=ctx.ticket_subject,
        ticket_body=ctx.ticket_body,
        vendor_name=ctx.vendor_name,
        policy_summary=ctx.policy_summary,
        previous_draft=ctx.previous_draft,
        operator_comment=comment,
        rag_documents=ctx.rag_documents,
    )
    settings = get_settings()
    try:
        response = generate_text(
            messages,
            provider=settings.llm_provider,
            model=settings.llm_model,
        )
    except Exception as exc:
        raise ControlledRedraftExecutionError("Controlled redraft generation failed.") from exc

    redraft_text = (response.content or "").strip()
    if not redraft_text:
        raise ControlledRedraftExecutionError("Controlled redraft returned empty draft text.")

    intent = TicketIntentResult(detected_intent=ctx.detected_intent)
    grounding = PolicyGroundingResult(
        grounding_summary=ctx.grounding_summary,
        grounding_sources=sorted({doc.source_type for doc in ctx.rag_documents}),
        rag_document_count=len(ctx.rag_documents),
        policy_summary=ctx.policy_summary,
    )
    qa = _qa_check_agent(
        draft_response=redraft_text,
        grounding=grounding,
        intent=intent,
    )

    redraft_artifact = build_redraft_result(
        source_action_id=action_id,
        review_item_id=review_item_id,
        previous_draft=ctx.previous_draft,
        redraft_text=redraft_text,
        operator_guidance=comment,
        qa_passed=qa.qa_passed,
        qa_issue_count=len(qa.qa_issues),
        llm_provider=response.provider,
        llm_model=response.model,
    )

    return ControlledRedraftResult(
        redraft_response=redraft_text,
        redraft_summary={
            "review_item_id": review_item_id,
            "action_id": action_id,
            "redraft_id": redraft_artifact.redraft_id,
            "operator_id": operator_id,
            "used_operator_comment": True,
            "requires_human_approval": True,
            "llm_provider": response.provider,
            "llm_model": response.model,
            "qa_passed": qa.qa_passed,
            "qa_issue_count": len(qa.qa_issues),
            "previous_draft_hash": redraft_artifact.previous_draft_hash,
            "redraft_hash": redraft_artifact.redraft_hash,
        },
        redraft_result=redraft_artifact,
    )

"""Unit tests for internal multi-agent vendor ticket specialists (offline-safe)."""

from __future__ import annotations

from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.common import retrieve_context
from app.nodes.vendor_ticket import (
    PolicyGroundingResult,
    QACheckResult,
    TicketIntentResult,
    _build_vendor_ticket_evidence,
    _drafting_agent,
    _policy_grounding_agent,
    _qa_check_agent,
    _risk_review_agent,
    _supervisor_router_agent,
    _ticket_intent_agent,
    vendor_ticket_node,
)

from tests.test_vendor_ticket_workflow import make_base_state


def test_ticket_intent_agent_billing_requires_finance_keywords() -> None:
    result = _ticket_intent_agent(
        ticket_subject="مشکل در تسویه فروش هفتگی",
        ticket_body="مبلغ واریز شده با فاکتور مغایرت دارد.",
        user_input="سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
    )
    assert result.detected_intent == "billing_discrepancy"


def test_ticket_intent_agent_generic_default_not_billing() -> None:
    result = _ticket_intent_agent(
        ticket_subject="سلام",
        ticket_body="وضعیت سفارش",
        user_input="لطفاً بررسی کنید",
    )
    assert result.detected_intent == "general_vendor_support"


def test_policy_grounding_agent_counts_rag_and_sources() -> None:
    state = make_base_state(
        user_input="سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-grounding-001",
    )
    state = retrieve_context(state)
    ctx = state["retrieved_context"]
    from app.nodes.vendor_ticket import _parse_rag_documents

    rag_documents = _parse_rag_documents(ctx.get("rag_documents"))
    grounding = _policy_grounding_agent(retrieved_context=ctx, rag_documents=rag_documents)

    assert grounding.rag_document_count == 5
    assert grounding.grounding_sources == ["approved_pattern", "policy", "style_guide"]
    assert "rag_documents=5" in grounding.grounding_summary
    assert "sources=approved_pattern,policy,style_guide" in grounding.grounding_summary


def test_evidence_builder_includes_rag_fields() -> None:
    state = make_base_state(ticket_id="t-evidence-001")
    state = retrieve_context(state)
    ctx = state["retrieved_context"]
    from app.nodes.vendor_ticket import _parse_rag_documents

    rag_documents = _parse_rag_documents(ctx.get("rag_documents"))
    grounding = _policy_grounding_agent(retrieved_context=ctx, rag_documents=rag_documents)
    draft = _drafting_agent(
        ticket_subject=str(ctx["ticket"]["subject"]),
        ticket_body=str(ctx["ticket"]["body"]),
        vendor_name=str(ctx["vendor"]["name"]),
        policy_summary=grounding.policy_summary,
        previous_cases_count=len(ctx.get("previous_cases") or []),
        rag_documents=rag_documents,
    )
    intent = _ticket_intent_agent(
        ticket_subject=str(ctx["ticket"]["subject"]),
        ticket_body=str(ctx["ticket"]["body"]),
        user_input=state["user_input"],
    )
    qa = _qa_check_agent(
        draft_response=draft.draft_response,
        grounding=grounding,
        intent=intent,
    )
    routing = _supervisor_router_agent(intent=intent, grounding=grounding, qa=qa)
    evidence = _build_vendor_ticket_evidence(
        ticket_subject=str(ctx["ticket"]["subject"]),
        vendor_name=str(ctx["vendor"]["name"]),
        grounding=grounding,
        drafting=draft,
        qa=qa,
        routing=routing,
    )
    assert any(line.startswith("rag_document_count=") for line in evidence)
    assert any(line.startswith("rag_sources=") for line in evidence)
    assert any(line.startswith("qa_passed=") for line in evidence)
    assert any(line.startswith("qa_issue_count=") for line in evidence)
    assert any("llm_provider=mock" in line for line in evidence)


def test_vendor_ticket_node_populates_structured_state_fields() -> None:
    state = make_base_state(
        user_input="سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-state-fields-001",
    )
    state = retrieve_context(state)
    state = vendor_ticket_node(state)

    specialist = state["specialist_output"]
    assert state["detected_intent"] == specialist["detected_intent"] == "billing_discrepancy"
    assert state["grounding_summary"]
    assert "rag_documents=5" in state["grounding_summary"]
    assert state["grounding_sources"] == ["approved_pattern", "policy", "style_guide"]
    assert state["qa_passed"] is specialist["qa_passed"]
    assert state["qa_issues"] == specialist["qa_issues"]
    assert state["qa_warnings"] == specialist["qa_warnings"]
    assert state["qa_summary"] == specialist["qa_summary"]
    assert state["route_label"] == specialist["route_label"] == "billing_review"
    assert state["routing_reasons"] == specialist["routing_reasons"]
    assert (
        state["specialist_recommended_action"]
        == specialist["recommended_action"]
        == "review_billing_reply_draft"
    )


def test_vendor_ticket_node_output_shape_unchanged() -> None:
    state = make_base_state(
        user_input="سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-shape-001",
    )
    state = retrieve_context(state)
    state = vendor_ticket_node(state)

    specialist = state["specialist_output"]
    assert set(specialist.keys()) >= {
        "draft_response",
        "detected_intent",
        "confidence_score",
        "risk_score",
        "evidence",
        "llm_provider",
        "llm_model",
        "llm_metadata",
        "qa_passed",
        "qa_issues",
        "qa_warnings",
        "qa_summary",
        "route_label",
        "routing_reasons",
        "recommended_action",
    }
    assert specialist["detected_intent"] == "billing_discrepancy"
    assert specialist["route_label"] == "billing_review"
    assert specialist["recommended_action"] == "review_billing_reply_draft"
    assert specialist["confidence_score"] == 0.82
    assert specialist["risk_score"] == 0.34
    assert state["confidence_score"] == 0.82
    assert state["risk_score"] == 0.34
    assert state["final_response"]


def test_vendor_ticket_node_audit_metadata() -> None:
    state = make_base_state(ticket_id="t-audit-001")
    state = retrieve_context(state)
    state = vendor_ticket_node(state)

    vt_audit = next(
        entry for entry in state["audit_log"] if entry.node_name == "vendor_ticket_node"
    )
    assert vt_audit.metadata.get("detected_intent") == "billing_discrepancy"
    assert vt_audit.metadata.get("rag_document_count") == 5
    assert vt_audit.metadata.get("llm_provider") == "mock"
    assert "grounding_summary" in vt_audit.metadata
    assert "qa_passed" in vt_audit.metadata
    assert "qa_issue_count" in vt_audit.metadata
    assert "qa_warning_count" in vt_audit.metadata
    assert vt_audit.metadata.get("route_label") == "billing_review"
    assert vt_audit.metadata.get("specialist_recommended_action") == "review_billing_reply_draft"


def test_supervisor_routes_qa_issues_to_qa_attention() -> None:
    intent = TicketIntentResult(detected_intent="billing_discrepancy")
    grounding = PolicyGroundingResult(grounding_summary="policy: x", rag_document_count=1)
    qa = QACheckResult(
        qa_passed=False,
        qa_issues=["risky_promise_language:مبلغ قطعی"],
        qa_summary="failed:1 issue(s), 0 warning(s)",
    )
    routing = _supervisor_router_agent(intent=intent, grounding=grounding, qa=qa)
    assert routing.route_label == "qa_attention"
    assert routing.recommended_action == "review_qa_issues_before_reply"
    assert "qa_issues_present" in routing.routing_reasons
    assert routing.requires_human_review is True


def test_supervisor_routes_billing_intent() -> None:
    intent = TicketIntentResult(detected_intent="billing_discrepancy")
    grounding = PolicyGroundingResult(
        grounding_summary="policy: x",
        grounding_sources=["policy", "style_guide"],
        rag_document_count=2,
    )
    qa = QACheckResult(qa_passed=True, qa_summary="passed")
    routing = _supervisor_router_agent(intent=intent, grounding=grounding, qa=qa)
    assert routing.route_label == "billing_review"
    assert routing.recommended_action == "review_billing_reply_draft"


def test_supervisor_routes_escalation_intent() -> None:
    intent = TicketIntentResult(detected_intent="escalation_sla")
    grounding = PolicyGroundingResult(grounding_summary="policy: x", rag_document_count=1)
    qa = QACheckResult(qa_passed=True, qa_summary="passed")
    routing = _supervisor_router_agent(intent=intent, grounding=grounding, qa=qa)
    assert routing.route_label == "escalation_review"
    assert routing.recommended_action == "review_escalation_context"


def test_supervisor_routes_style_only_grounding() -> None:
    intent = TicketIntentResult(detected_intent="general_inquiry")
    grounding = PolicyGroundingResult(
        grounding_summary="sources=style_guide",
        grounding_sources=["style_guide"],
        rag_document_count=1,
    )
    qa = QACheckResult(qa_passed=True, qa_summary="passed")
    routing = _supervisor_router_agent(intent=intent, grounding=grounding, qa=qa)
    assert routing.route_label == "style_guidance"
    assert routing.recommended_action == "review_tone_guidance"


def test_qa_check_agent_passes_safe_mock_draft() -> None:
    state = make_base_state(ticket_id="t-qa-pass-001")
    state = retrieve_context(state)
    ctx = state["retrieved_context"]
    from app.nodes.vendor_ticket import _parse_rag_documents

    rag_documents = _parse_rag_documents(ctx.get("rag_documents"))
    grounding = _policy_grounding_agent(retrieved_context=ctx, rag_documents=rag_documents)
    draft = _drafting_agent(
        ticket_subject=str(ctx["ticket"]["subject"]),
        ticket_body=str(ctx["ticket"]["body"]),
        vendor_name=str(ctx["vendor"]["name"]),
        policy_summary=grounding.policy_summary,
        previous_cases_count=len(ctx.get("previous_cases") or []),
        rag_documents=rag_documents,
    )
    intent = TicketIntentResult(detected_intent="billing_discrepancy")
    qa = _qa_check_agent(
        draft_response=draft.draft_response,
        grounding=grounding,
        intent=intent,
    )
    assert qa.qa_passed is True
    assert not qa.qa_issues
    assert "billing_missing_clarification_request" in qa.qa_warnings


def test_qa_check_agent_flags_risky_refund_language() -> None:
    intent = TicketIntentResult(detected_intent="billing_discrepancy")
    grounding = PolicyGroundingResult(
        grounding_summary="policy: test",
        rag_document_count=1,
        policy_summary="test",
    )
    qa = _qa_check_agent(
        draft_response="مبلغ قطعی فردا واریز می‌شود.",
        grounding=grounding,
        intent=intent,
    )
    assert qa.qa_passed is False
    assert any("risky_promise_language" in issue for issue in qa.qa_issues)


def test_qa_check_billing_without_clarification_warning_only() -> None:
    intent = TicketIntentResult(detected_intent="billing_discrepancy")
    grounding = PolicyGroundingResult(
        grounding_summary="policy: test",
        rag_document_count=2,
        policy_summary="test",
    )
    qa = _qa_check_agent(
        draft_response="سلام، موضوع را بررسی می‌کنیم.",
        grounding=grounding,
        intent=intent,
    )
    assert qa.qa_passed is True
    assert qa.qa_warnings == ["billing_missing_clarification_request"]


def test_risk_review_adjusts_when_qa_has_issues() -> None:
    qa_failed = QACheckResult(
        qa_passed=False,
        qa_issues=["risky_promise_language:مبلغ قطعی"],
        qa_summary="failed:1 issue(s), 0 warning(s)",
    )
    risk = _risk_review_agent(detected_intent="billing_discrepancy", qa_result=qa_failed)
    assert risk.risk_score == 0.65
    assert risk.confidence_score == 0.65

    qa_ok = QACheckResult(qa_passed=True, qa_warnings=["billing_missing_clarification_request"])
    risk_ok = _risk_review_agent(detected_intent="billing_discrepancy", qa_result=qa_ok)
    assert risk_ok.risk_score == 0.34
    assert risk_ok.confidence_score == 0.82


def test_vendor_ticket_node_qa_fields_and_evidence() -> None:
    state = make_base_state(ticket_id="t-qa-fields-001")
    state = retrieve_context(state)
    state = vendor_ticket_node(state)
    specialist = state["specialist_output"]
    assert "qa_passed" in specialist
    assert isinstance(specialist["qa_issues"], list)
    assert isinstance(specialist["qa_warnings"], list)
    assert specialist["qa_summary"]
    assert specialist["route_label"] == "billing_review"
    evidence = specialist["evidence"]
    assert any(line == "qa_passed=true" for line in evidence)
    assert any(line.startswith("qa_issue_count=") for line in evidence)
    assert any(line.startswith("route_label=") for line in evidence)


def test_top_level_recommended_action_unchanged_by_supervisor() -> None:
    state = run_vendor_ticket_demo(
        "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-route-top-001",
    )
    assert state["specialist_output"]["route_label"] == "billing_review"
    assert state["specialist_output"]["recommended_action"] == "review_billing_reply_draft"
    assert state["recommended_action"] == "review_ticket_reply_draft"
    assert state["human_approval_required"] is True


def test_risk_review_agent_deterministic_without_qa_issues() -> None:
    risk = _risk_review_agent(detected_intent="billing_discrepancy")
    assert risk.confidence_score == 0.82
    assert risk.risk_score == 0.34

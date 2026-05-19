"""Tests for feature-flagged vendor-ticket AI assist shadow LangGraph node."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from app.config import get_settings
from app.nodes.vendor_ticket_ai_assist_shadow import vendor_ticket_ai_assist_shadow
from app.workflows.vendor_ticket_ai_assist_models import (
    VendorTicketAIAssistActionType,
    VendorTicketAIAssistResult,
)

from tests.test_vendor_ticket_workflow import make_base_state


def _enable_assist_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setenv(
        "VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED",
        "true" if enabled else "false",
    )
    get_settings.cache_clear()


def test_settings_default_vendor_ticket_ai_assist_shadow_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED", raising=False)
    get_settings.cache_clear()
    assert get_settings().vendor_ticket_ai_assist_shadow_enabled is False


def test_flag_false_leaves_state_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_assist_flag(monkeypatch, False)
    state = make_base_state()
    state["ticket_label"] = "fund"
    state["route_label"] = "billing_review"
    before = dict(state)
    calls: list[str] = []

    def fake_evaluate(_payload: object) -> VendorTicketAIAssistResult:
        calls.append("evaluate")
        raise AssertionError("evaluator should not run")

    monkeypatch.setattr(
        "app.nodes.vendor_ticket_ai_assist_shadow.evaluate_vendor_ticket_ai_assist_shadow",
        fake_evaluate,
    )
    out = vendor_ticket_ai_assist_shadow(state)
    assert calls == []
    assert out.get("ai_assist_shadow_generated") is None
    assert before["user_input"] == out["user_input"]


def test_flag_true_writes_assist_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_assist_flag(monkeypatch, True)
    state = make_base_state()
    state["ticket_label"] = "complaint"
    state["route_label"] = "escalation_review"
    state["review_priority"] = "HIGH"
    state["retrieval_gate_decision"] = "allow"
    state["retrieval_result_count"] = 5
    state["retrieval_activated"] = False

    def fake_evaluate(_payload: object) -> VendorTicketAIAssistResult:
        return VendorTicketAIAssistResult(
            suggested_priority="high",
            escalation_recommended=True,
            duplicate_possible=True,
            suggested_action=VendorTicketAIAssistActionType.ESCALATE,
            retrieval_summary_available=True,
            confidence_band="high",
            assist_generated_at=VendorTicketAIAssistResult.utc_timestamp(),
        )

    monkeypatch.setattr(
        "app.nodes.vendor_ticket_ai_assist_shadow.evaluate_vendor_ticket_ai_assist_shadow",
        fake_evaluate,
    )
    out = vendor_ticket_ai_assist_shadow(state)
    assert out["ai_assist_shadow_generated"] is True
    assert out["ai_assist_suggested_priority"] == "high"
    assert out["ai_assist_escalation_recommended"] is True
    assert out["ai_assist_suggested_action"] == "escalate"
    assert out["ai_assist_human_review_required"] is True
    assert out["ai_assist_shadow_only"] is True
    assert "suggestions" not in out
    assert "user_input" not in str(out.get("audit_log", []))


def test_evaluator_rejection_is_safe_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_assist_flag(monkeypatch, True)
    state = make_base_state()
    state["retrieval_activated"] = True

    out = vendor_ticket_ai_assist_shadow(state)
    assert out["ai_assist_shadow_generated"] is False
    assert out["ai_assist_human_review_required"] is True
    assert any(
        e.tool_name == "vendor_ticket_ai_assist_shadow"
        and e.error_type == "ai_assist_shadow_rejected"
        for e in out["errors"]
    )


def test_evaluator_failure_is_safe_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_assist_flag(monkeypatch, True)
    state = make_base_state()
    state["ticket_label"] = "fund"

    def fail_evaluate(_payload: object) -> VendorTicketAIAssistResult:
        raise RuntimeError("injected assist failure")

    monkeypatch.setattr(
        "app.nodes.vendor_ticket_ai_assist_shadow.evaluate_vendor_ticket_ai_assist_shadow",
        fail_evaluate,
    )
    out = vendor_ticket_ai_assist_shadow(state)
    assert out["ai_assist_shadow_generated"] is False
    assert any(
        e.tool_name == "vendor_ticket_ai_assist_shadow"
        and e.error_type == "ai_assist_shadow_failed"
        for e in out["errors"]
    )


def test_vendor_ticket_node_source_does_not_reference_ai_assist_fields() -> None:
    path = Path(__file__).resolve().parents[1] / "app" / "nodes" / "vendor_ticket.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    joined = ast.dump(tree)
    assert "ai_assist_shadow_generated" not in joined
    assert "ai_assist_suggested_action" not in joined
    assert "ai_assist_escalation_recommended" not in joined


def test_main_graph_wires_assist_after_sandbox_retrieval() -> None:
    path = Path(__file__).resolve().parents[1] / "app" / "graph" / "main_graph.py"
    text = path.read_text(encoding="utf-8")
    assert "vendor_ticket_ai_assist_shadow" in text
    assert 'add_edge("sandbox_retrieve_pilot_shadow", "vendor_ticket_ai_assist_shadow")' in text
    assert 'add_edge("vendor_ticket_ai_assist_shadow", "retrieve_context")' in text


def test_vendor_ticket_workflow_unchanged_with_assist_flag_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_assist_flag(monkeypatch, False)
    monkeypatch.setenv("LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED", "false")
    get_settings.cache_clear()
    from app.nodes.common import normalize_request, retrieve_context, route_workflow
    from app.nodes.sandbox_retrieval_shadow import sandbox_retrieve_pilot_shadow
    from app.nodes.vendor_ticket import vendor_ticket_node as vt_node

    state = make_base_state(user_input="سلام، تسویه این هفته با فاکتور هم‌خوان نیست.")
    state = normalize_request(state)
    state = route_workflow(state)
    state = sandbox_retrieve_pilot_shadow(state)
    state = vendor_ticket_ai_assist_shadow(state)
    assert state.get("ai_assist_shadow_generated") is None
    state = retrieve_context(state)
    state = vt_node(state)
    assert state["specialist_output"].get("draft_response")

"""Tests for sandbox agentic LangGraph workflow (mock LLM; no network)."""

from __future__ import annotations

import json
from pathlib import Path

from app.agentic_sandbox.agentic_graph import (
    NODE_ORDER,
    build_agentic_sandbox_graph,
    build_safe_run_report,
    initial_state_from_ticket,
    run_agentic_sandbox_workflow,
)
from app.agentic_sandbox.agentic_nodes import safety_gate_node
from app.agentic_sandbox.agentic_state import initial_agentic_sandbox_state
from app.evals.actionability_validation import draft_claims_fake_operational_execution
from app.llm.types import LLMMessage, LLMResponse
from app.operator_console.console_models import OperatorTicket


def _mock_generate(messages: list[LLMMessage], *, provider: str, model: str) -> LLMResponse:
    combined = "\n".join(message.content for message in messages)
    assert "latest_vendor_message" not in combined
    assert "recent_context_preview" not in combined
    return LLMResponse(
        content=json.dumps(
            {
                "conceptual_intent_fa": "تایید کالا",
                "draft_reply": ("درخواست شما ثبت شد و برای بررسی به تیم مربوطه ارجاع شد."),
            },
            ensure_ascii=False,
        ),
        provider=provider,
        model=model,
        metadata={},
    )


def _ticket(*, room_id: str = "ROOM-AGENTIC-1", first_turn: str) -> OperatorTicket:
    return OperatorTicket(
        room_id=room_id,
        ticket_label="support",
        route_label="general_vendor_support",
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview="support: thread must not appear",
        open_ticket_preview="vendor: later message must not appear",
        original_vendor_issue_preview=first_turn,
        latest_vendor_message="vendor: later message must not appear",
        recent_context_preview="vendor: later context",
        extracted_order_id=None,
        extracted_order_ids=None,
        extracted_tracking_code=None,
        extracted_product_ids=None,
        extracted_tracking_carrier=None,
        extracted_iban=None,
        extracted_iban_masked=None,
        entity_warnings_summary=None,
        detected_intent=None,
    )


def test_graph_builds() -> None:
    graph = build_agentic_sandbox_graph()
    assert graph is not None


def test_all_nodes_run_in_order_mock_llm() -> None:
    ticket = _ticket(first_turn="لطفاً تایید کالا را بررسی کنید")
    initial = initial_state_from_ticket(
        ticket,
        llm_provider="mock",
        generate_fn=_mock_generate,
    )
    settings = (
        __import__("app.config", fromlist=["get_settings"])
        .get_settings()
        .model_copy(
            update={"knowledge_hints_enabled": False},
        )
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    nodes = [item["node"] for item in final["node_results"]]
    assert nodes == list(NODE_ORDER)
    assert final["execution_allowed"] is False
    assert final["customer_send_allowed"] is False
    assert final["human_review_required"] is True
    assert final["safety_status"] == "passed"
    assert final["draft_reply"]
    assert "ارجاع" not in (final["draft_reply"] or "")
    assert final["actionability"].get("requires_identifier_request") is True
    comparison = final.get("final_draft_reflection_comparison") or {}
    assert isinstance(comparison, dict)
    assert (comparison.get("pre_reflection_draft") or "").strip()
    assert (comparison.get("final_reflected_draft") or "").strip()


def test_missing_identifier_routes_to_identifier_request() -> None:
    ticket = _ticket(first_turn="لطفاً تایید کالا را بررسی کنید")
    initial = initial_state_from_ticket(ticket, generate_fn=_mock_generate)
    settings = (
        __import__("app.config", fromlist=["get_settings"])
        .get_settings()
        .model_copy(
            update={"knowledge_hints_enabled": False},
        )
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    draft = final.get("draft_reply") or ""
    assert ("شناسه کالا" in draft) or ("شماره سفارش" in draft)
    assert not draft_claims_fake_operational_execution(draft)


def test_first_turn_isolation_preserves_preview_only() -> None:
    ticket = _ticket(first_turn="ثبت تحویل سفارش 1234567")
    initial = initial_state_from_ticket(ticket, generate_fn=_mock_generate)
    assert initial["first_turn_text"] == "ثبت تحویل سفارش 1234567"
    assert "later message" not in initial["first_turn_text"]
    settings = (
        __import__("app.config", fromlist=["get_settings"])
        .get_settings()
        .model_copy(
            update={"knowledge_hints_enabled": False},
        )
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    assert final["extracted_entities"].get("order_ids") == ["1234567"]


def test_safety_gate_blocks_execution_and_send_flags() -> None:
    bad = initial_agentic_sandbox_state(room_id="R1", first_turn_text="test")
    bad["execution_allowed"] = True
    bad["customer_send_allowed"] = True
    result = safety_gate_node(bad)
    assert result["safety_status"] == "failed"
    assert result["errors"]


def test_safety_gate_blocks_forbidden_draft_markers() -> None:
    state = initial_agentic_sandbox_state(room_id="R2", first_turn_text="test")
    state["draft_reply"] = "See conversation transcript for details."
    state["execution_allowed"] = False
    state["customer_send_allowed"] = False
    state["human_review_required"] = True
    result = safety_gate_node(state)
    assert result["safety_status"] == "failed"


def test_safe_report_excludes_runtime_keys() -> None:
    ticket = _ticket(first_turn="تسویه واریز نشده")
    initial = initial_state_from_ticket(ticket, generate_fn=_mock_generate)
    settings = (
        __import__("app.config", fromlist=["get_settings"])
        .get_settings()
        .model_copy(
            update={"knowledge_hints_enabled": False},
        )
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    report = build_safe_run_report(final)
    assert "_generate_fn" not in report
    assert "human_review_payload" in report
    assert "conversation transcript" not in json.dumps(report, ensure_ascii=False).lower()


def test_cli_report_path_pattern(tmp_path: Path) -> None:
    from app.agentic_sandbox.agentic_graph import write_agentic_sandbox_report

    ticket = _ticket(room_id="ROOM-X", first_turn="سلام")
    initial = initial_state_from_ticket(ticket, generate_fn=_mock_generate)
    settings = (
        __import__("app.config", fromlist=["get_settings"])
        .get_settings()
        .model_copy(
            update={"knowledge_hints_enabled": False},
        )
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    out = tmp_path / "agentic_sandbox_run_ROOM-X.json"
    write_agentic_sandbox_report(final, out)
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["room_id"] == "ROOM-X"
    assert payload["node_order"] == list(NODE_ORDER)

"""Tests for operator-assisted agentic mode (HITL-only, session-only)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from app.agentic_sandbox.graduation_criteria import OverallGraduationStatus
from app.config import AppSettings
from app.operator_console.agentic_assisted_mode import (
    SESSION_AGENTIC_ASSISTED_KEY,
    AgenticAssistedPackage,
    assert_agentic_assisted_package_safe,
    build_agentic_assisted_package,
    get_session_agentic_assisted_package,
    is_agentic_assisted_mode_allowed,
    load_graduation_status,
    sanitize_agentic_assisted_package,
    store_session_agentic_assisted_package,
)
from app.operator_console.agentic_sandbox_preview import (
    AgenticSandboxPreviewResult,
    sanitize_agentic_preview_result,
)
from app.operator_console.console_models import OperatorTicket


def _ticket(*, room_id: str = "7743") -> OperatorTicket:
    return OperatorTicket(
        room_id=room_id,
        ticket_label="fund",
        route_label="billing_review",
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview="لطفاً تسویه را بررسی کنید",
        latest_vendor_message=None,
        recent_context_preview=None,
    )


def _final_state() -> dict[str, object]:
    return {
        "room_id": "7743",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "detected_intent": "settlement_status_inquiry",
        "conceptual_intent_fa": "پیگیری تسویه",
        "suggested_action": "billing_review",
        "suggested_action_reason": "fund_route",
        "actionability": {
            "actionability_actionable": True,
            "actionability_missing_entities": None,
            "actionability_validation_reason": "ok",
        },
        "extracted_entities": {
            "entity_source": "original_vendor_issue_preview",
            "order_ids": ["1234567"],
            "product_ids": [],
        },
        "knowledge_hints": [{"document_type": "settlement_rules"}],
        "draft_reply": "پاسخ کوتاه برای بررسی",
        "safety_status": "passed",
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "errors": [],
        "node_results": [
            {"node": "build_first_turn_context", "status": "ok", "summary": "first_turn"},
            {"node": "detect_intent", "status": "ok", "summary": "intent"},
        ],
    }


def _preview_result() -> AgenticSandboxPreviewResult:
    return sanitize_agentic_preview_result(_final_state(), knowledge_hints_enabled=True)


def _ready_graduation(tmp_path: Path) -> Path:
    path = tmp_path / "graduation.json"
    path.write_text(
        json.dumps(
            {
                "overall_status": (OverallGraduationStatus.READY_FOR_OPERATOR_ASSISTED_PHASE.value),
            },
        ),
        encoding="utf-8",
    )
    return path


def _not_ready_graduation(tmp_path: Path) -> Path:
    path = tmp_path / "graduation.json"
    path.write_text(
        json.dumps({"overall_status": "not_ready"}),
        encoding="utf-8",
    )
    return path


def test_assisted_mode_disabled_by_default() -> None:
    settings = AppSettings()
    assert settings.operator_agentic_assisted_mode_enabled is False
    allowed, reason = is_agentic_assisted_mode_allowed(settings)
    assert allowed is False
    assert reason is not None


def test_graduation_gate_blocks_when_not_ready(tmp_path: Path) -> None:
    grad_path = _not_ready_graduation(tmp_path)
    settings = AppSettings(
        operator_agentic_assisted_mode_enabled=True,
        operator_agentic_assisted_require_graduation_ready=True,
    )
    allowed, reason = is_agentic_assisted_mode_allowed(settings, graduation_path=grad_path)
    assert allowed is False
    assert reason is not None
    assert "ready_for_operator_assisted_phase" in reason


def test_graduation_ready_allows_mode(tmp_path: Path) -> None:
    grad_path = _ready_graduation(tmp_path)
    settings = AppSettings(
        operator_agentic_assisted_mode_enabled=True,
        operator_agentic_assisted_require_graduation_ready=True,
    )
    allowed, reason = is_agentic_assisted_mode_allowed(settings, graduation_path=grad_path)
    assert allowed is True
    assert reason is None


def test_package_excludes_forbidden_fields() -> None:
    graph = _preview_result()
    package = AgenticAssistedPackage(
        room_id="7743",
        graph=graph,
        operator_checklist=("verify intent",),
        graduation_overall_status="ready_for_operator_assisted_phase",
        graduation_gate_passed=True,
    )
    payload = json.dumps(sanitize_agentic_assisted_package(package), ensure_ascii=False)
    for forbidden in (
        "messages",
        "transcript",
        "raw_prompt",
        "full_first_vendor_message_text",
        "retrieval_results",
        "raw_snippets",
        "final_response",
    ):
        assert forbidden not in payload
    assert graph.draft_reply is not None
    assert_agentic_assisted_package_safe(package)


def test_safety_flags_enforced() -> None:
    graph = _preview_result()
    package = AgenticAssistedPackage(
        room_id="7743",
        graph=graph,
        operator_checklist=("check",),
        graduation_overall_status=None,
        graduation_gate_passed=True,
    )
    assert_agentic_assisted_package_safe(package)

    bad_graph = replace(graph, execution_allowed=True)
    bad = AgenticAssistedPackage(
        room_id="7743",
        graph=bad_graph,
        operator_checklist=("check",),
        graduation_overall_status=None,
        graduation_gate_passed=True,
    )
    with pytest.raises(ValueError, match="execution_allowed=false"):
        assert_agentic_assisted_package_safe(bad)


def test_session_only_package_storage() -> None:
    graph = _preview_result()
    package = AgenticAssistedPackage(
        room_id="7743",
        graph=graph,
        operator_checklist=("verify intent",),
        graduation_overall_status="ready_for_operator_assisted_phase",
        graduation_gate_passed=True,
    )
    session: dict[str, object] = {}
    store_session_agentic_assisted_package(session, package)
    assert get_session_agentic_assisted_package(session, "7743") is package
    assert session[SESSION_AGENTIC_ASSISTED_KEY]["7743"] is package  # type: ignore[index]
    assert get_session_agentic_assisted_package(session, "9999") is None


def test_preview_remains_independent_module() -> None:
    from app.operator_console import agentic_assisted_mode, agentic_sandbox_preview

    assert agentic_sandbox_preview.SESSION_AGENTIC_PREVIEW_KEY != (
        agentic_assisted_mode.SESSION_AGENTIC_ASSISTED_KEY
    )
    assert agentic_sandbox_preview.run_agentic_preview_for_ticket is not (
        agentic_assisted_mode.build_agentic_assisted_package
    )


@patch("app.operator_console.agentic_assisted_mode.run_agentic_preview_for_ticket")
def test_build_package_uses_assisted_runtime(
    mock_run: object,
    tmp_path: Path,
) -> None:
    grad_path = _ready_graduation(tmp_path)
    graph = _preview_result()
    mock_run.return_value = graph  # type: ignore[attr-defined]

    settings = AppSettings(
        operator_agentic_assisted_mode_enabled=True,
        operator_agentic_assisted_provider="mock",
        operator_agentic_assisted_knowledge_hints_enabled=False,
        operator_agentic_assisted_require_graduation_ready=True,
    )
    package = build_agentic_assisted_package(
        _ticket(),
        settings=settings,
        graduation_path=grad_path,
    )
    assert package.room_id == "7743"
    assert package.graph.graph_status == "ok"
    runtime = mock_run.call_args.kwargs["settings"]  # type: ignore[union-attr]
    assert runtime.operator_agentic_sandbox_provider == "mock"
    assert runtime.operator_agentic_sandbox_knowledge_hints_enabled is False


def test_load_graduation_status_missing(tmp_path: Path) -> None:
    assert load_graduation_status(tmp_path / "missing.json") is None

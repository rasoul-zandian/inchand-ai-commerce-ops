"""Tests for feature-flagged sandbox retrieval shadow LangGraph node."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from app.config import get_settings
from app.corpus_planning.retrieval_policy_gate import RetrievalGateDecision
from app.corpus_planning.retrieval_tool_models import (
    RetrievalToolMetadataFilter,
    RetrievalToolResponse,
    RetrievalToolResult,
)
from app.corpus_planning.sandbox_retrieval_chain_dry_run import (
    SandboxRetrievalChainDryRunConfig,
    SandboxRetrievalChainDryRunResult,
)
from app.nodes.sandbox_retrieval_shadow import sandbox_retrieve_pilot_shadow

from tests.test_vendor_ticket_workflow import make_base_state


def _enable_shadow_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setenv("LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED", "true" if enabled else "false")
    get_settings.cache_clear()


def test_settings_default_langgraph_sandbox_retrieval_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED", raising=False)
    get_settings.cache_clear()
    assert get_settings().langgraph_sandbox_retrieval_enabled is False


def test_flag_false_leaves_state_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_shadow_flag(monkeypatch, False)
    state = make_base_state()
    state["ticket_label"] = "fund"
    before = dict(state)
    calls: list[str] = []

    def fake_chain(*_a: object, **_k: object) -> SandboxRetrievalChainDryRunResult:
        calls.append("chain")
        raise AssertionError("chain should not run")

    monkeypatch.setattr(
        "app.corpus_planning.sandbox_retrieval_chain_dry_run.run_sandbox_retrieval_chain_on_state",
        fake_chain,
    )
    out = sandbox_retrieve_pilot_shadow(state)
    assert calls == []
    assert out.get("retrieval_gate_decision") is None
    assert before["user_input"] == out["user_input"]


def test_flag_true_writes_sanitized_retrieval_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_shadow_flag(monkeypatch, True)
    state = make_base_state(user_input="settlement payment status")
    state["ticket_label"] = "fund"
    state["route_label"] = "billing_review"

    def fake_chain(
        target_state: object,
        config: SandboxRetrievalChainDryRunConfig,
        **_kwargs: object,
    ) -> SandboxRetrievalChainDryRunResult:
        from app.corpus_planning.retrieval_policy_gate import (
            RetrievalPolicyGateResult,
            RetrievalScenario,
        )
        from app.state.retrieval_state import (
            apply_retrieval_gate_result_to_state,
            apply_retrieval_tool_response_to_state,
        )

        gate = RetrievalPolicyGateResult(
            decision=RetrievalGateDecision.ALLOW,
            scenario=RetrievalScenario.FUND_FINANCE,
            reasons=["retrieval_allowed for fund"],
            required_metadata_filter=RetrievalToolMetadataFilter(ticket_label="fund"),
        )
        apply_retrieval_gate_result_to_state(target_state, gate)
        response = RetrievalToolResponse(
            results=[
                RetrievalToolResult(
                    record_id="pilot::ns::v1::fund-1",
                    score=0.5,
                    ticket_label="fund",
                    route_label="billing_review",
                    review_priority="normal",
                )
            ],
            retrieval_activated=False,
            sandbox_only=True,
            query_hash="abc123456789abcd",
            result_count=1,
        )
        apply_retrieval_tool_response_to_state(target_state, response)
        _ = config
        from app.state.retrieval_state import sanitize_retrieval_state_snapshot

        return SandboxRetrievalChainDryRunResult(
            exit_code=0,
            snapshot=sanitize_retrieval_state_snapshot(target_state),
            gate_result=gate,
            executor_called=True,
        )

    monkeypatch.setattr(
        "app.corpus_planning.sandbox_retrieval_chain_dry_run.run_sandbox_retrieval_chain_on_state",
        fake_chain,
    )
    out = sandbox_retrieve_pilot_shadow(state)
    assert out["retrieval_gate_decision"] == "allow"
    assert out["retrieval_query_hash"] == "abc123456789abcd"
    assert out["retrieval_result_count"] == 1
    assert out["retrieval_activated"] is False
    assert out["retrieval_sandbox_only"] is True
    assert "results" not in out
    assert "settlement payment status" not in str(out.get("audit_log", []))


def test_shadow_chain_error_is_safe_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_shadow_flag(monkeypatch, True)
    state = make_base_state()
    state["ticket_label"] = "fund"

    def fail_chain(*_a: object, **_k: object) -> SandboxRetrievalChainDryRunResult:
        raise RuntimeError("injected shadow failure")

    monkeypatch.setattr(
        "app.corpus_planning.sandbox_retrieval_chain_dry_run.run_sandbox_retrieval_chain_on_state",
        fail_chain,
    )
    out = sandbox_retrieve_pilot_shadow(state)
    assert out["retrieval_activated"] is False
    assert any("sandbox_retrieval_shadow_error" in r for r in out["retrieval_policy_reasons"])
    assert any(
        e.tool_name == "sandbox_retrieve_pilot_shadow"
        and e.error_type == "sandbox_retrieval_shadow_failed"
        for e in out["errors"]
    )


def test_vendor_ticket_node_source_does_not_reference_retrieval_state_fields() -> None:
    path = Path(__file__).resolve().parents[1] / "app" / "nodes" / "vendor_ticket.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    joined = ast.dump(tree)
    assert "retrieval_gate_decision" not in joined
    assert "retrieval_query_hash" not in joined
    assert "retrieval_result_count" not in joined


def test_vendor_ticket_workflow_unchanged_with_flag_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_shadow_flag(monkeypatch, False)
    from app.nodes.common import normalize_request, retrieve_context, route_workflow
    from app.nodes.vendor_ticket import vendor_ticket_node as vt_node

    state = make_base_state(user_input="سلام، تسویه این هفته با فاکتور هم‌خوان نیست.")
    state = normalize_request(state)
    state = route_workflow(state)
    state = sandbox_retrieve_pilot_shadow(state)
    assert state.get("retrieval_gate_decision") is None
    state = retrieve_context(state)
    state = vt_node(state)
    assert state["specialist_output"].get("draft_response")

"""Tests for AI assist shadow replay JSONL export (offline metrics only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.config import AppSettings, get_settings
from app.corpus_planning.ai_assist_shadow_metrics_dashboard import load_ai_assist_shadow_rows
from app.corpus_planning.ai_assist_shadow_replay_export import (
    export_ai_assist_shadow_replay_jsonl_content,
    export_ai_assist_shadow_replay_jsonl_file,
)
from app.corpus_planning.ai_assist_shadow_replay_row_contract import (
    assert_ai_assist_shadow_replay_row_safe,
)
from app.corpus_planning.retrieval_policy_gate import (
    RetrievalGateDecision,
    RetrievalPolicyGateResult,
    RetrievalScenario,
)
from app.corpus_planning.sandbox_retrieval_chain_dry_run import (
    SandboxRetrievalChainDryRunConfig,
    SandboxRetrievalChainDryRunResult,
)
from app.corpus_planning.shadow_replay_jsonl_export import (
    ShadowReplayExportConfig,
    _default_chain_runner,
    resolve_sandbox_export_database_url,
)
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState
from app.state.retrieval_state import (
    apply_retrieval_gate_result_to_state,
    apply_retrieval_tool_response_to_state,
    sanitize_retrieval_state_snapshot,
)
from scripts.export_ai_assist_shadow_replay_jsonl import main as export_main


def _valid_line(*, label: str = "fund", room_id: str = "ROOM_FUND_1") -> str:
    payload = {
        "room_id": room_id,
        "ticket_label": label,
        "ticket_subtype": "settlement_discrepancy",
        "status": "closed",
        "seller_id": "SELLER_ID_001",
        "messages": [
            {"message_id": "m1", "sender_type": "seller", "text": "مبلغ تسویه اشتباه است"},
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _export_config() -> ShadowReplayExportConfig:
    return ShadowReplayExportConfig(
        namespace="vendor_ticket_real_pilot_balanced",
        index_version="pilot_balanced_v1",
        profile="semantic_pgvector",
        top_k=5,
        confirm_sandbox=True,
    )


def _enable_flags(
    monkeypatch: pytest.MonkeyPatch,
    *,
    retrieval: bool,
    assist: bool,
) -> None:
    monkeypatch.setenv("LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED", "true" if retrieval else "false")
    monkeypatch.setenv(
        "VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED",
        "true" if assist else "false",
    )
    get_settings.cache_clear()


def _fake_chain_runner(
    state: object,
    config: SandboxRetrievalChainDryRunConfig,
    _settings: object,
) -> SandboxRetrievalChainDryRunResult:
    from app.corpus_planning.retrieval_tool_models import (
        RetrievalToolMetadataFilter,
        RetrievalToolResponse,
        RetrievalToolResult,
    )

    gate = RetrievalPolicyGateResult(
        decision=RetrievalGateDecision.ALLOW,
        scenario=RetrievalScenario.FUND_FINANCE,
        reasons=["retrieval_allowed for fund"],
        required_metadata_filter=RetrievalToolMetadataFilter(
            ticket_label="fund",
            route_label="billing_review",
        ),
    )
    apply_retrieval_gate_result_to_state(state, gate)
    response = RetrievalToolResponse(
        results=[
            RetrievalToolResult(
                record_id="pilot::ns::v1::fund-1",
                score=0.5,
                ticket_label="fund",
                route_label="billing_review",
                review_priority="normal",
            ),
        ],
        retrieval_activated=False,
        sandbox_only=True,
        query_hash="abc123456789abcd",
        result_count=1,
    )
    apply_retrieval_tool_response_to_state(state, response)
    _ = config
    return SandboxRetrievalChainDryRunResult(
        exit_code=0,
        snapshot=sanitize_retrieval_state_snapshot(state),
        gate_result=gate,
        executor_called=True,
    )


def test_export_row_safe_with_assist_flag_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_flags(monkeypatch, retrieval=False, assist=True)
    rows, summary = export_ai_assist_shadow_replay_jsonl_content(
        [_valid_line()],
        _export_config(),
        run_chain=_fake_chain_runner,
    )
    assert summary.exported_rows == 1
    assert summary.assist_generated_count == 1
    row = rows[0]
    assert row["ai_assist_shadow_generated"] is True
    assert row["ai_assist_suggested_action"] == "billing_review"
    assert row["retrieval_activated"] is False
    assert row["downstream_consumed_retrieval"] is False
    assert row["ai_assist_shadow_only"] is True
    assert_ai_assist_shadow_replay_row_safe(row)
    assert "messages" not in row
    assert "draft_response" not in row


def test_export_skipped_when_assist_flag_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_flags(monkeypatch, retrieval=False, assist=False)
    rows, _summary = export_ai_assist_shadow_replay_jsonl_content(
        [_valid_line()],
        _export_config(),
    )
    row = rows[0]
    assert row["ai_assist_shadow_generated"] is False
    errors = row.get("errors") or []
    assert any("VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=false" in str(e) for e in errors)


def test_rejects_forbidden_messages_key_in_output_row() -> None:
    with pytest.raises(ValueError, match="forbidden keys"):
        assert_ai_assist_shadow_replay_row_safe(
            {
                "room_id": "R1",
                "ticket_label": "fund",
                "messages": [],
                "ai_assist_shadow_generated": False,
                "ai_assist_human_review_required": True,
                "ai_assist_shadow_only": True,
                "retrieval_activated": False,
                "downstream_consumed_retrieval": False,
                "errors": [],
            },
        )


def test_rejects_ai_assist_shadow_only_false() -> None:
    with pytest.raises(ValueError, match="ai_assist_shadow_only"):
        assert_ai_assist_shadow_replay_row_safe(
            {
                "room_id": "R1",
                "ticket_label": "fund",
                "ai_assist_shadow_generated": False,
                "ai_assist_human_review_required": True,
                "ai_assist_shadow_only": False,
                "retrieval_activated": False,
                "downstream_consumed_retrieval": False,
                "errors": [],
            },
        )


def test_export_file_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_flags(monkeypatch, retrieval=False, assist=True)
    input_path = tmp_path / "tickets.jsonl"
    output_path = tmp_path / "ai_assist.jsonl"
    input_path.write_text(_valid_line(label="complaint") + "\n", encoding="utf-8")

    summary = export_ai_assist_shadow_replay_jsonl_file(
        input_path,
        output_path,
        _export_config(),
        run_chain=_fake_chain_runner,
    )
    assert summary.exported_rows == 1
    loaded = load_ai_assist_shadow_rows(output_path)
    assert loaded[0]["ai_assist_escalation_recommended"] is True


def test_resolve_sandbox_export_database_url_uses_local_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PGVECTOR_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    from app.config import AppSettings

    url = resolve_sandbox_export_database_url(
        AppSettings(pgvector_database_url=None),
        validate_sandbox=True,
    )
    assert "127.0.0.1" in url
    assert "inchand_ai" in url


def test_default_chain_runner_passes_database_url_when_executor_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PGVECTOR_DATABASE_URL", raising=False)
    get_settings.cache_clear()

    captured: dict[str, object] = {}

    def fake_run(
        _state: CommerceAIState,
        _config: SandboxRetrievalChainDryRunConfig,
        *,
        database_url: str | None = None,
        **kwargs: object,
    ) -> SandboxRetrievalChainDryRunResult:
        _ = kwargs
        captured["database_url"] = database_url
        gate = RetrievalPolicyGateResult(
            decision=RetrievalGateDecision.SKIP,
            scenario=RetrievalScenario.UNKNOWN,
            reasons=["skip"],
            required_metadata_filter=None,
        )
        return SandboxRetrievalChainDryRunResult(
            exit_code=0,
            snapshot={},
            gate_result=gate,
            executor_called=False,
        )

    monkeypatch.setattr(
        "app.corpus_planning.shadow_replay_jsonl_export.run_sandbox_retrieval_chain_on_state",
        fake_run,
    )

    settings = AppSettings(pgvector_database_url=None)
    config = SandboxRetrievalChainDryRunConfig(
        query="test",
        ticket_label="fund",
        route_label="billing_review",
        namespace="vendor_ticket_real_pilot_balanced",
        index_version="pilot_balanced_v1",
        top_k=5,
        profile="semantic_pgvector",
        confirm_sandbox=True,
    )
    state: CommerceAIState = {
        "request_id": "r1",
        "session_id": None,
        "user_id": None,
        "user_role": None,
        "user_input": "test",
        "workflow_type": WorkflowType.UNKNOWN,
        "workflow_status": WorkflowStatus.STARTED,
        "entity_type": EntityType.UNKNOWN,
        "product_id": None,
        "vendor_id": None,
        "ticket_id": "t1",
        "application_id": None,
        "room_id": "ROOM_1",
        "ticket_label": "fund",
        "ticket_subtype": None,
        "workflow_state_snapshot": {},
        "retrieved_context": {},
        "rag_sources": [],
        "tool_results": {},
        "specialist_output": {},
        "risk_score": None,
        "confidence_score": None,
        "detected_intent": None,
        "grounding_summary": None,
        "grounding_sources": [],
        "qa_passed": None,
        "qa_issues": [],
        "qa_warnings": [],
        "qa_summary": None,
        "qa_requires_human_attention": False,
        "route_label": "billing_review",
        "routing_reasons": [],
        "specialist_recommended_action": None,
        "review_category": None,
        "review_priority": None,
        "review_reason": None,
        "recommended_action": None,
        "human_approval_required": False,
        "approval_status": ApprovalStatus.NOT_REQUIRED,
        "final_response": None,
        "errors": [],
        "audit_log": [],
    }
    _default_chain_runner(state, config, settings)
    assert captured["database_url"]
    assert "127.0.0.1" in str(captured["database_url"])


def test_export_retrieval_enabled_empty_errors_with_mocked_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PGVECTOR_DATABASE_URL", raising=False)
    _enable_flags(monkeypatch, retrieval=True, assist=True)
    rows, summary = export_ai_assist_shadow_replay_jsonl_content(
        [_valid_line()],
        _export_config(),
        run_chain=_fake_chain_runner,
    )
    assert summary.exported_rows == 1
    row = rows[0]
    errors = [str(e) for e in (row.get("errors") or [])]
    assert not any("database_url is required" in e for e in errors)
    assert not any(e.startswith("shadow_chain_error:") and "database_url" in e for e in errors)


def test_export_retrieval_disabled_no_database_url_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PGVECTOR_DATABASE_URL", raising=False)
    _enable_flags(monkeypatch, retrieval=False, assist=True)

    def fail_if_called(*_a: object, **_k: object) -> SandboxRetrievalChainDryRunResult:
        raise AssertionError("chain runner must not run when retrieval flag is false")

    rows, _summary = export_ai_assist_shadow_replay_jsonl_content(
        [_valid_line()],
        _export_config(),
        run_chain=fail_if_called,
    )
    errors = rows[0].get("errors") or []
    assert any("LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false" in str(e) for e in errors)


def test_cli_requires_confirm_sandbox(tmp_path: Path) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(_valid_line() + "\n", encoding="utf-8")
    rc = export_main(
        [
            str(input_path),
            "--namespace",
            "vendor_ticket_real_pilot_balanced",
            "--index-version",
            "pilot_balanced_v1",
            "--output",
            str(tmp_path / "out.jsonl"),
        ],
    )
    assert rc == 1

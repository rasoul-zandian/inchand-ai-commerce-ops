"""Tests for shadow replay JSONL export (sanitized rows for Step 136 dashboard)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.config import get_settings
from app.corpus_planning.retrieval_policy_gate import (
    RetrievalGateDecision,
    RetrievalPolicyGateResult,
    RetrievalScenario,
)
from app.corpus_planning.sandbox_retrieval_chain_dry_run import (
    SandboxRetrievalChainDryRunConfig,
    SandboxRetrievalChainDryRunResult,
    build_metadata_filter_from_config,
)
from app.corpus_planning.shadow_replay_jsonl_export import (
    ShadowReplayExportConfig,
    build_chain_config_from_state,
    export_shadow_replay_jsonl_content,
    export_shadow_replay_jsonl_file,
)
from app.corpus_planning.shadow_replay_row_contract import assert_shadow_replay_row_safe
from app.corpus_planning.shadow_retrieval_metrics_dashboard import load_shadow_retrieval_rows
from app.state.retrieval_state import (
    apply_retrieval_gate_result_to_state,
    apply_retrieval_tool_response_to_state,
    sanitize_retrieval_state_snapshot,
)
from scripts.export_shadow_replay_jsonl import main as export_main


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


def _enable_shadow_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setenv("LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED", "true" if enabled else "false")
    get_settings.cache_clear()


def _fake_chain_runner(
    state: object,
    config: SandboxRetrievalChainDryRunConfig,
    _settings: object,
) -> SandboxRetrievalChainDryRunResult:
    from app.corpus_planning.retrieval_tool_models import (
        RetrievalToolMetadataFilter,
        RetrievalToolResponse,
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
    from app.corpus_planning.retrieval_tool_models import RetrievalToolResult

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


def test_chain_config_omits_review_priority_from_metadata_filter() -> None:
    state = {
        "ticket_label": "fund",
        "route_label": "billing_review",
        "user_input": "settlement status",
    }
    config = build_chain_config_from_state(state, _export_config())  # type: ignore[arg-type]
    assert config.review_priority is None
    metadata = build_metadata_filter_from_config(config)
    assert metadata is not None
    dumped = metadata.model_dump(exclude_none=True)
    assert dumped == {"ticket_label": "fund", "route_label": "billing_review"}
    assert "review_priority" not in dumped


def test_export_produces_safe_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_shadow_flag(monkeypatch, True)
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line() + "\n", encoding="utf-8")
    out_file = tmp_path / "shadow.jsonl"

    summary = export_shadow_replay_jsonl_file(
        export_file,
        out_file,
        _export_config(),
        run_chain=_fake_chain_runner,
    )
    assert summary.exported_rows == 1
    assert summary.shadow_node_executed_count == 1

    rows = load_shadow_retrieval_rows(out_file)
    assert len(rows) == 1
    row = rows[0]
    assert row["room_id"] == "ROOM_FUND_1"
    assert row["shadow_node_executed"] is True
    assert row["retrieval_gate_decision"] == "allow"
    assert row["retrieval_activated"] is False
    assert row["downstream_consumed_retrieval"] is False
    assert row["retrieval_query_hash"] == "abc123456789abcd"
    assert row["retrieval_result_count"] == 1
    assert row["executor_called"] is True
    assert row["route_label"] == "billing_review"
    assert row["retrieval_metadata_filter"] == {
        "ticket_label": "fund",
        "route_label": "billing_review",
    }
    assert "review_priority" not in (row.get("retrieval_metadata_filter") or {})
    assert "query" not in row
    assert "messages" not in row
    serialized = out_file.read_text(encoding="utf-8")
    assert "مبلغ" not in serialized
    assert "settlement payment" not in serialized.lower()


def test_flag_false_skips_chain_but_exports_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_shadow_flag(monkeypatch, False)
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line() + "\n", encoding="utf-8")
    out_file = tmp_path / "shadow.jsonl"

    summary = export_shadow_replay_jsonl_file(
        export_file,
        out_file,
        _export_config(),
        run_chain=_fake_chain_runner,
    )
    assert summary.exported_rows == 1
    assert summary.shadow_node_executed_count == 0
    row = json.loads(out_file.read_text(encoding="utf-8").strip())
    assert row["shadow_node_executed"] is False
    assert any("LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false" in e for e in row["errors"])


def test_invalid_line_recorded_without_stopping_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_shadow_flag(monkeypatch, True)
    lines = [_valid_line(room_id="ROOM_OK"), "{not json"]
    rows, summary = export_shadow_replay_jsonl_content(
        lines,
        _export_config(),
        run_chain=_fake_chain_runner,
    )
    assert summary.valid_tickets == 1
    assert summary.invalid_lines == 1
    assert len(rows) == 1
    assert rows[0]["room_id"] == "ROOM_OK"


def test_build_row_rejects_forbidden_keys_in_output() -> None:
    with pytest.raises(ValueError, match="forbidden keys"):
        assert_shadow_replay_row_safe(
            {
                "room_id": "ROOM_1",
                "shadow_node_executed": True,
                "retrieval_activated": False,
                "downstream_consumed_retrieval": False,
                "query": "secret",
                "errors": [],
            },
        )


def test_cli_requires_confirm_sandbox(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line() + "\n", encoding="utf-8")
    out_file = tmp_path / "shadow.jsonl"
    rc = export_main(
        [
            str(export_file),
            "--output",
            str(out_file),
            "--namespace",
            "vendor_ticket_real_pilot_balanced",
            "--index-version",
            "pilot_balanced_v1",
        ],
    )
    assert rc == 1
    assert "--confirm-sandbox is required" in capsys.readouterr().err


def test_denied_gate_exports_without_result_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_shadow_flag(monkeypatch, True)

    def _deny_runner(
        state: object,
        config: SandboxRetrievalChainDryRunConfig,
        _settings: object,
    ) -> SandboxRetrievalChainDryRunResult:
        gate = RetrievalPolicyGateResult(
            decision=RetrievalGateDecision.DENY,
            scenario=RetrievalScenario.FUND_FINANCE,
            reasons=["fund retrieval requires metadata_filter.ticket_label=fund"],
        )
        apply_retrieval_gate_result_to_state(state, gate)
        _ = config
        return SandboxRetrievalChainDryRunResult(
            exit_code=2,
            snapshot=sanitize_retrieval_state_snapshot(state),
            gate_result=gate,
            executor_called=False,
        )

    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line(label="fund") + "\n", encoding="utf-8")
    rows, _ = export_shadow_replay_jsonl_content(
        export_file.read_text(encoding="utf-8").splitlines(),
        _export_config(),
        run_chain=_deny_runner,
    )
    row = rows[0]
    assert row["retrieval_gate_decision"] == "deny"
    assert row["executor_called"] is False
    assert row["retrieval_result_count"] is None


def test_dashboard_counts_result_distribution_after_hardened_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.corpus_planning.shadow_retrieval_metrics_dashboard import (
        compute_shadow_retrieval_metrics,
    )

    _enable_shadow_flag(monkeypatch, True)
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line() + "\n", encoding="utf-8")
    out_file = tmp_path / "shadow.jsonl"
    export_shadow_replay_jsonl_file(
        export_file,
        out_file,
        _export_config(),
        run_chain=_fake_chain_runner,
    )
    rows = load_shadow_retrieval_rows(out_file)
    metrics = compute_shadow_retrieval_metrics(rows)
    assert metrics.result_count_distribution.get("1") == 1


def test_assert_shadow_replay_row_safe_rejects_activation() -> None:
    with pytest.raises(ValueError, match="retrieval_activated"):
        assert_shadow_replay_row_safe(
            {
                "room_id": "R1",
                "retrieval_activated": True,
                "downstream_consumed_retrieval": False,
            },
        )

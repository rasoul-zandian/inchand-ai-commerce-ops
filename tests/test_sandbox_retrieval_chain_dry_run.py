"""Tests for sandbox retrieval chain dry-run (fake executor; no network/pgvector)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.corpus_planning.pilot_retrieval_eval import PilotScopedVectorStore
from app.corpus_planning.retrieval_policy_gate import RetrievalGateDecision
from app.corpus_planning.retrieval_tool_models import (
    RetrievalToolMetadataFilter,
    RetrievalToolRequest,
    RetrievalToolResponse,
    RetrievalToolResult,
)
from app.corpus_planning.sandbox_retrieval_chain_dry_run import (
    SandboxRetrievalChainDryRunConfig,
    build_gate_input_from_config,
    format_snapshot_json,
    run_sandbox_retrieval_chain_dry_run,
)
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import InMemoryVectorStore
from scripts.dry_run_sandbox_retrieval_chain import main as dry_run_main

_BALANCED_NS = "vendor_ticket_real_pilot_balanced"
_INDEX = "pilot_balanced_v1"
_QUERY = "settlement payment status"


def _config(**overrides: object) -> SandboxRetrievalChainDryRunConfig:
    defaults: dict[str, object] = {
        "query": _QUERY,
        "namespace": _BALANCED_NS,
        "index_version": _INDEX,
        "top_k": 5,
        "profile": "semantic_pgvector",
        "confirm_sandbox": True,
        "ticket_label": "fund",
        "route_label": "billing_review",
    }
    defaults.update(overrides)
    return SandboxRetrievalChainDryRunConfig(**defaults)  # type: ignore[arg-type]


def test_gate_deny_does_not_call_executor_or_embedding() -> None:
    calls: dict[str, int] = {"embed": 0, "exec": 0}

    def fake_embed(_: str) -> list[float]:
        calls["embed"] += 1
        return [1.0, 0.0]

    def fake_exec(*_args: object, **_kwargs: object) -> RetrievalToolResponse:
        calls["exec"] += 1
        raise AssertionError("executor should not run")

    result = run_sandbox_retrieval_chain_dry_run(
        _config(ticket_label="fund", route_label="other_route"),
        database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
        query_embedding_fn=fake_embed,
        execute_tool=fake_exec,
    )
    assert result.gate_result.decision == RetrievalGateDecision.DENY
    assert result.executor_called is False
    assert calls["embed"] == 0
    assert calls["exec"] == 0
    assert result.snapshot["retrieval_gate_decision"] == "deny"
    assert result.snapshot["retrieval_activated"] is False


def test_gate_allow_calls_executor_with_metadata_filter() -> None:
    captured: dict[str, Any] = {}

    def fake_embed(text: str) -> list[float]:
        captured["query"] = text
        return [1.0, 0.0]

    def fake_exec(
        request: RetrievalToolRequest,
        _store: object,
        _embed: object,
        *,
        profile: str,
    ) -> RetrievalToolResponse:
        captured["request"] = request
        captured["profile"] = profile
        return RetrievalToolResponse(
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

    result = run_sandbox_retrieval_chain_dry_run(
        _config(),
        database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
        store_factory=lambda _url: object(),
        query_embedding_fn=fake_embed,
        execute_tool=fake_exec,
    )
    assert result.executor_called is True
    assert captured["request"].metadata_filter is not None
    assert captured["request"].metadata_filter.ticket_label == "fund"
    assert captured["profile"] == "semantic_pgvector"
    assert result.snapshot["retrieval_query_hash"] == "abc123456789abcd"
    assert result.snapshot["retrieval_result_count"] == 1
    assert "results" not in result.snapshot


def test_allow_path_executes_default_executor_successfully() -> None:
    """Integration: dry-run chain calls execute_sandbox_retrieval_tool(profile=...)."""
    fund_vector = [0.99, 0.01] + [0.0] * 14
    inner = InMemoryVectorStore()
    inner.upsert(
        [
            VectorRecord(
                record_id=f"pilot::{_BALANCED_NS}::{_INDEX}::fund-1",
                document_id="fund-1",
                content="room_id=ROOM_fund-1|ticket_label=fund",
                vector=fund_vector,
                dimensions=len(fund_vector),
                embedding_provider="openai",
                embedding_model="text-embedding-3-small",
                source_type=_BALANCED_NS,
                metadata={
                    "ticket_label": "fund",
                    "route_label": "billing_review",
                    "review_priority": "normal",
                    "namespace": _BALANCED_NS,
                    "index_version": _INDEX,
                },
            )
        ]
    )
    store = PilotScopedVectorStore(inner, namespace=_BALANCED_NS, index_version=_INDEX)

    result = run_sandbox_retrieval_chain_dry_run(
        _config(),
        database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
        store_factory=lambda _url: store,
        query_embedding_fn=lambda _text: [1.0] + [0.0] * 15,
    )
    assert result.executor_called is True
    assert result.snapshot["retrieval_gate_decision"] == "allow"
    assert result.snapshot["retrieval_result_count"] == 1
    assert result.snapshot["retrieval_activated"] is False


def test_snapshot_is_safe_and_excludes_raw_query() -> None:
    def _fail_exec(*_a: object, **_k: object) -> RetrievalToolResponse:
        raise AssertionError("executor should not run")

    result = run_sandbox_retrieval_chain_dry_run(
        _config(ticket_label=None),
        query_embedding_fn=lambda _: [1.0],
        execute_tool=_fail_exec,
    )
    serialized = format_snapshot_json(result.snapshot)
    assert _QUERY not in serialized
    assert "content" not in serialized
    assert "vector" not in serialized
    assert result.snapshot["retrieval_sandbox_only"] is True
    assert result.snapshot["retrieval_activated"] is False


def test_gate_skip_does_not_call_executor() -> None:
    calls = {"exec": 0}

    def fake_exec(*_a: object, **_k: object) -> RetrievalToolResponse:
        calls["exec"] += 1
        raise AssertionError("executor should not run")

    result = run_sandbox_retrieval_chain_dry_run(
        _config(ticket_label=None),
        query_embedding_fn=lambda _: [1.0],
        execute_tool=fake_exec,
    )
    assert result.gate_result.decision == RetrievalGateDecision.SKIP
    assert result.executor_called is False
    assert calls["exec"] == 0
    assert result.exit_code == 0


def test_cli_requires_confirm_sandbox(capsys: pytest.CaptureFixture[str]) -> None:
    code = dry_run_main(
        [
            "--query",
            _QUERY,
            "--namespace",
            _BALANCED_NS,
            "--index-version",
            _INDEX,
            "--ticket-label",
            "fund",
        ]
    )
    assert code == 1
    assert "--confirm-sandbox is required" in capsys.readouterr().err


def test_cli_success_with_fake_chain(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run(config: SandboxRetrievalChainDryRunConfig, **kwargs: object) -> object:
        _ = config, kwargs
        from app.corpus_planning.retrieval_policy_gate import (
            RetrievalPolicyGateResult,
            RetrievalScenario,
        )

        gate = RetrievalPolicyGateResult(
            decision=RetrievalGateDecision.ALLOW,
            scenario=RetrievalScenario.FUND_FINANCE,
            reasons=["ok"],
            required_metadata_filter=RetrievalToolMetadataFilter(ticket_label="fund"),
        )
        snap = {
            "retrieval_gate_decision": "allow",
            "retrieval_scenario": "fund_finance",
            "retrieval_policy_reasons": ["ok"],
            "retrieval_query_hash": "deadbeefdeadbeef",
            "retrieval_result_count": 2,
            "retrieval_metadata_filter": {"ticket_label": "fund"},
            "retrieval_sandbox_only": True,
            "retrieval_activated": False,
        }
        from app.corpus_planning.sandbox_retrieval_chain_dry_run import (
            SandboxRetrievalChainDryRunResult,
        )

        return SandboxRetrievalChainDryRunResult(
            exit_code=0,
            snapshot=snap,
            gate_result=gate,
            executor_called=True,
        )

    monkeypatch.setattr(
        "scripts.dry_run_sandbox_retrieval_chain.run_sandbox_retrieval_chain_dry_run",
        fake_run,
    )
    code = dry_run_main(
        [
            "--query",
            _QUERY,
            "--namespace",
            _BALANCED_NS,
            "--index-version",
            _INDEX,
            "--ticket-label",
            "fund",
            "--route-label",
            "billing_review",
            "--confirm-sandbox",
            "--format",
            "json",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert _QUERY not in out
    payload = json.loads(out)
    assert payload["retrieval_activated"] is False
    assert payload["retrieval_gate_decision"] == "allow"


def test_build_gate_input_from_config() -> None:
    gate_input = build_gate_input_from_config(_config())
    assert gate_input.ticket_label == "fund"
    assert gate_input.metadata_filter is not None
    assert gate_input.metadata_filter.ticket_label == "fund"

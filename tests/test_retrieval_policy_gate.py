"""Tests for pre-retrieval policy gate contract (no pgvector / OpenAI)."""

from __future__ import annotations

import pytest
from app.corpus_planning.retrieval_policy_gate import (
    RetrievalGateDecision,
    RetrievalPolicyGateInput,
    RetrievalPolicyGateResult,
    RetrievalScenario,
    evaluate_retrieval_policy_gate,
)
from app.corpus_planning.retrieval_tool_models import RetrievalToolMetadataFilter

_BALANCED_NS = "vendor_ticket_real_pilot_balanced"
_INDEX = "pilot_balanced_v1"


def _gate_input(**kwargs: object) -> RetrievalPolicyGateInput:
    defaults: dict[str, object] = {
        "namespace": _BALANCED_NS,
        "index_version": _INDEX,
        "requested_top_k": 5,
        "sandbox_only": True,
    }
    defaults.update(kwargs)
    return RetrievalPolicyGateInput.model_validate(defaults)


def test_fund_allowed_with_matching_metadata_filter() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(
            ticket_label="fund",
            route_label="billing_review",
            metadata_filter=RetrievalToolMetadataFilter(ticket_label="fund"),
        )
    )
    assert result.decision == RetrievalGateDecision.ALLOW
    assert result.scenario == RetrievalScenario.FUND_FINANCE
    assert result.required_metadata_filter is not None
    assert result.required_metadata_filter.ticket_label == "fund"
    assert result.retrieval_activated is False
    assert result.sandbox_only is True


def test_fund_denied_without_metadata_filter() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(ticket_label="fund"),
    )
    assert result.decision == RetrievalGateDecision.DENY
    assert result.scenario == RetrievalScenario.FUND_FINANCE
    assert "metadata_filter" in " ".join(result.reasons).lower()


def test_complaint_allowed_with_matching_filter() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(
            ticket_label="complaint",
            metadata_filter=RetrievalToolMetadataFilter(ticket_label="complaint"),
        )
    )
    assert result.decision == RetrievalGateDecision.ALLOW
    assert result.scenario == RetrievalScenario.COMPLAINT_REVIEW


def test_support_allowed_with_matching_filter() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(
            ticket_label="support",
            metadata_filter=RetrievalToolMetadataFilter(ticket_label="support"),
        )
    )
    assert result.decision == RetrievalGateDecision.ALLOW
    assert result.scenario == RetrievalScenario.VENDOR_SUPPORT


def test_fund_denied_when_filter_label_mismatches() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(
            ticket_label="fund",
            metadata_filter=RetrievalToolMetadataFilter(ticket_label="support"),
        )
    )
    assert result.decision == RetrievalGateDecision.DENY


def test_fund_denied_when_route_label_provided_and_not_billing_review() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(
            ticket_label="fund",
            route_label="other_route",
            metadata_filter=RetrievalToolMetadataFilter(ticket_label="fund"),
        )
    )
    assert result.decision == RetrievalGateDecision.DENY
    assert "billing_review" in " ".join(result.reasons)


def test_namespace_gate_denies_unapproved_namespace() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(
            namespace="production_corpus",
            ticket_label="support",
            metadata_filter=RetrievalToolMetadataFilter(ticket_label="support"),
        )
    )
    assert result.decision == RetrievalGateDecision.DENY
    assert "namespace" in " ".join(result.reasons).lower()


def test_index_version_gate_denies_non_pilot_prefix() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(
            index_version="prod_v1",
            ticket_label="support",
            metadata_filter=RetrievalToolMetadataFilter(ticket_label="support"),
        )
    )
    assert result.decision == RetrievalGateDecision.DENY
    assert "index_version" in " ".join(result.reasons).lower()


@pytest.mark.parametrize("top_k", [0, 11, 50])
def test_top_k_bounds_denied(top_k: int) -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(
            requested_top_k=top_k,
            ticket_label="support",
            metadata_filter=RetrievalToolMetadataFilter(ticket_label="support"),
        )
    )
    assert result.decision == RetrievalGateDecision.DENY
    assert "requested_top_k" in " ".join(result.reasons)


def test_unknown_ticket_label_skipped() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(ticket_label="mystery"),
    )
    assert result.decision == RetrievalGateDecision.SKIP
    assert result.scenario == RetrievalScenario.UNKNOWN


def test_missing_ticket_label_skipped() -> None:
    result = evaluate_retrieval_policy_gate(_gate_input())
    assert result.decision == RetrievalGateDecision.SKIP
    assert result.scenario == RetrievalScenario.UNKNOWN


def test_sandbox_only_false_denied() -> None:
    result = evaluate_retrieval_policy_gate(
        _gate_input(
            sandbox_only=False,
            ticket_label="support",
            metadata_filter=RetrievalToolMetadataFilter(ticket_label="support"),
        )
    )
    assert result.decision == RetrievalGateDecision.DENY
    assert "sandbox_only" in " ".join(result.reasons)


def test_result_model_rejects_retrieval_activated_true() -> None:
    with pytest.raises(ValueError, match="retrieval_activated"):
        RetrievalPolicyGateResult(
            decision=RetrievalGateDecision.ALLOW,
            scenario=RetrievalScenario.VENDOR_SUPPORT,
            retrieval_activated=True,
        )


def test_gate_module_has_no_pgvector_or_openai_dependencies() -> None:
    """Gate is pure policy; no store or embedding client imports."""
    import ast
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1] / "app" / "corpus_planning" / "retrieval_policy_gate.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    joined = " ".join(modules).lower()
    assert "pgvector" not in joined
    assert "openai" not in joined
    assert "retrieve_for_workflow" not in joined

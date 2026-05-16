"""Filesystem checks for agent workflow visualization docs (no network)."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_README = _REPO_ROOT / "README.md"


def test_readme_agent_workflow_visualization_section() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "## Agent Workflow Visualization" in readme
    assert "TicketIntentAgent" in readme
    assert "PolicyGroundingAgent" in readme
    assert "RiskReviewAgent" in readme
    assert "QACheckAgent" in readme
    assert "SupervisorRouterAgent" in readme
    assert "route_after_vendor_ticket" in readme
    assert "billing_review" in readme
    assert "EvidenceBuilder" in readme
    assert "DraftingAgent" in readme
    assert "```mermaid" in readme
    assert "normalize_request" in readme
    assert "retrieve_context" in readme
    assert "vendor_ticket_node" in readme
    assert "Retrieval Strategy" in readme or "Retrieval layer" in readme

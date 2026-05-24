"""Tests for agentic sandbox graph visualization and LangSmith tracing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.agentic_sandbox.agentic_graph import NODE_ORDER, build_safe_run_report
from app.agentic_sandbox.agentic_graph_visualization import (
    format_agentic_sandbox_graph_markdown,
    render_agentic_sandbox_graph,
)
from app.agentic_sandbox.agentic_state import initial_agentic_sandbox_state
from app.agentic_sandbox.langsmith_tracing import (
    configure_agentic_sandbox_langsmith_tracing,
)
from app.config import AppSettings, get_settings


def test_mermaid_graph_file_generated(tmp_path: Path) -> None:
    result = render_agentic_sandbox_graph(
        mermaid_output=tmp_path / "graph.mmd",
        markdown_output=tmp_path / "graph.md",
        png_output=tmp_path / "graph.png",
        try_png=False,
    )
    assert result.mermaid_path.is_file()
    mermaid = result.mermaid_path.read_text(encoding="utf-8")
    assert "flowchart" in mermaid.lower() or "-->" in mermaid
    for node in NODE_ORDER:
        assert node in mermaid or node.replace("-", "_") in mermaid


def test_graph_report_includes_all_node_names_and_safety_boundaries(tmp_path: Path) -> None:
    result = render_agentic_sandbox_graph(
        mermaid_output=tmp_path / "g.mmd",
        markdown_output=tmp_path / "g.md",
        try_png=False,
    )
    markdown = result.markdown_path.read_text(encoding="utf-8")
    for node in NODE_ORDER:
        assert node in markdown
    assert "execution_allowed" in markdown
    assert "**false**" in markdown
    assert "customer_send_allowed" in markdown
    assert "human_review_required" in markdown
    assert "true" in markdown.lower()


def test_langsmith_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    get_settings.cache_clear()
    cfg = AppSettings(langsmith_tracing_enabled=False, langsmith_tracing=False)
    status = configure_agentic_sandbox_langsmith_tracing(enabled=False, settings=cfg)
    assert status.enabled is False


def test_enabling_langsmith_without_api_key_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    get_settings.cache_clear()
    cfg = AppSettings(langsmith_api_key=None)
    status = configure_agentic_sandbox_langsmith_tracing(enabled=True, settings=cfg)
    assert status.enabled is False
    assert status.warning
    assert "LANGSMITH_API_KEY" in status.warning
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()


def test_run_report_includes_tracing_metadata() -> None:
    state = initial_agentic_sandbox_state(room_id="R1", first_turn_text="test")
    tracing = {
        "langsmith_tracing_enabled": False,
        "langsmith_project": "inchand-agentic-sandbox",
        "langsmith_api_key_present": False,
        "langsmith_warning": None,
        "langsmith_run_note": None,
    }
    report = build_safe_run_report(state, tracing_metadata=tracing)
    assert report["langsmith_tracing_enabled"] is False
    assert report["langsmith_project"] == "inchand-agentic-sandbox"

    from app.agentic_sandbox.langsmith_tracing import LangSmithTracingStatus

    tracing_enabled = LangSmithTracingStatus(
        enabled=True,
        project="test-project",
        api_key_present=True,
        langsmith_run_note="Open LangSmith dashboard if configured",
    )
    report2 = build_safe_run_report(
        state,
        tracing_metadata=tracing_enabled.to_report_dict(),
    )
    assert report2["langsmith_tracing_enabled"] is True
    assert report2["langsmith_project"] == "test-project"
    assert report2["langsmith_run_note"] == "Open LangSmith dashboard if configured"
    serialized = json.dumps(report2, ensure_ascii=False)
    assert "lsv2_test_key" not in serialized


def test_format_markdown_has_mermaid_fence() -> None:
    md = format_agentic_sandbox_graph_markdown("flowchart TD\n  A --> B")
    assert "```mermaid" in md
    assert "flowchart TD" in md

"""Filesystem checks for Graphviz-based vendor-ticket workflow + legend diagrams."""

from __future__ import annotations

from pathlib import Path

from scripts.render_agent_workflow_diagram import build_dot, build_legend_dot

_REPO_ROOT = Path(__file__).resolve().parents[1]
_README = _REPO_ROOT / "README.md"
_ARCH_README = _REPO_ROOT / "docs" / "architecture" / "README.md"
_WORKFLOW_DOT = (
    _REPO_ROOT / "docs" / "architecture" / "diagrams" / "vendor_ticket_agent_workflow.dot"
)
_WORKFLOW_SVG = (
    _REPO_ROOT / "docs" / "architecture" / "diagrams" / "vendor_ticket_agent_workflow.svg"
)
_LEGEND_DOT = (
    _REPO_ROOT / "docs" / "architecture" / "diagrams" / "vendor_ticket_agent_workflow_legend.dot"
)
_LEGEND_SVG = (
    _REPO_ROOT / "docs" / "architecture" / "diagrams" / "vendor_ticket_agent_workflow_legend.svg"
)
_RENDER_SCRIPT = _REPO_ROOT / "scripts" / "render_agent_workflow_diagram.py"

_WORKFLOW_DOT_LABELS = (
    "SupervisorRouterAgent",
    "QACheckAgent",
    "Route Decision",
    "VectorStore / RAG Docs",
    "Human Approval",
    "billing_review",
    "vendor_ticket_node",
    "POST /review-actions",
    "Controlled Redraft",
)

_LEGEND_DOT_LABELS = (
    "Decision",
    "Agent / Process",
    "VectorStore / RAG",
    "Dashed arrow",
    "Human Approval",
    "Solid arrow",
    "Visual Notation Legend",
)


def test_render_script_exists() -> None:
    assert _RENDER_SCRIPT.is_file()


def test_workflow_dot_matches_generator_and_excludes_embedded_legend() -> None:
    assert _WORKFLOW_DOT.is_file()
    committed = _WORKFLOW_DOT.read_text(encoding="utf-8")
    generated = build_dot()
    assert committed == generated
    assert "cluster_legend" not in committed
    assert "Diagram Notation" not in committed


def test_workflow_dot_contains_key_labels() -> None:
    text = _WORKFLOW_DOT.read_text(encoding="utf-8")
    for label in _WORKFLOW_DOT_LABELS:
        assert label in text, f"missing label in workflow DOT: {label!r}"


def test_legend_dot_matches_generator() -> None:
    assert _LEGEND_DOT.is_file()
    committed = _LEGEND_DOT.read_text(encoding="utf-8")
    assert committed == build_legend_dot()


def test_legend_dot_contains_key_labels() -> None:
    text = _LEGEND_DOT.read_text(encoding="utf-8")
    for label in _LEGEND_DOT_LABELS:
        assert label in text, f"missing label in legend DOT: {label!r}"


def test_workflow_and_legend_svg_exist() -> None:
    for path in (_WORKFLOW_SVG, _LEGEND_SVG):
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert text.lstrip().startswith("<?xml") or "<svg" in text


def test_readme_links_workflow_and_legend_assets() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "vendor_ticket_agent_workflow.svg" in readme
    assert "vendor_ticket_agent_workflow_legend.svg" in readme
    assert "vendor_ticket_agent_workflow.dot" in readme
    assert "legend" in readme.lower()


def test_architecture_readme_links_workflow_and_legend() -> None:
    text = _ARCH_README.read_text(encoding="utf-8")
    assert "vendor_ticket_agent_workflow.svg" in text
    assert "vendor_ticket_agent_workflow_legend.svg" in text
    assert "vendor_ticket_agent_workflow_legend.dot" in text

"""Mermaid/markdown visualization for the agentic sandbox LangGraph (no ticket data)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agentic_sandbox.agentic_graph import NODE_ORDER, build_agentic_sandbox_graph

DEFAULT_MMD_PATH = Path("reports/agentic_sandbox_graph.mmd")
DEFAULT_MD_PATH = Path("reports/agentic_sandbox_graph.md")
DEFAULT_PNG_PATH = Path("reports/agentic_sandbox_graph.png")

NODE_DESCRIPTIONS: dict[str, str] = {
    "build_first_turn_context": (
        "Validate first-turn seller text from original_vendor_issue_preview only "
        "(no thread leakage)."
    ),
    "detect_intent": "Rule-based vendor ticket intent detection.",
    "extract_entities": "Operational entity extraction (order/product/tracking/IBAN).",
    "retrieve_knowledge_hints": (
        "Sandbox official policy hints only (KNOWLEDGE_HINTS path; not production RAG)."
    ),
    "suggest_action": "Map intent to internal suggested_action via taxonomy.",
    "validate_actionability": (
        "Check required identifiers; flag missing-ID identifier-request path."
    ),
    "generate_draft": (
        "Internal first-turn draft (LLM + style/completion/actionability post-process)."
    ),
    "safety_gate": ("Fail closed: no auto-send markers, forbidden fields, execution/send flags."),
    "human_review_handoff": "Read-only HITL handoff payload for operator review.",
}


@dataclass(frozen=True)
class AgenticGraphRenderResult:
    """Paths written by graph visualization."""

    mermaid_path: Path
    markdown_path: Path
    png_path: Path | None
    mermaid_source: str
    png_render_attempted: bool
    png_render_error: str | None = None


def build_agentic_sandbox_mermaid() -> str:
    """Build Mermaid flowchart for the linear sandbox graph."""
    try:
        compiled = build_agentic_sandbox_graph()
        return compiled.get_graph().draw_mermaid()
    except Exception:
        return _manual_mermaid_diagram()


def _manual_mermaid_diagram() -> str:
    """Deterministic Mermaid when LangGraph draw API is unavailable."""
    lines = [
        "flowchart TD",
        "    START([START])",
    ]
    previous = "START"
    for node in NODE_ORDER:
        node_id = node.replace("-", "_")
        lines.append(f"    {node_id}[{node}]")
        lines.append(f"    {previous} --> {node_id}")
        previous = node_id
    lines.append("    END_NODE([END])")
    lines.append(f"    {previous} --> END_NODE")
    return "\n".join(lines) + "\n"


def format_agentic_sandbox_graph_markdown(
    mermaid: str,
    *,
    png_path: Path | None = None,
    png_note: str | None = None,
) -> str:
    """Render markdown report with diagram, node table, and safety boundaries."""
    lines = [
        "# Agentic Sandbox LangGraph",
        "",
        "**Scope:** Observability / documentation only — no ticket data, prompts, or transcripts.",
        "",
        "## Safety boundaries (always enforced)",
        "",
        "| Flag | Value |",
        "|------|-------|",
        "| `execution_allowed` | **false** |",
        "| `customer_send_allowed` | **false** |",
        "| `human_review_required` | **true** |",
        "",
        "No operational API execution, no customer auto-send, no production `RAG_PROFILE` wiring.",
        "",
        "## Graph diagram",
        "",
        "```mermaid",
        mermaid.strip(),
        "```",
        "",
    ]
    if png_path is not None:
        lines.extend(
            [
                f"![Agentic sandbox graph]({png_path.name})",
                "",
            ],
        )
    elif png_note:
        lines.extend([f"*{png_note}*", "", ""])

    lines.extend(
        [
            "## Node order",
            "",
            "| Step | Node | Description |",
            "|-----:|------|-------------|",
        ],
    )
    for index, node in enumerate(NODE_ORDER, start=1):
        description = NODE_DESCRIPTIONS.get(node, "—")
        lines.append(f"| {index} | `{node}` | {description} |")
    lines.append("")
    lines.extend(
        [
            "## Linear flow",
            "",
            "START → " + " → ".join(f"`{node}`" for node in NODE_ORDER) + " → END",
            "",
            "## Governance",
            "",
            "- Sandbox graph only — does not replace `app/graph/main_graph.py`.",
            "- Optional LangSmith tracing via "
            "`scripts/run_agentic_sandbox_workflow.py --enable-langsmith`.",
            "- No committed run reports should include raw transcripts or full prompts.",
            "",
        ],
    )
    return "\n".join(lines)


def _try_render_png(mermaid: str, output_path: Path) -> tuple[bool, str | None]:
    """Attempt PNG export; return (success, error_message)."""
    try:
        compiled = build_agentic_sandbox_graph()
        png_bytes = compiled.get_graph().draw_mermaid_png()
        if png_bytes:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(png_bytes)
            return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return False, "draw_mermaid_png returned empty output"


def render_agentic_sandbox_graph(
    *,
    mermaid_output: Path = DEFAULT_MMD_PATH,
    markdown_output: Path = DEFAULT_MD_PATH,
    png_output: Path = DEFAULT_PNG_PATH,
    try_png: bool = True,
) -> AgenticGraphRenderResult:
    """Write Mermaid, markdown, and optional PNG graph artifacts."""
    mermaid = build_agentic_sandbox_mermaid()
    mermaid_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    mermaid_output.write_text(mermaid.strip() + "\n", encoding="utf-8")

    png_path: Path | None = None
    png_error: str | None = None
    png_attempted = False
    if try_png:
        png_attempted = True
        ok, png_error = _try_render_png(mermaid, png_output)
        if ok:
            png_path = png_output

    png_note = None
    if try_png and png_path is None:
        png_note = (
            "PNG not generated (optional dependency unavailable). "
            "Mermaid diagram above is sufficient."
        )
        if png_error:
            png_note += f" Detail: {png_error[:120]}"

    markdown = format_agentic_sandbox_graph_markdown(
        mermaid,
        png_path=png_path,
        png_note=png_note,
    )
    markdown_output.write_text(markdown, encoding="utf-8")

    return AgenticGraphRenderResult(
        mermaid_path=mermaid_output,
        markdown_path=markdown_output,
        png_path=png_path,
        mermaid_source=mermaid,
        png_render_attempted=png_attempted,
        png_render_error=png_error,
    )

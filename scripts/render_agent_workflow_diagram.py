#!/usr/bin/env python3
"""Regenerate vendor-ticket workflow + legend diagrams from Graphviz DOT (local `dot` for SVG)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIAGRAMS_DIR = _REPO_ROOT / "docs" / "architecture" / "diagrams"
_WORKFLOW_DOT = _DIAGRAMS_DIR / "vendor_ticket_agent_workflow.dot"
_WORKFLOW_SVG = _DIAGRAMS_DIR / "vendor_ticket_agent_workflow.svg"
_LEGEND_DOT = _DIAGRAMS_DIR / "vendor_ticket_agent_workflow_legend.dot"
_LEGEND_SVG = _DIAGRAMS_DIR / "vendor_ticket_agent_workflow_legend.svg"

_GRAPHVIZ_INSTALL_HINT = (
    "Graphviz `dot` is not installed. Install locally to render SVG, e.g.:\n"
    "  brew install graphviz\n"
    "Then re-run: python3.11 scripts/render_agent_workflow_diagram.py"
)


def build_dot() -> str:
    """Return deterministic Graphviz DOT for the vendor-ticket workflow (topology only)."""
    return r"""digraph vendor_ticket_agent_workflow {
  graph [
    rankdir=TB,
    splines=ortho,
    nodesep=0.55,
    ranksep=0.75,
    fontsize=11,
    fontname="Helvetica",
    label="Inchand AI — Vendor Ticket Agent Workflow",
    labelloc=t,
    labeljust=c,
    bgcolor="#f8fafc"
  ];
  node [fontname="Helvetica", fontsize=10, shape=box, style="rounded,filled", fillcolor="#ffffff"];
  edge [fontname="Helvetica", fontsize=9, color="#334155"];

  subgraph cluster_runtime {
    label="Runtime — LangGraph";
    style="rounded,filled";
    color="#94a3b8";
    fillcolor="#ffffff";

    fastapi [label="FastAPI Request", shape=ellipse, fillcolor="#dcfce7"];
    langgraph [label="LangGraph Workflow", fillcolor="#eef2ff"];
    normalize_request [label="normalize_request"];
    route_workflow [label="route_workflow"];
    retrieve_context [label="retrieve_context", fillcolor="#f1f5f9"];
    vendor_ticket_orchestrator [
      label="vendor_ticket_node\nOrchestrator",
      fillcolor="#faf5ff",
      color="#7c3aed",
      penwidth=1.5
    ];
    validate_output [label="validate_output"];
    risk_and_approval [label="risk_and_approval_decision", fillcolor="#fef3c7"];
    persist_trace [label="persist_trace"];
    end_node [label="End", shape=ellipse, fillcolor="#dcfce7"];

    fastapi -> langgraph -> normalize_request -> route_workflow -> retrieve_context;
    retrieve_context -> vendor_ticket_orchestrator;
  }

  subgraph cluster_retrieval {
    label="Retrieval layer (supporting)";
    style="rounded,filled";
    color="#0369a1";
    fillcolor="#f0f9ff";

    retrieval_strategy [label="Retrieval Strategy", fillcolor="#e0f2fe"];
    vectorstore [label="VectorStore / RAG Docs", shape=cylinder, fillcolor="#bae6fd"];
    rag_policy_context [label="RAG / Policy Context", shape=note, fillcolor="#e0f2fe"];

    retrieval_strategy -> vectorstore -> rag_policy_context;
  }

  subgraph cluster_specialists {
    label="Internal Agent Specialists";
    style="rounded,filled";
    color="#7c3aed";
    fillcolor="#faf5ff";

    ticket_intent [label="TicketIntentAgent"];
    policy_grounding [label="PolicyGroundingAgent"];
    drafting [label="DraftingAgent"];
    qa_check [label="QACheckAgent"];
    supervisor [label="SupervisorRouterAgent"];
    risk_review [label="RiskReviewAgent"];
    evidence [label="EvidenceBuilder"];
    specialist_output [label="specialist_output", shape=note, fillcolor="#f5f3ff"];

    ticket_intent -> policy_grounding -> drafting -> qa_check -> supervisor;
    supervisor -> risk_review -> evidence -> specialist_output;
  }

  subgraph cluster_route_obs {
    label="Route Observability";
    style="rounded,filled";
    color="#ca8a04";
    fillcolor="#fffbeb";

    route_decision [
      label="Route Decision\n(route_after_vendor_ticket)",
      shape=diamond,
      fillcolor="#fef9c3"
    ];
    qa_attention_review [
      label="QA Attention Review\n(surfaces QA issues)",
      fillcolor="#fef9c3"
    ];
    escalation_review [label="escalation_review", fillcolor="#fef9c3"];
    billing_review [label="billing_review", fillcolor="#fef9c3"];
    style_guidance_review [label="style_guidance_review", fillcolor="#fef9c3"];
    general_vendor_review [label="general_vendor_review", fillcolor="#fef9c3"];

    route_decision -> qa_attention_review [style=dashed];
    route_decision -> escalation_review [style=dashed];
    route_decision -> billing_review;
    route_decision -> style_guidance_review [style=dashed];
    route_decision -> general_vendor_review [style=dashed];
  }

  subgraph cluster_approval {
    label="Validation & Human Approval";
    style="rounded,filled";
    color="#ea580c";
    fillcolor="#fff7ed";

    human_approval_required [
      label="Human Approval\nRequired?",
      shape=diamond,
      fillcolor="#fef9c3"
    ];
    human_approval [label="Human Approval", fillcolor="#ffedd5", color="#ea580c", penwidth=1.5];
    final_response [
      label="Final Response\n(future / bypass)",
      style="rounded,dashed",
      fillcolor="#f8fafc"
    ];
  }

  subgraph cluster_operator_hitl {
    label="Operator HITL (API)";
    style="rounded,filled";
    color="#0f766e";
    fillcolor="#ecfdf5";

    operator_review [
      label="POST /review-actions\nOperator Review Action",
      fillcolor="#ccfbf1"
    ];
    redraft_execute_gate [
      label="execute=true\nrequest_redraft?",
      shape=diamond,
      fillcolor="#fef9c3"
    ];
    controlled_redraft [
      label="Controlled Redraft\nExecution",
      fillcolor="#99f6e4"
    ];
    draft_pending_approval [
      label="New Draft\nPending Human Approval",
      fillcolor="#fef3c7",
      color="#ea580c",
      penwidth=1.5
    ];

    operator_review -> redraft_execute_gate;
    redraft_execute_gate -> controlled_redraft [label="yes"];
    controlled_redraft -> draft_pending_approval;
  }

  retrieve_context -> retrieval_strategy [style=dashed, label="retrieve"];
  rag_policy_context -> policy_grounding [style=dashed, label="context"];

  vendor_ticket_orchestrator -> ticket_intent [style=dashed, label="internal"];
  specialist_output -> route_decision;

  qa_attention_review -> validate_output;
  escalation_review -> validate_output;
  billing_review -> validate_output;
  style_guidance_review -> validate_output;
  general_vendor_review -> validate_output;

  validate_output -> risk_and_approval -> persist_trace -> human_approval_required;
  human_approval_required -> human_approval [label="yes"];
  human_approval_required -> final_response [label="no", style=dashed];
  human_approval -> end_node;
  final_response -> end_node [style=dashed];
  human_approval -> operator_review [style=dashed, label="operator action"];
  draft_pending_approval -> human_approval [style=dashed, label="re-approve"];
}
"""


def build_legend_dot() -> str:
    """Return deterministic Graphviz DOT for the standalone notation legend."""
    return r"""digraph vendor_ticket_agent_workflow_legend {
  graph [
    rankdir=TB,
    splines=ortho,
    nodesep=0.5,
    ranksep=0.55,
    fontsize=11,
    fontname="Helvetica",
    label="Vendor Ticket Workflow — Visual Notation Legend",
    labelloc=t,
    labeljust=c,
    bgcolor="#ffffff"
  ];
  node [fontname="Helvetica", fontsize=10];
  edge [fontname="Helvetica", fontsize=9, color="#334155"];

  subgraph cluster_shapes {
    label="Shapes";
    style="rounded,filled";
    color="#94a3b8";
    fillcolor="#ffffff";

    leg_terminal [
      shape=ellipse,
      label="Start / End\n(external entrypoint)",
      fillcolor="#dcfce7",
      width=1.5,
      height=0.65
    ];
    leg_agent [
      label="Agent / Process\n(rounded rectangle)",
      shape=box,
      style="rounded,filled",
      fillcolor="#ffffff"
    ];
    leg_decision [
      shape=diamond,
      label="Decision\n(routing logic)",
      fillcolor="#fef9c3",
      width=1.25,
      height=0.8
    ];
    leg_storage [
      shape=cylinder,
      label="VectorStore / RAG\n(storage)",
      fillcolor="#bae6fd",
      width=1.35,
      height=0.6
    ];
    leg_artifact [
      shape=note,
      label="specialist_output\n/ evidence",
      fillcolor="#f5f3ff",
      width=1.25
    ];
    leg_cluster [
      label="Subsystem / layer\n(cluster group)",
      style="rounded,dashed",
      fillcolor="#f8fafc",
      color="#94a3b8"
    ];

    { rank=same;
      leg_terminal; leg_agent; leg_decision; leg_storage; leg_artifact; leg_cluster;
    }
  }

  subgraph cluster_lines {
    label="Line styles";
    style="rounded,filled";
    color="#64748b";
    fillcolor="#ffffff";

    leg_solid_a [
      shape=circle, label="", width=0.14, height=0.14,
      fixedsize=true, style=filled, fillcolor="#334155"
    ];
    leg_solid_b [
      shape=circle, label="", width=0.14, height=0.14,
      fixedsize=true, style=filled, fillcolor="#334155"
    ];
    leg_dash_a [
      shape=circle, label="", width=0.14, height=0.14,
      fixedsize=true, style=filled, fillcolor="#334155"
    ];
    leg_dash_b [
      shape=circle, label="", width=0.14, height=0.14,
      fixedsize=true, style=filled, fillcolor="#334155"
    ];
    leg_join_a [
      shape=circle, label="", width=0.14, height=0.14,
      fixedsize=true, style=filled, fillcolor="#334155"
    ];
    leg_join_b [
      shape=circle, label="", width=0.14, height=0.14,
      fixedsize=true, style=filled, fillcolor="#334155"
    ];
    leg_join_c [
      shape=circle, label="", width=0.14, height=0.14,
      fixedsize=true, style=filled, fillcolor="#334155"
    ];
    leg_join_target [shape=plaintext, label="converge", fontsize=9];

    leg_solid_a -> leg_solid_b [label="Solid arrow — primary workflow execution"];
    leg_dash_a -> leg_dash_b [style=dashed, label="Dashed arrow — context / retrieval signal"];
    leg_join_a -> leg_join_target;
    leg_join_b -> leg_join_target [style=dashed];
    leg_join_target -> leg_join_c [label="Rejoining arrows — branch convergence"];

    { rank=same; leg_solid_a; leg_dash_a; leg_join_a; }
  }

  subgraph cluster_colors {
    label="Color semantics";
    style="rounded,filled";
    color="#64748b";
    fillcolor="#ffffff";

    leg_color_runtime [
      label="Runtime /\norchestration",
      fillcolor="#eef2ff",
      shape=box,
      style="rounded,filled"
    ];
    leg_color_retrieval [
      label="Retrieval layer",
      fillcolor="#e0f2fe",
      shape=box,
      style="rounded,filled",
      color="#0369a1"
    ];
    leg_color_specialists [
      label="Internal\nspecialists",
      fillcolor="#faf5ff",
      shape=box,
      style="rounded,filled",
      color="#7c3aed"
    ];
    leg_color_approval [
      label="Human Approval\n/ governance",
      fillcolor="#ffedd5",
      shape=box,
      style="rounded,filled",
      color="#ea580c"
    ];
    leg_color_qa [
      label="QA attention /\nroute observability",
      fillcolor="#fef9c3",
      shape=box,
      style="rounded,filled",
      color="#ca8a04"
    ];

    { rank=same;
      leg_color_runtime;
      leg_color_retrieval;
      leg_color_specialists;
      leg_color_approval;
      leg_color_qa;
    }
  }

  cluster_shapes -> cluster_lines [style=invis, weight=0];
  cluster_lines -> cluster_colors [style=invis, weight=0];
}
"""


def write_dot(path: Path | None = None, *, legend: bool = False) -> Path:
    target = path or (_LEGEND_DOT if legend else _WORKFLOW_DOT)
    content = build_legend_dot() if legend else build_dot()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def render_svg(dot_path: Path, svg_path: Path) -> Path:
    dot_bin = shutil.which("dot")
    if not dot_bin:
        print(_GRAPHVIZ_INSTALL_HINT, file=sys.stderr)
        sys.exit(1)

    subprocess.run(
        [dot_bin, "-Tsvg", str(dot_path), "-o", str(svg_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return svg_path


def main() -> None:
    workflow_dot = write_dot(_WORKFLOW_DOT)
    legend_dot = write_dot(_LEGEND_DOT, legend=True)
    print(f"wrote {workflow_dot.relative_to(_REPO_ROOT)}")
    print(f"wrote {legend_dot.relative_to(_REPO_ROOT)}")

    workflow_svg = render_svg(workflow_dot, _WORKFLOW_SVG)
    legend_svg = render_svg(legend_dot, _LEGEND_SVG)
    print(f"wrote {workflow_svg.relative_to(_REPO_ROOT)}")
    print(f"wrote {legend_svg.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()

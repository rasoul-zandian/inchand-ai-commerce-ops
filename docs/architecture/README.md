# Architecture diagrams

Static, version-controlled visuals for the Agentic AI Commerce OS.

| Diagram | Source | Rendered | Regenerate |
|---------|--------|----------|------------|
| Vendor ticket workflow | [vendor_ticket_agent_workflow.dot](diagrams/vendor_ticket_agent_workflow.dot) | [vendor_ticket_agent_workflow.svg](diagrams/vendor_ticket_agent_workflow.svg) | `python3.11 scripts/render_agent_workflow_diagram.py` |
| Visual notation legend | [vendor_ticket_agent_workflow_legend.dot](diagrams/vendor_ticket_agent_workflow_legend.dot) | [vendor_ticket_agent_workflow_legend.svg](diagrams/vendor_ticket_agent_workflow_legend.svg) | (same command) |

The render script writes both DOT files and invokes Graphviz `dot` to produce SVG. The **workflow diagram** shows topology only; the **legend** is a separate artifact (shapes, line styles, color semantics). Install Graphviz locally if needed (e.g. `brew install graphviz`). CI validates committed DOT content and file presence; it does not run `dot`.

Mermaid overview for the same flow lives in the root [README.md](../../README.md) under **Agent Workflow Visualization**.

## Review queue contract

Operator review persistence is defined in `app/review_queue/` (`ReviewQueueItem`, `ReviewQueueAdapter`, `build_review_queue_item`). Operator decisions use `OperatorReviewAction` / `ReviewActionType` in `actions.py`, recorded via `ReviewActionAdapter` (`action_adapters.py`, default noop). Controlled redraft (`redraft_execution.py`, `POST /review-actions` with `execute=true`) regenerates a draft outside LangGraph; it does not send or auto-approve. See **Review queue persistence contract**, **Operator review actions contract**, **Review action intake API**, and **Controlled redraft execution** in the root README.

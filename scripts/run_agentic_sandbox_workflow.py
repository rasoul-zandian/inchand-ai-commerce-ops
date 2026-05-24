#!/usr/bin/env python3
"""Run sandbox-only agentic LangGraph workflow for one ticket room (HITL, no send)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.agentic_graph import (
    initial_state_from_ticket,
    resolve_ticket_for_sandbox,
    run_agentic_sandbox_workflow,
    write_agentic_sandbox_report,
)
from app.agentic_sandbox.langsmith_tracing import (
    DEFAULT_AGENTIC_SANDBOX_LANGSMITH_PROJECT,
    configure_agentic_sandbox_langsmith_tracing,
)
from app.config import get_settings
from app.operator_console.console_loader import DEFAULT_REPLAY_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run agentic sandbox LangGraph for one ticket (first-turn only, no execution/send)."
        ),
    )
    parser.add_argument("--room-id", required=True, help="Ticket room_id to process")
    parser.add_argument(
        "--replay-jsonl",
        type=Path,
        default=DEFAULT_REPLAY_PATH,
        help=(
            "Replay JSONL with ticket metadata (default: reports/ai_assist_shadow_replay_v1.jsonl)"
        ),
    )
    parser.add_argument(
        "--redacted-jsonl",
        type=Path,
        default=None,
        help="Optional redacted tickets JSONL for original_vendor_issue_preview",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: reports/agentic_sandbox_run_<room_id>.json)",
    )
    parser.add_argument(
        "--provider",
        choices=("mock", "openai"),
        default="mock",
        help="LLM provider for internal draft node only",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model override (default: settings.operator_draft_model or mock)",
    )
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required when --provider openai",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output file",
    )
    parser.add_argument(
        "--enable-langsmith",
        action="store_true",
        help="Enable LangSmith tracing for this run (requires API key)",
    )
    parser.add_argument(
        "--langsmith-project",
        default=DEFAULT_AGENTIC_SANDBOX_LANGSMITH_PROJECT,
        help=f"LangSmith project name (default: {DEFAULT_AGENTIC_SANDBOX_LANGSMITH_PROJECT})",
    )
    args = parser.parse_args(argv)

    if args.provider == "openai" and not args.confirm_real_openai:
        print("error: --provider openai requires --confirm-real-openai", file=sys.stderr)
        return 2

    settings = get_settings()
    cfg = settings.model_copy(update={"knowledge_hints_enabled": False})
    if args.provider == "openai":
        model = (args.model or cfg.openai_draft_model or "gpt-4o-mini").strip()
    else:
        model = (args.model or "mock-vendor-ticket-drafter").strip()

    output = args.output or Path(f"reports/agentic_sandbox_run_{args.room_id}.json")
    if output.exists() and not args.overwrite:
        print(f"agentic_sandbox: output exists: {output} (use --overwrite)", file=sys.stderr)
        return 2

    try:
        ticket = resolve_ticket_for_sandbox(
            args.room_id,
            replay_jsonl=args.replay_jsonl,
            redacted_jsonl=args.redacted_jsonl,
        )
    except ValueError as exc:
        print(f"agentic_sandbox: {exc}", file=sys.stderr)
        return 1

    tracing = configure_agentic_sandbox_langsmith_tracing(
        enabled=args.enable_langsmith or cfg.langsmith_tracing_enabled,
        project=args.langsmith_project,
        settings=cfg,
    )

    initial = initial_state_from_ticket(
        ticket,
        llm_provider=args.provider,
        llm_model=model,
        generate_fn=None,
    )
    final = run_agentic_sandbox_workflow(initial, settings=cfg)
    write_agentic_sandbox_report(final, output, tracing_metadata=tracing.to_report_dict())

    print("agentic_sandbox: success")
    print(f"  langsmith_tracing_enabled={tracing.enabled}")
    print(f"  langsmith_project={tracing.project}")
    if tracing.langsmith_run_note:
        print(f"  langsmith_run_note={tracing.langsmith_run_note}")
    if tracing.warning:
        print(f"  langsmith_warning={tracing.warning}", file=sys.stderr)
    print(f"  output={output.resolve()}")
    print(f"  safety_status={final.get('safety_status')}")
    print(f"  suggested_action={final.get('suggested_action')}")
    print(f"  execution_allowed={final.get('execution_allowed')}")
    print(f"  customer_send_allowed={final.get('customer_send_allowed')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

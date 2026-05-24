#!/usr/bin/env python3
"""Batch agentic sandbox runs for first-vendor tickets + aggregate report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.agentic_batch_report import (
    DEFAULT_BATCH_REPORT_MD,
    DEFAULT_BATCH_RUNS_JSONL,
    DEFAULT_BATCH_SUMMARY_JSON,
    build_agentic_batch_report,
)
from app.agentic_sandbox.langsmith_tracing import DEFAULT_AGENTIC_SANDBOX_LANGSMITH_PROJECT
from app.config import get_settings
from app.operator_console.console_loader import DEFAULT_REPLAY_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run agentic sandbox batch for first-vendor rooms only "
            "(sandbox observability; no execution/send)."
        ),
    )
    parser.add_argument(
        "--replay-jsonl",
        type=Path,
        default=DEFAULT_REPLAY_PATH,
        help="Replay JSONL (default: reports/ai_assist_shadow_replay_v1.jsonl)",
    )
    parser.add_argument(
        "--redacted-jsonl",
        type=Path,
        default=Path("data/private/vendor_tickets_400.redacted.jsonl"),
        help="Redacted tickets JSONL for first-vendor filter + first-turn text",
    )
    parser.add_argument(
        "--runs-jsonl",
        type=Path,
        default=DEFAULT_BATCH_RUNS_JSONL,
        help="Per-room safe batch rows (default: reports/agentic_sandbox_batch_runs.jsonl)",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_BATCH_SUMMARY_JSON,
        help="Aggregate summary JSON (default: reports/agentic_sandbox_batch_summary.json)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_BATCH_REPORT_MD,
        help="Markdown report (default: reports/agentic_sandbox_batch_report.md)",
    )
    parser.add_argument(
        "--provider",
        choices=("mock", "openai"),
        default="mock",
        help="LLM provider for generate_draft node",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model override",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max first-vendor rooms to process",
    )
    parser.add_argument(
        "--enable-knowledge-hints",
        action="store_true",
        help="Enable sandbox knowledge hints in each batch graph run (default: disabled)",
    )
    parser.add_argument(
        "--enable-langsmith",
        action="store_true",
        help="Enable LangSmith tracing for batch runs",
    )
    parser.add_argument(
        "--langsmith-project",
        default=DEFAULT_AGENTIC_SANDBOX_LANGSMITH_PROJECT,
        help="LangSmith project when tracing enabled",
    )
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required when --provider openai",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if args.provider == "openai" and not args.confirm_real_openai:
        print("error: --provider openai requires --confirm-real-openai", file=sys.stderr)
        return 2

    for path in (args.runs_jsonl, args.summary_json, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"agentic_sandbox_batch: output exists: {path} (use --overwrite)", file=sys.stderr
            )
            return 2

    settings = get_settings()
    summary = build_agentic_batch_report(
        replay_jsonl=args.replay_jsonl,
        redacted_jsonl=args.redacted_jsonl,
        settings=settings,
        provider=args.provider,
        model=args.model,
        generate_fn=None,
        limit=args.limit,
        enable_langsmith=args.enable_langsmith,
        langsmith_project=args.langsmith_project,
        enable_knowledge_hints=args.enable_knowledge_hints,
        runs_jsonl=args.runs_jsonl,
        summary_json=args.summary_json,
        report_md=args.markdown_output,
    )

    print("agentic_sandbox_batch: success")
    print(f"  runs_jsonl={args.runs_jsonl.resolve()}")
    print(f"  summary={args.summary_json.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  first_vendor_rooms={summary.first_vendor_rooms}")
    print(f"  processed_count={summary.processed_count}")
    print(f"  success_count={summary.success_count}")
    print(f"  error_count={summary.error_count}")
    print(f"  execution_allowed_true_count={summary.execution_allowed_true_count}")
    print(f"  knowledge_hints_enabled={summary.knowledge_hints_enabled}")
    print(f"  knowledge_hint_coverage_rate={summary.knowledge_hint_coverage_rate:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

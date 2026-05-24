#!/usr/bin/env python3
"""Compare operator console vs agentic sandbox graph interpretation (diagnostics only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.console_graph_consistency import (
    DEFAULT_BATCH_JSONL,
    DEFAULT_BATCH_REPORT_MD,
    ConsoleGraphConsistencyBatchSummary,
    ConsoleGraphConsistencyResult,
    room_report_paths,
    run_console_graph_consistency_check,
    write_console_graph_consistency_batch_outputs,
    write_console_graph_consistency_outputs,
)
from app.operator_console.console_loader import DEFAULT_REDACTED_TICKETS_PATH, DEFAULT_REPLAY_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare console first-turn draft interpretation with agentic sandbox "
            "graph preview (no behavior changes)."
        ),
    )
    parser.add_argument("--room-id", type=str, default=None, help="Single room to check")
    parser.add_argument(
        "--replay-jsonl",
        type=Path,
        default=DEFAULT_REPLAY_PATH,
        help="AI assist shadow replay JSONL",
    )
    parser.add_argument(
        "--redacted-jsonl",
        type=Path,
        default=DEFAULT_REDACTED_TICKETS_PATH,
        help="Redacted ticket export JSONL",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="mock",
        help="Sandbox LLM provider (mock recommended for diagnostics)",
    )
    parser.add_argument(
        "--enable-knowledge-hints",
        action="store_true",
        help="Enable knowledge hints for console draft and sandbox graph",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max first-vendor rooms when --room-id omitted (default 20)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="JSON output path (default per-room or batch summary)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=None,
        help="Markdown output path (default per-room or batch report)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if args.room_id:
        json_path, md_path = room_report_paths(str(args.room_id).strip())
        json_path = args.json_output or json_path
        md_path = args.markdown_output or md_path
        for path in (json_path, md_path):
            if path.exists() and not args.overwrite:
                print(f"refusing to overwrite existing file: {path}", file=sys.stderr)
                return 1
        result = run_console_graph_consistency_check(
            room_id=args.room_id,
            replay_path=args.replay_jsonl,
            redacted_path=args.redacted_jsonl,
            provider=args.provider,
            knowledge_hints_enabled=args.enable_knowledge_hints,
        )
        if not isinstance(result, ConsoleGraphConsistencyResult):
            print("unexpected batch result for single room", file=sys.stderr)
            return 1
        write_console_graph_consistency_outputs(
            result,
            json_path=json_path,
            markdown_path=md_path,
        )
        print("console_graph_consistency: success")
        print(f"  room_id={result.room_id}")
        print(f"  status={result.consistency_status}")
        print(f"  json={json_path.resolve()}")
        print(f"  markdown={md_path.resolve()}")
        return 0

    jsonl_path = args.json_output or DEFAULT_BATCH_JSONL
    summary_path = Path("reports/console_graph_consistency_summary.json")
    if args.json_output and args.json_output.suffix == ".jsonl":
        jsonl_path = args.json_output
        summary_path = args.json_output.with_name("console_graph_consistency_summary.json")
    md_path = args.markdown_output or DEFAULT_BATCH_REPORT_MD
    for path in (jsonl_path, summary_path, md_path):
        if path.exists() and not args.overwrite:
            print(f"refusing to overwrite existing file: {path}", file=sys.stderr)
            return 1

    batch = run_console_graph_consistency_check(
        room_id=None,
        replay_path=args.replay_jsonl,
        redacted_path=args.redacted_jsonl,
        provider=args.provider,
        knowledge_hints_enabled=args.enable_knowledge_hints,
        limit=args.limit,
    )
    if not isinstance(batch, ConsoleGraphConsistencyBatchSummary):
        print("unexpected single-room result for batch run", file=sys.stderr)
        return 1
    write_console_graph_consistency_batch_outputs(
        batch,
        jsonl_path=jsonl_path,
        summary_json_path=summary_path,
        markdown_path=md_path,
    )
    print("console_graph_consistency_batch: success")
    print(f"  rooms={batch.room_count}")
    print(f"  status_counts={batch.status_counts}")
    print(f"  jsonl={jsonl_path.resolve()}")
    print(f"  summary={summary_path.resolve()}")
    print(f"  markdown={md_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

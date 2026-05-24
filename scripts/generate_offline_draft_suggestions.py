#!/usr/bin/env python3
"""Generate offline internal draft reply suggestions from historical benchmark cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.config import get_settings
from app.evals.offline_draft_generation import generate_offline_draft_suggestions

_DEFAULT_INPUT = Path("reports/historical_reply_benchmark_v1.jsonl")
_DEFAULT_JSONL = Path("reports/offline_draft_suggestions_v1.jsonl")
_DEFAULT_SUMMARY = Path("reports/offline_draft_suggestions_summary.json")


def resolve_benchmark_input_path(
    *,
    input_flag: Path,
    positional: Path | None,
) -> Path:
    """Positional benchmark path wins when set; otherwise use ``--input`` (or its default)."""
    if positional is not None:
        return positional
    return input_flag


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline draft suggestion MVP (Step 171): benchmark snapshot + intent + "
            "policy hints → internal Persian drafts in gitignored reports/. "
            "No customer send, no operator console, no gold reply in prompts."
        ),
    )
    parser.add_argument(
        "--input",
        dest="input_path",
        type=Path,
        default=_DEFAULT_INPUT,
        help=(
            "Historical reply benchmark JSONL "
            "(default: reports/historical_reply_benchmark_v1.jsonl)"
        ),
    )
    parser.add_argument(
        "benchmark_positional",
        nargs="?",
        type=Path,
        default=None,
        metavar="input_path",
        help="Benchmark JSONL path (positional alternative to --input)",
    )
    parser.add_argument(
        "--output-jsonl",
        "--output",
        dest="output_jsonl",
        type=Path,
        default=_DEFAULT_JSONL,
        help="Output draft suggestions JSONL (default: reports/offline_draft_suggestions_v1.jsonl)",
    )
    parser.add_argument(
        "--output-summary",
        "--summary-output",
        dest="output_summary",
        type=Path,
        default=_DEFAULT_SUMMARY,
        help="Output summary JSON (default: reports/offline_draft_suggestions_summary.json)",
    )
    parser.add_argument(
        "--provider",
        choices=("mock", "openai"),
        default=os.environ.get("LLM_PROVIDER", "mock").strip().lower() or "mock",
        help="LLM provider (default: mock or LLM_PROVIDER env)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("LLM_MODEL", "mock-vendor-ticket-drafter"),
        help="LLM model name",
    )
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required when --provider openai (uses OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N benchmark cases (local smoke)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing output files",
    )
    parser.add_argument(
        "--write-prompt-audit",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Optional safe prompt audit JSONL (metadata only; no full prompt bodies). "
            "Default path when flag alone: reports/offline_draft_prompt_audit.jsonl"
        ),
        nargs="?",
        const=Path("reports/offline_draft_prompt_audit.jsonl"),
    )
    args = parser.parse_args(argv)
    input_path = resolve_benchmark_input_path(
        input_flag=args.input_path,
        positional=args.benchmark_positional,
    )

    if args.provider == "openai" and not args.confirm_real_openai:
        print(
            "error: --provider openai requires --confirm-real-openai",
            file=sys.stderr,
        )
        return 2
    if args.provider == "openai" and not os.environ.get("OPENAI_API_KEY", "").strip():
        print("error: OPENAI_API_KEY is required for openai provider", file=sys.stderr)
        return 2

    if not input_path.is_file():
        print(f"error: input not found: {input_path}", file=sys.stderr)
        return 2

    for path in (args.output_jsonl, args.output_summary):
        if path.exists() and not args.overwrite:
            print(f"error: output exists (use --overwrite): {path}", file=sys.stderr)
            return 2

    settings = get_settings()
    if not settings.knowledge_hints_enabled:
        print(
            "note: KNOWLEDGE_HINTS_ENABLED is false; drafts will run without policy hints",
            file=sys.stderr,
        )

    stats = generate_offline_draft_suggestions(
        input_path,
        output_jsonl_path=args.output_jsonl,
        output_summary_path=args.output_summary,
        provider=args.provider,
        model=args.model,
        settings=settings,
        limit=args.limit,
        prompt_audit_path=args.write_prompt_audit,
    )
    print(json.dumps(stats.to_json_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

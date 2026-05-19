#!/usr/bin/env python3
"""Run shadow vendor-ticket AI assist on a sanitized replay row or minimal state JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.workflows.vendor_ticket_ai_assist_shadow import evaluate_vendor_ticket_ai_assist_shadow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Shadow vendor-ticket AI operational assist (HITL-only suggestions). "
            "No LangGraph, no customer messages, no retrieval content."
        ),
    )
    parser.add_argument(
        "input_json",
        type=Path,
        help="Sanitized shadow replay row or minimal state JSON (aggregate fields only)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for assist JSON (gitignored reports/ recommended)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output file")
    args = parser.parse_args(argv)

    if not args.input_json.is_file():
        print(
            f"run_vendor_ticket_ai_assist_shadow: missing input {args.input_json}",
            file=sys.stderr,
        )
        return 1

    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        print("run_vendor_ticket_ai_assist_shadow: input must be a JSON object", file=sys.stderr)
        return 1

    try:
        result = evaluate_vendor_ticket_ai_assist_shadow(payload)
    except ValueError as exc:
        print(f"run_vendor_ticket_ai_assist_shadow: {exc}", file=sys.stderr)
        return 1

    output_text = result.model_dump_json(indent=2)
    print(output_text)

    if args.output is not None:
        if args.output.exists() and not args.overwrite:
            print(
                f"run_vendor_ticket_ai_assist_shadow: {args.output} exists (use --overwrite)",
                file=sys.stderr,
            )
            return 1
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

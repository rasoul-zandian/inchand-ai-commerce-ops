#!/usr/bin/env python3
"""Build sample HITL read-only payloads from sanitized AI assist shadow replay JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.hitl.hitl_payload_builder import (
    assert_hitl_payload_ready,
    build_hitl_read_only_payload_from_replay_row,
)

_DEFAULT_INPUT = Path("reports/ai_assist_shadow_replay_v1.jsonl")
_DEFAULT_OUTPUT = Path("reports/hitl_read_only_payload_sample.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build sample HITL read-only panel payloads from sanitized replay JSONL "
            "(aggregate fields only; no raw content)."
        ),
    )
    parser.add_argument(
        "input_path",
        type=Path,
        nargs="?",
        default=_DEFAULT_INPUT,
        help="AI assist shadow replay JSONL path",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Output JSON array path (gitignored reports/ recommended)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of replay rows to convert (default: 5)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output file")
    args = parser.parse_args(argv)

    if not args.input_path.is_file():
        print(
            f"build_hitl_read_only_payload_sample: file not found: {args.input_path}",
            file=sys.stderr,
        )
        return 1

    if args.output.exists() and not args.overwrite:
        print(
            f"build_hitl_read_only_payload_sample: output exists: {args.output} (use --overwrite)",
            file=sys.stderr,
        )
        return 1

    if args.limit < 1:
        print("build_hitl_read_only_payload_sample: --limit must be >= 1", file=sys.stderr)
        return 1

    payloads: list[dict[str, object]] = []
    for line_number, raw_line in enumerate(
        args.input_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if len(payloads) >= args.limit:
            break
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            msg = (
                f"build_hitl_read_only_payload_sample: invalid JSON on line "
                f"{line_number}: {exc.msg}"
            )
            print(msg, file=sys.stderr)
            return 1
        if not isinstance(row, dict):
            print(
                f"build_hitl_read_only_payload_sample: line {line_number} must be a JSON object",
                file=sys.stderr,
            )
            return 1
        try:
            payload = build_hitl_read_only_payload_from_replay_row(row)
            assert_hitl_payload_ready(payload)
        except ValueError as exc:
            print(
                f"build_hitl_read_only_payload_sample: line {line_number}: {exc}",
                file=sys.stderr,
            )
            return 1
        payloads.append(payload)

    if not payloads:
        print("build_hitl_read_only_payload_sample: no rows converted", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_text = json.dumps(payloads, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(output_text, encoding="utf-8")

    print("build_hitl_read_only_payload_sample: success")
    print(f"  input={args.input_path.resolve()}")
    print(f"  output={args.output.resolve()}")
    print(f"  payload_count={len(payloads)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

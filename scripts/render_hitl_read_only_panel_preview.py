#!/usr/bin/env python3
"""Render local read-only HITL panel preview Markdown from safe payloads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.hitl.hitl_payload_builder import (
    assert_hitl_payload_ready,
    build_hitl_read_only_payload_from_replay_row,
)
from app.hitl.hitl_read_only_panel_preview import render_hitl_payloads_markdown

_DEFAULT_JSON = Path("reports/hitl_read_only_payload_sample.json")
_DEFAULT_JSONL = Path("reports/ai_assist_shadow_replay_v1.jsonl")
_DEFAULT_OUTPUT = Path("reports/hitl_read_only_panel_preview.md")


def _load_payloads(path: Path, *, limit: int | None) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"input file is empty: {path}")

    if path.suffix == ".jsonl":
        payloads: list[dict[str, object]] = []
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            if limit is not None and len(payloads) >= limit:
                break
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            if not isinstance(row, dict):
                msg = f"line {line_number}: row must be a JSON object"
                raise ValueError(msg)
            payloads.append(build_hitl_read_only_payload_from_replay_row(row))
        return payloads

    data = json.loads(text)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = [data]
    else:
        raise ValueError("JSON input must be an object or array of HITL payloads")

    payloads = []
    for index, item in enumerate(items):
        if limit is not None and len(payloads) >= limit:
            break
        if not isinstance(item, dict):
            raise ValueError(f"payload at index {index} must be a JSON object")
        payloads.append(item)
    return payloads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render local read-only HITL panel preview Markdown (mock only; no web UI or FastAPI)."
        ),
    )
    parser.add_argument(
        "input_path",
        type=Path,
        nargs="?",
        default=None,
        help="JSON array of HITL payloads or JSONL replay rows",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Markdown preview output path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max tickets to render (JSONL or JSON array)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output")
    args = parser.parse_args(argv)

    input_path = args.input_path
    if input_path is None:
        if _DEFAULT_JSON.is_file():
            input_path = _DEFAULT_JSON
        elif _DEFAULT_JSONL.is_file():
            input_path = _DEFAULT_JSONL
        else:
            print(
                "render_hitl_read_only_panel_preview: provide input_path or create "
                f"{_DEFAULT_JSON} / {_DEFAULT_JSONL}",
                file=sys.stderr,
            )
            return 1

    if not input_path.is_file():
        print(
            f"render_hitl_read_only_panel_preview: file not found: {input_path}",
            file=sys.stderr,
        )
        return 1

    if args.output.exists() and not args.overwrite:
        print(
            f"render_hitl_read_only_panel_preview: output exists: {args.output} (use --overwrite)",
            file=sys.stderr,
        )
        return 1

    try:
        payloads = _load_payloads(input_path, limit=args.limit)
        for payload in payloads:
            assert_hitl_payload_ready(payload)
        markdown = render_hitl_payloads_markdown(payloads)
    except ValueError as exc:
        print(f"render_hitl_read_only_panel_preview: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")

    print("render_hitl_read_only_panel_preview: success")
    print(f"  input={input_path.resolve()}")
    print(f"  output={args.output.resolve()}")
    print(f"  ticket_count={len(payloads)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

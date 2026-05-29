#!/usr/bin/env python3
"""Manual CLI for Iran Post tracking verification (read-only; not CI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.tools.tracking.iran_post_tracking import (
    assert_private_raw_output_path,
    assert_safe_tracking_result_payload,
    build_iran_post_request_payload,
    normalize_iran_post_tracking_code_field,
    normalize_tracking_code,
    resolve_tracking_code_from_text,
    verify_iran_post_tracking_code,
)

DEFAULT_SUMMARY_PATH = Path("reports/iran_post_tracking_check_summary.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Iran Post tracking code via Ayantech Core API (manual only).",
    )
    parser.add_argument(
        "--tracking-code",
        required=True,
        help="Iran Post tracking code or seller message containing a code",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="Safe summary JSON path (default: reports/...)",
    )
    parser.add_argument(
        "--raw-private-output",
        type=Path,
        default=None,
        help="Optional raw JSON under data/private/ only",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Do not write raw API response even if --raw-private-output is set",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output files")
    parser.add_argument(
        "--debug-extraction",
        action="store_true",
        help="Print extraction diagnostics (no token)",
    )
    parser.add_argument(
        "--code-field",
        choices=("TraceNumber", "PackageNumber", "both"),
        default=None,
        help=(
            "Override IRAN_POST_TRACKING_CODE_FIELD (default PackageNumber). "
            "Use TraceNumber or both only for API diagnostics."
        ),
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.iran_post_tracking_enabled:
        print("error: IRAN_POST_TRACKING_ENABLED is false", file=sys.stderr)
        return 2
    if not (settings.iran_post_tracking_token or "").strip():
        print("error: IRAN_POST_TRACKING_TOKEN is not set", file=sys.stderr)
        return 2

    code_field = (
        normalize_iran_post_tracking_code_field(args.code_field)
        if args.code_field
        else settings.iran_post_tracking_code_field
    )
    selected, diagnostics = resolve_tracking_code_from_text(
        args.tracking_code,
        code_field=code_field,
    )
    normalized_input = normalize_tracking_code(args.tracking_code)
    selected_code = selected or normalized_input

    if args.debug_extraction:
        print("--- extraction debug ---")
        print(f"normalized_input: {normalized_input}")
        print(f"selected_code: {selected_code}")
        print(f"selection_reason: {diagnostics.selected_candidate_reason}")
        print(f"candidates_found: {diagnostics.numeric_candidates_found}")
        print(f"normalized_candidates: {list(diagnostics.normalized_candidates)}")
        if diagnostics.rejected_candidates:
            print("rejected:")
            for code, reason in diagnostics.rejected_candidates:
                print(f"  {code}: {reason}")
        _, param_summary = build_iran_post_request_payload(
            selected_code,
            (settings.iran_post_tracking_token or "").strip(),
            code_field=code_field,
        )
        print(f"code_field_mode: {code_field}")
        print(f"payload TraceNumber: {param_summary.get('TraceNumber')!r}")
        print(f"payload PackageNumber: {param_summary.get('PackageNumber')!r}")

    result = verify_iran_post_tracking_code(
        args.tracking_code,
        settings=settings,
        code_field_override=code_field,
    )
    summary = result.to_safe_dict()
    assert_safe_tracking_result_payload(summary)

    if args.debug_extraction:
        print("--- api result (safe) ---")
        print(f"status_code: {result.status_code}")
        print(f"status_description: {result.status_description}")
        print(f"verified: {result.verified}")
        print(f"event_count: {result.event_count}")
        print("--- full safe summary json ---")

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    summary_path = args.summary_output
    if summary_path.exists() and not args.overwrite:
        print(f"error: {summary_path} exists (use --overwrite)", file=sys.stderr)
        return 2
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    summary_path.write_text(summary_text, encoding="utf-8")

    if args.raw_private_output and not args.no_raw:
        raw_path = assert_private_raw_output_path(args.raw_private_output)
        if raw_path.exists() and not args.overwrite:
            print(f"error: {raw_path} exists (use --overwrite)", file=sys.stderr)
            return 2
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_payload = {
            "tracking_code": result.tracking_code,
            "verified": result.verified,
            "status_code": result.status_code,
            "status_description": result.status_description,
            "event_count": result.event_count,
        }
        raw_path.write_text(
            json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return 0 if result.error_type is None else 1


if __name__ == "__main__":
    raise SystemExit(main())

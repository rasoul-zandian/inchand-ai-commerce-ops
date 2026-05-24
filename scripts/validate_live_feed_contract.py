#!/usr/bin/env python3
"""Validate a live vendor ticket JSONL file against the live feed adapter contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.live_shadow.live_feed_contract import (
    DEFAULT_VALIDATION_REPORT_PATH,
    DEFAULT_VALIDATION_SUMMARY_PATH,
    resolve_allow_raw_pii_internal_pilot,
    summarize_live_feed_contract_validation,
    write_live_feed_contract_validation_reports,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate live feed JSONL against the live feed adapter contract.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Live feed JSONL path (e.g. data/private/live_vendor_tickets.jsonl)",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_VALIDATION_SUMMARY_PATH,
        help="JSON summary output path",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_VALIDATION_REPORT_PATH,
        help="Markdown report output path",
    )
    parser.add_argument(
        "--reject-raw-pii",
        action="store_true",
        help="Reject raw phone/IBAN/email/card (strict mode; default allows for internal pilot)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing report files",
    )
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"live_feed_contract: source not found: {args.source}", file=sys.stderr)
        return 2

    for path in (args.summary_json, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"live_feed_contract: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    settings = get_settings()
    allow_raw_pii = resolve_allow_raw_pii_internal_pilot(
        allow_raw_pii_internal_pilot=not args.reject_raw_pii,
        settings=settings,
    )
    summary = summarize_live_feed_contract_validation(
        args.source,
        allow_raw_pii_internal_pilot=allow_raw_pii,
        settings=settings,
    )
    write_live_feed_contract_validation_reports(
        summary,
        summary_json=args.summary_json,
        report_md=args.markdown_output,
    )

    print("live_feed_contract: success")
    print(f"  passed={summary.passed}")
    print(f"  allow_raw_pii_internal_pilot={summary.allow_raw_pii_internal_pilot}")
    print(f"  valid_rows={summary.valid_rows}")
    print(f"  invalid_rows={summary.invalid_rows}")
    print(f"  warning_rows={summary.warning_rows}")
    print(f"  info_rows={summary.info_rows}")
    print(f"  summary_json={args.summary_json.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    return 0 if summary.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

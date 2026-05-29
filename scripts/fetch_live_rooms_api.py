#!/usr/bin/env python3
"""Fetch live rooms from Inchand internal API and write normalized JSONL (read-only)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.config import get_settings
from app.live_shadow.live_feed_contract import (
    DEFAULT_VALIDATION_REPORT_PATH,
    DEFAULT_VALIDATION_SUMMARY_PATH,
)
from app.live_shadow.live_rooms_fetch_service import fetch_and_prepare_live_rooms_feed
from app.operator_console.live_feed_loader import DEFAULT_LIVE_ROOMS_FETCH_LIMIT

DEFAULT_RAW_OUTPUT = Path("data/private/live_rooms_raw.json")
DEFAULT_NORMALIZED_OUTPUT = Path("data/private/live_vendor_tickets.jsonl")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch live rooms (read-only), normalize to live feed JSONL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"Max rooms to fetch (default: settings, typically {DEFAULT_LIVE_ROOMS_FETCH_LIMIT}).",
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=DEFAULT_RAW_OUTPUT,
        help="Raw API JSON archive path (must stay under data/private/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_NORMALIZED_OUTPUT,
        help="Normalized JSONL output path (must stay under data/private/).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing output files.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run live feed contract validation and write reports under reports/.",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_VALIDATION_SUMMARY_PATH,
        help="Validation summary JSON path.",
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=DEFAULT_VALIDATION_REPORT_PATH,
        help="Validation markdown report path.",
    )
    parser.add_argument(
        "--allow-non-private-output",
        action="store_true",
        help="Test-only: skip private-path guard.",
    )
    parser.add_argument(
        "--token-env",
        default="LIVE_ROOMS_API_TOKEN",
        help="Environment variable for bearer token (default: LIVE_ROOMS_API_TOKEN).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()
    token = os.environ.get(args.token_env, "").strip()
    if token:
        settings = settings.model_copy(update={"live_rooms_api_token": token})

    result = fetch_and_prepare_live_rooms_feed(
        limit=args.limit,
        overwrite=args.overwrite,
        validate=args.validate,
        settings=settings,
        raw_output=args.raw_output,
        normalized_output=args.output,
        summary_json=args.summary_json,
        report_md=args.report_md,
        allow_non_private_output=args.allow_non_private_output,
    )

    for warning in result.fetch_warnings:
        print(f"fetch_live_rooms_api: warning: {warning}", file=sys.stderr)
    for err in result.normalize_errors:
        print(f"fetch_live_rooms_api: normalize warning: {err}", file=sys.stderr)

    if result.error_message:
        print(f"fetch_live_rooms_api: {result.error_message}", file=sys.stderr)

    if result.success:
        print(
            f"fetch_live_rooms_api: wrote {result.tickets_written} tickets "
            f"from {result.rooms_fetched} rooms -> {result.normalized_output}",
        )
        if result.validation_passed is not None:
            print(
                f"fetch_live_rooms_api: validation "
                f"{'passed' if result.validation_passed else 'failed'} "
                f"({result.valid_rows} valid, {result.invalid_rows} invalid)",
            )
            if result.summary_json:
                print(f"fetch_live_rooms_api: summary -> {result.summary_json}")
            if result.report_md:
                print(f"fetch_live_rooms_api: report -> {result.report_md}")
        return 0

    if result.tickets_written == 0 and result.rooms_fetched >= 0:
        if result.error_message and "No tickets normalized" in result.error_message:
            return 1
        if result.error_message == "توکن API تنظیم نشده است.":
            return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

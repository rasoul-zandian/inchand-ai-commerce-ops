#!/usr/bin/env python3
"""Manual CLI for Inchand internal order lookup (read-only; not CI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.tools.inchand.order_lookup import (
    assert_private_order_raw_output_path,
    assert_safe_order_lookup_payload,
    lookup_inchand_order,
    normalize_inchand_order_id,
)

DEFAULT_SUMMARY_PATH = Path("reports/inchand_order_lookup_summary.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Look up Inchand order by id via internal API (manual only).",
    )
    parser.add_argument(
        "--order-id",
        required=True,
        help="Inchand order id (INC-####### or 7-digit) or text containing one",
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
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.inchand_order_lookup_enabled:
        print("error: INCHAND_ORDER_LOOKUP_ENABLED is false", file=sys.stderr)
        return 2
    from app.tools.inchand.order_lookup import resolve_inchand_api_token

    if not resolve_inchand_api_token(settings):
        print(
            "error: INCHAND_API_KEY_VALUE or LIVE_ROOMS_API_TOKEN is not set",
            file=sys.stderr,
        )
        return 2

    captured_raw: dict[str, object] = {}

    def _capturing_get(url: str, headers: dict[str, str], timeout: float) -> dict:
        from app.tools.inchand.order_lookup import http_get_order_json

        payload = dict(http_get_order_json(url, headers, timeout))
        captured_raw["response"] = payload
        return payload

    result = lookup_inchand_order(
        args.order_id,
        settings=settings,
        http_client=_capturing_get,
    )
    summary = result.to_safe_dict()
    assert_safe_order_lookup_payload(summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    summary_path = args.summary_output
    if summary_path.exists() and not args.overwrite:
        print(f"error: {summary_path} exists (use --overwrite)", file=sys.stderr)
        return 2
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.raw_private_output and not args.no_raw:
        raw_path = assert_private_order_raw_output_path(args.raw_private_output)
        if raw_path.exists() and not args.overwrite:
            print(f"error: {raw_path} exists (use --overwrite)", file=sys.stderr)
            return 2
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        order_norm = normalize_inchand_order_id(args.order_id) or result.order_id
        raw_payload = {
            "order_id": order_norm,
            "request_url_suffix": f"/orders/{order_norm}",
            "response": captured_raw.get("response"),
        }
        raw_path.write_text(
            json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return 0 if result.error_type is None else 1


if __name__ == "__main__":
    raise SystemExit(main())

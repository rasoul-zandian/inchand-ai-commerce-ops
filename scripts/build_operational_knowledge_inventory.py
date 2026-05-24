#!/usr/bin/env python3
"""Build combined operational knowledge inventory (official policy + historical memory)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.knowledge.historical_ticket_memory import (
    build_historical_ticket_memory_inventory,
    load_historical_reply_benchmark_summary,
)
from app.knowledge.knowledge_loader import (
    build_knowledge_inventory,
    knowledge_document_to_dict,
)

_DEFAULT_OFFICIAL = Path("data/private/knowledge/operations")
_DEFAULT_BENCHMARK_SUMMARY = Path("reports/historical_reply_benchmark_summary.json")
_DEFAULT_JSON_OUT = Path("reports/operational_knowledge_inventory.json")
_DEFAULT_MD_OUT = Path("reports/operational_knowledge_inventory.md")


def _render_markdown(
    *,
    official_docs: list[dict[str, object]],
    historical: dict[str, object],
    warnings: list[str],
    generated_at: str,
) -> str:
    lines = [
        "# Operational knowledge inventory",
        "",
        f"_Generated (UTC): {generated_at}_",
        "",
        "## Policy precedence",
        "",
        "**Official policy** is authoritative. **Historical ticket memory** is reference",
        "experience only; if they conflict, **official policy wins**.",
        "",
        "## Official policy lane",
        "",
        f"Document count: **{len(official_docs)}**",
        "",
        "| doc_id | title | type | language | sections | chars |",
        "|--------|-------|------|----------|----------|-------|",
    ]
    for row in official_docs:
        lines.append(
            f"| {row['doc_id']} | {row['title']} | {row['document_type']} | "
            f"{row['language']} | {row['section_count']} | {row['char_count']} |",
        )
    lines += [
        "",
        "## Historical memory lane (aggregates only)",
        "",
        "No gold replies or ticket bodies in this report — counts from benchmark summary only.",
        "",
        "```json",
        json.dumps(historical, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Warnings",
        "",
    ]
    if warnings:
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("_None._")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan official knowledge markdown and historical benchmark summary; "
            "write inventory JSON + Markdown under reports/ (gitignored)."
        ),
    )
    parser.add_argument(
        "--official-path",
        type=Path,
        default=_DEFAULT_OFFICIAL,
        help="Directory of official *.md knowledge files",
    )
    parser.add_argument(
        "--benchmark-summary",
        type=Path,
        default=_DEFAULT_BENCHMARK_SUMMARY,
        help="Path to historical_reply_benchmark_summary.json",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=_DEFAULT_JSON_OUT,
        help="Output JSON path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=_DEFAULT_MD_OUT,
        help="Output Markdown path",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    for path in (args.output_json, args.output_md):
        if path.exists() and not args.overwrite:
            print(f"error: output exists (use --overwrite): {path}", file=sys.stderr)
            return 2

    warnings: list[str] = [
        "Private operational markdown under data/private/ is not committed; "
        "copy from docs/templates/knowledge/*.md.example after internal review.",
    ]

    official_inv = build_knowledge_inventory(args.official_path)
    warnings.extend(official_inv.warnings)
    if not args.official_path.is_dir():
        warnings.append(
            f"Official knowledge directory missing or not a directory: {args.official_path}",
        )
    elif not official_inv.documents:
        warnings.append(
            "No valid official knowledge documents found "
            f"(expected markdown under {args.official_path}).",
        )

    summary_raw = load_historical_reply_benchmark_summary(args.benchmark_summary)
    if summary_raw is None:
        warnings.append(
            f"Historical benchmark summary not found or unreadable: {args.benchmark_summary}",
        )

    hist = build_historical_ticket_memory_inventory(
        summary_raw,
        source_summary_path=str(args.benchmark_summary.resolve())
        if args.benchmark_summary.is_file()
        else None,
    )
    if hist.total_cases == 0 and summary_raw is None:
        warnings.append("Historical case count is zero (no summary loaded).")

    generated = datetime.now(UTC).replace(microsecond=0).isoformat()
    official_rows = [knowledge_document_to_dict(d) for d in official_inv.documents]
    historical_dict = hist.to_json_dict()

    payload = {
        "generated_at_utc": generated,
        "conflict_resolution": "official_policy_overrides_historical_memory",
        "official_doc_count": len(official_inv.documents),
        "historical_case_count": hist.total_cases,
        "lanes": {
            "official_policy": {
                "documents": official_rows,
                "loader_warnings": list(official_inv.warnings),
            },
            "historical_memory": historical_dict,
        },
        "warnings": warnings,
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md = _render_markdown(
        official_docs=official_rows,
        historical=historical_dict,
        warnings=warnings,
        generated_at=generated,
    )
    args.output_md.write_text(md, encoding="utf-8")
    print(
        json.dumps(
            {"written_json": str(args.output_json), "written_md": str(args.output_md)},
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

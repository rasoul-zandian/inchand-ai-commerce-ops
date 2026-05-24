#!/usr/bin/env python3
"""Build dual-lane knowledge chunk preview (official policy + historical aggregates)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.knowledge.knowledge_chunking import (
    build_combined_knowledge_chunks,
    summarize_knowledge_chunks,
    write_chunks_jsonl,
)

_DEFAULT_OFFICIAL = Path("data/private/knowledge/operations")
_DEFAULT_HISTORICAL = Path("reports/historical_reply_benchmark_summary.json")
_DEFAULT_JSONL = Path("reports/knowledge_chunks_preview.jsonl")
_DEFAULT_SUMMARY_JSON = Path("reports/knowledge_chunks_summary.json")
_DEFAULT_SUMMARY_MD = Path("reports/knowledge_chunks_summary.md")


def _render_markdown(summary: dict[str, object], generated_at: str) -> str:
    lines = [
        "# Knowledge chunks summary",
        "",
        f"_Generated (UTC): {generated_at}_",
        "",
        "## Precedence",
        "",
        f"**{summary.get('conflict_resolution')}** — official policy chunks use "
        f"priority_rank **{summary.get('official_policy_priority_rank')}**; "
        f"historical memory uses **{summary.get('historical_memory_priority_rank')}**.",
        "",
        "## Counts",
        "",
        f"- **total_chunks:** {summary.get('total_chunks')}",
        f"- **official_policy_chunk_count:** {summary.get('official_policy_chunk_count')}",
        f"- **historical_memory_chunk_count:** {summary.get('historical_memory_chunk_count')}",
        f"- **skipped_unsafe:** {summary.get('skipped_unsafe')}",
        f"- **average_chunk_size:** {summary.get('average_chunk_size')}",
        f"- **max_chunk_size:** {summary.get('max_chunk_size')}",
        "",
        "## By source lane",
        "",
        "```json",
        json.dumps(summary.get("chunks_by_source_lane"), ensure_ascii=False, indent=2),
        "```",
        "",
        "## By document type",
        "",
        "```json",
        json.dumps(summary.get("chunks_by_document_type"), ensure_ascii=False, indent=2),
        "```",
        "",
        "_No embeddings or pgvector indexing in this step — preview JSONL only._",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Chunk official policy markdown and historical benchmark aggregates "
            "for future retrieval metadata (no embedding/index)."
        ),
    )
    parser.add_argument(
        "--official-path",
        type=Path,
        default=_DEFAULT_OFFICIAL,
        help="Official knowledge markdown directory",
    )
    parser.add_argument(
        "--historical-summary",
        type=Path,
        default=_DEFAULT_HISTORICAL,
        help="historical_reply_benchmark_summary.json path",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=_DEFAULT_JSONL,
        help="Preview JSONL output path",
    )
    parser.add_argument(
        "--output-summary-json",
        type=Path,
        default=_DEFAULT_SUMMARY_JSON,
    )
    parser.add_argument(
        "--output-summary-md",
        type=Path,
        default=_DEFAULT_SUMMARY_MD,
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    for path in (args.output_jsonl, args.output_summary_json, args.output_summary_md):
        if path.exists() and not args.overwrite:
            print(f"error: output exists (use --overwrite): {path}", file=sys.stderr)
            return 2

    chunks, skipped = build_combined_knowledge_chunks(
        official_path=args.official_path,
        historical_summary_path=args.historical_summary,
    )
    summary = summarize_knowledge_chunks(
        chunks,
        skipped_unsafe=skipped,
        official_path=str(args.official_path.resolve()),
        historical_summary_path=str(args.historical_summary.resolve())
        if args.historical_summary.is_file()
        else str(args.historical_summary),
    )
    generated = datetime.now(UTC).replace(microsecond=0).isoformat()
    summary["generated_at_utc"] = generated

    write_chunks_jsonl(chunks, args.output_jsonl)
    args.output_summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_summary_md.write_text(
        _render_markdown(summary, generated),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

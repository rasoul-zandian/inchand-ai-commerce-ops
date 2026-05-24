#!/usr/bin/env python3
"""Index operational knowledge chunks into sandbox pgvector (local DB only)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from app.knowledge.knowledge_embedding_index import (
    assert_safe_knowledge_output,
    build_knowledge_vector_records,
    generate_knowledge_embeddings,
    index_knowledge_chunks_pgvector,
    load_knowledge_chunks,
    summarize_knowledge_indexing,
)

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
_DEFAULT_JSONL = Path("reports/knowledge_chunks_preview.jsonl")
_DEFAULT_SUMMARY = Path("reports/knowledge_pgvector_indexing_summary.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sandbox pgvector index for operational knowledge chunks.",
    )
    parser.add_argument(
        "chunks_jsonl",
        type=Path,
        nargs="?",
        default=_DEFAULT_JSONL,
        help="knowledge_chunks_preview.jsonl path",
    )
    parser.add_argument(
        "--namespace",
        required=True,
        help="Sandbox namespace (e.g. knowledge_operations_sandbox)",
    )
    parser.add_argument(
        "--index-version",
        required=True,
        help="Index version label (e.g. knowledge_v1)",
    )
    parser.add_argument("--provider", default="mock", choices=("mock", "openai"))
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--dimensions", type=int, default=1536)
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required when --provider openai",
    )
    parser.add_argument(
        "--confirm-sandbox",
        action="store_true",
        help="Required explicit approval for sandbox DB writes",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=_DEFAULT_SUMMARY,
    )
    parser.add_argument("--dry-run", action="store_true", help="Build records only; no DB upsert")
    args = parser.parse_args(argv)

    if not args.confirm_sandbox:
        print("index_knowledge_chunks_pgvector: --confirm-sandbox is required", file=sys.stderr)
        return 1

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    table_name = os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip()

    try:
        chunks = load_knowledge_chunks(args.chunks_jsonl)
        batch = generate_knowledge_embeddings(
            chunks,
            provider=args.provider,
            model=args.model,
            dimensions=args.dimensions,
            confirm_real_openai=args.confirm_real_openai,
        )
        records = build_knowledge_vector_records(
            batch,
            namespace=args.namespace,
            index_version=args.index_version,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"index_knowledge_chunks_pgvector: {exc}", file=sys.stderr)
        return 1

    skipped_unsafe = 0
    by_lane = Counter(c.chunk.source_lane.value for c in chunks)

    if args.dry_run:
        indexed = len(records)
    else:
        try:
            indexed = index_knowledge_chunks_pgvector(
                records,
                database_url=database_url,
                table_name=table_name,
                dimensions=args.dimensions,
            )
        except Exception as exc:
            print(f"index_knowledge_chunks_pgvector: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    summary = summarize_knowledge_indexing(
        indexed_count=indexed,
        namespace=args.namespace,
        index_version=args.index_version,
        provider=batch.provider,
        model=batch.model,
        dimensions=batch.dimensions,
        chunk_count=len(chunks),
        skipped_unsafe=skipped_unsafe,
        chunks_by_source_lane=dict(by_lane),
    )
    summary["dry_run"] = args.dry_run
    summary["database_table"] = table_name

    args.summary_path.parent.mkdir(parents=True, exist_ok=True)
    args.summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    output = json.dumps(summary, ensure_ascii=False, indent=2)
    assert_safe_knowledge_output(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

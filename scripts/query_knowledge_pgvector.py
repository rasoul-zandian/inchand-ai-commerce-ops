#!/usr/bin/env python3
"""Sandbox knowledge retrieval smoke query (priority-aware ranking; safe output)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.knowledge.knowledge_embedding_index import (
    assert_safe_knowledge_output,
    query_knowledge_pgvector,
)

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
_DEFAULT_OUTPUT = Path("reports/knowledge_query_smoke.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Query sandbox knowledge pgvector index. "
            "Ranks official_policy (priority 10) before historical_memory (priority 1), "
            "then by vector score."
        ),
    )
    parser.add_argument("--query", required=True, help="Query text (Persian/English)")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--index-version", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--provider", default="mock", choices=("mock", "openai"))
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--dimensions", type=int, default=1536)
    parser.add_argument("--confirm-real-openai", action="store_true")
    parser.add_argument("--confirm-sandbox", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    if not args.confirm_sandbox:
        print("query_knowledge_pgvector: --confirm-sandbox is required", file=sys.stderr)
        return 1

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    table_name = os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip()

    try:
        hits = query_knowledge_pgvector(
            args.query,
            namespace=args.namespace,
            index_version=args.index_version,
            database_url=database_url,
            table_name=table_name,
            dimensions=args.dimensions,
            top_k=args.top_k,
            provider=args.provider,
            model=args.model,
            confirm_real_openai=args.confirm_real_openai,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"query_knowledge_pgvector: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"query_knowledge_pgvector: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    payload = {
        "namespace": args.namespace,
        "index_version": args.index_version,
        "top_k": args.top_k,
        "ranking_policy": "priority_rank_desc_then_score_desc",
        "conflict_resolution": "official_policy_overrides_historical_memory",
        "hits": hits,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    assert_safe_knowledge_output(text)
    print(text)

    if args.output is not None:
        if args.output.exists() and not args.overwrite:
            print(f"error: output exists (use --overwrite): {args.output}", file=sys.stderr)
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

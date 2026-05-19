#!/usr/bin/env python3
"""Dry-run sandbox retrieval chain: policy gate → executor → state snapshot (no LangGraph)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.corpus_planning.sandbox_retrieval_chain_dry_run import (
    SandboxRetrievalChainDryRunConfig,
    assert_safe_chain_output,
    format_snapshot_json,
    format_snapshot_summary,
    run_sandbox_retrieval_chain_dry_run,
)
from app.embeddings import generate_embedding

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
_OPENAI_PROVIDER = "openai"
_OPENAI_MODEL = "text-embedding-3-small"


def _openai_query_embedding_fn(text: str) -> list[float]:
    embedding = generate_embedding(
        text,
        provider=_OPENAI_PROVIDER,
        model=_OPENAI_MODEL,
    )
    return embedding.vector


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run sandbox retrieval chain (gate → executor → state snapshot). "
            "Not LangGraph; not production."
        ),
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Retrieval query text (not echoed in output)",
    )
    parser.add_argument("--ticket-label", default=None, help="Workflow ticket_label for gate")
    parser.add_argument("--route-label", default=None, help="Workflow route_label for gate")
    parser.add_argument("--review-priority", default=None, help="Optional metadata filter field")
    parser.add_argument("--namespace", required=True, help="Pilot sandbox namespace")
    parser.add_argument("--index-version", required=True, help="Pilot sandbox index version")
    parser.add_argument(
        "--profile",
        default="semantic_pgvector",
        help="Retrieval profile gate (must be semantic_pgvector)",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Requested top_k (gate bounds 1–10)")
    parser.add_argument(
        "--confirm-sandbox",
        action="store_true",
        help="Required explicit approval for sandbox dry-run chain",
    )
    parser.add_argument(
        "--format",
        choices=("summary", "json"),
        default="summary",
        help="Output format for safe retrieval state snapshot",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for JSON snapshot (gitignored reports/ recommended)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output file")
    args = parser.parse_args(argv)

    if not args.confirm_sandbox:
        print(
            "dry_run_sandbox_retrieval_chain: --confirm-sandbox is required",
            file=sys.stderr,
        )
        return 1

    if args.output is not None and args.output.exists() and not args.overwrite:
        print(
            f"dry_run_sandbox_retrieval_chain: output exists: {args.output}",
            file=sys.stderr,
        )
        return 1

    config = SandboxRetrievalChainDryRunConfig(
        query=args.query,
        ticket_label=args.ticket_label,
        route_label=args.route_label,
        review_priority=args.review_priority,
        namespace=args.namespace,
        index_version=args.index_version,
        top_k=args.top_k,
        profile=args.profile,
        confirm_sandbox=True,
    )

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()

    embedding_fn = None
    if _OPENAI_PROVIDER == "openai":
        embedding_fn = _openai_query_embedding_fn

    try:
        result = run_sandbox_retrieval_chain_dry_run(
            config,
            database_url=database_url,
            table_name=os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip(),
            dimensions=int(os.environ.get("PGVECTOR_DIMENSIONS", "1536")),
            query_embedding_fn=embedding_fn,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"dry_run_sandbox_retrieval_chain: {exc}", file=sys.stderr)
        return 1

    if result.executor_called and not os.environ.get("OPENAI_API_KEY", "").strip():
        print(
            "dry_run_sandbox_retrieval_chain: OPENAI_API_KEY is required when executor runs",
            file=sys.stderr,
        )
        return 1

    serialized = format_snapshot_json(result.snapshot)
    if args.query.strip() and args.query.strip() in serialized:
        print(
            "dry_run_sandbox_retrieval_chain: raw query leaked into output",
            file=sys.stderr,
        )
        return 1

    if args.output is not None:
        path = args.output.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")

    if args.format == "json":
        print(serialized, end="")
    else:
        summary = format_snapshot_summary(result)
        assert_safe_chain_output(summary)
        print(summary, end="")
        if args.output is not None:
            print(f"  output_path={args.output.resolve()}")

    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

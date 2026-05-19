#!/usr/bin/env python3
"""Index pilot OpenAI embedding artifacts into local sandbox pgvector (no retrieval activation)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.corpus_planning.pgvector_sandbox_indexing import (
    index_embeddings_to_pgvector_sandbox,
)

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
_FORBIDDEN_OUTPUT = (
    "conversation_transcript",
    "OPENAI_API_KEY",
    "sk-",
    "BEGIN PRIVATE KEY",
)


def _assert_safe_stdout(text: str) -> None:
    lowered = text.lower()
    for token in _FORBIDDEN_OUTPUT:
        if token.lower() in lowered:
            raise RuntimeError(f"unsafe output token detected in summary: {token}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sandbox pgvector index for pilot OpenAI embeddings (local DB only).",
    )
    parser.add_argument(
        "embedding_dir",
        type=Path,
        help="Directory with embeddings.jsonl and embedding_manifest.json",
    )
    parser.add_argument(
        "--namespace",
        required=True,
        help="Sandbox namespace label (e.g. vendor_ticket_real_pilot)",
    )
    parser.add_argument(
        "--index-version",
        required=True,
        help="Sandbox index version label (e.g. pilot_v1)",
    )
    parser.add_argument(
        "--profile",
        default="semantic_pgvector",
        help="Retrieval profile gate (must be semantic_pgvector)",
    )
    parser.add_argument(
        "--confirm-sandbox",
        action="store_true",
        help="Explicit operator approval for sandbox indexing",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=Path("reports/pgvector_sandbox_indexing_pilot_v1.json"),
        help="Local indexing summary report path (gitignored)",
    )
    args = parser.parse_args(argv)

    if not args.confirm_sandbox:
        print(
            "index_pilot_embeddings_pgvector: --confirm-sandbox is required",
            file=sys.stderr,
        )
        return 1

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    table_name = os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip()
    dimensions = int(os.environ.get("PGVECTOR_DIMENSIONS", "1536"))

    try:
        result = index_embeddings_to_pgvector_sandbox(
            args.embedding_dir,
            namespace=args.namespace,
            index_version=args.index_version,
            profile=args.profile,
            database_url=database_url,
            table_name=table_name,
            dimensions=dimensions,
            summary_path=args.summary_path,
        )
    except ValueError as exc:
        print(f"index_pilot_embeddings_pgvector: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"index_pilot_embeddings_pgvector: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    lock_prefix = result.source_corpus_lockfile_hash[:12]
    lines = [
        "pgvector_sandbox_indexing: success",
        f"  indexed_count={result.indexed_count}",
        f"  namespace={result.namespace}",
        f"  index_version={result.index_version}",
        f"  profile={result.profile}",
        f"  dimensions={result.dimensions}",
        f"  embedding_provider={result.embedding_provider}",
        f"  embedding_model={result.embedding_model}",
        f"  source_corpus_id={result.source_corpus_id}",
        f"  source_corpus_lockfile_hash_prefix={lock_prefix}...",
        f"  embedding_artifact_id={result.embedding_artifact_id}",
        "  indexing_status=sandbox_indexed retrieval_activated=false",
        f"  summary_path={result.summary_path}",
    ]
    output = "\n".join(lines)
    _assert_safe_stdout(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

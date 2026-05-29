#!/usr/bin/env python3
"""Rebuild operational knowledge OpenAI embeddings + sandbox pgvector index."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.knowledge.knowledge_openai_rebuild import (
    DEFAULT_INDEX_VERSION,
    DEFAULT_NAMESPACE,
    DEFAULT_OFFICIAL_PATH,
    run_knowledge_openai_rebuild,
)

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild knowledge chunks, OpenAI embeddings, and sandbox pgvector index "
            "(local/dev only; requires explicit confirmation flags)."
        ),
    )
    parser.add_argument(
        "--official-path",
        type=Path,
        default=DEFAULT_OFFICIAL_PATH,
        help="Official knowledge markdown directory",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help="Sandbox pgvector namespace",
    )
    parser.add_argument(
        "--index-version",
        default=DEFAULT_INDEX_VERSION,
        help="Sandbox index version label",
    )
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required: allow real OpenAI embedding API calls",
    )
    parser.add_argument(
        "--confirm-sandbox",
        action="store_true",
        help="Required: allow sandbox pgvector writes",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite report files")
    parser.add_argument("--dry-run", action="store_true", help="Build chunks/embeddings only")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip retrieval smoke tests")
    parser.add_argument("--skip-policy-check", action="store_true", help="Skip policy fact check")
    args = parser.parse_args(argv)

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    table_name = os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip()

    try:
        result = run_knowledge_openai_rebuild(
            official_path=args.official_path,
            namespace=args.namespace,
            index_version=args.index_version,
            database_url=database_url,
            table_name=table_name,
            confirm_real_openai=args.confirm_real_openai,
            confirm_sandbox=args.confirm_sandbox,
            overwrite=args.overwrite,
            skip_smoke=args.skip_smoke,
            skip_policy_check=args.skip_policy_check,
            dry_run=args.dry_run,
        )
    except (ValueError, FileNotFoundError, FileExistsError, RuntimeError) as exc:
        print(f"rebuild_knowledge_openai_index: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

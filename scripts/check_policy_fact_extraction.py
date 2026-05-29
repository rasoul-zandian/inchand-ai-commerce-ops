#!/usr/bin/env python3
"""Check settlement policy fact extraction against sandbox knowledge retrieval."""

from __future__ import annotations

import argparse
import json
import os
import sys

from app.knowledge.knowledge_openai_rebuild import DEFAULT_INDEX_VERSION, DEFAULT_NAMESPACE
from app.knowledge.policy_fact_extraction_check import (
    run_policy_fact_extraction_check,
    write_policy_fact_extraction_check_reports,
)

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify settlement policy facts from sandbox knowledge retrieval.",
    )
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--index-version", default=DEFAULT_INDEX_VERSION)
    parser.add_argument("--provider", default="mock", choices=("mock", "openai"))
    parser.add_argument("--confirm-real-openai", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    if args.provider == "openai" and not args.confirm_real_openai:
        print("check_policy_fact_extraction: --confirm-real-openai required", file=sys.stderr)
        return 1

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    table_name = os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip()

    try:
        result = run_policy_fact_extraction_check(
            namespace=args.namespace,
            index_version=args.index_version,
            database_url=database_url,
            table_name=table_name,
            provider=args.provider,
            confirm_real_openai=args.confirm_real_openai,
        )
        write_policy_fact_extraction_check_reports(result, overwrite=args.overwrite)
    except (ValueError, FileExistsError, RuntimeError) as exc:
        print(f"check_policy_fact_extraction: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

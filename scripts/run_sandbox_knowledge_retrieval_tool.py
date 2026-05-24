#!/usr/bin/env python3
"""Run sandbox knowledge retrieval tool (local pgvector; no draft/final activation)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.corpus_planning.pgvector_sandbox_indexing import assert_sandbox_database_url
from app.embeddings import generate_embedding
from app.knowledge.knowledge_retrieval_tool import (
    KnowledgeRetrievalRequest,
    assert_safe_knowledge_retrieval_response,
    execute_sandbox_knowledge_retrieval,
    knowledge_query_hash,
)
from app.rag.pgvector_store import PgVectorStore

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
_OPENAI_PROVIDER = "openai"
_OPENAI_MODEL = "text-embedding-3-small"
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
            raise RuntimeError(f"unsafe output token detected: {token}")


def _openai_query_embedding_fn(text: str) -> list[float]:
    return list(
        generate_embedding(text, provider=_OPENAI_PROVIDER, model=_OPENAI_MODEL).vector,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sandbox knowledge retrieval tool (local pgvector only). "
            "Official policy ranks above historical memory when enabled."
        ),
    )
    parser.add_argument("--query", required=True, help="Query text (not echoed in summary)")
    parser.add_argument(
        "--namespace",
        default="knowledge_operations_sandbox",
        help="Knowledge sandbox namespace",
    )
    parser.add_argument(
        "--index-version",
        default="knowledge_v1_openai",
        help="Knowledge index version (must start with knowledge_v)",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--allowed-document-type",
        action="append",
        default=None,
        dest="allowed_document_types",
        help="Optional repeat flag to restrict document_type",
    )
    parser.add_argument(
        "--no-prefer-official-policy",
        action="store_true",
        help="Rank by vector score only (default: official_policy first)",
    )
    parser.add_argument(
        "--provider",
        default="openai",
        choices=("mock", "openai"),
        help="Query embedding provider",
    )
    parser.add_argument("--model", default=_OPENAI_MODEL)
    parser.add_argument("--dimensions", type=int, default=1536)
    parser.add_argument("--confirm-real-openai", action="store_true")
    parser.add_argument(
        "--confirm-sandbox",
        action="store_true",
        help="Required explicit approval for sandbox execution",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional gitignored JSON output path",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    if not args.confirm_sandbox:
        print(
            "run_sandbox_knowledge_retrieval_tool: --confirm-sandbox is required",
            file=sys.stderr,
        )
        return 1

    if args.output is not None and args.output.exists() and not args.overwrite:
        print(
            f"run_sandbox_knowledge_retrieval_tool: output exists: {args.output}",
            file=sys.stderr,
        )
        return 1

    if args.provider == "openai":
        if not args.confirm_real_openai:
            print(
                "run_sandbox_knowledge_retrieval_tool: "
                "--confirm-real-openai is required for openai provider",
                file=sys.stderr,
            )
            return 1
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            print(
                "run_sandbox_knowledge_retrieval_tool: OPENAI_API_KEY is required",
                file=sys.stderr,
            )
            return 1
        embed_fn = _openai_query_embedding_fn
    else:
        from app.corpus_planning.embedding_dry_run import build_mock_embedding

        dims = args.dimensions

        def _mock_fn(text: str) -> list[float]:
            return build_mock_embedding(text, dims)

        embed_fn = _mock_fn

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    table_name = os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip()

    try:
        assert_sandbox_database_url(database_url)
        request = KnowledgeRetrievalRequest(
            query=args.query,
            namespace=args.namespace,
            index_version=args.index_version,
            top_k=args.top_k,
            allowed_document_types=args.allowed_document_types,
            prefer_official_policy=not args.no_prefer_official_policy,
        )
        store = PgVectorStore(
            database_url,
            table_name=table_name,
            dimensions=args.dimensions,
        )
        response = execute_sandbox_knowledge_retrieval(request, store, embed_fn)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"run_sandbox_knowledge_retrieval_tool: {exc}", file=sys.stderr)
        return 1

    assert_safe_knowledge_retrieval_response(response)
    payload = response.model_dump()
    payload["query_hash"] = knowledge_query_hash(args.query)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _assert_safe_stdout(serialized)

    if args.output is not None:
        path = args.output.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")

    print("run_sandbox_knowledge_retrieval_tool: success")
    print(f"  namespace={args.namespace}")
    print(f"  index_version={args.index_version}")
    print(f"  query_hash={payload['query_hash']}")
    print(f"  result_count={response.result_count}")
    print(f"  official_policy_hit_count={response.official_policy_hit_count}")
    print(f"  historical_memory_hit_count={response.historical_memory_hit_count}")
    print(f"  retrieval_activated={response.retrieval_activated}")
    print(f"  sandbox_only={response.sandbox_only}")
    if response.hits:
        top = response.hits[0]
        print(
            f"  top_hit={top.document_type}/{top.source_lane}/"
            f"{top.section_title} score={top.score}",
        )
    if args.output is not None:
        print(f"  output_path={args.output.resolve()}")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

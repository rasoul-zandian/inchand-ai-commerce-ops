#!/usr/bin/env python3
"""Run sandbox retrieval tool against local pgvector (no LangGraph / production activation)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.corpus_planning.pilot_retrieval_eval import build_pilot_pgvector_store
from app.corpus_planning.retrieval_tool_models import RetrievalToolRequest
from app.corpus_planning.retrieval_tool_validation import validate_allowed_metadata_filter
from app.corpus_planning.sandbox_retrieval_tool import execute_sandbox_retrieval_tool_to_dict
from app.embeddings import generate_embedding

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


def _build_metadata_filter(args: argparse.Namespace) -> object:
    raw: dict[str, str] = {}
    if args.ticket_label:
        raw["ticket_label"] = args.ticket_label
    if args.route_label:
        raw["route_label"] = args.route_label
    if args.review_priority:
        raw["review_priority"] = args.review_priority
    if not raw:
        return None
    return validate_allowed_metadata_filter(raw)


def _openai_query_embedding_fn(text: str) -> list[float]:
    embedding = generate_embedding(
        text,
        provider=_OPENAI_PROVIDER,
        model=_OPENAI_MODEL,
    )
    return embedding.vector


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sandbox retrieval tool (local pgvector only; not production).",
    )
    parser.add_argument(
        "--query", required=True, help="Retrieval query text (not echoed in output)"
    )
    parser.add_argument("--namespace", required=True, help="Pilot sandbox namespace")
    parser.add_argument("--index-version", required=True, help="Pilot sandbox index version")
    parser.add_argument(
        "--profile",
        default="semantic_pgvector",
        help="Retrieval profile gate (must be semantic_pgvector)",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Number of hits to return")
    parser.add_argument("--ticket-label", default=None, help="Metadata filter: ticket_label")
    parser.add_argument("--route-label", default=None, help="Metadata filter: route_label")
    parser.add_argument("--review-priority", default=None, help="Metadata filter: review_priority")
    parser.add_argument(
        "--eval-mode",
        choices=("vector_only", "metadata_filtered"),
        default=None,
        help="Optional eval parity mode for metadata filter application",
    )
    parser.add_argument(
        "--confirm-sandbox",
        action="store_true",
        help="Required explicit approval for sandbox retrieval execution",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for safe JSON output (gitignored reports/ recommended)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output file")
    args = parser.parse_args(argv)

    if not args.confirm_sandbox:
        print(
            "run_sandbox_retrieval_tool: --confirm-sandbox is required",
            file=sys.stderr,
        )
        return 1

    if args.output is not None and args.output.exists() and not args.overwrite:
        print(f"run_sandbox_retrieval_tool: output exists: {args.output}", file=sys.stderr)
        return 1

    if _OPENAI_PROVIDER == "openai" and not os.environ.get("OPENAI_API_KEY", "").strip():
        print(
            "run_sandbox_retrieval_tool: OPENAI_API_KEY is required for query embeddings",
            file=sys.stderr,
        )
        return 1

    metadata_filter = _build_metadata_filter(args)
    eval_mode = args.eval_mode
    if metadata_filter is not None and eval_mode is None:
        eval_mode = "metadata_filtered"

    request = RetrievalToolRequest(
        query=args.query,
        top_k=args.top_k,
        namespace=args.namespace,
        index_version=args.index_version,
        metadata_filter=metadata_filter,
        eval_mode=eval_mode,
    )

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    table_name = os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip()
    dimensions = int(os.environ.get("PGVECTOR_DIMENSIONS", "1536"))

    try:
        store = build_pilot_pgvector_store(
            database_url,
            namespace=request.namespace,
            index_version=request.index_version,
            table_name=table_name,
            dimensions=dimensions,
        )
        payload = execute_sandbox_retrieval_tool_to_dict(
            request,
            store,
            _openai_query_embedding_fn,
            profile=args.profile,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"run_sandbox_retrieval_tool: {exc}", file=sys.stderr)
        return 1

    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _assert_safe_stdout(serialized)

    if args.output is not None:
        path = args.output.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")

    print("run_sandbox_retrieval_tool: success")
    print(f"  namespace={request.namespace}")
    print(f"  index_version={request.index_version}")
    print(f"  query_hash={payload['query_hash']}")
    print(f"  result_count={payload['result_count']}")
    print(f"  retrieval_activated={payload['retrieval_activated']}")
    print(f"  sandbox_only={payload['sandbox_only']}")
    if args.output is not None:
        print(f"  output_path={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

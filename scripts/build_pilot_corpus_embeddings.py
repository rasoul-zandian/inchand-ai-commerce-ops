#!/usr/bin/env python3
"""Build embedding artifacts for pilot corpus (mock or local OpenAI; no pgvector)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.embedding_dry_run import run_embedding_dry_run
from app.corpus_planning.real_embedding_generation import (
    run_real_embedding_generation,
    validate_openai_pilot_config,
)

_FORBIDDEN_OUTPUT_TOKENS = (
    "conversation_transcript",
    "BEGIN PRIVATE KEY",
    "sk-",
    "OPENAI_API_KEY",
)


def _assert_safe_stdout(text: str) -> None:
    lowered = text.lower()
    for token in _FORBIDDEN_OUTPUT_TOKENS:
        if token.lower() in lowered:
            raise RuntimeError(f"unsafe output token detected in summary: {token}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate embedding artifacts from pilot corpus (mock or OpenAI).",
    )
    parser.add_argument(
        "corpus_dir",
        type=Path,
        help="Pilot corpus directory (e.g. corpus/vendor_ticket_real_pilot)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/embeddings/vendor_ticket_real_pilot"),
        help="Output directory for embedding artifacts",
    )
    parser.add_argument(
        "--provider",
        default="mock",
        help="Embedding provider: mock (default) or openai",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Embedding model (default: mock-embedding-1536 or text-embedding-3-small)",
    )
    parser.add_argument(
        "--dimensions",
        type=int,
        default=1536,
        help="Embedding vector dimensions",
    )
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required when --provider openai (explicit operator approval)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing output directory contents",
    )
    parser.add_argument(
        "--created-at",
        default=None,
        help="Optional fixed UTC timestamp (ISO-8601) for reproducible runs",
    )
    args = parser.parse_args(argv)

    provider = args.provider.strip().lower()
    if provider not in {"mock", "openai"}:
        print(
            f"build_pilot_corpus_embeddings: unsupported provider: {args.provider}",
            file=sys.stderr,
        )
        return 1

    model = args.model
    if model is None:
        model = "text-embedding-3-small" if provider == "openai" else "mock-embedding-1536"

    try:
        if provider == "openai":
            if not args.confirm_real_openai:
                raise ValueError(
                    "provider=openai requires --confirm-real-openai (local operator approval)"
                )
            validate_openai_pilot_config(model=model, dimensions=args.dimensions)
            result = run_real_embedding_generation(
                args.corpus_dir,
                args.output_dir,
                embedding_model=model,
                embedding_dimensions=args.dimensions,
                overwrite=args.overwrite,
                created_at=args.created_at,
            )
            status_label = "real_generated"
        else:
            result = run_embedding_dry_run(
                args.corpus_dir,
                args.output_dir,
                embedding_provider=provider,
                embedding_model=model,
                embedding_dimensions=args.dimensions,
                overwrite=args.overwrite,
                created_at=args.created_at,
            )
            status_label = "mock_generated"
    except ValueError as exc:
        print(f"build_pilot_corpus_embeddings: {exc}", file=sys.stderr)
        return 1

    lines = [
        f"pilot_corpus_embeddings: wrote {provider} artifacts",
        f"  output_dir={result.output_dir}",
        f"  document_count={result.document_count}",
        f"  embedding_dimensions={result.embedding_dimensions}",
        f"  embedding_provider={result.embedding_provider}",
        f"  embedding_model={result.embedding_model}",
        f"  source_corpus_id={result.source_corpus_id}",
        f"  source_corpus_lockfile_hash={result.source_corpus_lockfile_hash[:12]}...",
        f"  embedding_status={status_label} indexing_status=not_started",
    ]
    output = "\n".join(lines)
    _assert_safe_stdout(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

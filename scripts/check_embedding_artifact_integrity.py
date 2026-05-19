#!/usr/bin/env python3
"""Verify mock embedding artifact integrity (no vectors, transcripts, or network)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.embedding_integrity import check_embedding_artifact_integrity

_FORBIDDEN_OUTPUT_TOKENS = (
    "conversation_transcript",
    "BEGIN PRIVATE KEY",
    "sk-",
    "OPENAI_API_KEY",
)


def _hash_prefix(value: str | None) -> str:
    if not value:
        return "n/a"
    cleaned = value.strip()
    if len(cleaned) <= 12:
        return cleaned
    return f"{cleaned[:12]}..."


def _assert_safe_stdout(text: str) -> None:
    lowered = text.lower()
    for token in _FORBIDDEN_OUTPUT_TOKENS:
        if token.lower() in lowered:
            raise RuntimeError(f"unsafe output token detected in summary: {token}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify mock embedding artifacts (manifest, lockfile, records).",
    )
    parser.add_argument(
        "embedding_dir",
        type=Path,
        help="Embedding artifact directory (e.g. artifacts/embeddings/vendor_ticket_real_pilot)",
    )
    args = parser.parse_args(argv)

    report = check_embedding_artifact_integrity(args.embedding_dir)

    status = "passed" if report.passed else "FAILED"
    lines = [
        f"embedding_artifact_integrity: {status}",
        f"  embedding_dir={report.metadata.get('embedding_dir')}",
    ]
    if report.document_count is not None:
        lines.append(f"  document_count={report.document_count}")
    if report.embedding_record_count is not None:
        lines.append(f"  embedding_record_count={report.embedding_record_count}")
    if report.embedding_dimensions is not None:
        lines.append(f"  embedding_dimensions={report.embedding_dimensions}")
    if report.embedding_provider is not None:
        lines.append(f"  embedding_provider={report.embedding_provider}")
    if report.embedding_model is not None:
        lines.append(f"  embedding_model={report.embedding_model}")
    lines.append(
        f"  source_corpus_lockfile_hash_prefix={_hash_prefix(report.source_corpus_lockfile_hash)}"
    )
    if report.embedding_status is not None:
        lines.append(f"  embedding_status={report.embedding_status}")
    if report.indexing_status is not None:
        lines.append(f"  indexing_status={report.indexing_status}")
    if report.pgvector_indexed is not None:
        lines.append(f"  pgvector_indexed={report.pgvector_indexed}")
    if report.retrieval_activated is not None:
        lines.append(f"  retrieval_activated={report.retrieval_activated}")
    lines.append(f"  issue_count={report.issue_count}")

    output = "\n".join(lines)
    _assert_safe_stdout(output)
    print(output)

    if report.issues:
        for issue in report.issues:
            print(f"  - {issue}", file=sys.stderr)

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

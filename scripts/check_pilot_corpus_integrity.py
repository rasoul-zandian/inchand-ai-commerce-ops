#!/usr/bin/env python3
"""Verify governance-gated pilot corpus integrity (no embeddings, network, or raw exports)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.pilot_corpus_integrity import verify_pilot_corpus_integrity

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
        description="Verify pilot corpus manifest, lockfile, and governance flags.",
    )
    parser.add_argument(
        "corpus_dir",
        type=Path,
        help="Pilot corpus directory (e.g. corpus/vendor_ticket_real_pilot)",
    )
    args = parser.parse_args(argv)

    report = verify_pilot_corpus_integrity(args.corpus_dir)

    status = "passed" if report.passed else "FAILED"
    lines = [
        f"pilot_corpus_integrity: {status}",
        f"  corpus_dir={report.metadata.get('corpus_dir')}",
    ]
    if report.corpus_id is not None:
        lines.append(f"  corpus_id={report.corpus_id}")
    if report.corpus_version is not None:
        lines.append(f"  corpus_version={report.corpus_version}")
    if report.approved_record_count is not None:
        lines.append(f"  approved_record_count={report.approved_record_count}")
    if report.document_count is not None:
        lines.append(f"  document_count={report.document_count}")
    if report.source_batch_id is not None:
        lines.append(f"  source_batch_id={report.source_batch_id}")
    if report.reviewer_signoff_id is not None:
        lines.append(f"  reviewer_signoff_id={report.reviewer_signoff_id}")
    if report.embedding_status is not None:
        lines.append(f"  embedding_status={report.embedding_status}")
    if report.indexing_status is not None:
        lines.append(f"  indexing_status={report.indexing_status}")
    if report.lockfile_entry_count is not None:
        lines.append(f"  lockfile_entry_count={report.lockfile_entry_count}")
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

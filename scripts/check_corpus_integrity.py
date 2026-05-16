#!/usr/bin/env python3
"""Offline corpus integrity, lockfile, and manifest/eval consistency check (no network)."""

from __future__ import annotations

import sys

from app.rag.consistency import (
    assert_corpus_eval_consistency,
    check_default_vendor_ticket_corpus_eval_consistency,
)
from app.rag.corpus_integrity import (
    default_vendor_ticket_corpus_integrity,
    verify_default_vendor_ticket_corpus_lockfile,
)


def main() -> int:
    integrity = default_vendor_ticket_corpus_integrity()
    lockfile_report = verify_default_vendor_ticket_corpus_lockfile()
    consistency = check_default_vendor_ticket_corpus_eval_consistency()

    print(f"corpus integrity: {'passed' if integrity.passed else 'FAILED'}")
    print(f"  checked_file_count={integrity.checked_file_count}")
    print(f"  issue_count={integrity.issue_count}")
    if integrity.issues:
        for issue in integrity.issues:
            print(f"  - {issue}")

    print(f"corpus lockfile: {'passed' if lockfile_report.passed else 'FAILED'}")
    print(f"  issue_count={lockfile_report.issue_count}")
    if lockfile_report.issues:
        for issue in lockfile_report.issues:
            print(f"  - {issue}")

    print(f"corpus/eval consistency: {'passed' if consistency.passed else 'FAILED'}")
    print(f"  eval_case_count={consistency.eval_case_count}")
    print(f"  issue_count={consistency.issue_count}")
    if consistency.issues:
        for issue in consistency.issues:
            print(
                f"  - {issue.issue_type} case_id={issue.case_id!r} "
                f"document_id={issue.document_id!r}: {issue.message}"
            )

    if not integrity.passed:
        return 1

    if not lockfile_report.passed:
        return 1

    try:
        assert_corpus_eval_consistency(consistency)
    except AssertionError as exc:
        print(f"consistency assertion failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

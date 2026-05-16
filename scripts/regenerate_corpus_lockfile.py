#!/usr/bin/env python3
"""Regenerate corpus/vendor_ticket/corpus.lock.json from the current on-disk corpus (offline)."""

from __future__ import annotations

import sys

from app.rag.corpus_integrity import (
    default_vendor_ticket_corpus_lockfile_path,
    write_corpus_lockfile,
)

_CORPUS_NAME = "vendor_ticket"


def main() -> int:
    lock_path = default_vendor_ticket_corpus_lockfile_path()
    base_dir = lock_path.parent
    try:
        lockfile = write_corpus_lockfile(
            base_dir=base_dir,
            lockfile_path=lock_path,
            corpus_name=_CORPUS_NAME,
        )
    except (ValueError, OSError) as exc:
        print(f"lockfile regeneration failed: {exc}", file=sys.stderr)
        return 1

    checked = lockfile.metadata.get("checked_file_count", len(lockfile.files))
    print(f"regenerated: {lock_path}")
    print(f"checked_file_count={checked}")
    print(f"corpus_name={lockfile.corpus_name}")
    print(f"lock_version={lockfile.lock_version}")
    print("Review corpus changes before committing the regenerated lockfile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

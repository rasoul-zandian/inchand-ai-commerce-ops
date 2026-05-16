#!/usr/bin/env python3
"""Verify committed corpus.lock.json matches a fresh regeneration (does not modify the lockfile)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.rag.corpus_integrity import (
    default_vendor_ticket_corpus_lockfile_path,
    write_corpus_lockfile,
)

_CORPUS_NAME = "vendor_ticket"


def _normalize_json_payload(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2)


def _load_normalized(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    return _normalize_json_payload(json.loads(raw))


def check_lockfile_fresh(*, committed_path: Path | None = None) -> bool:
    """Return True if ``committed_path`` matches a fresh lockfile for the same corpus."""
    if committed_path is not None:
        lock_path = Path(committed_path)
    else:
        lock_path = default_vendor_ticket_corpus_lockfile_path()
    if not lock_path.is_file():
        return False

    base_dir = lock_path.parent
    with tempfile.TemporaryDirectory() as tmp:
        temp_lock = Path(tmp) / "corpus.lock.json"
        write_corpus_lockfile(
            base_dir=base_dir,
            lockfile_path=temp_lock,
            corpus_name=_CORPUS_NAME,
        )
        return _load_normalized(lock_path) == _load_normalized(temp_lock)


def main() -> int:
    lock_path = default_vendor_ticket_corpus_lockfile_path()
    if not lock_path.is_file():
        print("corpus lockfile freshness: failed", file=sys.stderr)
        print(f"committed lockfile not found: {lock_path}", file=sys.stderr)
        return 1

    try:
        fresh = check_lockfile_fresh(committed_path=lock_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print("corpus lockfile freshness: failed", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    if fresh:
        print("corpus lockfile freshness: passed")
        return 0

    print("corpus lockfile freshness: failed")
    print("corpus.lock.json is stale. Run: make lockfile")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

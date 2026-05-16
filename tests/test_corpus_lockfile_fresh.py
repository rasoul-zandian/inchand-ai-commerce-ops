"""Tests for corpus lockfile freshness check (no modification of committed lockfile)."""

from __future__ import annotations

import json
from pathlib import Path

from app.rag.corpus_integrity import write_corpus_lockfile
from scripts.check_corpus_lockfile_fresh import check_lockfile_fresh


def _write_min_corpus(base: Path) -> None:
    (base / "manifest.json").write_text(
        json.dumps(
            {"manifest_version": "1", "workflow_type": "w", "locale": "fa-IR", "documents": []}
        ),
        encoding="utf-8",
    )
    (base / "eval_cases.json").write_text(
        json.dumps({"eval_version": "1", "workflow_type": "w", "locale": "fa-IR", "cases": []}),
        encoding="utf-8",
    )
    (base / "body.txt").write_text("content", encoding="utf-8")


def test_check_lockfile_fresh_passes_when_lockfile_current(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    lock_path = tmp_path / "corpus.lock.json"
    write_corpus_lockfile(base_dir=tmp_path, lockfile_path=lock_path, corpus_name="vendor_ticket")
    assert check_lockfile_fresh(committed_path=lock_path) is True


def test_check_lockfile_fresh_fails_when_corpus_changed(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    lock_path = tmp_path / "corpus.lock.json"
    write_corpus_lockfile(base_dir=tmp_path, lockfile_path=lock_path, corpus_name="vendor_ticket")
    (tmp_path / "body.txt").write_text("changed", encoding="utf-8")
    assert check_lockfile_fresh(committed_path=lock_path) is False


def test_check_lockfile_fresh_fails_when_lockfile_missing(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    assert check_lockfile_fresh(committed_path=tmp_path / "corpus.lock.json") is False

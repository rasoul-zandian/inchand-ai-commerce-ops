"""Tests for corpus SHA-256 integrity inventory and lockfile (local filesystem only)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app.rag.corpus_integrity import (
    CorpusFileHash,
    collect_corpus_files,
    default_vendor_ticket_corpus_integrity,
    default_vendor_ticket_corpus_lockfile_path,
    load_corpus_lockfile,
    sha256_file,
    verify_corpus_against_lockfile,
    verify_corpus_integrity,
    verify_default_vendor_ticket_corpus_lockfile,
    write_corpus_lockfile,
)
from pydantic import ValidationError
from scripts.check_corpus_integrity import main as check_corpus_integrity_main


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


def test_sha256_file_known_content(tmp_path: Path) -> None:
    p = tmp_path / "sample.bin"
    content = b"hello corpus integrity"
    p.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert sha256_file(p) == expected


def test_collect_corpus_files_deterministic_order(tmp_path: Path) -> None:
    (tmp_path / "policies").mkdir()
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "eval_cases.json").write_text("{}", encoding="utf-8")
    (tmp_path / "policies" / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "policies" / "a.txt").write_text("a", encoding="utf-8")

    files = collect_corpus_files(tmp_path)
    rels = [str(f.relative_to(tmp_path.resolve())).replace("\\", "/") for f in files]
    assert rels == [
        "eval_cases.json",
        "manifest.json",
        "policies/a.txt",
        "policies/b.txt",
    ]


def test_collect_corpus_files_excludes_hidden_and_pycache(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "eval_cases.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".hidden.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".DS_Store").write_bytes(b"")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "junk.pyc").write_bytes(b"\x00")

    files = collect_corpus_files(tmp_path)
    rels = {f.name for f in files}
    assert rels == {"manifest.json", "eval_cases.json"}


def test_verify_corpus_integrity_passes_for_temp_corpus(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "eval_cases.json").write_text("{}", encoding="utf-8")
    (tmp_path / "body.txt").write_text("content", encoding="utf-8")

    report = verify_corpus_integrity(tmp_path)
    assert report.passed is True
    assert report.checked_file_count == 3
    assert report.issue_count == 0
    assert len(report.file_hashes) == 3
    assert report.metadata.get("verifier") == "local_sha256"


def test_verify_corpus_integrity_fails_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    report = verify_corpus_integrity(missing)
    assert report.passed is False
    assert report.checked_file_count == 0
    assert any("does not exist" in issue for issue in report.issues)


def test_verify_corpus_integrity_fails_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    report = verify_corpus_integrity(empty)
    assert report.passed is False
    assert report.checked_file_count == 0
    assert any("No corpus files found" in issue for issue in report.issues)


def test_default_vendor_ticket_corpus_integrity_passes() -> None:
    report = default_vendor_ticket_corpus_integrity()
    assert report.passed is True
    assert report.checked_file_count >= 7
    assert report.issue_count == 0


def test_collect_corpus_files_excludes_corpus_lock_json(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    (tmp_path / "corpus.lock.json").write_text("{}", encoding="utf-8")
    files = collect_corpus_files(tmp_path)
    assert all(f.name != "corpus.lock.json" for f in files)


def test_write_corpus_lockfile_creates_valid_lockfile(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    lock_path = tmp_path / "corpus.lock.json"
    lockfile = write_corpus_lockfile(
        base_dir=tmp_path,
        lockfile_path=lock_path,
        corpus_name="test_corpus",
    )
    assert lock_path.is_file()
    assert lockfile.corpus_name == "test_corpus"
    assert lockfile.manifest_version == "1"
    assert lockfile.eval_version == "1"
    assert len(lockfile.files) == 3
    loaded = load_corpus_lockfile(lock_path)
    assert loaded.lock_version == lockfile.lock_version


def test_load_corpus_lockfile_malformed_raises_value_error(tmp_path: Path) -> None:
    bad = tmp_path / "corpus.lock.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="valid JSON"):
        load_corpus_lockfile(bad)


def test_load_corpus_lockfile_invalid_schema_raises_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "corpus.lock.json"
    bad.write_text(json.dumps({"lock_version": "1"}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_corpus_lockfile(bad)


def test_verify_corpus_against_lockfile_passes_when_files_match(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    lock_path = tmp_path / "corpus.lock.json"
    write_corpus_lockfile(base_dir=tmp_path, lockfile_path=lock_path, corpus_name="test")
    report = verify_corpus_against_lockfile(base_dir=tmp_path, lockfile_path=lock_path)
    assert report.passed is True
    assert report.metadata.get("verifier") == "local_sha256_lockfile"


def test_verify_corpus_against_lockfile_fails_hash_mismatch(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    lock_path = tmp_path / "corpus.lock.json"
    write_corpus_lockfile(base_dir=tmp_path, lockfile_path=lock_path, corpus_name="test")
    (tmp_path / "body.txt").write_text("changed", encoding="utf-8")
    report = verify_corpus_against_lockfile(base_dir=tmp_path, lockfile_path=lock_path)
    assert report.passed is False
    assert any("Hash mismatch" in issue for issue in report.issues)


def test_verify_corpus_against_lockfile_fails_size_mismatch(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    lock_path = tmp_path / "corpus.lock.json"
    lock = write_corpus_lockfile(base_dir=tmp_path, lockfile_path=lock_path, corpus_name="test")
    entry = next(f for f in lock.files if f.path == "body.txt")
    tampered = lock.model_copy(
        update={
            "files": [
                CorpusFileHash(
                    path=entry.path,
                    sha256=entry.sha256,
                    size_bytes=entry.size_bytes + 1,
                )
                if f.path == "body.txt"
                else f
                for f in lock.files
            ]
        }
    )
    lock_path.write_text(
        json.dumps(tampered.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    report = verify_corpus_against_lockfile(base_dir=tmp_path, lockfile_path=lock_path)
    assert report.passed is False
    assert any("Size mismatch" in issue for issue in report.issues)


def test_verify_corpus_against_lockfile_fails_missing_locked_file(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    lock_path = tmp_path / "corpus.lock.json"
    write_corpus_lockfile(base_dir=tmp_path, lockfile_path=lock_path, corpus_name="test")
    (tmp_path / "body.txt").unlink()
    report = verify_corpus_against_lockfile(base_dir=tmp_path, lockfile_path=lock_path)
    assert report.passed is False
    assert any("Missing locked corpus file" in issue for issue in report.issues)


def test_verify_corpus_against_lockfile_fails_unexpected_file(tmp_path: Path) -> None:
    _write_min_corpus(tmp_path)
    lock_path = tmp_path / "corpus.lock.json"
    write_corpus_lockfile(base_dir=tmp_path, lockfile_path=lock_path, corpus_name="test")
    (tmp_path / "extra.txt").write_text("new", encoding="utf-8")
    report = verify_corpus_against_lockfile(base_dir=tmp_path, lockfile_path=lock_path)
    assert report.passed is False
    assert any("Unexpected corpus file" in issue for issue in report.issues)


def test_default_vendor_ticket_corpus_lockfile_path_exists() -> None:
    path = default_vendor_ticket_corpus_lockfile_path()
    assert path.is_file()
    assert path.name == "corpus.lock.json"


def test_verify_default_vendor_ticket_corpus_lockfile_passes() -> None:
    report = verify_default_vendor_ticket_corpus_lockfile()
    assert report.passed is True
    assert report.issue_count == 0


def test_check_corpus_integrity_script_main_exits_zero() -> None:
    assert check_corpus_integrity_main() == 0

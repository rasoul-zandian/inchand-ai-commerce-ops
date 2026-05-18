"""Tests for pilot corpus integrity checker (synthetic fixtures only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.pilot_corpus_builder import build_pilot_corpus
from app.corpus_planning.pilot_corpus_integrity import verify_pilot_corpus_integrity
from scripts.check_pilot_corpus_integrity import main as check_main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUILD_REPORT = _REPO_ROOT / "docs" / "operations" / "pilot_corpus_25_build_report.md"
_README = _REPO_ROOT / "README.md"


def _export_line(*, room_id: str = "ROOM_A", label: str = "support") -> str:
    payload = {
        "room_id": room_id,
        "ticket_label": label,
        "ticket_subtype": "general",
        "seller_id": "SELLER_ID_001",
        "messages": [
            {"message_id": "m1", "sender_type": "seller", "text": "سلام"},
            {"message_id": "m2", "sender_type": "support_agent", "text": "بررسی"},
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _write_synthetic_corpus(tmp_path: Path, *, room_ids: list[str] | None = None) -> Path:
    export = tmp_path / "export.jsonl"
    approved = tmp_path / "approved.txt"
    corpus_dir = tmp_path / "pilot_corpus"
    ids = room_ids or ["ROOM_A", "ROOM_B"]
    export.write_text(
        "\n".join(_export_line(room_id=room_id) for room_id in ids) + "\n",
        encoding="utf-8",
    )
    approved.write_text("\n".join(ids) + "\n", encoding="utf-8")
    build_pilot_corpus(
        export,
        approved_room_ids=ids,
        corpus_dir=corpus_dir,
        source_batch_id="replay_test_v1",
        reviewer_signoff_id="SIGNOFF_TEST",
        created_at="2026-05-16T10:00:00Z",
    )
    return corpus_dir


def test_integrity_passes_on_synthetic_corpus(tmp_path: Path) -> None:
    corpus_dir = _write_synthetic_corpus(tmp_path)
    report = verify_pilot_corpus_integrity(corpus_dir)
    assert report.passed
    assert report.approved_record_count == 2
    assert report.document_count == 2
    assert report.embedding_status == "not_started"
    assert report.indexing_status == "not_started"


def test_fails_if_document_missing(tmp_path: Path) -> None:
    corpus_dir = _write_synthetic_corpus(tmp_path)
    (corpus_dir / "documents" / "ROOM_B.json").unlink()
    report = verify_pilot_corpus_integrity(corpus_dir)
    assert not report.passed
    assert any("ROOM_B" in issue for issue in report.issues)


def test_fails_if_lock_hash_mismatch(tmp_path: Path) -> None:
    corpus_dir = _write_synthetic_corpus(tmp_path)
    doc_path = corpus_dir / "documents" / "ROOM_A.json"
    doc_path.write_text(doc_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    report = verify_pilot_corpus_integrity(corpus_dir)
    assert not report.passed
    assert any("hash mismatch" in issue for issue in report.issues)


def test_fails_if_embedding_status_not_not_started(tmp_path: Path) -> None:
    corpus_dir = _write_synthetic_corpus(tmp_path)
    manifest_path = corpus_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["embedding_status"] = "completed"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    report = verify_pilot_corpus_integrity(corpus_dir)
    assert not report.passed
    assert any("embedding_status" in issue for issue in report.issues)


def test_fails_if_governance_flags_unsafe(tmp_path: Path) -> None:
    corpus_dir = _write_synthetic_corpus(tmp_path)
    manifest_path = corpus_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["governance"]["embeddings_generated"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    report = verify_pilot_corpus_integrity(corpus_dir)
    assert not report.passed
    assert any("embeddings_generated" in issue for issue in report.issues)


def test_cli_passes_on_synthetic_corpus(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus_dir = _write_synthetic_corpus(tmp_path)
    code = check_main([str(corpus_dir)])
    captured = capsys.readouterr()
    assert code == 0
    assert "pilot_corpus_integrity: passed" in captured.out
    assert "approved_record_count=2" in captured.out


def test_cli_does_not_print_transcripts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus_dir = _write_synthetic_corpus(tmp_path)
    check_main([str(corpus_dir)])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "conversation_transcript" not in combined
    assert "سلام" not in combined


def test_build_report_doc_exists() -> None:
    text = _BUILD_REPORT.read_text(encoding="utf-8")
    assert "Pilot Corpus 25 Build Report" in text
    assert "approved_record_count" in text
    assert "**25**" in text or "approved_record_count=25" in text
    assert "replay_166_redacted_v1" in text
    assert "signoff_replay_166_redacted_v1" in text
    assert "not_started" in text
    assert "pilot_corpus_repository_policy.md" in text


def test_readme_links_build_report_and_integrity_checker() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "pilot_corpus_25_build_report.md" in readme
    assert "check_pilot_corpus_integrity.py" in readme


def test_no_embeddings_or_openai_in_integrity_modules() -> None:
    for rel in (
        "app/corpus_planning/pilot_corpus_integrity.py",
        "scripts/check_pilot_corpus_integrity.py",
    ):
        source = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "import openai" not in source
        assert "from openai" not in source
        assert "embeddings_factory" not in source
        assert "index_corpus_to_pgvector" not in source


def test_integrity_checker_does_not_create_repo_pilot_corpus(tmp_path: Path) -> None:
    repo_pilot = _REPO_ROOT / "corpus" / "vendor_ticket_real_pilot"
    before = repo_pilot.exists()
    _write_synthetic_corpus(tmp_path)
    assert repo_pilot.exists() == before

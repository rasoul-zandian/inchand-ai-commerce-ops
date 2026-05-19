"""Tests for mock embedding artifact integrity (synthetic fixtures only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.embedding_dry_run import run_embedding_dry_run
from app.corpus_planning.embedding_integrity import check_embedding_artifact_integrity
from app.corpus_planning.pilot_corpus_builder import build_pilot_corpus
from app.rag.corpus_integrity import sha256_file
from scripts.check_embedding_artifact_integrity import main as check_main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_REPORT = (
    _REPO_ROOT / "docs" / "operations" / "mock_embedding_artifact_integrity_report.md"
)
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


def _build_synthetic_artifacts(tmp_path: Path, *room_ids: str) -> Path:
    export = tmp_path / "export.jsonl"
    corpus_dir = tmp_path / "corpus" / "vendor_ticket_real_pilot"
    output_dir = tmp_path / "artifacts" / "embeddings" / "vendor_ticket_real_pilot"
    export.write_text(
        "\n".join(_export_line(room_id=room_id) for room_id in room_ids) + "\n",
        encoding="utf-8",
    )
    build_pilot_corpus(
        export,
        approved_room_ids=list(room_ids),
        corpus_dir=corpus_dir,
        source_batch_id="replay_test_v1",
        reviewer_signoff_id="SIGNOFF_TEST",
        created_at="2026-05-16T10:00:00Z",
    )
    run_embedding_dry_run(
        corpus_dir,
        output_dir,
        embedding_provider="mock",
        embedding_model="mock-embedding-1536",
        embedding_dimensions=1536,
        created_at="2026-05-16T12:00:00Z",
    )
    return output_dir


def test_integrity_passes_on_synthetic_artifacts(tmp_path: Path) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A", "ROOM_B")
    report = check_embedding_artifact_integrity(output_dir)
    assert report.passed
    assert report.document_count == 2
    assert report.embedding_record_count == 2
    assert report.embedding_dimensions == 1536
    assert report.embedding_status == "mock_generated"
    assert report.indexing_status == "not_started"
    assert report.pgvector_indexed is False


def test_fails_if_manifest_missing(tmp_path: Path) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A")
    (output_dir / "embedding_manifest.json").unlink()
    report = check_embedding_artifact_integrity(output_dir)
    assert not report.passed
    assert any("embedding_manifest.json" in issue for issue in report.issues)


def test_fails_if_lockfile_hash_mismatch(tmp_path: Path) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A")
    manifest_path = output_dir / "embedding_manifest.json"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    report = check_embedding_artifact_integrity(output_dir)
    assert not report.passed
    assert any("hash mismatch" in issue for issue in report.issues)


def test_fails_if_dimension_mismatch(tmp_path: Path) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A")
    manifest = json.loads((output_dir / "embedding_manifest.json").read_text(encoding="utf-8"))
    manifest["embedding_dimensions"] = 64
    (output_dir / "embedding_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    report = check_embedding_artifact_integrity(output_dir)
    assert not report.passed
    assert any("embedding_dimensions" in issue for issue in report.issues)


def test_fails_if_record_count_mismatch(tmp_path: Path) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A", "ROOM_B")
    lines = (output_dir / "embeddings.jsonl").read_text(encoding="utf-8").strip().splitlines()
    (output_dir / "embeddings.jsonl").write_text(lines[0] + "\n", encoding="utf-8")
    report = check_embedding_artifact_integrity(output_dir)
    assert not report.passed
    assert any("record count" in issue for issue in report.issues)


def test_fails_if_forbidden_text_field(tmp_path: Path) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A")
    lines = (output_dir / "embeddings.jsonl").read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[0])
    record["conversation_transcript"] = "must not appear"
    (output_dir / "embeddings.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    report = check_embedding_artifact_integrity(output_dir)
    assert not report.passed
    assert any("forbidden field" in issue for issue in report.issues)


def test_passes_on_real_generated_artifacts(tmp_path: Path) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A")
    manifest = json.loads((output_dir / "embedding_manifest.json").read_text(encoding="utf-8"))
    manifest["embedding_status"] = "real_generated"
    manifest["embedding_provider"] = "openai"
    manifest["embedding_model"] = "text-embedding-3-small"
    (output_dir / "embedding_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = (output_dir / "embeddings.jsonl").read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]
    for record in records:
        record["embedding_provider"] = "openai"
        record["embedding_model"] = "text-embedding-3-small"
    (output_dir / "embeddings.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )
    from app.corpus_planning.embedding_dry_run import build_embedding_lockfile

    lockfile = build_embedding_lockfile(
        output_dir,
        embedding_artifact_id=manifest["embedding_artifact_id"],
        generated_at=manifest["generated_at"],
        document_count=manifest["document_count"],
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
    )
    (output_dir / "embedding.lock.json").write_text(
        json.dumps(lockfile, indent=2) + "\n",
        encoding="utf-8",
    )
    report = check_embedding_artifact_integrity(output_dir)
    assert report.passed
    assert report.embedding_status == "real_generated"


def test_fails_if_indexing_status_not_not_started(tmp_path: Path) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A")
    manifest = json.loads((output_dir / "embedding_manifest.json").read_text(encoding="utf-8"))
    manifest["indexing_status"] = "completed"
    (output_dir / "embedding_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    report = check_embedding_artifact_integrity(output_dir)
    assert not report.passed
    assert any("indexing_status" in issue for issue in report.issues)


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A")
    assert check_main([str(output_dir)]) == 0
    assert "embedding_artifact_integrity: passed" in capsys.readouterr().out

    (output_dir / "embedding_manifest.json").unlink()
    assert check_main([str(output_dir)]) == 1


def test_cli_does_not_print_vectors_or_transcripts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A")
    check_main([str(output_dir)])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "conversation_transcript" not in combined
    assert "[0." not in combined


def test_integrity_report_doc_exists() -> None:
    text = _INTEGRITY_REPORT.read_text(encoding="utf-8")
    assert "Mock Embedding Artifact Integrity Report" in text
    assert "document_count=25" in text or "**25**" in text
    assert "mock_generated" in text
    assert "check_embedding_artifact_integrity.py" in text


def test_readme_links_embedding_integrity_checker() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "check_embedding_artifact_integrity.py" in readme
    assert "mock_embedding_artifact_integrity_report.md" in readme


def test_lockfile_hashes_match_on_valid_artifacts(tmp_path: Path) -> None:
    output_dir = _build_synthetic_artifacts(tmp_path, "ROOM_A")
    lockfile = json.loads((output_dir / "embedding.lock.json").read_text(encoding="utf-8"))
    by_path = {entry["path"]: entry for entry in lockfile["files"]}
    assert by_path["embeddings.jsonl"]["sha256"] == sha256_file(output_dir / "embeddings.jsonl")

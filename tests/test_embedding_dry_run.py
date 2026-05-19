"""Tests for mock pilot corpus embedding dry-run (synthetic fixtures only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.embedding_dry_run import (
    build_mock_embedding,
    compute_corpus_lockfile_hash,
    run_embedding_dry_run,
)
from app.corpus_planning.pilot_corpus_builder import build_pilot_corpus
from app.rag.corpus_integrity import sha256_file
from scripts.build_pilot_corpus_embeddings import main as build_embeddings_main

_REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _build_synthetic_corpus(tmp_path: Path, *room_ids: str) -> Path:
    export = tmp_path / "export.jsonl"
    corpus_dir = tmp_path / "corpus" / "vendor_ticket_real_pilot"
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
    return corpus_dir


def test_mock_embedding_deterministic_and_not_all_zeros() -> None:
    first = build_mock_embedding("room_id=ROOM_A|ticket_label=support", 1536)
    second = build_mock_embedding("room_id=ROOM_A|ticket_label=support", 1536)
    assert first == second
    assert len(first) == 1536
    assert any(abs(v) > 1e-12 for v in first)


def test_mock_embedding_dimensions() -> None:
    vector = build_mock_embedding("test", 64)
    assert len(vector) == 64


def test_cli_writes_expected_files(tmp_path: Path) -> None:
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A", "ROOM_B")
    output_dir = tmp_path / "artifacts" / "embeddings" / "vendor_ticket_real_pilot"
    code = build_embeddings_main(
        [
            str(corpus_dir),
            "--output-dir",
            str(output_dir),
            "--provider",
            "mock",
            "--model",
            "mock-embedding-1536",
            "--dimensions",
            "1536",
            "--created-at",
            "2026-05-16T12:00:00Z",
        ]
    )
    assert code == 0
    assert (output_dir / "embeddings.jsonl").is_file()
    assert (output_dir / "embedding_manifest.json").is_file()
    assert (output_dir / "embedding.lock.json").is_file()

    manifest = json.loads((output_dir / "embedding_manifest.json").read_text(encoding="utf-8"))
    assert manifest["document_count"] == 2
    assert manifest["embedding_status"] == "mock_generated"
    assert manifest["indexing_status"] == "not_started"
    assert manifest["pgvector_indexed"] is False
    assert manifest["source_corpus_lockfile_hash"] == compute_corpus_lockfile_hash(corpus_dir)


def test_provider_not_mock_fails(tmp_path: Path) -> None:
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A")
    output_dir = tmp_path / "out"
    with pytest.raises(ValueError, match="provider=mock"):
        run_embedding_dry_run(
            corpus_dir,
            output_dir,
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
        )


def test_output_exists_without_overwrite_fails(tmp_path: Path) -> None:
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A")
    output_dir = tmp_path / "out"
    run_embedding_dry_run(
        corpus_dir,
        output_dir,
        embedding_provider="mock",
        embedding_model="mock-embedding-1536",
        embedding_dimensions=1536,
        created_at="2026-05-16T12:00:00Z",
    )
    with pytest.raises(ValueError, match="already exists"):
        run_embedding_dry_run(
            corpus_dir,
            output_dir,
            embedding_provider="mock",
            embedding_model="mock-embedding-1536",
            embedding_dimensions=1536,
            created_at="2026-05-16T12:00:00Z",
        )


def test_embedding_records_exclude_transcript(tmp_path: Path) -> None:
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A")
    output_dir = tmp_path / "out"
    run_embedding_dry_run(
        corpus_dir,
        output_dir,
        embedding_provider="mock",
        embedding_model="mock-embedding-1536",
        embedding_dimensions=1536,
        created_at="2026-05-16T12:00:00Z",
    )
    raw = (output_dir / "embeddings.jsonl").read_text(encoding="utf-8")
    assert "conversation_transcript" not in raw
    assert "سلام" not in raw
    record = json.loads(raw.strip().splitlines()[0])
    assert record["metadata"]["ticket_label"] == "support"
    assert "route_label" in record["metadata"]


def test_lockfile_hashes_output_files(tmp_path: Path) -> None:
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A")
    output_dir = tmp_path / "out"
    run_embedding_dry_run(
        corpus_dir,
        output_dir,
        embedding_provider="mock",
        embedding_model="mock-embedding-1536",
        embedding_dimensions=1536,
        created_at="2026-05-16T12:00:00Z",
    )
    lockfile = json.loads((output_dir / "embedding.lock.json").read_text(encoding="utf-8"))
    by_path = {entry["path"]: entry for entry in lockfile["files"]}
    assert by_path["embeddings.jsonl"]["sha256"] == sha256_file(output_dir / "embeddings.jsonl")
    assert by_path["embedding_manifest.json"]["sha256"] == sha256_file(
        output_dir / "embedding_manifest.json"
    )


def test_record_count_matches_corpus(tmp_path: Path) -> None:
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A", "ROOM_B", "ROOM_C")
    output_dir = tmp_path / "out"
    result = run_embedding_dry_run(
        corpus_dir,
        output_dir,
        embedding_provider="mock",
        embedding_model="mock-embedding-1536",
        embedding_dimensions=1536,
        created_at="2026-05-16T12:00:00Z",
    )
    assert result.document_count == 3
    lines = (output_dir / "embeddings.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


def test_no_openai_or_pgvector_indexing_in_modules() -> None:
    for rel in (
        "app/corpus_planning/embedding_dry_run.py",
        "scripts/build_pilot_corpus_embeddings.py",
    ):
        source = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "import openai" not in source
        assert "embeddings_factory" not in source
        assert "index_corpus_to_pgvector" not in source
        assert "PgVectorStore" not in source

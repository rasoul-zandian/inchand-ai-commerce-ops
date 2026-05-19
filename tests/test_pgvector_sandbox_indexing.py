"""Tests for sandbox pgvector indexing (no Postgres, no OpenAI)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.corpus_planning.embedding_dry_run import (
    build_embedding_lockfile,
    build_embedding_manifest,
    build_mock_embedding,
)
from app.corpus_planning.embedding_integrity import check_embedding_artifact_integrity
from app.corpus_planning.embedding_plan_models import EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED
from app.corpus_planning.pgvector_sandbox_indexing import (
    assert_sandbox_database_url,
    build_indexing_summary,
    build_pgvector_records,
    index_embeddings_to_pgvector_sandbox,
    load_embedding_artifacts,
    validate_embedding_artifact_for_pgvector,
    write_indexing_summary_report,
)
from app.rag.vector_records import VectorRecord
from scripts.index_pilot_embeddings_pgvector import main as index_main

_LOCKFILE_HASH = "8cfc18e1c392a1b2c3d4e5f678901234567890abcdef1234567890abcd"
_OPENAI_MODEL = "text-embedding-3-small"
_DIMENSIONS = 1536


def _write_real_openai_artifacts(
    output_dir: Path,
    *,
    record_count: int = 25,
    embedding_status: str = EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED,
    embedding_provider: str = "openai",
    embedding_model: str = _OPENAI_MODEL,
    embedding_dimensions: int = _DIMENSIONS,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index in range(record_count):
        room_id = f"ROOM_{index:02d}"
        document_id = f"doc-{room_id.lower()}"
        embedding_input = f"room_id={room_id}|ticket_label=support|route_label=general"
        vector = build_mock_embedding(embedding_input, embedding_dimensions)
        records.append(
            {
                "document_id": document_id,
                "room_id": room_id,
                "embedding": vector,
                "embedding_provider": embedding_provider,
                "embedding_model": embedding_model,
                "embedding_dimensions": embedding_dimensions,
                "source_corpus_lockfile_hash": _LOCKFILE_HASH,
                "metadata": {
                    "ticket_label": "support",
                    "route_label": "general",
                    "review_priority": "medium",
                },
            }
        )

    embeddings_path = output_dir / "embeddings.jsonl"
    embeddings_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    manifest = build_embedding_manifest(
        embedding_artifact_id="artifact-pilot-openai-test",
        source_corpus_id="vendor_ticket_real_pilot",
        source_corpus_version="1",
        source_corpus_lockfile_hash=_LOCKFILE_HASH,
        source_batch_id="replay_test_v1",
        reviewer_signoff_id="SIGNOFF_TEST",
        document_count=record_count,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        generated_at="2026-05-19T12:00:00Z",
        embedding_status=embedding_status,
    )
    (output_dir / "embedding_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    lockfile = build_embedding_lockfile(
        output_dir,
        embedding_artifact_id="artifact-pilot-openai-test",
        generated_at="2026-05-19T12:00:00Z",
        document_count=record_count,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
    )
    (output_dir / "embedding.lock.json").write_text(
        json.dumps(lockfile, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_dir


def test_load_embedding_artifacts_and_integrity(tmp_path: Path) -> None:
    output_dir = _write_real_openai_artifacts(tmp_path / "embeddings")
    artifacts = load_embedding_artifacts(output_dir)
    assert len(artifacts.records) == 25
    assert artifacts.manifest["embedding_status"] == "real_generated"
    report = check_embedding_artifact_integrity(output_dir)
    assert report.passed


def test_rejects_mock_embeddings(tmp_path: Path) -> None:
    output_dir = _write_real_openai_artifacts(
        tmp_path / "mock_embeddings",
        embedding_status="mock_generated",
        embedding_provider="mock",
        embedding_model="mock-embedding-1536",
    )
    artifacts = load_embedding_artifacts(output_dir)
    with pytest.raises(ValueError, match="real_generated"):
        validate_embedding_artifact_for_pgvector(artifacts)


def test_rejects_wrong_dimensions(tmp_path: Path) -> None:
    output_dir = _write_real_openai_artifacts(
        tmp_path / "bad_dims",
        embedding_dimensions=64,
    )
    artifacts = load_embedding_artifacts(output_dir)
    with pytest.raises(ValueError, match="1536"):
        validate_embedding_artifact_for_pgvector(artifacts)


def test_rejects_forbidden_transcript_field(tmp_path: Path) -> None:
    output_dir = _write_real_openai_artifacts(tmp_path / "forbidden")
    embeddings_path = output_dir / "embeddings.jsonl"
    first = json.loads(embeddings_path.read_text(encoding="utf-8").splitlines()[0])
    first["conversation_transcript"] = "secret text"
    lines = embeddings_path.read_text(encoding="utf-8").splitlines()
    lines[0] = json.dumps(first, ensure_ascii=False)
    embeddings_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    artifacts = load_embedding_artifacts(output_dir)
    with pytest.raises(ValueError, match="forbidden"):
        validate_embedding_artifact_for_pgvector(artifacts)


def test_build_pgvector_records_provenance_no_transcript(tmp_path: Path) -> None:
    output_dir = _write_real_openai_artifacts(tmp_path / "embeddings")
    artifacts = load_embedding_artifacts(output_dir)
    validate_embedding_artifact_for_pgvector(artifacts)
    records = build_pgvector_records(
        artifacts,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
    )
    assert len(records) == 25
    sample = records[0]
    assert sample.record_id.startswith("pilot::vendor_ticket_real_pilot::pilot_v1::")
    assert sample.dimensions == _DIMENSIONS
    assert sample.embedding_provider == "openai"
    assert sample.metadata["namespace"] == "vendor_ticket_real_pilot"
    assert sample.metadata["index_version"] == "pilot_v1"
    assert sample.metadata["pilot_sandbox"] is True
    serialized = sample.model_dump_json()
    for forbidden in ("conversation_transcript", "transcript", "messages"):
        assert forbidden not in serialized.lower()


def test_rejects_semantic_pgvector_16_profile(tmp_path: Path) -> None:
    output_dir = _write_real_openai_artifacts(tmp_path / "embeddings")
    with pytest.raises(ValueError, match="semantic_pgvector_16"):
        index_embeddings_to_pgvector_sandbox(
            output_dir,
            namespace="vendor_ticket_real_pilot",
            index_version="pilot_v1",
            profile="semantic_pgvector_16",
            database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
            upsert_fn=lambda records: len(records),
        )


def test_rejects_production_database_url() -> None:
    with pytest.raises(ValueError, match="production or staging"):
        assert_sandbox_database_url(
            "postgresql://user:pass@mydb.prod.amazonaws.com:5432/inchand_ai"
        )


def test_fake_index_adapter_receives_25_records(tmp_path: Path) -> None:
    output_dir = _write_real_openai_artifacts(tmp_path / "embeddings")
    captured: list[VectorRecord] = []

    def fake_upsert(records: list[VectorRecord]) -> int:
        captured.extend(records)
        return len(records)

    result = index_embeddings_to_pgvector_sandbox(
        output_dir,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
        upsert_fn=fake_upsert,
        summary_path=tmp_path / "reports" / "pgvector_sandbox_indexing_pilot_v1.json",
    )
    assert result.indexed_count == 25
    assert len(captured) == 25
    assert all(record.metadata.get("sandbox_only") for record in captured)


def test_summary_artifact_shape(tmp_path: Path) -> None:
    manifest = {
        "embedding_provider": "openai",
        "embedding_model": _OPENAI_MODEL,
        "embedding_dimensions": _DIMENSIONS,
        "source_corpus_id": "vendor_ticket_real_pilot",
        "source_corpus_lockfile_hash": _LOCKFILE_HASH,
        "embedding_artifact_id": "artifact-pilot-openai-test",
    }
    summary = build_indexing_summary(
        indexed_count=25,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        manifest=manifest,
    )
    assert summary["indexed_count"] == 25
    assert summary["indexing_status"] == "sandbox_indexed"
    assert summary["retrieval_activated"] is False
    assert summary["profile"] == "semantic_pgvector"
    assert "8cfc18e1c392" in summary["source_corpus_lockfile_hash_prefix"]

    path = write_indexing_summary_report(
        summary,
        output_path=tmp_path / "reports" / "pgvector_sandbox_indexing_pilot_v1.json",
    )
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["indexed_count"] == 25


def test_cli_requires_confirm_sandbox(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_dir = _write_real_openai_artifacts(tmp_path / "embeddings")
    code = index_main(
        [
            str(output_dir),
            "--namespace",
            "vendor_ticket_real_pilot",
            "--index-version",
            "pilot_v1",
            "--profile",
            "semantic_pgvector",
        ]
    )
    assert code == 1
    assert "--confirm-sandbox" in capsys.readouterr().err


def test_cli_rejects_semantic_pgvector_16(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = _write_real_openai_artifacts(tmp_path / "embeddings")
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
    )
    code = index_main(
        [
            str(output_dir),
            "--namespace",
            "vendor_ticket_real_pilot",
            "--index-version",
            "pilot_v1",
            "--profile",
            "semantic_pgvector_16",
            "--confirm-sandbox",
        ]
    )
    assert code == 1
    assert "semantic_pgvector_16" in capsys.readouterr().err


def test_cli_success_with_fake_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = _write_real_openai_artifacts(tmp_path / "embeddings")
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
    )

    def fake_index(
        embedding_dir: Path,
        **kwargs: object,
    ) -> object:
        from app.corpus_planning.pgvector_sandbox_indexing import SandboxIndexingResult

        _ = embedding_dir
        summary_path = tmp_path / "reports" / "pgvector_sandbox_indexing_pilot_v1.json"
        return SandboxIndexingResult(
            indexed_count=25,
            namespace="vendor_ticket_real_pilot",
            index_version="pilot_v1",
            profile="semantic_pgvector",
            dimensions=_DIMENSIONS,
            embedding_provider="openai",
            embedding_model=_OPENAI_MODEL,
            source_corpus_id="vendor_ticket_real_pilot",
            source_corpus_lockfile_hash=_LOCKFILE_HASH,
            embedding_artifact_id="artifact-pilot-openai-test",
            summary_path=summary_path,
        )

    monkeypatch.setattr(
        "scripts.index_pilot_embeddings_pgvector.index_embeddings_to_pgvector_sandbox",
        fake_index,
    )
    code = index_main(
        [
            str(output_dir),
            "--namespace",
            "vendor_ticket_real_pilot",
            "--index-version",
            "pilot_v1",
            "--profile",
            "semantic_pgvector",
            "--confirm-sandbox",
            "--summary-path",
            str(tmp_path / "reports" / "pgvector_sandbox_indexing_pilot_v1.json"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "indexed_count=25" in out
    assert "conversation_transcript" not in out.lower()
    assert "sk-" not in out

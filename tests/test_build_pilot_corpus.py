"""Tests for controlled pilot corpus builder (synthetic fixtures only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.pilot_corpus_builder import (
    build_pilot_corpus,
    build_pilot_lockfile,
    load_approved_room_ids,
    load_snapshots_by_room_id,
)
from scripts.build_pilot_corpus import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PILOT_CORPUS_DIR = _REPO_ROOT / "corpus" / "vendor_ticket_real_pilot"


def _export_line(
    *,
    room_id: str = "ROOM_A",
    label: str = "support",
    text: str = "سلام پشتیبانی",
) -> str:
    payload = {
        "room_id": room_id,
        "ticket_label": label,
        "ticket_subtype": "general",
        "seller_id": "SELLER_ID_001",
        "messages": [
            {"message_id": "m1", "sender_type": "seller", "text": text},
            {
                "message_id": "m2",
                "sender_type": "support_agent",
                "text": "در حال بررسی",
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _write_export(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_approved(path: Path, *room_ids: str) -> None:
    content = "# approved subset\n\n" + "\n".join(room_ids) + "\n"
    path.write_text(content, encoding="utf-8")


def test_load_approved_room_ids_skips_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "approved.txt"
    path.write_text("# header\nROOM_B\n\nROOM_A\n", encoding="utf-8")
    assert load_approved_room_ids(path) == ["ROOM_B", "ROOM_A"]


def test_empty_approved_list_fails(tmp_path: Path) -> None:
    path = tmp_path / "approved.txt"
    path.write_text("# only comment\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_approved_room_ids(path)


def test_builds_corpus_with_selected_records_only(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    approved = tmp_path / "approved.txt"
    corpus_dir = tmp_path / "corpus" / "vendor_ticket_real_pilot"

    _write_export(
        export,
        _export_line(room_id="ROOM_A", label="support"),
        _export_line(room_id="ROOM_B", label="fund"),
        _export_line(room_id="ROOM_C", label="complaint"),
    )
    _write_approved(approved, "ROOM_B", "ROOM_A")

    result = build_pilot_corpus(
        export,
        approved_room_ids=["ROOM_B", "ROOM_A"],
        corpus_dir=corpus_dir,
        source_batch_id="replay_test_v1",
        reviewer_signoff_id="SIGNOFF_TEST_001",
        created_at="2026-05-16T10:00:00Z",
    )

    assert result.approved_record_count == 2
    assert result.document_ids == ["ROOM_B", "ROOM_A"]

    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["embedding_status"] == "not_started"
    assert manifest["indexing_status"] == "not_started"
    assert manifest["document_ids"] == ["ROOM_B", "ROOM_A"]
    assert manifest["governance"]["embeddings_generated"] is False
    assert manifest["governance"]["indexed_to_pgvector"] is False

    doc_b = json.loads((corpus_dir / "documents" / "ROOM_B.json").read_text(encoding="utf-8"))
    assert doc_b["room_id"] == "ROOM_B"
    assert doc_b["metadata"]["replay_approved"] is True
    assert "conversation_transcript" in doc_b
    assert (corpus_dir / "documents" / "ROOM_C.json").exists() is False

    summary_path = corpus_dir / "metadata" / "build_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["ordering"] == "approved_room_ids_file_order"


def test_fails_on_missing_room_id(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    _write_export(export, _export_line(room_id="ROOM_A"))
    with pytest.raises(ValueError, match="not found"):
        build_pilot_corpus(
            export,
            approved_room_ids=["ROOM_MISSING"],
            corpus_dir=tmp_path / "corpus",
            source_batch_id="batch",
            reviewer_signoff_id="SIGNOFF_1",
        )


def test_fails_on_duplicate_room_id_in_export(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    _write_export(export, _export_line(room_id="ROOM_A"), _export_line(room_id="ROOM_A"))
    with pytest.raises(ValueError, match="duplicate room_id"):
        load_snapshots_by_room_id(export.read_text(encoding="utf-8").splitlines())


def test_lockfile_hashes_files(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    corpus_dir = tmp_path / "corpus"
    _write_export(export, _export_line(room_id="ROOM_A"))
    build_pilot_corpus(
        export,
        approved_room_ids=["ROOM_A"],
        corpus_dir=corpus_dir,
        source_batch_id="batch",
        reviewer_signoff_id="SIGNOFF_1",
        created_at="2026-05-16T10:00:00Z",
    )
    lockfile = json.loads((corpus_dir / "corpus.lock.json").read_text(encoding="utf-8"))
    paths = {entry["path"] for entry in lockfile["files"]}
    assert "manifest.json" in paths
    assert "documents/ROOM_A.json" in paths
    assert lockfile["metadata"]["approved_record_count"] == 1
    assert all(entry["sha256"] for entry in lockfile["files"])

    recomputed = build_pilot_lockfile(
        corpus_dir,
        created_at="2026-05-16T10:00:00Z",
        approved_record_count=1,
    )
    assert recomputed["files"] == lockfile["files"]


def test_overwrite_behavior(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    corpus_dir = tmp_path / "corpus"
    _write_export(export, _export_line(room_id="ROOM_A"))
    build_pilot_corpus(
        export,
        approved_room_ids=["ROOM_A"],
        corpus_dir=corpus_dir,
        source_batch_id="batch",
        reviewer_signoff_id="SIGNOFF_1",
        created_at="2026-05-16T10:00:00Z",
    )
    with pytest.raises(ValueError, match="already exists"):
        build_pilot_corpus(
            export,
            approved_room_ids=["ROOM_A"],
            corpus_dir=corpus_dir,
            source_batch_id="batch",
            reviewer_signoff_id="SIGNOFF_1",
        )
    build_pilot_corpus(
        export,
        approved_room_ids=["ROOM_A"],
        corpus_dir=corpus_dir,
        source_batch_id="batch",
        reviewer_signoff_id="SIGNOFF_2",
        overwrite=True,
        created_at="2026-05-16T11:00:00Z",
    )
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["reviewer_signoff_id"] == "SIGNOFF_2"


def test_forbidden_secret_in_export_fails(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    line = json.loads(_export_line(room_id="ROOM_A"))
    line["api_key"] = "sk-should-not-appear"
    export.write_text(json.dumps(line) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden"):
        build_pilot_corpus(
            export,
            approved_room_ids=["ROOM_A"],
            corpus_dir=tmp_path / "corpus",
            source_batch_id="batch",
            reviewer_signoff_id="SIGNOFF_1",
        )


def test_cli_success(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    approved = tmp_path / "approved.txt"
    corpus_dir = tmp_path / "pilot_corpus"
    _write_export(export, _export_line(room_id="ROOM_A"))
    _write_approved(approved, "ROOM_A")

    code = main(
        [
            str(export),
            "--approved-room-ids",
            str(approved),
            "--corpus-dir",
            str(corpus_dir),
            "--source-batch-id",
            "replay_cli_v1",
            "--reviewer-signoff-id",
            "SIGNOFF_CLI",
            "--created-at",
            "2026-05-16T12:00:00Z",
        ]
    )
    assert code == 0
    assert (corpus_dir / "manifest.json").is_file()


def test_no_embeddings_or_pgvector_imports() -> None:
    builder_source = (_REPO_ROOT / "app" / "corpus_planning" / "pilot_corpus_builder.py").read_text(
        encoding="utf-8"
    )
    script_source = (_REPO_ROOT / "scripts" / "build_pilot_corpus.py").read_text(encoding="utf-8")
    for source in (builder_source, script_source):
        assert "import openai" not in source
        assert "pgvector_store" not in source
        assert "index_corpus_to_pgvector" not in source
        assert "embeddings_factory" not in source


@pytest.mark.skipif(
    _PILOT_CORPUS_DIR.exists(),
    reason="local pilot corpus present after controlled build",
)
def test_committed_repo_has_no_pilot_corpus_directory() -> None:
    assert not _PILOT_CORPUS_DIR.exists()

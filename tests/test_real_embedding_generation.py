"""Tests for real OpenAI pilot embedding generation (mocked/no network)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.corpus_planning.embedding_plan_models import EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED
from app.corpus_planning.pilot_corpus_builder import build_pilot_corpus
from app.corpus_planning.real_embedding_generation import (
    generate_openai_embedding,
    require_openai_api_key,
    run_real_embedding_generation,
    validate_openai_pilot_config,
)
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


def _fake_openai_vector(dimensions: int = 1536) -> list[float]:
    return [0.01] * (dimensions - 1) + [0.02]


def test_openai_without_confirm_flag_fails_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A")
    output_dir = tmp_path / "out"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    with patch(
        "app.corpus_planning.real_embedding_generation.generate_openai_embedding",
        side_effect=lambda text, model, dimensions: _fake_openai_vector(dimensions),
    ):
        code_ok = build_embeddings_main(
            [
                str(corpus_dir),
                "--output-dir",
                str(output_dir),
                "--provider",
                "openai",
                "--confirm-real-openai",
                "--created-at",
                "2026-05-16T14:00:00Z",
            ]
        )
    assert code_ok == 0
    code_no_confirm = build_embeddings_main(
        [
            str(corpus_dir),
            "--output-dir",
            str(output_dir / "other"),
            "--provider",
            "openai",
        ]
    )
    assert code_no_confirm == 1


def test_openai_without_api_key_fails_before_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A")
    output_dir = tmp_path / "out"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = build_embeddings_main(
        [
            str(corpus_dir),
            "--output-dir",
            str(output_dir),
            "--provider",
            "openai",
            "--confirm-real-openai",
        ]
    )
    assert code == 1
    assert not output_dir.exists() or not any(output_dir.iterdir())


def test_openai_invalid_dimensions_fails() -> None:
    with pytest.raises(ValueError, match="dimensions must be 1536"):
        validate_openai_pilot_config(model="text-embedding-3-small", dimensions=64)


def test_require_openai_api_key_fails_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        require_openai_api_key()


@patch("app.corpus_planning.real_embedding_generation.generate_openai_embedding")
def test_real_provider_writes_artifacts(
    mock_embed: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_embed.side_effect = lambda text, model, dimensions: _fake_openai_vector(dimensions)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A", "ROOM_B")
    output_dir = tmp_path / "openai_out"
    result = run_real_embedding_generation(
        corpus_dir,
        output_dir,
        created_at="2026-05-16T14:00:00Z",
    )
    assert result.document_count == 2
    manifest = json.loads((output_dir / "embedding_manifest.json").read_text(encoding="utf-8"))
    assert manifest["embedding_status"] == EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED
    assert manifest["embedding_provider"] == "openai"
    assert manifest["embedding_model"] == "text-embedding-3-small"
    assert manifest["embedding_dimensions"] == 1536
    assert manifest["indexing_status"] == "not_started"
    assert manifest["pgvector_indexed"] is False

    raw_lines = (output_dir / "embeddings.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(raw_lines[0])
    assert record["embedding_provider"] == "openai"
    assert record["embedding_model"] == "text-embedding-3-small"
    assert len(record["embedding"]) == 1536


@patch("openai.OpenAI")
def test_generate_openai_embedding_monkeypatched(
    mock_openai_cls: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=_fake_openai_vector())]
    mock_client.embeddings.create.return_value = mock_response
    mock_openai_cls.return_value = mock_client

    vector = generate_openai_embedding("test text", "text-embedding-3-small", 1536)
    assert len(vector) == 1536
    mock_client.embeddings.create.assert_called_once()


def test_artifacts_contain_no_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-test-key-do-not-leak")
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A")
    output_dir = tmp_path / "openai_out"

    with patch(
        "app.corpus_planning.real_embedding_generation.generate_openai_embedding",
        side_effect=lambda text, model, dimensions: _fake_openai_vector(dimensions),
    ):
        run_real_embedding_generation(
            corpus_dir,
            output_dir,
            created_at="2026-05-16T14:00:00Z",
        )

    for path in output_dir.glob("*"):
        content = path.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" not in content
        assert "sk-secret" not in content
        assert "conversation_transcript" not in content


def test_output_dir_exists_without_overwrite_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A")
    output_dir = tmp_path / "openai_out"
    with patch(
        "app.corpus_planning.real_embedding_generation.generate_openai_embedding",
        side_effect=lambda text, model, dimensions: _fake_openai_vector(dimensions),
    ):
        run_real_embedding_generation(
            corpus_dir,
            output_dir,
            created_at="2026-05-16T14:00:00Z",
        )
        with pytest.raises(ValueError, match="already exists"):
            run_real_embedding_generation(
                corpus_dir,
                output_dir,
                created_at="2026-05-16T15:00:00Z",
            )


def test_mock_provider_still_works_via_cli(tmp_path: Path) -> None:
    corpus_dir = _build_synthetic_corpus(tmp_path, "ROOM_A")
    output_dir = tmp_path / "mock_out"
    code = build_embeddings_main(
        [
            str(corpus_dir),
            "--output-dir",
            str(output_dir),
            "--provider",
            "mock",
            "--created-at",
            "2026-05-16T12:00:00Z",
        ]
    )
    assert code == 0
    manifest = json.loads((output_dir / "embedding_manifest.json").read_text(encoding="utf-8"))
    assert manifest["embedding_status"] == "mock_generated"


def test_real_module_no_top_level_openai_import() -> None:
    source = (_REPO_ROOT / "app/corpus_planning/real_embedding_generation.py").read_text(
        encoding="utf-8"
    )
    lines = source.splitlines()
    for line in lines[:30]:
        assert not line.strip().startswith("import openai")
        assert not line.strip().startswith("from openai")

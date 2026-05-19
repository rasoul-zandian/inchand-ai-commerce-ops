"""Tests for offline embedding generation planning (no API calls or embeddings)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.corpus_planning.embedding_plan_models import (
    EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED,
    EmbeddingGenerationPlan,
    EmbeddingPlanStatus,
    embedding_plan_ready_for_dry_run,
    real_embedding_plan_ready,
)
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EMBEDDING_PLAN_DOC = _REPO_ROOT / "docs" / "operations" / "offline_embedding_generation_plan.md"
_REAL_EMBEDDING_PLAN_DOC = (
    _REPO_ROOT / "docs" / "operations" / "real_openai_embedding_generation_plan.md"
)
_README = _REPO_ROOT / "README.md"
_GITIGNORE = _REPO_ROOT / ".gitignore"


def _sample_plan(**overrides: object) -> EmbeddingGenerationPlan:
    base: dict[str, object] = {
        "corpus_id": "vendor_ticket_real_pilot",
        "corpus_version": "1",
        "corpus_lockfile_hash": "abc123def456",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
        "output_policy": "local/private artifacts only",
        "status": EmbeddingPlanStatus.APPROVED_FOR_DRY_RUN,
    }
    base.update(overrides)
    return EmbeddingGenerationPlan.model_validate(base)


def test_embedding_plan_model_validation() -> None:
    plan = _sample_plan()
    assert plan.corpus_id == "vendor_ticket_real_pilot"
    assert plan.embedding_dimensions == 1536


def test_invalid_dimensions_rejected() -> None:
    with pytest.raises(ValidationError):
        _sample_plan(embedding_dimensions=0)
    with pytest.raises(ValidationError):
        _sample_plan(embedding_dimensions=-1)


def test_empty_lockfile_hash_rejected() -> None:
    with pytest.raises(ValidationError):
        _sample_plan(corpus_lockfile_hash="   ")


def test_empty_output_policy_rejected() -> None:
    with pytest.raises(ValidationError):
        _sample_plan(output_policy="")


def test_ready_for_dry_run_when_approved() -> None:
    assert embedding_plan_ready_for_dry_run(_sample_plan()) is True


def test_planned_status_not_ready() -> None:
    plan = _sample_plan(status=EmbeddingPlanStatus.PLANNED)
    assert embedding_plan_ready_for_dry_run(plan) is False


def test_blocked_status_not_ready() -> None:
    plan = _sample_plan(status=EmbeddingPlanStatus.BLOCKED)
    assert embedding_plan_ready_for_dry_run(plan) is False


def test_completed_status_not_ready() -> None:
    plan = _sample_plan(status=EmbeddingPlanStatus.COMPLETED)
    assert embedding_plan_ready_for_dry_run(plan) is False


def test_output_policy_must_indicate_local_or_private() -> None:
    plan = _sample_plan(output_policy="public cloud bucket")
    assert embedding_plan_ready_for_dry_run(plan) is False


def test_real_embedding_plan_ready_when_approved_for_real_run() -> None:
    plan = _sample_plan(status=EmbeddingPlanStatus.APPROVED_FOR_REAL_RUN)
    assert real_embedding_plan_ready(plan) is True


def test_real_embedding_plan_ready_when_approved_for_dry_run() -> None:
    plan = _sample_plan(status=EmbeddingPlanStatus.APPROVED_FOR_DRY_RUN)
    assert real_embedding_plan_ready(plan) is True


def test_real_embedding_invalid_dimensions_not_ready() -> None:
    plan = _sample_plan(embedding_dimensions=64)
    assert real_embedding_plan_ready(plan) is False


def test_real_embedding_missing_corpus_hash_not_ready() -> None:
    with pytest.raises(ValidationError):
        _sample_plan(corpus_lockfile_hash="")
    with pytest.raises(ValidationError):
        EmbeddingGenerationPlan.model_validate(
            {
                "corpus_id": "vendor_ticket_real_pilot",
                "corpus_version": "1",
                "corpus_lockfile_hash": "",
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-small",
                "embedding_dimensions": 1536,
                "output_policy": "local/private",
                "status": EmbeddingPlanStatus.APPROVED_FOR_REAL_RUN,
            }
        )


def test_real_embedding_non_openai_provider_not_ready() -> None:
    plan = _sample_plan(
        embedding_provider="mock",
        status=EmbeddingPlanStatus.APPROVED_FOR_REAL_RUN,
    )
    assert real_embedding_plan_ready(plan) is False


def test_real_embedding_planned_status_not_ready() -> None:
    plan = _sample_plan(status=EmbeddingPlanStatus.PLANNED)
    assert real_embedding_plan_ready(plan) is False


def test_real_generated_status_constant() -> None:
    assert EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED == "real_generated"


def test_real_openai_embedding_plan_doc_governance() -> None:
    text = _REAL_EMBEDDING_PLAN_DOC.read_text(encoding="utf-8")
    assert "Real OpenAI Embedding Generation Plan" in text
    assert "Planning only" in text or "planning only" in text
    assert "no OpenAI API" in text or "no OpenAI" in text or "no API" in text.lower()
    assert "pgvector" in text.lower()
    assert "not_started" in text
    assert "artifacts/embeddings/" in text
    assert "vendor_ticket_real_pilot_openai" in text
    assert "real_generated" in text
    assert "OPENAI_API_KEY" in text


def test_readme_links_real_openai_embedding_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/real_openai_embedding_generation_plan.md" in readme


def test_offline_embedding_plan_doc_governance() -> None:
    text = _EMBEDDING_PLAN_DOC.read_text(encoding="utf-8")
    assert "Offline Embedding Generation Plan" in text
    assert "Planning only" in text or "planning only" in text
    assert "not_started" in text
    assert "no embeddings generated" in text.lower() or "no embedding" in text.lower()
    assert "OpenAI" in text or "openai" in text
    assert "no OpenAI" in text or "no API" in text or "no api" in text.lower()
    assert "pgvector" in text.lower()
    assert "corpus_lockfile_hash" in text
    assert "artifacts/embeddings/" in text


def test_readme_links_offline_embedding_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/offline_embedding_generation_plan.md" in readme


def test_gitignore_excludes_embedding_artifacts() -> None:
    text = _GITIGNORE.read_text(encoding="utf-8")
    assert "artifacts/embeddings/" in text
    assert "artifacts/vector_indexes/" in text


def test_embedding_plan_module_has_no_openai_import() -> None:
    source = (_REPO_ROOT / "app" / "corpus_planning" / "embedding_plan_models.py").read_text(
        encoding="utf-8"
    )
    assert "import openai" not in source
    assert "embeddings_factory" not in source

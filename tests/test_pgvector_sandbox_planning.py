"""Tests for pgvector sandbox indexing planning (no Postgres or pgvector runtime)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.corpus_planning.pgvector_plan_models import (
    PgVectorPlanStatus,
    PgVectorSandboxPlan,
    pgvector_plan_ready_for_sandbox,
)
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PGVECTOR_PLAN_DOC = _REPO_ROOT / "docs" / "operations" / "pgvector_sandbox_indexing_plan.md"
_README = _REPO_ROOT / "README.md"


def _sample_plan(**overrides: object) -> PgVectorSandboxPlan:
    base: dict[str, object] = {
        "corpus_id": "vendor_ticket_real_pilot",
        "embedding_artifact_id": "vendor_ticket_real_pilot_openai_8cfc18e1c392",
        "source_corpus_lockfile_hash": "abc123def456",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
        "proposed_profile": "semantic_pgvector",
        "sandbox_only": True,
        "retrieval_activation_allowed": False,
        "status": PgVectorPlanStatus.APPROVED_FOR_SANDBOX,
    }
    base.update(overrides)
    return PgVectorSandboxPlan.model_validate(base)


def test_pgvector_plan_model_validation() -> None:
    plan = _sample_plan()
    assert plan.corpus_id == "vendor_ticket_real_pilot"
    assert plan.embedding_dimensions == 1536
    assert plan.proposed_profile == "semantic_pgvector"


def test_empty_corpus_lockfile_hash_rejected() -> None:
    with pytest.raises(ValidationError):
        _sample_plan(source_corpus_lockfile_hash="   ")


def test_ready_for_sandbox_when_approved() -> None:
    assert pgvector_plan_ready_for_sandbox(_sample_plan()) is True


def test_planned_status_not_ready() -> None:
    plan = _sample_plan(status=PgVectorPlanStatus.PLANNED)
    assert pgvector_plan_ready_for_sandbox(plan) is False


def test_retrieval_activation_allowed_not_ready() -> None:
    plan = _sample_plan(retrieval_activation_allowed=True)
    assert pgvector_plan_ready_for_sandbox(plan) is False


def test_sandbox_only_false_not_ready() -> None:
    plan = _sample_plan(sandbox_only=False)
    assert pgvector_plan_ready_for_sandbox(plan) is False


def test_invalid_dimensions_rejected() -> None:
    with pytest.raises(ValidationError):
        _sample_plan(embedding_dimensions=0)


def test_pgvector_plan_doc_exists() -> None:
    text = _PGVECTOR_PLAN_DOC.read_text(encoding="utf-8")
    assert "PgVector Sandbox Indexing Plan" in text
    assert "sandbox" in text.lower()
    assert "no production retrieval" in text.lower() or "No production retrieval" in text
    assert "cosine" in text.lower()
    assert "semantic_pgvector" in text
    assert "semantic_pgvector_16" in text
    assert "evaluation" in text.lower()
    assert "schema proposal only" in text.lower()


def test_readme_links_pgvector_sandbox_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "pgvector_sandbox_indexing_plan.md" in readme


def test_pgvector_plan_module_no_runtime_imports() -> None:
    source = (_REPO_ROOT / "app/corpus_planning/pgvector_plan_models.py").read_text(
        encoding="utf-8"
    )
    assert "psycopg" not in source
    assert "PgVectorStore" not in source
    assert "import openai" not in source

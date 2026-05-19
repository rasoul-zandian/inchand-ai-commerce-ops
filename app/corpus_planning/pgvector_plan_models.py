"""PgVector sandbox indexing planning contracts (no DB, SQL, or retrieval I/O)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class PgVectorPlanStatus(StrEnum):
    PLANNED = "planned"
    APPROVED_FOR_SANDBOX = "approved_for_sandbox"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class PgVectorSandboxPlan(BaseModel):
    corpus_id: str
    embedding_artifact_id: str
    source_corpus_lockfile_hash: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int = Field(gt=0)
    proposed_profile: str
    sandbox_only: bool = True
    retrieval_activation_allowed: bool = False
    status: PgVectorPlanStatus = PgVectorPlanStatus.PLANNED
    notes: str | None = None

    @field_validator(
        "corpus_id",
        "embedding_artifact_id",
        "source_corpus_lockfile_hash",
        "proposed_profile",
    )
    @classmethod
    def non_empty_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must be non-empty")
        return cleaned

    @field_validator("embedding_provider", "embedding_model")
    @classmethod
    def provider_fields_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("embedding_provider and embedding_model must be non-empty")
        return value.strip()


def pgvector_plan_ready_for_sandbox(plan: PgVectorSandboxPlan) -> bool:
    """True when governance metadata allows a future sandbox indexing run (not execution)."""
    if plan.status is not PgVectorPlanStatus.APPROVED_FOR_SANDBOX:
        return False
    if not plan.sandbox_only:
        return False
    if plan.retrieval_activation_allowed:
        return False
    if plan.embedding_dimensions <= 0:
        return False
    if not plan.embedding_provider.strip() or not plan.embedding_model.strip():
        return False
    if not plan.source_corpus_lockfile_hash.strip():
        return False
    if not plan.embedding_artifact_id.strip():
        return False
    return True

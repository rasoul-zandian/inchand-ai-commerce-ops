"""Offline embedding generation planning contracts (no API calls or vector I/O)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

EMBEDDING_ARTIFACT_STATUS_MOCK_GENERATED = "mock_generated"
EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED = "real_generated"
_OPENAI_PILOT_DIMENSIONS = 1536


class EmbeddingPlanStatus(StrEnum):
    PLANNED = "planned"
    APPROVED_FOR_DRY_RUN = "approved_for_dry_run"
    APPROVED_FOR_REAL_RUN = "approved_for_real_run"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class EmbeddingGenerationPlan(BaseModel):
    corpus_id: str
    corpus_version: str
    corpus_lockfile_hash: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int = Field(gt=0)
    output_policy: str
    status: EmbeddingPlanStatus = EmbeddingPlanStatus.PLANNED
    notes: str | None = None

    @field_validator("corpus_id", "corpus_version", "corpus_lockfile_hash", "output_policy")
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


def _output_policy_is_local_private(plan: EmbeddingGenerationPlan) -> bool:
    policy = plan.output_policy.lower()
    return "local" in policy or "private" in policy


def embedding_plan_ready_for_dry_run(plan: EmbeddingGenerationPlan) -> bool:
    """True when governance metadata allows a future offline dry-run (not execution)."""
    if plan.status is not EmbeddingPlanStatus.APPROVED_FOR_DRY_RUN:
        return False
    if not plan.corpus_lockfile_hash.strip():
        return False
    if plan.embedding_dimensions <= 0:
        return False
    return _output_policy_is_local_private(plan)


def real_embedding_plan_ready(plan: EmbeddingGenerationPlan) -> bool:
    """True when governance metadata allows a future real OpenAI run (not execution)."""
    if plan.status not in (
        EmbeddingPlanStatus.APPROVED_FOR_DRY_RUN,
        EmbeddingPlanStatus.APPROVED_FOR_REAL_RUN,
    ):
        return False
    if plan.embedding_provider.strip().lower() != "openai":
        return False
    if not plan.embedding_model.strip():
        return False
    if plan.embedding_dimensions != _OPENAI_PILOT_DIMENSIONS:
        return False
    if not plan.corpus_lockfile_hash.strip():
        return False
    return _output_policy_is_local_private(plan)

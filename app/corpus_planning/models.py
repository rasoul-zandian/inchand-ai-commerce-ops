"""Pilot corpus planning metadata (no persistence, indexing, or embeddings)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class PilotCorpusStatus(StrEnum):
    PLANNED = "planned"
    REVIEW_REQUIRED = "review_required"
    APPROVED_FOR_BUILD = "approved_for_build"
    BLOCKED = "blocked"


class PilotCorpusPlan(BaseModel):
    corpus_id: str
    source_batch_id: str
    candidate_record_count: int = Field(ge=0)
    approved_record_count: int = Field(ge=0)
    blocked_record_count: int = Field(ge=0)
    privacy_review_completed: bool = False
    replay_review_completed: bool = False
    status: PilotCorpusStatus = PilotCorpusStatus.PLANNED
    notes: str | None = None

    @field_validator("corpus_id", "source_batch_id")
    @classmethod
    def identifiers_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("corpus_id and source_batch_id must be non-empty")
        return value.strip()

    @model_validator(mode="after")
    def counts_within_candidate(self) -> PilotCorpusPlan:
        if self.approved_record_count > self.candidate_record_count:
            raise ValueError("approved_record_count cannot exceed candidate_record_count")
        if self.blocked_record_count > self.candidate_record_count:
            raise ValueError("blocked_record_count cannot exceed candidate_record_count")
        if self.approved_record_count + self.blocked_record_count > self.candidate_record_count:
            raise ValueError(
                "approved_record_count + blocked_record_count cannot exceed candidate_record_count"
            )
        return self

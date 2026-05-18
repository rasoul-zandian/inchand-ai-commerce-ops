"""Structured privacy-warning review contracts (aggregate-safe, no raw text)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class PrivacyWarningType(StrEnum):
    CARD_LIKE_LONG_DIGITS = "card_like_long_digits"
    IBAN_LIKE = "iban_like"
    PHONE_LIKE = "phone_like"


class PrivacyWarningRecord(BaseModel):
    room_id: str
    warning_types: list[PrivacyWarningType]
    warning_count: int
    requires_manual_review: bool = True
    corpus_eligible: bool = False
    notes: str | None = None

    @field_validator("room_id")
    @classmethod
    def room_id_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("room_id must be non-empty")
        return value.strip()

    @field_validator("warning_types")
    @classmethod
    def warning_types_non_empty(
        cls,
        value: list[PrivacyWarningType],
    ) -> list[PrivacyWarningType]:
        if not value:
            raise ValueError("warning_types must be non-empty")
        return value

    @field_validator("warning_count")
    @classmethod
    def warning_count_at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("warning_count must be >= 1")
        return value

    @model_validator(mode="after")
    def warning_count_matches_types(self) -> PrivacyWarningRecord:
        if self.warning_count != len(self.warning_types):
            raise ValueError("warning_count must equal len(warning_types)")
        if self.corpus_eligible:
            raise ValueError("corpus_eligible must be False when warnings are present")
        if not self.requires_manual_review:
            raise ValueError("requires_manual_review must be True when warnings are present")
        return self


class PrivacyReviewSummary(BaseModel):
    total_tickets_reviewed: int = Field(ge=0)
    tickets_with_warnings: int = Field(ge=0)
    warning_type_counts: dict[str, int] = Field(default_factory=dict)
    manual_review_required_count: int = Field(ge=0)
    corpus_eligible_count: int = Field(ge=0)
    corpus_blocked_count: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_consistent(self) -> PrivacyReviewSummary:
        if self.tickets_with_warnings > self.total_tickets_reviewed:
            raise ValueError("tickets_with_warnings cannot exceed total_tickets_reviewed")
        if self.manual_review_required_count != self.tickets_with_warnings:
            raise ValueError("manual_review_required_count must equal tickets_with_warnings")
        if self.corpus_eligible_count + self.corpus_blocked_count != self.total_tickets_reviewed:
            raise ValueError("corpus_eligible_count + corpus_blocked_count must equal total")
        if self.corpus_blocked_count != self.tickets_with_warnings:
            raise ValueError("corpus_blocked_count must equal tickets_with_warnings")
        return self

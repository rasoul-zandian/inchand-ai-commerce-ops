"""Human reviewer sign-off contracts (governance metadata only; no corpus I/O)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

_MAX_NOTES_LENGTH = 280
_REQUIRED_CHECKLIST_ITEMS = frozenset(
    {
        "no_raw_pii_visible",
        "anonymization_verified",
        "retrieval_safe",
        "governance_approved",
        "corpus_scope_validated",
    }
)


class ReviewerDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REDACTION = "needs_redaction"
    ESCALATE = "escalate"


class ReviewerRole(StrEnum):
    AI_OPS_REVIEWER = "ai_ops_reviewer"
    PRIVACY_REVIEWER = "privacy_reviewer"
    BUSINESS_REVIEWER = "business_reviewer"
    COMPLIANCE_REVIEWER = "compliance_reviewer"


class ReviewerChecklistItem(StrEnum):
    NO_RAW_PII_VISIBLE = "no_raw_pii_visible"
    ANONYMIZATION_VERIFIED = "anonymization_verified"
    RETRIEVAL_SAFE = "retrieval_safe"
    GOVERNANCE_APPROVED = "governance_approved"
    CORPUS_SCOPE_VALIDATED = "corpus_scope_validated"


class ReviewerChecklistResult(BaseModel):
    item: ReviewerChecklistItem
    passed: bool
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def notes_bounded(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > _MAX_NOTES_LENGTH:
            raise ValueError(f"notes must be at most {_MAX_NOTES_LENGTH} characters")
        if "\n" in cleaned or "\r" in cleaned:
            raise ValueError("notes must be a single-line governance comment")
        return cleaned


class ReviewerSignoffRecord(BaseModel):
    signoff_id: str
    source_batch_id: str
    reviewer_role: ReviewerRole
    reviewer_id: str
    decision: ReviewerDecision
    checklist_results: list[ReviewerChecklistResult]
    privacy_review_completed: bool
    replay_review_completed: bool
    approved_record_count: int = Field(ge=0)
    signed_at_utc: str | None = None

    @field_validator("signoff_id", "source_batch_id", "reviewer_id")
    @classmethod
    def identifiers_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier fields must be non-empty")
        cleaned = value.strip()
        if any(char.isspace() for char in cleaned):
            raise ValueError("identifier fields must not contain whitespace")
        return cleaned

    @field_validator("signed_at_utc")
    @classmethod
    def signed_at_iso8601(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        normalized = cleaned.replace("Z", "+00:00")
        datetime.fromisoformat(normalized)
        return cleaned

    @model_validator(mode="after")
    def checklist_complete_and_consistent(self) -> ReviewerSignoffRecord:
        items = {result.item for result in self.checklist_results}
        missing = _REQUIRED_CHECKLIST_ITEMS - {item.value for item in items}
        if missing:
            raise ValueError(f"missing required checklist items: {sorted(missing)}")

        if len(self.checklist_results) != len(_REQUIRED_CHECKLIST_ITEMS):
            raise ValueError("checklist_results must contain exactly one entry per required item")

        if self.decision == ReviewerDecision.APPROVED:
            failed = [result.item.value for result in self.checklist_results if not result.passed]
            if failed:
                raise ValueError(
                    f"approved decision requires all checklist items passed; failed: {failed}"
                )

        return self

    def checklist_passed(self, item: ReviewerChecklistItem) -> bool:
        for result in self.checklist_results:
            if result.item == item:
                return result.passed
        return False

    @property
    def all_checklist_passed(self) -> bool:
        return all(result.passed for result in self.checklist_results)

    @property
    def requires_escalation(self) -> bool:
        return self.decision == ReviewerDecision.ESCALATE

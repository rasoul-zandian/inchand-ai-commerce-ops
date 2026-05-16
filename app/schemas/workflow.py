"""Core workflow enums and Pydantic schemas (no business logic)."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowType(StrEnum):
    MARKETPLACE_ANALYSIS = "marketplace_analysis"
    VENDOR_TICKET = "vendor_ticket"
    PRODUCT_MODERATION = "product_moderation"
    VENDOR_ONBOARDING = "vendor_onboarding"
    UNKNOWN = "unknown"


class WorkflowStatus(StrEnum):
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class EntityType(StrEnum):
    PRODUCT = "product"
    VENDOR = "vendor"
    TICKET = "ticket"
    APPLICATION = "application"
    UNKNOWN = "unknown"


class ApprovalStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AuditLogEntry(BaseModel):
    node_name: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)


class ToolError(BaseModel):
    tool_name: str
    error_type: str
    message: str
    retryable: bool = False


class RAGSource(BaseModel):
    source_type: str
    title: str
    chunk_id: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

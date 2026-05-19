"""Sandbox retrieval tool contract models (governance boundary; no runtime execution)."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EvalMode = Literal["vector_only", "metadata_filtered"]

_VALID_EVAL_MODES = frozenset({"vector_only", "metadata_filtered"})
_VALID_TICKET_LABELS = frozenset({"support", "complaint", "fund"})
_MIN_TOP_K = 1
_MAX_TOP_K = 50

_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "conversation_transcript",
        "transcript",
        "raw_text",
        "draft_response",
        "final_response",
        "messages",
        "content",
        "retrieved_context",
        "vector",
        "embedding",
        "embeddings",
        "query",
    }
)

_ALLOWED_METADATA_FILTER_FIELDS = frozenset(
    {
        "ticket_label",
        "route_label",
        "review_priority",
    }
)

_FORBIDDEN_METADATA_FILTER_FIELDS = frozenset(
    {
        "namespace",
        "index_version",
        "department",
    }
)


class RetrievalToolMetadataFilter(BaseModel):
    """Approved metadata predicates for sandbox retrieval (stored index fields only)."""

    model_config = ConfigDict(extra="forbid")

    ticket_label: str | None = None
    route_label: str | None = None
    review_priority: str | None = None

    @field_validator("ticket_label")
    @classmethod
    def normalize_ticket_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        label = value.strip().lower()
        if label not in _VALID_TICKET_LABELS:
            allowed = ", ".join(sorted(_VALID_TICKET_LABELS))
            raise ValueError(f"ticket_label must be one of: {allowed}")
        return label

    @field_validator("route_label", "review_priority")
    @classmethod
    def normalize_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> RetrievalToolMetadataFilter:
        if not any((self.ticket_label, self.route_label, self.review_priority)):
            raise ValueError(
                "metadata_filter must include at least one of: "
                "ticket_label, route_label, review_priority"
            )
        return self


class RetrievalToolRequest(BaseModel):
    """Sandbox retrieval tool input (contract only; execution not implemented here)."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=_MIN_TOP_K, le=_MAX_TOP_K)
    namespace: str = Field(min_length=1)
    index_version: str = Field(min_length=1)
    metadata_filter: RetrievalToolMetadataFilter | None = None
    eval_mode: EvalMode | None = None

    @field_validator("query", "namespace", "index_version")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("field must be a non-empty string")
        return text

    @field_validator("eval_mode")
    @classmethod
    def validate_eval_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        mode = value.strip().lower()
        if mode not in _VALID_EVAL_MODES:
            raise ValueError(f"eval_mode must be one of: {', '.join(sorted(_VALID_EVAL_MODES))}")
        return mode


class RetrievalToolResult(BaseModel):
    """Aggregate-safe hit metadata (no transcript, content, or vectors)."""

    model_config = ConfigDict(extra="forbid")

    record_id: str
    score: float
    ticket_label: str
    route_label: str
    review_priority: str

    @field_validator("record_id", "ticket_label", "route_label", "review_priority")
    @classmethod
    def strip_fields(cls, value: str) -> str:
        return value.strip()


class RetrievalToolResponse(BaseModel):
    """Sandbox retrieval tool output envelope."""

    model_config = ConfigDict(extra="forbid")

    results: list[RetrievalToolResult]
    retrieval_activated: bool = False
    sandbox_only: bool = True
    query_hash: str = Field(min_length=8, max_length=64)
    result_count: int = Field(ge=0)

    @model_validator(mode="after")
    def enforce_sandbox_flags_and_counts(self) -> RetrievalToolResponse:
        if self.retrieval_activated:
            raise ValueError("retrieval_activated must be false for sandbox retrieval tool")
        if not self.sandbox_only:
            raise ValueError("sandbox_only must be true for sandbox retrieval tool")
        if self.result_count != len(self.results):
            raise ValueError("result_count must equal len(results)")
        return self


def query_hash(text: str) -> str:
    """Deterministic query fingerprint for audit logs (no raw query in committed artifacts)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def retrieval_tool_response_to_dict(response: RetrievalToolResponse) -> dict[str, Any]:
    """Serialize response for reports; caller must run output safety checks."""
    return response.model_dump()

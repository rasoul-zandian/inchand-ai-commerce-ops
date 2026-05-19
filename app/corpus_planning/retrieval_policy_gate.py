"""Pre-retrieval policy gate contract (allow / skip / deny; no store or network access)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.corpus_planning.retrieval_tool_models import RetrievalToolMetadataFilter
from app.corpus_planning.retrieval_tool_validation import (
    validate_sandbox_index_version,
    validate_sandbox_namespace,
)

_GATE_MIN_TOP_K = 1
_GATE_MAX_TOP_K = 10

_VALID_TICKET_LABELS = frozenset({"support", "complaint", "fund"})
_FUND_REQUIRED_ROUTE_LABEL = "billing_review"


class RetrievalGateDecision(StrEnum):
    ALLOW = "allow"
    SKIP = "skip"
    DENY = "deny"


class RetrievalScenario(StrEnum):
    VENDOR_SUPPORT = "vendor_support"
    COMPLAINT_REVIEW = "complaint_review"
    FUND_FINANCE = "fund_finance"
    UNKNOWN = "unknown"


class RetrievalPolicyGateInput(BaseModel):
    """Inputs available before any pgvector or embedding access."""

    model_config = ConfigDict(extra="forbid")

    ticket_label: str | None = None
    route_label: str | None = None
    detected_intent: str | None = None
    namespace: str = Field(min_length=1)
    index_version: str = Field(min_length=1)
    requested_top_k: int = Field(default=5)
    metadata_filter: RetrievalToolMetadataFilter | None = None
    sandbox_only: bool = True

    @field_validator("ticket_label", "route_label", "detected_intent", "namespace", "index_version")
    @classmethod
    def strip_optional_or_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class RetrievalPolicyGateResult(BaseModel):
    """Policy gate outcome; does not execute retrieval."""

    model_config = ConfigDict(extra="forbid")

    decision: RetrievalGateDecision
    scenario: RetrievalScenario
    reasons: list[str] = Field(default_factory=list)
    required_metadata_filter: RetrievalToolMetadataFilter | None = None
    retrieval_activated: bool = False
    sandbox_only: bool = True

    @field_validator("retrieval_activated")
    @classmethod
    def retrieval_must_stay_off(cls, value: bool) -> bool:
        if value:
            raise ValueError("retrieval_activated must be false for policy gate contract")
        return value


def _scenario_for_ticket_label(ticket_label: str | None) -> RetrievalScenario:
    if ticket_label == "support":
        return RetrievalScenario.VENDOR_SUPPORT
    if ticket_label == "complaint":
        return RetrievalScenario.COMPLAINT_REVIEW
    if ticket_label == "fund":
        return RetrievalScenario.FUND_FINANCE
    return RetrievalScenario.UNKNOWN


def _normalize_ticket_label(value: str | None) -> str | None:
    if value is None:
        return None
    label = value.strip().lower()
    if label in _VALID_TICKET_LABELS:
        return label
    return None


def _deny(
    scenario: RetrievalScenario,
    *reasons: str,
) -> RetrievalPolicyGateResult:
    return RetrievalPolicyGateResult(
        decision=RetrievalGateDecision.DENY,
        scenario=scenario,
        reasons=list(reasons),
        required_metadata_filter=None,
        retrieval_activated=False,
        sandbox_only=True,
    )


def _skip(
    scenario: RetrievalScenario,
    *reasons: str,
) -> RetrievalPolicyGateResult:
    return RetrievalPolicyGateResult(
        decision=RetrievalGateDecision.SKIP,
        scenario=scenario,
        reasons=list(reasons),
        required_metadata_filter=None,
        retrieval_activated=False,
        sandbox_only=True,
    )


def _allow(
    scenario: RetrievalScenario,
    metadata_filter: RetrievalToolMetadataFilter,
    *reasons: str,
) -> RetrievalPolicyGateResult:
    return RetrievalPolicyGateResult(
        decision=RetrievalGateDecision.ALLOW,
        scenario=scenario,
        reasons=list(reasons) or ["retrieval_allowed_for_scenario"],
        required_metadata_filter=metadata_filter,
        retrieval_activated=False,
        sandbox_only=True,
    )


def evaluate_retrieval_policy_gate(
    gate_input: RetrievalPolicyGateInput,
) -> RetrievalPolicyGateResult:
    """Deterministic pre-retrieval policy (no pgvector, embeddings, or LangGraph)."""
    if not gate_input.sandbox_only:
        return _deny(
            RetrievalScenario.UNKNOWN,
            "sandbox_only must be true",
        )

    try:
        validate_sandbox_namespace(gate_input.namespace)
    except ValueError as exc:
        return _deny(RetrievalScenario.UNKNOWN, f"namespace rejected: {exc}")

    try:
        validate_sandbox_index_version(gate_input.index_version)
    except ValueError as exc:
        return _deny(RetrievalScenario.UNKNOWN, f"index_version rejected: {exc}")

    if gate_input.requested_top_k < _GATE_MIN_TOP_K or gate_input.requested_top_k > _GATE_MAX_TOP_K:
        return _deny(
            RetrievalScenario.UNKNOWN,
            f"requested_top_k must be between {_GATE_MIN_TOP_K} and {_GATE_MAX_TOP_K}",
        )

    ticket_label = _normalize_ticket_label(gate_input.ticket_label)
    scenario = _scenario_for_ticket_label(ticket_label)

    if ticket_label is None:
        return _skip(
            RetrievalScenario.UNKNOWN,
            "ticket_label missing or unknown",
        )

    metadata_filter = gate_input.metadata_filter
    if metadata_filter is None:
        if ticket_label == "fund":
            return _deny(
                scenario,
                "fund retrieval requires metadata_filter.ticket_label=fund",
            )
        return _deny(
            scenario,
            f"{ticket_label} retrieval requires metadata_filter.ticket_label={ticket_label}",
        )

    filter_label = metadata_filter.ticket_label
    if filter_label is None:
        return _deny(
            scenario,
            "metadata_filter.ticket_label is required",
        )

    if filter_label != ticket_label:
        return _deny(
            scenario,
            f"metadata_filter.ticket_label={filter_label!r} "
            f"does not match ticket_label={ticket_label!r}",
        )

    if ticket_label == "fund":
        route_label = gate_input.route_label
        if route_label is not None and route_label.strip() != _FUND_REQUIRED_ROUTE_LABEL:
            return _deny(
                scenario,
                f"fund retrieval requires route_label={_FUND_REQUIRED_ROUTE_LABEL!r} "
                f"when route_label is provided",
            )

    return _allow(
        scenario,
        metadata_filter,
        f"retrieval_allowed for {ticket_label}",
    )

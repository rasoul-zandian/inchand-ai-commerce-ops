"""Validation helpers for the sandbox retrieval tool contract (no DB or network)."""

from __future__ import annotations

from typing import Any

from app.corpus_planning.retrieval_tool_models import (
    _ALLOWED_METADATA_FILTER_FIELDS,
    _FORBIDDEN_METADATA_FILTER_FIELDS,
    _FORBIDDEN_OUTPUT_KEYS,
    _MAX_TOP_K,
    _MIN_TOP_K,
    RetrievalToolMetadataFilter,
    RetrievalToolRequest,
    RetrievalToolResponse,
)

_SANDBOX_NAMESPACE_PREFIXES = (
    "vendor_ticket_real_pilot",
    "vendor_ticket_real_pilot_balanced",
)


def validate_sandbox_namespace(namespace: str) -> str:
    """Ensure namespace is non-empty and matches approved sandbox pilot naming."""
    text = namespace.strip()
    if not text:
        raise ValueError("namespace must be a non-empty string")
    approved = any(
        text == prefix or text.startswith(f"{prefix}_") for prefix in _SANDBOX_NAMESPACE_PREFIXES
    )
    if not approved:
        allowed = ", ".join(sorted(_SANDBOX_NAMESPACE_PREFIXES))
        raise ValueError(
            f"namespace {text!r} is not an approved sandbox pilot namespace "
            f"(expected one of: {allowed})"
        )
    return text


def validate_sandbox_index_version(index_version: str) -> str:
    """Ensure index_version is a non-empty sandbox label."""
    text = index_version.strip()
    if not text:
        raise ValueError("index_version must be a non-empty string")
    if not text.startswith("pilot_"):
        raise ValueError("index_version must start with 'pilot_' for sandbox indexes")
    return text


def validate_top_k(top_k: int) -> int:
    """Bound top_k for sandbox retrieval (deterministic, small pilot scope)."""
    if top_k < _MIN_TOP_K or top_k > _MAX_TOP_K:
        raise ValueError(f"top_k must be between {_MIN_TOP_K} and {_MAX_TOP_K}")
    return top_k


def validate_allowed_metadata_filter(
    raw: RetrievalToolMetadataFilter | dict[str, Any] | None,
) -> RetrievalToolMetadataFilter | None:
    """Reject scope pins and arbitrary metadata keys before building the filter model."""
    if raw is None:
        return None
    if isinstance(raw, RetrievalToolMetadataFilter):
        return raw

    if not isinstance(raw, dict):
        raise ValueError("metadata_filter must be an object")

    keys = {str(key) for key in raw.keys()}
    forbidden = keys.intersection(_FORBIDDEN_METADATA_FILTER_FIELDS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(
            f"metadata_filter must not include forbidden keys: {joined} "
            "(use request.namespace and request.index_version)"
        )

    unknown = keys - _ALLOWED_METADATA_FILTER_FIELDS
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"metadata_filter has unsupported keys: {joined}")

    if not any(raw.get(field) for field in _ALLOWED_METADATA_FILTER_FIELDS):
        raise ValueError("metadata_filter must include at least one allowed field")

    return RetrievalToolMetadataFilter.model_validate(raw)


def _collect_json_keys(value: Any, keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).lower())
            _collect_json_keys(child, keys)
    elif isinstance(value, list):
        for item in value:
            _collect_json_keys(item, keys)


def assert_no_forbidden_output_fields(payload: dict[str, Any]) -> None:
    """Reject serialized tool output that would leak transcripts, vectors, or raw queries."""
    keys: set[str] = set()
    _collect_json_keys(payload, keys)
    forbidden = keys.intersection(_FORBIDDEN_OUTPUT_KEYS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(f"retrieval tool output contains forbidden JSON keys: {joined}")


def validate_retrieval_tool_request(
    raw: RetrievalToolRequest | dict[str, Any],
) -> RetrievalToolRequest:
    """Validate a full sandbox retrieval request (contract boundary)."""
    if isinstance(raw, RetrievalToolRequest):
        request = raw
    elif isinstance(raw, dict):
        metadata = validate_allowed_metadata_filter(raw.get("metadata_filter"))
        payload = dict(raw)
        payload["metadata_filter"] = metadata
        request = RetrievalToolRequest.model_validate(payload)
    else:
        raise ValueError("request must be a RetrievalToolRequest or dict")

    validate_sandbox_namespace(request.namespace)
    validate_sandbox_index_version(request.index_version)
    validate_top_k(request.top_k)
    return request


def assert_safe_retrieval_tool_response(response: RetrievalToolResponse) -> None:
    """Validate response flags and serialized safety."""
    if response.retrieval_activated or not response.sandbox_only:
        raise ValueError("sandbox retrieval tool response has invalid activation flags")
    assert_no_forbidden_output_fields(response.model_dump())

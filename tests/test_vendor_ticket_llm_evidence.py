"""Unit tests for vendor ticket LLM evidence helper (no OpenAI calls)."""

from __future__ import annotations

from app.llm.types import LLMResponse
from app.nodes.vendor_ticket import _llm_evidence


def test_llm_evidence_mock_includes_digest() -> None:
    response = LLMResponse(
        content="x",
        provider="mock",
        model="mock-vendor-ticket-drafter",
        metadata={"digest": "deadbeef", "message_count": 2},
    )
    ev = _llm_evidence(response)
    assert "llm_provider=mock" in ev
    assert "llm_model=mock-vendor-ticket-drafter" in ev
    assert "llm_digest=deadbeef" in ev
    assert not any("None" in line for line in ev)


def test_llm_evidence_openai_includes_response_id() -> None:
    response = LLMResponse(
        content="y",
        provider="openai",
        model="gpt-4.1-mini",
        metadata={"response_id": "resp_123", "usage": {"total_tokens": 10}},
    )
    ev = _llm_evidence(response)
    assert "llm_provider=openai" in ev
    assert "llm_model=gpt-4.1-mini" in ev
    assert "llm_response_id=resp_123" in ev
    assert all("llm_digest" not in line for line in ev)
    assert not any("None" in line for line in ev)


def test_llm_evidence_omits_empty_optional_fields() -> None:
    response = LLMResponse(
        content="z",
        provider="mock",
        model="m",
        metadata={"digest": None, "response_id": ""},
    )
    ev = _llm_evidence(response)
    assert "llm_provider=mock" in ev
    assert "llm_model=m" in ev
    assert not any(line.startswith("llm_digest=") for line in ev)
    assert not any(line.startswith("llm_response_id=") for line in ev)
    assert not any("None" in line for line in ev)

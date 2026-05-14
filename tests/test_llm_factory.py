"""Minimal checks for the LLM factory (mock + error paths; no network)."""

import pytest

from app.llm import LLMMessage, LLMResponse, generate_text


def test_mock_provider_returns_llm_response() -> None:
    messages = [
        LLMMessage(role="system", content="You are a support assistant."),
        LLMMessage(role="user", content="سلام، تسویه اشتباه است."),
    ]
    out = generate_text(messages, provider="mock", model="mock-vendor-ticket-drafter")
    assert isinstance(out, LLMResponse)
    assert out.provider == "mock"
    assert out.model == "mock-vendor-ticket-drafter"
    assert out.content
    assert "آزمایشی" in out.content
    assert out.metadata.get("message_count") == 2
    assert out.metadata.get("digest")


def test_unsupported_provider_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        generate_text([], provider="unknown-vendor", model="x")


def test_openai_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without OPENAI_API_KEY, openai branch must fail fast (no network call)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required when LLM_PROVIDER=openai"):
        generate_text(
            [LLMMessage(role="user", content="hello")],
            provider="openai",
            model="gpt-4o-mini",
        )


def test_messages_to_openai_input_format() -> None:
    """Private helper: stable bracketed layout for Responses API input string."""
    from app.llm import factory as factory_module

    text = factory_module._messages_to_openai_input(
        [
            LLMMessage(role="system", content="Sys line."),
            LLMMessage(role="user", content="User line."),
        ]
    )
    assert "[SYSTEM]" in text
    assert "[USER]" in text
    assert "Sys line." in text
    assert "User line." in text

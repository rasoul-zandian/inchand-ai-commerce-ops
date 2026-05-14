"""LLM text generation entry point; routes by provider string (no direct SDK coupling in nodes)."""

from __future__ import annotations

import hashlib
import os
from typing import Any

from openai import OpenAI

from app.llm.types import LLMMessage, LLMResponse


def _messages_to_openai_input(messages: list[LLMMessage]) -> str:
    """Flatten chat-style messages into a single prompt string for the Responses API."""
    blocks: list[str] = []
    for message in messages:
        label = (message.role or "message").strip().upper()
        blocks.append(f"[{label}]\n{message.content}")
    return "\n\n".join(blocks).strip()


def _usage_to_dict(usage: Any) -> Any:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return usage


def _mock_digest(messages: list[LLMMessage]) -> str:
    payload = "|".join(f"{m.role}:{m.content}" for m in messages).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _mock_persian_content(messages: list[LLMMessage], *, model: str) -> str:
    digest = _mock_digest(messages)
    return (
        f"[خروجی آزمایشی قطعی — مدل: {model} — امضای پیام‌ها: {digest}]\n"
        "این یک پاسخ آزمایشی فارسی است که برای توسعهٔ محلی بدون فراخوانی واقعی به ارائه‌دهندهٔ "
        "زبان تولید می‌شود. لطفاً آن را به‌عنوان پاسخ نهایی به فروشنده ارسال نکنید."
    )


def generate_text(
    messages: list[LLMMessage],
    *,
    provider: str = "mock",
    model: str = "mock-vendor-ticket-drafter",
) -> LLMResponse:
    """Generate assistant text; mock is deterministic, OpenAI uses the Responses API."""
    normalized = provider.strip().lower()
    if normalized == "mock":
        content = _mock_persian_content(messages, model=model)
        return LLMResponse(
            content=content,
            provider="mock",
            model=model,
            metadata={
                "message_count": len(messages),
                "digest": _mock_digest(messages),
            },
        )
    if normalized == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        client = OpenAI(api_key=api_key)
        prompt = _messages_to_openai_input(messages)
        response = client.responses.create(model=model, input=prompt)

        return LLMResponse(
            content=response.output_text or "",
            provider="openai",
            model=model,
            metadata={
                "response_id": response.id,
                "usage": _usage_to_dict(response.usage),
            },
        )
    raise ValueError(f"Unsupported LLM provider: {provider!r}")

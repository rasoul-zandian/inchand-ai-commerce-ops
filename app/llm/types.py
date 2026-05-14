"""Provider-agnostic LLM message/response types (no vendor SDK imports here)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    metadata: dict[str, Any] = Field(default_factory=dict)

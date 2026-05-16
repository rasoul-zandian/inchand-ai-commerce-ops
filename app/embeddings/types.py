"""Embedding request/response types (provider-agnostic)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EmbeddingRequest(BaseModel):
    text: str
    model: str
    provider: str = "mock"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingResponse(BaseModel):
    vector: list[float]
    provider: str
    model: str
    dimensions: int
    metadata: dict[str, Any] = Field(default_factory=dict)

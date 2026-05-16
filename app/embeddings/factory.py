"""Embedding generation entry point (mock + optional OpenAI; no vector DB)."""

from __future__ import annotations

import hashlib
import os
from typing import Any

from openai import OpenAI

from app.embeddings.types import EmbeddingResponse


def _mock_vector_and_digest(text: str, *, model: str, provider: str) -> tuple[list[float], str]:
    payload = f"{provider}|{model}|{text}".encode()
    digest = hashlib.sha256(payload).digest()
    vector = [(digest[i] / 127.5) - 1.0 for i in range(16)]
    return vector, hashlib.sha256(payload).hexdigest()


def _usage_metadata(usage: Any) -> Any:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return usage


def generate_embedding(
    text: str,
    *,
    provider: str = "mock",
    model: str = "mock-embedding-small",
) -> EmbeddingResponse:
    """Return an embedding vector.

    ``mock`` is deterministic; ``openai`` calls the Embeddings API.
    """
    normalized = provider.strip().lower()
    if normalized == "mock":
        vector, digest_hex = _mock_vector_and_digest(text, model=model, provider=normalized)
        return EmbeddingResponse(
            vector=vector,
            provider="mock",
            model=model,
            dimensions=len(vector),
            metadata={
                "text_length": len(text),
                "digest": digest_hex,
            },
        )
    if normalized == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")

        client = OpenAI(api_key=api_key)
        response = client.embeddings.create(model=model, input=text)
        vec = list(response.data[0].embedding)
        meta: dict[str, Any] = {}
        usage = getattr(response, "usage", None)
        usage_data = _usage_metadata(usage)
        if usage_data is not None:
            meta["usage"] = usage_data
        resp_model = getattr(response, "model", None)
        if resp_model is not None:
            meta["response_model"] = resp_model
        return EmbeddingResponse(
            vector=vec,
            provider="openai",
            model=model,
            dimensions=len(vec),
            metadata=meta,
        )
    raise ValueError(f"Unsupported embedding provider: {provider!r}")

"""Embedding generation surface (types + factory)."""

from app.embeddings.factory import generate_embedding
from app.embeddings.types import EmbeddingRequest, EmbeddingResponse

__all__ = [
    "EmbeddingRequest",
    "EmbeddingResponse",
    "generate_embedding",
]

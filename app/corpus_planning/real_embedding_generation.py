"""Local real OpenAI embedding generation for pilot corpus (no pgvector or retrieval)."""

from __future__ import annotations

import os
from pathlib import Path

from app.corpus_planning.embedding_dry_run import EmbeddingDryRunResult, run_pilot_corpus_embeddings
from app.corpus_planning.embedding_plan_models import (
    EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED,
)

_GENERATOR_VERSION = "real_embedding_generation/1"
_OPENAI_PILOT_MODEL = "text-embedding-3-small"
_OPENAI_PILOT_DIMENSIONS = 1536


def require_openai_api_key() -> None:
    """Fail before any output if the OpenAI API key is not configured locally."""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError("OPENAI_API_KEY is required for provider=openai")


def validate_openai_pilot_config(*, model: str, dimensions: int) -> None:
    """Enforce pilot OpenAI model and dimension policy."""
    if model.strip() != _OPENAI_PILOT_MODEL:
        raise ValueError(
            f"model must be {_OPENAI_PILOT_MODEL!r} for pilot real embedding run (got {model!r})"
        )
    if dimensions != _OPENAI_PILOT_DIMENSIONS:
        raise ValueError(
            f"dimensions must be {_OPENAI_PILOT_DIMENSIONS} for {_OPENAI_PILOT_MODEL} "
            f"(got {dimensions})"
        )


def generate_openai_embedding(text: str, model: str, dimensions: int) -> list[float]:
    """Call OpenAI embeddings API (lazy import; uses ``OPENAI_API_KEY`` from environment)."""
    require_openai_api_key()
    validate_openai_pilot_config(model=model, dimensions=dimensions)

    from openai import OpenAI

    client = OpenAI()
    response = client.embeddings.create(model=model, input=text)
    vector = [float(value) for value in response.data[0].embedding]
    if len(vector) != dimensions:
        raise ValueError(
            f"OpenAI embedding length {len(vector)} != requested dimensions {dimensions}"
        )
    if all(abs(value) < 1e-12 for value in vector):
        raise ValueError("OpenAI embedding must not be all zeros")
    return vector


def run_real_embedding_generation(
    corpus_dir: Path,
    output_dir: Path,
    *,
    embedding_model: str = _OPENAI_PILOT_MODEL,
    embedding_dimensions: int = _OPENAI_PILOT_DIMENSIONS,
    overwrite: bool = False,
    created_at: str | None = None,
) -> EmbeddingDryRunResult:
    """Generate real OpenAI embedding artifacts for the pilot corpus."""
    require_openai_api_key()
    validate_openai_pilot_config(model=embedding_model, dimensions=embedding_dimensions)

    def _embed(text: str) -> list[float]:
        return generate_openai_embedding(text, embedding_model, embedding_dimensions)

    return run_pilot_corpus_embeddings(
        corpus_dir,
        output_dir,
        embedding_provider="openai",
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        embedding_status=EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED,
        generator_version=_GENERATOR_VERSION,
        artifact_label="openai",
        embed_fn=_embed,
        overwrite=overwrite,
        created_at=created_at,
    )

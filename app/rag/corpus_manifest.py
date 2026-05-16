"""Versioned corpus manifest: filesystem-only loading into ``RAGDocument`` rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.rag.types import RAGDocument


class CorpusManifestDocument(BaseModel):
    """Single corpus entry: body lives on disk at ``path`` relative to the corpus root."""

    document_id: str
    source_type: str
    path: str
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def path_must_be_relative(cls, v: str) -> str:
        p = Path(v)
        if p.is_absolute():
            raise ValueError("manifest path must be relative to the corpus directory")
        if ".." in p.parts:
            raise ValueError("manifest path must not contain '..'")
        return v


class CorpusManifest(BaseModel):
    """Typed manifest for a workflow-scoped corpus (explicit document list, deterministic order)."""

    manifest_version: str
    workflow_type: str
    locale: str
    documents: list[CorpusManifestDocument]


def load_corpus_manifest(path: str | Path) -> CorpusManifest:
    """Load and validate ``manifest.json`` from disk (UTF-8)."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corpus manifest is not valid JSON: {p}") from exc
    return CorpusManifest.model_validate(data)


def load_manifest_documents(manifest: CorpusManifest, *, base_dir: Path) -> list[RAGDocument]:
    """Load each manifest row as a ``RAGDocument`` from ``base_dir`` (list order preserved)."""
    root = base_dir.resolve()
    out: list[RAGDocument] = []
    for entry in manifest.documents:
        candidate = (root / entry.path).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"Resolved path escapes corpus root: {entry.path!r}")
        if not candidate.is_file():
            raise FileNotFoundError(
                f"Corpus body file missing for {entry.document_id!r}: {candidate}"
            )
        body = candidate.read_text(encoding="utf-8").rstrip("\r\n")
        meta = dict(entry.metadata)
        meta["workflow_type"] = manifest.workflow_type
        meta["locale"] = manifest.locale
        out.append(
            RAGDocument(
                document_id=entry.document_id,
                title=entry.title,
                content=body,
                source_type=entry.source_type,
                score=None,
                metadata=meta,
            )
        )
    return out

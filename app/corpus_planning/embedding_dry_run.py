"""Offline mock embedding dry-run for pilot corpus (no network, OpenAI, or pgvector)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.corpus_planning.pilot_corpus_builder import _document_filename
from app.corpus_planning.pilot_corpus_integrity import verify_pilot_corpus_integrity
from app.rag.corpus_integrity import sha256_file

_GENERATOR_VERSION = "embedding_dry_run/1"
_LOCK_VERSION = "1"
_FORBIDDEN_ARTIFACT_KEYS = frozenset(
    {
        "conversation_transcript",
        "transcript",
        "messages",
        "final_resolution",
    }
)
_ROUTE_LABEL_BY_TICKET_LABEL: dict[str, str] = {
    "support": "general_vendor_support",
    "complaint": "escalation_review",
    "fund": "billing_review",
}
_PRIORITY_BY_ROUTE: dict[str, str] = {
    "billing_review": "high",
    "escalation_review": "high",
    "qa_attention": "high",
    "general_vendor_support": "normal",
}


@dataclass(frozen=True)
class EmbeddingDryRunResult:
    output_dir: Path
    document_count: int
    embedding_dimensions: int
    embedding_provider: str
    embedding_model: str
    source_corpus_id: str
    source_corpus_lockfile_hash: str
    embeddings_path: Path
    manifest_path: Path
    lockfile_path: Path


def compute_corpus_lockfile_hash(corpus_dir: Path) -> str:
    """SHA-256 hex digest of ``corpus.lock.json``."""
    lock_path = corpus_dir / "corpus.lock.json"
    if not lock_path.is_file():
        raise ValueError(f"corpus lockfile not found: {lock_path}")
    return sha256_file(lock_path)


def build_mock_embedding(text: str, dimensions: int = 1536) -> list[float]:
    """Deterministic mock vector from text (no network; not all zeros)."""
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")

    values: list[float] = []
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    round_index = 0
    while len(values) < dimensions:
        block = hashlib.sha256(seed + round_index.to_bytes(4, "big")).digest()
        for byte in block:
            values.append((byte / 127.5) - 1.0)
            if len(values) >= dimensions:
                break
        round_index += 1

    if all(abs(v) < 1e-12 for v in values):
        values[0] = 0.001
    return values


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _route_label_for_document(document: dict[str, Any]) -> str:
    existing = document.get("route_label")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    label = str(document.get("ticket_label", "")).strip().lower()
    return _ROUTE_LABEL_BY_TICKET_LABEL.get(label, "general_vendor_support")


def _review_priority_for_document(document: dict[str, Any], route_label: str) -> str:
    existing = document.get("review_priority")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    return _PRIORITY_BY_ROUTE.get(route_label, "normal")


def embedding_input_text(document: dict[str, Any]) -> str:
    """Build deterministic embedding input without transcript text."""
    room_id = str(document.get("room_id", ""))
    ticket_label = str(document.get("ticket_label", ""))
    ticket_subtype = str(document.get("ticket_subtype", ""))
    message_count = document.get("message_count", 0)
    route_label = _route_label_for_document(document)
    return "|".join(
        [
            f"room_id={room_id}",
            f"ticket_label={ticket_label}",
            f"ticket_subtype={ticket_subtype}",
            f"message_count={message_count}",
            f"route_label={route_label}",
        ]
    )


def load_pilot_corpus_documents(corpus_dir: Path) -> list[dict[str, Any]]:
    """Load pilot corpus documents in manifest order."""
    manifest_path = corpus_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"manifest not found: {manifest_path}")

    manifest = _load_json(manifest_path)
    document_ids = manifest.get("document_ids")
    if not isinstance(document_ids, list) or not document_ids:
        raise ValueError("manifest.document_ids must be a non-empty list")

    documents_dir = corpus_dir / "documents"
    if not documents_dir.is_dir():
        raise ValueError(f"documents directory not found: {documents_dir}")

    loaded: list[dict[str, Any]] = []
    for doc_id in document_ids:
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError("manifest.document_ids must contain non-empty strings")
        doc_path = documents_dir / _document_filename(doc_id)
        if not doc_path.is_file():
            raise ValueError(f"missing document file for {doc_id!r}: {doc_path}")
        document = _load_json(doc_path)
        document["_document_id"] = doc_id
        document["_source_path"] = str(doc_path)
        loaded.append(document)
    return loaded


def build_embedding_record(
    document: dict[str, Any],
    embedding: list[float],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Build one embeddings.jsonl record (no transcript fields)."""
    document_id = str(document.get("_document_id", document.get("room_id", "")))
    room_id = str(document.get("room_id", document_id))
    source_path = Path(str(document["_source_path"]))
    source_document_hash = sha256_file(source_path)

    record: dict[str, Any] = {
        "document_id": document_id,
        "room_id": room_id,
        "embedding": embedding,
        "embedding_dimensions": len(embedding),
        "embedding_provider": metadata["embedding_provider"],
        "embedding_model": metadata["embedding_model"],
        "source_corpus_id": metadata["source_corpus_id"],
        "source_corpus_version": metadata["source_corpus_version"],
        "source_corpus_lockfile_hash": metadata["source_corpus_lockfile_hash"],
        "source_document_hash": source_document_hash,
        "metadata": {
            "ticket_label": document.get("ticket_label"),
            "route_label": metadata["route_label"],
            "review_priority": metadata["review_priority"],
        },
    }
    _assert_record_safe(record)
    return record


def build_embedding_manifest(
    *,
    embedding_artifact_id: str,
    source_corpus_id: str,
    source_corpus_version: str,
    source_corpus_lockfile_hash: str,
    source_batch_id: str,
    reviewer_signoff_id: str,
    document_count: int,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimensions: int,
    generated_at: str,
    embedding_status: str,
    generator_version: str = _GENERATOR_VERSION,
) -> dict[str, Any]:
    return {
        "embedding_artifact_id": embedding_artifact_id,
        "source_corpus_id": source_corpus_id,
        "source_corpus_version": source_corpus_version,
        "source_corpus_lockfile_hash": source_corpus_lockfile_hash,
        "source_batch_id": source_batch_id,
        "reviewer_signoff_id": reviewer_signoff_id,
        "document_count": document_count,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions,
        "generated_at": generated_at,
        "generator_version": generator_version,
        "embedding_status": embedding_status,
        "indexing_status": "not_started",
        "pgvector_indexed": False,
        "retrieval_activated": False,
    }


def build_embedding_lockfile(
    output_dir: Path,
    *,
    embedding_artifact_id: str,
    generated_at: str,
    document_count: int,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimensions: int,
) -> dict[str, Any]:
    files_to_hash = [
        output_dir / "embeddings.jsonl",
        output_dir / "embedding_manifest.json",
    ]
    entries: list[dict[str, Any]] = []
    for path in files_to_hash:
        rel = path.name
        entries.append(
            {
                "path": rel,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return {
        "lock_version": _LOCK_VERSION,
        "embedding_artifact_id": embedding_artifact_id,
        "files": entries,
        "metadata": {
            "document_count": document_count,
            "embedding_dimensions": embedding_dimensions,
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
            "generated_at": generated_at,
            "generated_by": _GENERATOR_VERSION,
        },
    }


def _assert_record_safe(record: dict[str, Any]) -> None:
    serialized = json.dumps(record, ensure_ascii=False)
    lowered = serialized.lower()
    for key in _FORBIDDEN_ARTIFACT_KEYS:
        if f'"{key}"' in lowered:
            raise ValueError(f"embedding record must not contain forbidden field: {key}")


def _assert_output_dir_safe(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(
            f"output directory already exists: {output_dir} (use --overwrite to replace)"
        )


def _prepare_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    if output_dir.exists():
        if not overwrite:
            _assert_output_dir_safe(output_dir)
        else:
            for child in output_dir.iterdir():
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    raise ValueError(f"unexpected subdirectory in output dir: {child}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)


def write_embedding_artifacts(
    output_dir: Path,
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    overwrite: bool = False,
) -> None:
    _prepare_output_dir(output_dir, overwrite=overwrite)

    embeddings_path = output_dir / "embeddings.jsonl"
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    embeddings_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    manifest_path = output_dir / "embedding_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_pilot_corpus_embeddings(
    corpus_dir: Path,
    output_dir: Path,
    *,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimensions: int,
    embedding_status: str,
    generator_version: str,
    artifact_label: str,
    embed_fn: Callable[[str], list[float]],
    overwrite: bool = False,
    created_at: str | None = None,
) -> EmbeddingDryRunResult:
    """Generate embedding artifacts after corpus integrity verification."""
    integrity = verify_pilot_corpus_integrity(corpus_dir)
    if not integrity.passed:
        issues = "; ".join(integrity.issues)
        raise ValueError(f"corpus integrity check failed: {issues}")

    manifest_path = corpus_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    approved_count = manifest.get("approved_record_count")
    if not isinstance(approved_count, int) or approved_count <= 0:
        raise ValueError("manifest.approved_record_count must be a positive integer")

    corpus_id = str(manifest.get("corpus_id", "")).strip()
    corpus_version = str(manifest.get("corpus_version", "")).strip()
    source_batch_id = str(manifest.get("source_batch_id", "")).strip()
    reviewer_signoff_id = str(manifest.get("reviewer_signoff_id", "")).strip()
    if not all((corpus_id, corpus_version, source_batch_id, reviewer_signoff_id)):
        raise ValueError("manifest missing required provenance fields")

    lockfile_hash = compute_corpus_lockfile_hash(corpus_dir)
    documents = load_pilot_corpus_documents(corpus_dir)
    if len(documents) != approved_count:
        raise ValueError(
            f"document count ({len(documents)}) != manifest.approved_record_count "
            f"({approved_count})"
        )

    timestamp = created_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    artifact_id = f"{corpus_id}_{artifact_label}_{lockfile_hash[:12]}"

    provider_norm = embedding_provider.strip().lower()
    model_norm = embedding_model.strip()
    base_metadata = {
        "embedding_provider": provider_norm,
        "embedding_model": model_norm,
        "source_corpus_id": corpus_id,
        "source_corpus_version": corpus_version,
        "source_corpus_lockfile_hash": lockfile_hash,
    }

    records: list[dict[str, Any]] = []
    for document in documents:
        route_label = _route_label_for_document(document)
        review_priority = _review_priority_for_document(document, route_label)
        text = embedding_input_text(document)
        vector = embed_fn(text)
        if len(vector) != embedding_dimensions:
            raise ValueError("embedding length does not match requested dimensions")
        if all(abs(v) < 1e-12 for v in vector):
            raise ValueError(f"embedding for document {document.get('_document_id')} is all zeros")

        record_meta = {
            **base_metadata,
            "route_label": route_label,
            "review_priority": review_priority,
        }
        records.append(build_embedding_record(document, vector, record_meta))

    embedding_manifest = build_embedding_manifest(
        embedding_artifact_id=artifact_id,
        source_corpus_id=corpus_id,
        source_corpus_version=corpus_version,
        source_corpus_lockfile_hash=lockfile_hash,
        source_batch_id=source_batch_id,
        reviewer_signoff_id=reviewer_signoff_id,
        document_count=len(records),
        embedding_provider=provider_norm,
        embedding_model=model_norm,
        embedding_dimensions=embedding_dimensions,
        generated_at=timestamp,
        embedding_status=embedding_status,
        generator_version=generator_version,
    )

    write_embedding_artifacts(
        output_dir,
        records,
        embedding_manifest,
        overwrite=overwrite,
    )

    lockfile = build_embedding_lockfile(
        output_dir,
        embedding_artifact_id=artifact_id,
        generated_at=timestamp,
        document_count=len(records),
        embedding_provider=base_metadata["embedding_provider"],
        embedding_model=base_metadata["embedding_model"],
        embedding_dimensions=embedding_dimensions,
    )
    (output_dir / "embedding.lock.json").write_text(
        json.dumps(lockfile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return EmbeddingDryRunResult(
        output_dir=output_dir,
        document_count=len(records),
        embedding_dimensions=embedding_dimensions,
        embedding_provider=base_metadata["embedding_provider"],
        embedding_model=base_metadata["embedding_model"],
        source_corpus_id=corpus_id,
        source_corpus_lockfile_hash=lockfile_hash,
        embeddings_path=output_dir / "embeddings.jsonl",
        manifest_path=output_dir / "embedding_manifest.json",
        lockfile_path=output_dir / "embedding.lock.json",
    )


def run_embedding_dry_run(
    corpus_dir: Path,
    output_dir: Path,
    *,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimensions: int,
    overwrite: bool = False,
    created_at: str | None = None,
) -> EmbeddingDryRunResult:
    """Run mock embedding dry-run after corpus integrity verification."""
    if embedding_provider.strip().lower() != "mock":
        raise ValueError("embedding dry-run requires provider=mock")

    def _embed(text: str) -> list[float]:
        return build_mock_embedding(text, embedding_dimensions)

    return run_pilot_corpus_embeddings(
        corpus_dir,
        output_dir,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        embedding_status="mock_generated",
        generator_version=_GENERATOR_VERSION,
        artifact_label="mock",
        embed_fn=_embed,
        overwrite=overwrite,
        created_at=created_at,
    )

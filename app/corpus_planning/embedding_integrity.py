"""Offline integrity verification for mock embedding artifacts (no network)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.rag.corpus_integrity import sha256_file

_REQUIRED_FILES = (
    "embedding_manifest.json",
    "embeddings.jsonl",
    "embedding.lock.json",
)

_FORBIDDEN_RECORD_KEYS = frozenset(
    {
        "conversation_transcript",
        "transcript",
        "raw_text",
        "draft_response",
        "final_response",
        "messages",
        "retrieved_context",
    }
)


@dataclass(frozen=True)
class EmbeddingArtifactIntegrityReport:
    passed: bool
    issue_count: int
    issues: tuple[str, ...]
    document_count: int | None = None
    embedding_record_count: int | None = None
    embedding_dimensions: int | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    source_corpus_id: str | None = None
    source_corpus_version: str | None = None
    source_corpus_lockfile_hash: str | None = None
    embedding_status: str | None = None
    indexing_status: str | None = None
    pgvector_indexed: bool | None = None
    retrieval_activated: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _collect_forbidden_keys(value: Any, *, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_str = str(key)
            child_path = f"{path}.{key_str}" if path else key_str
            if key_str in _FORBIDDEN_RECORD_KEYS:
                found.append(child_path)
            found.extend(_collect_forbidden_keys(child, path=child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_collect_forbidden_keys(item, path=f"{path}[{index}]"))
    return found


def _load_embedding_records(embeddings_path: Path) -> list[dict[str, Any]]:
    if not embeddings_path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        embeddings_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"embeddings.jsonl line {line_number}: invalid JSON: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(f"embeddings.jsonl line {line_number}: expected JSON object")
        records.append(payload)
    return records


def check_embedding_artifact_integrity(embedding_dir: Path) -> EmbeddingArtifactIntegrityReport:
    """Verify mock embedding artifact tree under ``embedding_dir``."""
    root = embedding_dir.resolve()
    issues: list[str] = []

    if not root.is_dir():
        return EmbeddingArtifactIntegrityReport(
            passed=False,
            issue_count=1,
            issues=(f"embedding directory does not exist: {root}",),
            metadata={"embedding_dir": str(root)},
        )

    for rel in _REQUIRED_FILES:
        if not (root / rel).is_file():
            issues.append(f"missing required file: {rel}")

    manifest: dict[str, Any] = {}
    manifest_path = root / "embedding_manifest.json"
    if manifest_path.is_file():
        try:
            manifest = _load_json(manifest_path)
        except ValueError as exc:
            issues.append(str(exc))

    document_count = manifest.get("document_count")
    manifest_dimensions = manifest.get("embedding_dimensions")
    embedding_provider = manifest.get("embedding_provider")
    embedding_model = manifest.get("embedding_model")
    source_corpus_id = manifest.get("source_corpus_id")
    source_corpus_version = manifest.get("source_corpus_version")
    source_corpus_lockfile_hash = manifest.get("source_corpus_lockfile_hash")
    embedding_status = manifest.get("embedding_status")
    indexing_status = manifest.get("indexing_status")
    pgvector_indexed = manifest.get("pgvector_indexed")
    retrieval_activated = manifest.get("retrieval_activated")

    if embedding_status not in ("mock_generated", "real_generated"):
        issues.append(
            f"embedding_status must be mock_generated or real_generated (got {embedding_status!r})"
        )
    if embedding_status == "real_generated" and embedding_provider != "openai":
        issues.append("embedding_provider must be openai when embedding_status is real_generated")
    if embedding_status == "mock_generated" and embedding_provider != "mock":
        issues.append("embedding_provider must be mock when embedding_status is mock_generated")
    if indexing_status != "not_started":
        issues.append(f"indexing_status must be not_started (got {indexing_status!r})")
    if pgvector_indexed is not False:
        issues.append(f"pgvector_indexed must be false (got {pgvector_indexed!r})")
    if retrieval_activated is not False:
        issues.append(f"retrieval_activated must be false (got {retrieval_activated!r})")

    lockfile_hash = source_corpus_lockfile_hash
    if not isinstance(lockfile_hash, str) or not lockfile_hash.strip():
        issues.append("manifest.source_corpus_lockfile_hash must be non-empty")
    elif len(lockfile_hash.strip()) < 12:
        issues.append("manifest.source_corpus_lockfile_hash is too short")

    lockfile_path = root / "embedding.lock.json"
    if lockfile_path.is_file():
        try:
            lockfile = _load_json(lockfile_path)
        except ValueError as exc:
            issues.append(str(exc))
            lockfile = {}
        entries = lockfile.get("files")
        if not isinstance(entries, list):
            issues.append("embedding.lock.json files must be a list")
        else:
            for entry in entries:
                if not isinstance(entry, dict):
                    issues.append("lockfile entry must be an object")
                    continue
                rel = entry.get("path")
                expected_hash = entry.get("sha256")
                expected_size = entry.get("size_bytes")
                if not isinstance(rel, str) or not rel:
                    issues.append("lockfile entry missing path")
                    continue
                file_path = root / rel
                if not file_path.is_file():
                    issues.append(f"lockfile path missing on disk: {rel}")
                    continue
                actual_hash = sha256_file(file_path)
                actual_size = file_path.stat().st_size
                if expected_hash != actual_hash:
                    issues.append(f"lockfile hash mismatch: {rel}")
                if expected_size != actual_size:
                    issues.append(f"lockfile size mismatch: {rel}")

    records: list[dict[str, Any]] = []
    embeddings_path = root / "embeddings.jsonl"
    if embeddings_path.is_file():
        try:
            records = _load_embedding_records(embeddings_path)
        except ValueError as exc:
            issues.append(str(exc))

    embedding_record_count = len(records)
    if isinstance(document_count, int):
        if embedding_record_count != document_count:
            issues.append(
                f"embedding record count ({embedding_record_count}) != "
                f"manifest.document_count ({document_count})"
            )
    else:
        issues.append("manifest.document_count missing or invalid")

    expected_dimensions: int | None = None
    if isinstance(manifest_dimensions, int) and manifest_dimensions > 0:
        expected_dimensions = manifest_dimensions
    else:
        issues.append("manifest.embedding_dimensions must be a positive integer")

    if isinstance(embedding_provider, str) and embedding_provider.strip():
        provider_norm = embedding_provider.strip().lower()
    else:
        provider_norm = None
        issues.append("manifest.embedding_provider missing or invalid")

    if not isinstance(embedding_model, str) or not embedding_model.strip():
        issues.append("manifest.embedding_model missing or invalid")

    for index, record in enumerate(records):
        forbidden = _collect_forbidden_keys(record)
        for key_path in forbidden:
            issues.append(f"record {index}: forbidden field {key_path}")

        vector = record.get("embedding")
        if not isinstance(vector, list) or not vector:
            issues.append(f"record {index}: embedding must be a non-empty list")
            continue
        if not all(isinstance(value, (int, float)) for value in vector):
            issues.append(f"record {index}: embedding must contain floats only")
            continue
        if expected_dimensions is not None and len(vector) != expected_dimensions:
            issues.append(
                f"record {index}: embedding length {len(vector)} != "
                f"manifest.embedding_dimensions ({expected_dimensions})"
            )
        if all(abs(float(value)) < 1e-12 for value in vector):
            issues.append(f"record {index}: embedding must not be all zeros")

        record_provider = record.get("embedding_provider")
        record_model = record.get("embedding_model")
        if provider_norm is not None and str(record_provider).strip().lower() != provider_norm:
            issues.append(f"record {index}: embedding_provider mismatch with manifest")
        if isinstance(embedding_model, str) and record_model != embedding_model:
            issues.append(f"record {index}: embedding_model mismatch with manifest")

        record_lock_hash = record.get("source_corpus_lockfile_hash")
        if isinstance(lockfile_hash, str) and record_lock_hash != lockfile_hash:
            issues.append(f"record {index}: source_corpus_lockfile_hash mismatch with manifest")

    if records and expected_dimensions is not None:
        lengths = {len(record.get("embedding", [])) for record in records if "embedding" in record}
        if len(lengths) > 1:
            issues.append("embedding vectors have inconsistent dimensions across records")

    return EmbeddingArtifactIntegrityReport(
        passed=len(issues) == 0,
        issue_count=len(issues),
        issues=tuple(issues),
        document_count=document_count if isinstance(document_count, int) else None,
        embedding_record_count=embedding_record_count,
        embedding_dimensions=expected_dimensions,
        embedding_provider=str(embedding_provider) if embedding_provider is not None else None,
        embedding_model=str(embedding_model) if embedding_model is not None else None,
        source_corpus_id=str(source_corpus_id) if source_corpus_id is not None else None,
        source_corpus_version=str(source_corpus_version)
        if source_corpus_version is not None
        else None,
        source_corpus_lockfile_hash=str(lockfile_hash) if isinstance(lockfile_hash, str) else None,
        embedding_status=str(embedding_status) if embedding_status is not None else None,
        indexing_status=str(indexing_status) if indexing_status is not None else None,
        pgvector_indexed=pgvector_indexed if isinstance(pgvector_indexed, bool) else None,
        retrieval_activated=retrieval_activated if isinstance(retrieval_activated, bool) else None,
        metadata={"embedding_dir": str(root)},
    )

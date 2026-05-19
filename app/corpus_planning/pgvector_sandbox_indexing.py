"""Sandbox pgvector indexing from pilot OpenAI embedding artifacts (no retrieval)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.corpus_planning.embedding_integrity import (
    _FORBIDDEN_RECORD_KEYS,
    _collect_forbidden_keys,
    _load_json,
    check_embedding_artifact_integrity,
)
from app.corpus_planning.embedding_plan_models import EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED
from app.rag.vector_records import VectorRecord

_OPENAI_PILOT_MODEL = "text-embedding-3-small"
_OPENAI_PILOT_DIMENSIONS = 1536
_PILOT_PROFILE = "semantic_pgvector"
_FORBIDDEN_PROFILES = frozenset({"semantic_pgvector_16"})
_PRODUCTION_DB_MARKERS = (
    "amazonaws.com",
    "rds.amazonaws",
    ".prod.",
    "-prod.",
    "_prod_",
    "production.",
    ".staging.",
    "-staging.",
    "_staging_",
    "stg.",
)
_LOCAL_DB_MARKERS = ("127.0.0.1", "localhost", "::1", "host.docker.internal")
_DEFAULT_SUMMARY_PATH = Path("reports/pgvector_sandbox_indexing_pilot_v1.json")
_SOURCE_TYPE = "vendor_ticket_real_pilot"


class VectorStoreUpsert(Protocol):
    def upsert(self, records: list[VectorRecord]) -> int: ...


@dataclass(frozen=True)
class LoadedEmbeddingArtifacts:
    embedding_dir: Path
    manifest: dict[str, Any]
    records: list[dict[str, Any]]


@dataclass(frozen=True)
class SandboxIndexingResult:
    indexed_count: int
    namespace: str
    index_version: str
    profile: str
    dimensions: int
    embedding_provider: str
    embedding_model: str
    source_corpus_id: str
    source_corpus_lockfile_hash: str
    embedding_artifact_id: str
    summary_path: Path


def load_embedding_artifacts(embedding_dir: Path) -> LoadedEmbeddingArtifacts:
    """Load embedding manifest and JSONL records from ``embedding_dir``."""
    root = embedding_dir.resolve()
    manifest_path = root / "embedding_manifest.json"
    embeddings_path = root / "embeddings.jsonl"
    if not manifest_path.is_file():
        raise ValueError(f"embedding manifest not found: {manifest_path}")
    if not embeddings_path.is_file():
        raise ValueError(f"embeddings.jsonl not found: {embeddings_path}")

    manifest = _load_json(manifest_path)
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
    return LoadedEmbeddingArtifacts(
        embedding_dir=root,
        manifest=manifest,
        records=records,
    )


def validate_embedding_artifact_for_pgvector(
    artifacts: LoadedEmbeddingArtifacts,
    *,
    expected_dimensions: int = _OPENAI_PILOT_DIMENSIONS,
) -> None:
    """Validate artifacts are eligible for sandbox pgvector indexing."""
    integrity = check_embedding_artifact_integrity(artifacts.embedding_dir)
    if not integrity.passed:
        issues = "; ".join(integrity.issues)
        raise ValueError(f"embedding artifact integrity failed: {issues}")

    manifest = artifacts.manifest
    if manifest.get("embedding_status") != EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED:
        raise ValueError("embedding_status must be real_generated for sandbox pilot indexing")
    if manifest.get("embedding_provider") != "openai":
        raise ValueError("embedding_provider must be openai for sandbox pilot indexing")
    if manifest.get("embedding_model") != _OPENAI_PILOT_MODEL:
        raise ValueError(f"embedding_model must be {_OPENAI_PILOT_MODEL!r}")
    if manifest.get("embedding_dimensions") != expected_dimensions:
        raise ValueError(f"embedding_dimensions must be {expected_dimensions}")
    if manifest.get("indexing_status") != "not_started":
        raise ValueError(
            "artifact manifest indexing_status must be not_started before sandbox index"
        )
    if manifest.get("pgvector_indexed") is not False:
        raise ValueError("artifact manifest pgvector_indexed must be false")
    if manifest.get("retrieval_activated") is not False:
        raise ValueError("artifact manifest retrieval_activated must be false")

    if not artifacts.records:
        raise ValueError("embedding record count is zero")

    document_count = manifest.get("document_count")
    if isinstance(document_count, int) and len(artifacts.records) != document_count:
        raise ValueError(
            f"record count ({len(artifacts.records)}) != manifest.document_count ({document_count})"
        )

    for index, record in enumerate(artifacts.records):
        for key_path in _collect_forbidden_keys(record):
            if key_path.split(".")[0] in _FORBIDDEN_RECORD_KEYS:
                raise ValueError(f"record {index}: forbidden field {key_path}")
        vector = record.get("embedding")
        if not isinstance(vector, list) or len(vector) != expected_dimensions:
            raise ValueError(f"record {index}: embedding length must be {expected_dimensions}")


def assert_sandbox_database_url(database_url: str) -> None:
    """Reject database URLs that look like production or shared staging."""
    if not database_url.strip():
        raise ValueError("PGVECTOR_DATABASE_URL is required for sandbox indexing")

    lowered = database_url.lower()
    if any(marker in lowered for marker in _PRODUCTION_DB_MARKERS):
        raise ValueError("database URL appears to target production or staging — sandbox only")

    if not any(marker in lowered for marker in _LOCAL_DB_MARKERS):
        raise ValueError(
            "database URL must target local sandbox host "
            "(127.0.0.1, localhost, or host.docker.internal)"
        )


def _safe_record_content(record: dict[str, Any]) -> str:
    meta = record.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
    room_id = str(record.get("room_id", ""))
    ticket_label = str(meta.get("ticket_label", ""))
    route_label = str(meta.get("route_label", ""))
    review_priority = str(meta.get("review_priority", ""))
    return "|".join(
        [
            f"room_id={room_id}",
            f"ticket_label={ticket_label}",
            f"route_label={route_label}",
            f"review_priority={review_priority}",
        ]
    )


def build_pgvector_records(
    artifacts: LoadedEmbeddingArtifacts,
    *,
    namespace: str,
    index_version: str,
) -> list[VectorRecord]:
    """Build ``VectorRecord`` rows with provenance in metadata (no transcript text)."""
    ns = namespace.strip()
    version = index_version.strip()
    if not ns:
        raise ValueError("namespace must be non-empty")
    if not version:
        raise ValueError("index_version must be non-empty")

    manifest = artifacts.manifest
    corpus_id = str(manifest.get("source_corpus_id", _SOURCE_TYPE))
    corpus_version = str(manifest.get("source_corpus_version", "1"))
    lockfile_hash = str(manifest.get("source_corpus_lockfile_hash", ""))
    artifact_id = str(manifest.get("embedding_artifact_id", ""))
    provider = str(manifest.get("embedding_provider", "openai"))
    model = str(manifest.get("embedding_model", _OPENAI_PILOT_MODEL))
    dimensions = int(manifest.get("embedding_dimensions", _OPENAI_PILOT_DIMENSIONS))

    built: list[VectorRecord] = []
    for record in artifacts.records:
        document_id = str(record.get("document_id", ""))
        room_id = str(record.get("room_id", document_id))
        meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        vector = record.get("embedding")
        if not isinstance(vector, list):
            raise ValueError(f"record {document_id!r}: embedding must be a list")

        record_id = f"pilot::{ns}::{version}::{document_id}"
        content = _safe_record_content(record)
        serialized = json.dumps({"content": content, "metadata": meta}, ensure_ascii=False)
        for forbidden in _FORBIDDEN_RECORD_KEYS:
            if forbidden in serialized.lower():
                raise ValueError(f"record {document_id!r}: forbidden content in serialized record")

        metadata = {
            "room_id": room_id,
            "ticket_label": meta.get("ticket_label"),
            "route_label": meta.get("route_label"),
            "review_priority": meta.get("review_priority"),
            "source_corpus_id": corpus_id,
            "source_corpus_version": corpus_version,
            "source_corpus_lockfile_hash": lockfile_hash,
            "embedding_artifact_id": artifact_id,
            "embedding_provider": provider,
            "embedding_model": model,
            "embedding_dimensions": dimensions,
            "index_version": version,
            "namespace": ns,
            "pilot_sandbox": True,
            "sandbox_only": True,
        }

        built.append(
            VectorRecord(
                record_id=record_id,
                document_id=document_id,
                content=content,
                vector=[float(v) for v in vector],
                dimensions=dimensions,
                embedding_provider=provider,
                embedding_model=model,
                source_type=_SOURCE_TYPE,
                metadata=metadata,
            )
        )
    return built


def build_indexing_summary(
    *,
    indexed_count: int,
    namespace: str,
    index_version: str,
    profile: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    lockfile_hash = str(manifest.get("source_corpus_lockfile_hash", ""))
    prefix = lockfile_hash[:12] + "..." if len(lockfile_hash) > 12 else lockfile_hash
    return {
        "indexed_count": indexed_count,
        "namespace": namespace,
        "index_version": index_version,
        "profile": profile,
        "dimensions": manifest.get("embedding_dimensions", _OPENAI_PILOT_DIMENSIONS),
        "embedding_provider": manifest.get("embedding_provider", "openai"),
        "embedding_model": manifest.get("embedding_model", _OPENAI_PILOT_MODEL),
        "source_corpus_id": manifest.get("source_corpus_id", _SOURCE_TYPE),
        "source_corpus_lockfile_hash_prefix": prefix,
        "embedding_artifact_id": manifest.get("embedding_artifact_id"),
        "indexing_status": "sandbox_indexed",
        "retrieval_activated": False,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "table_metadata_note": (
            "Provenance stored in rag_vector_records.metadata JSON; "
            "pilot rows use record_id prefix pilot::"
        ),
    }


def write_indexing_summary_report(
    summary: dict[str, Any],
    *,
    output_path: Path = _DEFAULT_SUMMARY_PATH,
) -> Path:
    path = output_path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def index_embeddings_to_pgvector_sandbox(
    embedding_dir: Path,
    *,
    namespace: str,
    index_version: str,
    profile: str,
    database_url: str,
    table_name: str = "rag_vector_records",
    dimensions: int = _OPENAI_PILOT_DIMENSIONS,
    upsert_fn: Callable[[list[VectorRecord]], int] | None = None,
    summary_path: Path = _DEFAULT_SUMMARY_PATH,
) -> SandboxIndexingResult:
    """Index pilot embedding artifacts into sandbox pgvector (local DB only)."""
    profile_norm = profile.strip().lower()
    if profile_norm in _FORBIDDEN_PROFILES:
        raise ValueError(f"profile {profile!r} is not allowed for OpenAI pilot sandbox indexing")
    if profile_norm != _PILOT_PROFILE:
        raise ValueError(f"profile must be {_PILOT_PROFILE!r} for pilot sandbox indexing")

    assert_sandbox_database_url(database_url)

    artifacts = load_embedding_artifacts(embedding_dir)
    validate_embedding_artifact_for_pgvector(artifacts, expected_dimensions=dimensions)
    vector_records = build_pgvector_records(
        artifacts,
        namespace=namespace,
        index_version=index_version,
    )

    if upsert_fn is None:
        from app.rag.pgvector_store import PgVectorStore

        store: VectorStoreUpsert = PgVectorStore(
            database_url,
            table_name=table_name,
            dimensions=dimensions,
        )
        indexed_count = store.upsert(vector_records)
    else:
        indexed_count = upsert_fn(vector_records)

    if indexed_count != len(vector_records):
        raise ValueError(f"indexed_count ({indexed_count}) != expected ({len(vector_records)})")

    summary = build_indexing_summary(
        indexed_count=indexed_count,
        namespace=namespace.strip(),
        index_version=index_version.strip(),
        profile=profile_norm,
        manifest=artifacts.manifest,
    )
    written_path = write_indexing_summary_report(summary, output_path=summary_path)

    return SandboxIndexingResult(
        indexed_count=indexed_count,
        namespace=namespace.strip(),
        index_version=index_version.strip(),
        profile=profile_norm,
        dimensions=dimensions,
        embedding_provider=str(artifacts.manifest.get("embedding_provider", "openai")),
        embedding_model=str(artifacts.manifest.get("embedding_model", _OPENAI_PILOT_MODEL)),
        source_corpus_id=str(artifacts.manifest.get("source_corpus_id", _SOURCE_TYPE)),
        source_corpus_lockfile_hash=str(artifacts.manifest.get("source_corpus_lockfile_hash", "")),
        embedding_artifact_id=str(artifacts.manifest.get("embedding_artifact_id", "")),
        summary_path=written_path,
    )

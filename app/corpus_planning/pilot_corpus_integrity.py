"""Offline integrity verification for governance-gated pilot corpus trees (no network)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.corpus_planning.pilot_corpus_builder import _document_filename
from app.rag.corpus_integrity import sha256_file

_REQUIRED_PATHS = (
    "manifest.json",
    "corpus.lock.json",
    "metadata/build_summary.json",
    "governance/reviewer_signoff_reference.json",
)

_REQUIRED_GOVERNANCE_FLAGS: dict[str, bool] = {
    "raw_exports_committed": False,
    "embeddings_generated": False,
    "indexed_to_pgvector": False,
}


@dataclass(frozen=True)
class PilotCorpusIntegrityReport:
    passed: bool
    issue_count: int
    issues: tuple[str, ...]
    corpus_id: str | None = None
    corpus_version: str | None = None
    approved_record_count: int | None = None
    document_count: int | None = None
    source_batch_id: str | None = None
    reviewer_signoff_id: str | None = None
    embedding_status: str | None = None
    indexing_status: str | None = None
    lockfile_entry_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def verify_pilot_corpus_integrity(corpus_dir: Path) -> PilotCorpusIntegrityReport:
    """Verify pilot corpus layout, manifest, governance flags, and lockfile hashes."""
    root = corpus_dir.resolve()
    issues: list[str] = []

    if not root.is_dir():
        return PilotCorpusIntegrityReport(
            passed=False,
            issue_count=1,
            issues=(f"corpus directory does not exist: {root}",),
            metadata={"corpus_dir": str(root)},
        )

    for rel in _REQUIRED_PATHS:
        path = root / rel
        if not path.is_file():
            issues.append(f"missing required file: {rel}")

    documents_dir = root / "documents"
    if not documents_dir.is_dir():
        issues.append("missing documents directory")

    manifest: dict[str, Any] = {}
    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = _load_json(manifest_path)
        except ValueError as exc:
            issues.append(str(exc))

    corpus_id = manifest.get("corpus_id")
    corpus_version = manifest.get("corpus_version")
    source_batch_id = manifest.get("source_batch_id")
    reviewer_signoff_id = manifest.get("reviewer_signoff_id")
    embedding_status = manifest.get("embedding_status")
    indexing_status = manifest.get("indexing_status")
    approved_record_count = manifest.get("approved_record_count")
    document_ids = manifest.get("document_ids")

    if embedding_status != "not_started":
        issues.append(f"embedding_status must be not_started (got {embedding_status!r})")
    if indexing_status != "not_started":
        issues.append(f"indexing_status must be not_started (got {indexing_status!r})")

    governance = manifest.get("governance")
    if not isinstance(governance, dict):
        issues.append("manifest.governance must be an object")
    else:
        for flag, expected in _REQUIRED_GOVERNANCE_FLAGS.items():
            actual = governance.get(flag)
            if actual is not expected:
                issues.append(f"governance.{flag} must be {expected} (got {actual!r})")

    document_count: int | None = None
    if documents_dir.is_dir():
        document_count = len(list(documents_dir.glob("*.json")))

    if isinstance(approved_record_count, int) and document_count is not None:
        if document_count != approved_record_count:
            issues.append(
                "document file count "
                f"({document_count}) != manifest.approved_record_count "
                f"({approved_record_count})"
            )
    elif approved_record_count is None:
        issues.append("manifest.approved_record_count missing or invalid")

    if isinstance(document_ids, list):
        if not all(isinstance(doc_id, str) and doc_id.strip() for doc_id in document_ids):
            issues.append("manifest.document_ids must be a list of non-empty strings")
        elif documents_dir.is_dir():
            for doc_id in document_ids:
                doc_path = documents_dir / _document_filename(doc_id)
                if not doc_path.is_file():
                    issues.append(f"missing document file for manifest id: {doc_id}")
            manifest_id_set = set(document_ids)
            for doc_path in documents_dir.glob("*.json"):
                stem = doc_path.stem
                if stem not in manifest_id_set:
                    issues.append(f"unexpected document file not listed in manifest: {stem}")
    else:
        issues.append("manifest.document_ids must be a list")

    lockfile_entry_count: int | None = None
    lockfile_path = root / "corpus.lock.json"
    if lockfile_path.is_file():
        try:
            lockfile = _load_json(lockfile_path)
        except ValueError as exc:
            issues.append(str(exc))
            lockfile = {}
        entries = lockfile.get("files")
        if not isinstance(entries, list):
            issues.append("corpus.lock.json files must be a list")
        else:
            lockfile_entry_count = len(entries)
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

    return PilotCorpusIntegrityReport(
        passed=len(issues) == 0,
        issue_count=len(issues),
        issues=tuple(issues),
        corpus_id=str(corpus_id) if corpus_id is not None else None,
        corpus_version=str(corpus_version) if corpus_version is not None else None,
        approved_record_count=approved_record_count
        if isinstance(approved_record_count, int)
        else None,
        document_count=document_count,
        source_batch_id=str(source_batch_id) if source_batch_id is not None else None,
        reviewer_signoff_id=str(reviewer_signoff_id) if reviewer_signoff_id is not None else None,
        embedding_status=str(embedding_status) if embedding_status is not None else None,
        indexing_status=str(indexing_status) if indexing_status is not None else None,
        lockfile_entry_count=lockfile_entry_count,
        metadata={"corpus_dir": str(root)},
    )

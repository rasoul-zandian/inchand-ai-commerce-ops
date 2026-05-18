"""Build governance-gated pilot corpus artifacts from approved room IDs (no embeddings)."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.rag.corpus_integrity import sha256_file
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    conversation_to_plain_text,
    parse_conversation_ticket_snapshot,
)
from app.tickets.workflow_mapping import conversation_snapshot_to_workflow_input

_CORPUS_ID = "vendor_ticket_real_pilot"
_MANIFEST_VERSION = "1"
_LOCK_VERSION = "1"

_FORBIDDEN_SNAPSHOT_KEYS = frozenset(
    {
        "draft_response",
        "final_response",
        "user_input",
        "retrieved_context",
        "tool_results",
        "rag_sources",
        "grounding_sources",
        "audit_log",
        "api_key",
        "secret",
        "password",
        "token",
    }
)
_FORBIDDEN_OUTPUT_SUBSTRINGS = (
    "sk-",
    "OPENAI_API_KEY",
    "BEGIN PRIVATE KEY",
    "postgresql://",
)


@dataclass(frozen=True)
class PilotCorpusBuildResult:
    corpus_dir: Path
    approved_record_count: int
    document_ids: list[str]
    manifest_path: Path
    lockfile_path: Path


def load_approved_room_ids(path: Path) -> list[str]:
    """Load approved room IDs in file order (comments and blank lines skipped)."""
    if not path.is_file():
        raise ValueError(f"approved room IDs file not found: {path}")

    ordered: list[str] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in seen:
            raise ValueError(
                f"duplicate approved room_id {stripped!r} on line {line_number} of {path}"
            )
        seen.add(stripped)
        ordered.append(stripped)

    if not ordered:
        raise ValueError("approved room IDs list is empty")
    return ordered


def load_snapshots_by_room_id(lines: list[str]) -> dict[str, ConversationTicketSnapshot]:
    """Parse JSONL export; fail on duplicate room_id in source."""
    by_room: dict[str, ConversationTicketSnapshot] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: export line must be a JSON object")
        for key in _FORBIDDEN_SNAPSHOT_KEYS:
            if key in payload:
                raise ValueError(f"line {line_number}: forbidden key {key!r} in export snapshot")
        snapshot = parse_conversation_ticket_snapshot(payload)
        _assert_snapshot_safe(snapshot, line_number=line_number)
        if snapshot.room_id in by_room:
            raise ValueError(f"duplicate room_id in export: {snapshot.room_id!r}")
        by_room[snapshot.room_id] = snapshot
    return by_room


def _assert_snapshot_safe(snapshot: ConversationTicketSnapshot, *, line_number: int) -> None:
    payload = snapshot.model_dump(mode="json")
    for key in _FORBIDDEN_SNAPSHOT_KEYS:
        if key in payload:
            raise ValueError(f"line {line_number}: forbidden key {key!r} in export snapshot")
    if snapshot.metadata:
        for key in snapshot.metadata:
            if key.lower() in _FORBIDDEN_SNAPSHOT_KEYS:
                raise ValueError(f"line {line_number}: forbidden metadata key {key!r}")


def _assert_output_text_safe(text: str, *, context: str) -> None:
    lowered = text.lower()
    for token in _FORBIDDEN_OUTPUT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"{context} must not contain forbidden token: {token}")


def _document_filename(room_id: str) -> str:
    safe = re.sub(r"[^\w.\-]+", "_", room_id.strip())
    if not safe:
        raise ValueError(f"room_id cannot be used as filename: {room_id!r}")
    return f"{safe}.json"


def build_pilot_document(
    snapshot: ConversationTicketSnapshot,
    *,
    source_batch_id: str,
    reviewer_signoff_id: str,
    corpus_id: str = _CORPUS_ID,
) -> dict[str, Any]:
    """Build one approved corpus document payload."""
    workflow = conversation_snapshot_to_workflow_input(snapshot)
    workflow_meta = workflow["workflow_metadata"]
    transcript = conversation_to_plain_text(snapshot)

    document: dict[str, Any] = {
        "room_id": snapshot.room_id,
        "ticket_label": snapshot.ticket_label,
        "ticket_subtype": snapshot.ticket_subtype,
        "seller_id": snapshot.seller_id,
        "message_count": workflow_meta["message_count"],
        "sender_types": workflow_meta["sender_types"],
        "conversation_transcript": transcript,
        "final_resolution": dict(snapshot.final_resolution),
        "metadata": {
            "source_batch_id": source_batch_id,
            "reviewer_signoff_id": reviewer_signoff_id,
            "corpus_id": corpus_id,
            "replay_approved": True,
            "embedding_status": "not_started",
            "indexing_status": "not_started",
        },
    }
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True)
    _assert_output_text_safe(serialized, context=f"document {snapshot.room_id}")
    return document


def build_pilot_manifest(
    *,
    document_ids: list[str],
    source_batch_id: str,
    reviewer_signoff_id: str,
    label_counts: dict[str, int],
    created_at: str,
    corpus_id: str = _CORPUS_ID,
) -> dict[str, Any]:
    return {
        "corpus_id": corpus_id,
        "corpus_version": "1",
        "manifest_version": _MANIFEST_VERSION,
        "source_batch_id": source_batch_id,
        "reviewer_signoff_id": reviewer_signoff_id,
        "approved_record_count": len(document_ids),
        "document_ids": document_ids,
        "source_types": {
            "conversation_ticket": len(document_ids),
        },
        "ticket_label_counts": label_counts,
        "embedding_status": "not_started",
        "indexing_status": "not_started",
        "created_at": created_at,
        "governance": {
            "privacy_review_required": True,
            "reviewer_signoff_required": True,
            "raw_exports_committed": False,
            "embeddings_generated": False,
            "indexed_to_pgvector": False,
        },
    }


def build_pilot_lockfile(
    corpus_dir: Path,
    *,
    created_at: str,
    approved_record_count: int,
    corpus_name: str = _CORPUS_ID,
) -> dict[str, Any]:
    """Hash manifest, documents, metadata, and governance files (excludes lockfile itself)."""
    files_to_hash: list[Path] = []
    for rel in (
        "manifest.json",
        "metadata/build_summary.json",
        "governance/reviewer_signoff_reference.json",
    ):
        path = corpus_dir / rel
        if path.is_file():
            files_to_hash.append(path)

    documents_dir = corpus_dir / "documents"
    if documents_dir.is_dir():
        files_to_hash.extend(sorted(documents_dir.glob("*.json")))

    entries: list[dict[str, Any]] = []
    for path in sorted(files_to_hash, key=lambda p: str(p.relative_to(corpus_dir))):
        rel = path.relative_to(corpus_dir).as_posix()
        entries.append(
            {
                "path": rel,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )

    return {
        "lock_version": _LOCK_VERSION,
        "corpus_name": corpus_name,
        "manifest_version": _MANIFEST_VERSION,
        "files": entries,
        "metadata": {
            "created_at": created_at,
            "approved_record_count": approved_record_count,
            "generated_by": "build_pilot_corpus",
        },
    }


def build_pilot_corpus(
    export_path: Path,
    *,
    approved_room_ids: list[str],
    corpus_dir: Path,
    source_batch_id: str,
    reviewer_signoff_id: str,
    overwrite: bool = False,
    created_at: str | None = None,
) -> PilotCorpusBuildResult:
    """Write pilot corpus tree from normalized export and approved room ID list."""
    if corpus_dir.exists():
        if not overwrite:
            raise ValueError(
                f"corpus directory already exists: {corpus_dir} (use --overwrite to rebuild)"
            )
    else:
        corpus_dir.mkdir(parents=True, exist_ok=True)

    if not export_path.is_file():
        raise ValueError(f"export file not found: {export_path}")

    snapshots_by_room = load_snapshots_by_room_id(
        export_path.read_text(encoding="utf-8").splitlines(),
    )

    missing = [room_id for room_id in approved_room_ids if room_id not in snapshots_by_room]
    if missing:
        raise ValueError(f"approved room_id(s) not found in export: {', '.join(missing)}")

    timestamp = created_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    documents_dir = corpus_dir / "documents"
    metadata_dir = corpus_dir / "metadata"
    governance_dir = corpus_dir / "governance"
    documents_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    governance_dir.mkdir(parents=True, exist_ok=True)

    document_ids: list[str] = []
    label_counter: Counter[str] = Counter()

    for room_id in approved_room_ids:
        snapshot = snapshots_by_room[room_id]
        document = build_pilot_document(
            snapshot,
            source_batch_id=source_batch_id,
            reviewer_signoff_id=reviewer_signoff_id,
        )
        doc_path = documents_dir / _document_filename(room_id)
        doc_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        document_ids.append(room_id)
        label_counter[snapshot.ticket_label] += 1

    if not document_ids:
        raise ValueError("selected record count is zero")

    build_summary = {
        "source_batch_id": source_batch_id,
        "reviewer_signoff_id": reviewer_signoff_id,
        "approved_record_count": len(document_ids),
        "approved_room_ids": document_ids,
        "export_path": str(export_path),
        "ordering": "approved_room_ids_file_order",
        "created_at": timestamp,
    }
    (metadata_dir / "build_summary.json").write_text(
        json.dumps(build_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    governance_ref = {
        "reviewer_signoff_id": reviewer_signoff_id,
        "source_batch_id": source_batch_id,
        "approved_record_count": len(document_ids),
        "note": "Reference only; full signoff record remains local/private.",
    }
    (governance_dir / "reviewer_signoff_reference.json").write_text(
        json.dumps(governance_ref, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = build_pilot_manifest(
        document_ids=document_ids,
        source_batch_id=source_batch_id,
        reviewer_signoff_id=reviewer_signoff_id,
        label_counts=dict(label_counter),
        created_at=timestamp,
    )
    manifest_path = corpus_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lockfile = build_pilot_lockfile(
        corpus_dir,
        created_at=timestamp,
        approved_record_count=len(document_ids),
    )
    lockfile_path = corpus_dir / "corpus.lock.json"
    lockfile_path.write_text(
        json.dumps(lockfile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return PilotCorpusBuildResult(
        corpus_dir=corpus_dir,
        approved_record_count=len(document_ids),
        document_ids=document_ids,
        manifest_path=manifest_path,
        lockfile_path=lockfile_path,
    )

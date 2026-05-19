"""Sandbox pilot pgvector metadata inventory (diagnostics only; no retrieval activation)."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from app.corpus_planning.pgvector_sandbox_indexing import assert_sandbox_database_url
from app.corpus_planning.pilot_retrieval_eval import (
    assert_eval_profile,
    department_from_metadata,
    pilot_record_matches_scope,
)

_PILOT_RECORD_PREFIX = "pilot::"
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "conversation_transcript",
        "transcript",
        "messages",
        "raw_text",
        "vector",
        "embedding",
        "content",
    }
)
_TRACKED_METADATA_FIELDS = (
    "ticket_label",
    "department",
    "route_label",
    "review_priority",
    "source_corpus_id",
    "embedding_provider",
    "embedding_model",
    "namespace",
    "index_version",
)


@dataclass(frozen=True)
class PilotMetadataRow:
    record_id: str
    metadata: dict[str, Any]
    embedding_provider: str
    embedding_model: str


@dataclass(frozen=True)
class PilotMetadataInventory:
    row_count: int
    namespace: str
    index_version: str
    profile: str
    ticket_label_counts: dict[str, int]
    department_counts: dict[str, int]
    route_label_counts: dict[str, int]
    review_priority_counts: dict[str, int]
    source_corpus_id_counts: dict[str, int]
    embedding_provider_counts: dict[str, int]
    embedding_model_counts: dict[str, int]
    missing_field_counts: dict[str, int]
    metadata_keys_present: tuple[str, ...]
    explicit_department_present_count: int
    derived_department_empty_count: int
    retrieval_activated: bool = False
    generated_at: str = ""


def _validate_table_name(table_name: str) -> str:
    if not _TABLE_NAME_RE.fullmatch(table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")
    return table_name


def _record_prefix(namespace: str, index_version: str) -> str:
    return f"{_PILOT_RECORD_PREFIX}{namespace.strip()}::{index_version.strip()}::"


def fetch_pilot_metadata_rows(
    database_url: str,
    *,
    table_name: str,
    namespace: str,
    index_version: str,
) -> list[PilotMetadataRow]:
    """Load pilot-scoped rows (metadata columns only; no content or vectors)."""
    assert_sandbox_database_url(database_url)
    table = _validate_table_name(table_name)
    prefix = _record_prefix(namespace, index_version)
    sql = f"""
        SELECT record_id, embedding_provider, embedding_model, metadata
        FROM {table}
        WHERE record_id LIKE %s
    """
    rows: list[PilotMetadataRow] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (f"{prefix}%",))
            for record_id, provider, model, metadata in cur.fetchall():
                meta: dict[str, Any]
                if isinstance(metadata, dict):
                    meta = metadata
                elif isinstance(metadata, str):
                    meta = json.loads(metadata)
                else:
                    meta = dict(metadata) if metadata is not None else {}
                if not pilot_record_matches_scope(
                    str(record_id),
                    meta,
                    namespace=namespace,
                    index_version=index_version,
                ):
                    continue
                rows.append(
                    PilotMetadataRow(
                        record_id=str(record_id),
                        metadata=meta,
                        embedding_provider=str(provider or ""),
                        embedding_model=str(model or ""),
                    )
                )
    return rows


def _field_value(row: PilotMetadataRow, field: str) -> str:
    if field == "department":
        explicit = row.metadata.get("department")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip().lower()
        return department_from_metadata(row.metadata)
    if field == "embedding_provider":
        stored = row.metadata.get("embedding_provider")
        if isinstance(stored, str) and stored.strip():
            return stored.strip().lower()
        return row.embedding_provider.strip().lower()
    if field == "embedding_model":
        stored = row.metadata.get("embedding_model")
        if isinstance(stored, str) and stored.strip():
            return stored.strip()
        return row.embedding_model.strip()
    raw = row.metadata.get(field)
    if raw is None:
        return ""
    return str(raw).strip()


def build_pilot_metadata_inventory(
    rows: list[PilotMetadataRow],
    *,
    namespace: str,
    index_version: str,
    profile: str,
) -> PilotMetadataInventory:
    """Aggregate safe metadata statistics for pilot sandbox rows."""
    profile_norm = assert_eval_profile(profile)
    ns = namespace.strip()
    version = index_version.strip()

    ticket_labels: Counter[str] = Counter()
    departments: Counter[str] = Counter()
    route_labels: Counter[str] = Counter()
    review_priorities: Counter[str] = Counter()
    source_corpus_ids: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    models: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    metadata_keys: set[str] = set()
    explicit_department_present = 0
    derived_department_empty = 0

    for row in rows:
        metadata_keys.update(str(key) for key in row.metadata.keys())

        for field in _TRACKED_METADATA_FIELDS:
            if field == "department":
                explicit_dept = row.metadata.get("department")
                if not (isinstance(explicit_dept, str) and explicit_dept.strip()):
                    missing["department"] += 1
                continue
            value = _field_value(row, field)
            if not value:
                missing[field] += 1

        ticket_label = _field_value(row, "ticket_label")
        if ticket_label:
            ticket_labels[ticket_label] += 1

        route_label = _field_value(row, "route_label")
        if route_label:
            route_labels[route_label] += 1

        review_priority = _field_value(row, "review_priority")
        if review_priority:
            review_priorities[review_priority] += 1

        source_corpus_id = _field_value(row, "source_corpus_id")
        if source_corpus_id:
            source_corpus_ids[source_corpus_id] += 1

        provider = _field_value(row, "embedding_provider")
        if provider:
            providers[provider] += 1

        model = _field_value(row, "embedding_model")
        if model:
            models[model] += 1

        explicit_dept = row.metadata.get("department")
        if isinstance(explicit_dept, str) and explicit_dept.strip():
            explicit_department_present += 1
        derived_dept = department_from_metadata(row.metadata)
        if derived_dept:
            departments[derived_dept] += 1
        else:
            derived_department_empty += 1

    return PilotMetadataInventory(
        row_count=len(rows),
        namespace=ns,
        index_version=version,
        profile=profile_norm,
        ticket_label_counts=dict(sorted(ticket_labels.items())),
        department_counts=dict(sorted(departments.items())),
        route_label_counts=dict(sorted(route_labels.items())),
        review_priority_counts=dict(sorted(review_priorities.items())),
        source_corpus_id_counts=dict(sorted(source_corpus_ids.items())),
        embedding_provider_counts=dict(sorted(providers.items())),
        embedding_model_counts=dict(sorted(models.items())),
        missing_field_counts=dict(sorted(missing.items())),
        metadata_keys_present=tuple(sorted(metadata_keys)),
        explicit_department_present_count=explicit_department_present,
        derived_department_empty_count=derived_department_empty,
        retrieval_activated=False,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def inventory_to_dict(inventory: PilotMetadataInventory) -> dict[str, Any]:
    return {
        "row_count": inventory.row_count,
        "namespace": inventory.namespace,
        "index_version": inventory.index_version,
        "profile": inventory.profile,
        "ticket_label_counts": inventory.ticket_label_counts,
        "department_counts": inventory.department_counts,
        "route_label_counts": inventory.route_label_counts,
        "review_priority_counts": inventory.review_priority_counts,
        "source_corpus_id_counts": inventory.source_corpus_id_counts,
        "embedding_provider_counts": inventory.embedding_provider_counts,
        "embedding_model_counts": inventory.embedding_model_counts,
        "missing_field_counts": inventory.missing_field_counts,
        "metadata_keys_present": list(inventory.metadata_keys_present),
        "explicit_department_present_count": inventory.explicit_department_present_count,
        "derived_department_empty_count": inventory.derived_department_empty_count,
        "retrieval_activated": False,
        "generated_at": inventory.generated_at,
        "diagnostic_note": (
            "department_counts uses derived department (route_label/ticket_label); "
            "metadata_filtered eval must use ticket_label/route_label — department filter "
            "matches explicit metadata.department only"
        ),
    }


def assert_safe_inventory_report(payload: dict[str, Any]) -> None:
    keys: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                keys.add(str(key).lower())
                collect(child)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload)
    forbidden = keys.intersection(_FORBIDDEN_OUTPUT_KEYS)
    if forbidden:
        raise ValueError(
            f"inventory report contains forbidden keys: {', '.join(sorted(forbidden))}"
        )
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    if re.search(r"sk-[a-z0-9]{10,}", serialized):
        raise ValueError("inventory report must not include API key material")


def write_pilot_metadata_inventory_report(
    inventory: PilotMetadataInventory,
    *,
    output_path: Path,
) -> Path:
    payload = inventory_to_dict(inventory)
    assert_safe_inventory_report(payload)
    path = output_path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_pilot_metadata_inventory(
    database_url: str,
    *,
    namespace: str,
    index_version: str,
    profile: str,
    table_name: str = "rag_vector_records",
    row_fetcher: Callable[..., list[PilotMetadataRow]] | None = None,
) -> PilotMetadataInventory:
    """Run inventory against sandbox Postgres (or injected row fetcher for tests)."""
    fetch = row_fetcher or fetch_pilot_metadata_rows
    rows = fetch(
        database_url,
        table_name=table_name,
        namespace=namespace,
        index_version=index_version,
    )
    return build_pilot_metadata_inventory(
        rows,
        namespace=namespace,
        index_version=index_version,
        profile=profile,
    )

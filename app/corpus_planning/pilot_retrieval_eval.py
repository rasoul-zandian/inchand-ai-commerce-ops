"""Offline pilot corpus retrieval evaluation against sandbox pgvector (no LangGraph activation)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.corpus_planning.pgvector_sandbox_indexing import assert_sandbox_database_url
from app.embeddings import generate_embedding
from app.rag.pgvector_store import PgVectorStore
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import (
    InMemoryVectorStore,
    VectorSearchResult,
    VectorStore,
    cosine_similarity,
)

EvalMode = Literal["vector_only", "metadata_filtered"]

_PILOT_PROFILE = "semantic_pgvector"
_FORBIDDEN_PROFILES = frozenset({"semantic_pgvector_16"})
_OPENAI_EMBEDDING_PROVIDER = "openai"
_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
_PILOT_RECORD_PREFIX = "pilot::"
_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "conversation_transcript",
        "transcript",
        "messages",
        "raw_text",
        "draft_response",
        "final_response",
        "retrieved_context",
        "vector",
        "embedding",
    }
)
_ROUTE_TO_DEPARTMENT: dict[str, str] = {
    "general_vendor_support": "support",
    "escalation_review": "complaint",
    "billing_review": "finance",
    "qa_attention": "support",
}
_TICKET_LABEL_TO_DEPARTMENT: dict[str, str] = {
    "support": "support",
    "complaint": "complaint",
    "fund": "finance",
}
_VALID_LABELS = frozenset({"support", "complaint", "fund"})
_VALID_DEPARTMENTS = frozenset({"support", "complaint", "finance"})
_VALID_EVAL_MODES = frozenset({"vector_only", "metadata_filtered"})
_ALLOWED_METADATA_FILTER_KEYS = frozenset(
    {
        "ticket_label",
        "department",
        "route_label",
        "review_priority",
        "namespace",
        "index_version",
    }
)
_PILOT_SEARCH_OVERSAMPLE = 100


@dataclass(frozen=True)
class PilotMetadataFilter:
    ticket_label: str | None = None
    department: str | None = None
    route_label: str | None = None
    review_priority: str | None = None
    namespace: str | None = None
    index_version: str | None = None


@dataclass(frozen=True)
class PilotRetrievalCase:
    case_id: str
    query: str
    expected_ticket_label: str
    expected_department: str
    expected_room_ids: tuple[str, ...] = ()
    must_not_return_labels: tuple[str, ...] = ()
    notes: str = ""
    eval_mode: EvalMode = "vector_only"
    metadata_filter: PilotMetadataFilter | None = None


@dataclass(frozen=True)
class PilotRetrievalHit:
    record_id: str
    document_id: str
    ticket_label: str
    department: str
    room_id: str
    score: float


@dataclass(frozen=True)
class PilotRetrievalCaseResult:
    case_id: str
    query_hash: str
    expected_ticket_label: str
    expected_department: str
    returned_count: int
    top_labels: tuple[str, ...]
    top_departments: tuple[str, ...]
    passed: bool
    failure_reasons: tuple[str, ...]


@dataclass(frozen=True)
class PilotRetrievalEvalReport:
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    mean_top_score: float
    label_match_rate: float
    department_match_rate: float
    wrong_label_return_count: int
    empty_result_count: int
    top_k: int
    namespace: str
    index_version: str
    profile: str
    eval_mode: EvalMode = "vector_only"
    retrieval_activated: bool = False
    results: tuple[PilotRetrievalCaseResult, ...] = ()
    generated_at: str = ""


@dataclass(frozen=True)
class PilotRetrievalComparisonReport:
    vector_only: PilotRetrievalEvalReport
    metadata_filtered: PilotRetrievalEvalReport
    delta_pass_rate: float
    delta_wrong_label_return_count: int
    namespace: str
    index_version: str
    profile: str
    retrieval_activated: bool = False
    generated_at: str = ""


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _normalize_label(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_department(value: Any) -> str:
    return str(value or "").strip().lower()


def department_from_metadata(metadata: dict[str, Any]) -> str:
    """Derive department from pilot row metadata (no transcript fields)."""
    explicit = metadata.get("department")
    if isinstance(explicit, str) and explicit.strip():
        return _normalize_department(explicit)

    route_label = _normalize_label(metadata.get("route_label"))
    if route_label in _ROUTE_TO_DEPARTMENT:
        return _ROUTE_TO_DEPARTMENT[route_label]

    ticket_label = _normalize_label(metadata.get("ticket_label"))
    return _TICKET_LABEL_TO_DEPARTMENT.get(ticket_label, "")


def query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _parse_metadata_filter(raw: Any, *, case_id: str) -> PilotMetadataFilter | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"case {case_id}: metadata_filter must be an object")
    if not raw:
        return None

    unknown = set(raw.keys()) - _ALLOWED_METADATA_FILTER_KEYS
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"case {case_id}: metadata_filter has unsupported keys: {joined}")

    ticket_label = raw.get("ticket_label")
    department = raw.get("department")
    route_label = raw.get("route_label")
    review_priority = raw.get("review_priority")
    namespace = raw.get("namespace")
    index_version = raw.get("index_version")

    filt = PilotMetadataFilter(
        ticket_label=_normalize_label(ticket_label) if ticket_label else None,
        department=_normalize_department(department) if department else None,
        route_label=str(route_label).strip() if route_label else None,
        review_priority=str(review_priority).strip() if review_priority else None,
        namespace=str(namespace).strip() if namespace else None,
        index_version=str(index_version).strip() if index_version else None,
    )
    if not any(
        (
            filt.ticket_label,
            filt.department,
            filt.route_label,
            filt.review_priority,
            filt.namespace,
            filt.index_version,
        )
    ):
        raise ValueError(f"case {case_id}: metadata_filter must include at least one field")
    return filt


def record_matches_metadata_filter(
    metadata: dict[str, Any],
    metadata_filter: PilotMetadataFilter,
) -> bool:
    """Match pilot row metadata against a safe eval-only filter (no transcript fields)."""
    if metadata_filter.ticket_label is not None:
        if _normalize_label(metadata.get("ticket_label")) != metadata_filter.ticket_label:
            return False
    if metadata_filter.department is not None:
        explicit = metadata.get("department")
        if not isinstance(explicit, str) or not explicit.strip():
            return False
        if _normalize_department(explicit) != metadata_filter.department:
            return False
    if metadata_filter.route_label is not None:
        if _normalize_label(metadata.get("route_label")) != _normalize_label(
            metadata_filter.route_label
        ):
            return False
    if metadata_filter.review_priority is not None:
        if str(metadata.get("review_priority", "")).strip() != metadata_filter.review_priority:
            return False
    if metadata_filter.namespace is not None:
        if str(metadata.get("namespace", "")).strip() != metadata_filter.namespace:
            return False
    if metadata_filter.index_version is not None:
        if str(metadata.get("index_version", "")).strip() != metadata_filter.index_version:
            return False
    return True


def _parse_case(raw: dict[str, Any], *, index: int) -> PilotRetrievalCase:
    case_id = raw.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError(f"case {index}: case_id must be non-empty string")

    query = raw.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"case {case_id}: query must be non-empty string")

    expected_label = _normalize_label(raw.get("expected_ticket_label"))
    if expected_label not in _VALID_LABELS:
        raise ValueError(f"case {case_id}: invalid expected_ticket_label {expected_label!r}")

    expected_department = _normalize_department(raw.get("expected_department"))
    if expected_department not in _VALID_DEPARTMENTS:
        raise ValueError(f"case {case_id}: invalid expected_department {expected_department!r}")

    room_ids_raw = raw.get("expected_room_ids", [])
    if not isinstance(room_ids_raw, list):
        raise ValueError(f"case {case_id}: expected_room_ids must be a list")
    room_ids = tuple(str(item) for item in room_ids_raw if str(item).strip())

    forbidden_raw = raw.get("must_not_return_labels", [])
    if not isinstance(forbidden_raw, list):
        raise ValueError(f"case {case_id}: must_not_return_labels must be a list")
    forbidden = tuple(_normalize_label(item) for item in forbidden_raw if str(item).strip())
    for label in forbidden:
        if label not in _VALID_LABELS:
            raise ValueError(f"case {case_id}: invalid must_not_return_labels entry {label!r}")

    notes = raw.get("notes", "")
    if notes is not None and not isinstance(notes, str):
        raise ValueError(f"case {case_id}: notes must be a string")

    eval_mode_raw = raw.get("eval_mode", "vector_only")
    if not isinstance(eval_mode_raw, str):
        raise ValueError(f"case {case_id}: eval_mode must be a string")
    eval_mode = eval_mode_raw.strip().lower()
    if eval_mode not in _VALID_EVAL_MODES:
        raise ValueError(f"case {case_id}: invalid eval_mode {eval_mode!r}")

    metadata_filter = _parse_metadata_filter(raw.get("metadata_filter"), case_id=case_id)
    if eval_mode == "metadata_filtered" and metadata_filter is None:
        raise ValueError(f"case {case_id}: eval_mode metadata_filtered requires metadata_filter")
    if metadata_filter is not None and (
        metadata_filter.namespace is not None or metadata_filter.index_version is not None
    ):
        raise ValueError(
            f"case {case_id}: metadata_filter must not pin namespace or index_version "
            "(pilot scope comes from CLI --namespace and --index-version)"
        )

    return PilotRetrievalCase(
        case_id=case_id.strip(),
        query=query.strip(),
        expected_ticket_label=expected_label,
        expected_department=expected_department,
        expected_room_ids=room_ids,
        must_not_return_labels=forbidden,
        notes=str(notes or ""),
        eval_mode=eval_mode,  # type: ignore[arg-type]
        metadata_filter=metadata_filter,
    )


def load_pilot_retrieval_cases(path: Path) -> list[PilotRetrievalCase]:
    """Load synthetic pilot retrieval eval cases from JSON."""
    root = path.resolve()
    if not root.is_file():
        raise ValueError(f"eval cases file not found: {root}")

    payload = _load_json(root)
    cases_raw = payload.get("cases")
    if not isinstance(cases_raw, list) or not cases_raw:
        raise ValueError("eval cases file must contain a non-empty cases array")

    return [_parse_case(item, index=index) for index, item in enumerate(cases_raw)]


def pilot_scope_record_id_prefix(namespace: str, index_version: str) -> str:
    """``record_id`` prefix for pilot sandbox rows in a namespace/index version."""
    return f"{_PILOT_RECORD_PREFIX}{namespace}::{index_version}::"


def pilot_record_matches_scope(
    record_id: str,
    metadata: dict[str, Any],
    *,
    namespace: str,
    index_version: str,
) -> bool:
    prefix = pilot_scope_record_id_prefix(namespace, index_version)
    if record_id.startswith(prefix):
        return True
    meta_ns = str(metadata.get("namespace", "")).strip()
    meta_ver = str(metadata.get("index_version", "")).strip()
    return meta_ns == namespace and meta_ver == index_version


def _collect_pilot_scoped_records(
    inner: VectorStore,
    *,
    namespace: str,
    index_version: str,
) -> list[VectorRecord]:
    """Fetch all pilot-scoped rows for ranking (eval-only; not global top-k)."""
    prefix = pilot_scope_record_id_prefix(namespace, index_version)
    if isinstance(inner, PgVectorStore):
        records = inner.fetch_by_record_id_prefix(prefix)
    elif isinstance(inner, InMemoryVectorStore):
        records = []
        for rec in inner._records.values():
            metadata = rec.metadata if isinstance(rec.metadata, dict) else {}
            if pilot_record_matches_scope(
                rec.record_id,
                metadata,
                namespace=namespace,
                index_version=index_version,
            ):
                records.append(rec)
    else:
        raise TypeError(
            "PilotScopedVectorStore metadata filtering requires "
            "PgVectorStore or InMemoryVectorStore"
        )
    return records


def _rank_records_by_query_vector(
    query_vector: list[float],
    records: list[VectorRecord],
    *,
    top_k: int,
) -> list[VectorSearchResult]:
    if top_k <= 0 or not query_vector or not records:
        return []

    qdim = len(query_vector)
    scored: list[tuple[float, VectorRecord]] = []
    for rec in records:
        if len(rec.vector) != qdim:
            continue
        score = cosine_similarity(query_vector, rec.vector)
        scored.append((score, rec))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [VectorSearchResult(record=rec, score=score) for score, rec in scored[:top_k]]


def count_pilot_scoped_metadata_matches(
    store: PilotScopedVectorStore,
    metadata_filter: PilotMetadataFilter,
) -> int:
    """Count pilot rows matching a metadata filter (safe aggregate; no content/vectors)."""
    matches = 0
    for rec in _collect_pilot_scoped_records(
        store._inner,
        namespace=store._namespace,
        index_version=store._index_version,
    ):
        metadata = rec.metadata if isinstance(rec.metadata, dict) else {}
        if record_matches_metadata_filter(metadata, metadata_filter):
            matches += 1
    return matches


def hit_from_search_result(result: VectorSearchResult) -> PilotRetrievalHit:
    metadata = result.record.metadata if isinstance(result.record.metadata, dict) else {}
    return PilotRetrievalHit(
        record_id=result.record.record_id,
        document_id=result.record.document_id,
        ticket_label=_normalize_label(metadata.get("ticket_label")),
        department=department_from_metadata(metadata),
        room_id=str(metadata.get("room_id", "")),
        score=float(result.score),
    )


class PilotScopedVectorStore(VectorStore):
    """Filter pgvector hits to pilot sandbox rows for a namespace/index version."""

    def __init__(
        self,
        inner: VectorStore,
        *,
        namespace: str,
        index_version: str,
    ) -> None:
        self._inner = inner
        self._namespace = namespace.strip()
        self._index_version = index_version.strip()

    def upsert(self, records: list) -> int:
        raise NotImplementedError("PilotScopedVectorStore is read-only for evaluation")

    def count(self) -> int:
        return self._inner.count()

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        metadata_filter: PilotMetadataFilter | None = None,
    ) -> list[VectorSearchResult]:
        if top_k <= 0:
            return []
        if metadata_filter is not None:
            return self._search_with_metadata_filter(
                query_vector,
                top_k=top_k,
                metadata_filter=metadata_filter,
            )

        oversample = max(top_k, min(_PILOT_SEARCH_OVERSAMPLE, top_k * 20))
        raw_hits = self._inner.search(query_vector, top_k=oversample)
        filtered: list[VectorSearchResult] = []
        for hit in raw_hits:
            metadata = hit.record.metadata if isinstance(hit.record.metadata, dict) else {}
            if not pilot_record_matches_scope(
                hit.record.record_id,
                metadata,
                namespace=self._namespace,
                index_version=self._index_version,
            ):
                continue
            filtered.append(hit)
            if len(filtered) >= top_k:
                break
        return filtered

    def _search_with_metadata_filter(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        metadata_filter: PilotMetadataFilter,
    ) -> list[VectorSearchResult]:
        """Rank within pilot scope + metadata predicate (not global pgvector top-k)."""
        candidates = _collect_pilot_scoped_records(
            self._inner,
            namespace=self._namespace,
            index_version=self._index_version,
        )
        matching: list[VectorRecord] = []
        for rec in candidates:
            metadata = rec.metadata if isinstance(rec.metadata, dict) else {}
            if record_matches_metadata_filter(metadata, metadata_filter):
                matching.append(rec)
        return _rank_records_by_query_vector(query_vector, matching, top_k=top_k)

    def count_metadata_matches(self, metadata_filter: PilotMetadataFilter) -> int:
        """Safe diagnostic: rows in pilot scope matching ``metadata_filter``."""
        return count_pilot_scoped_metadata_matches(self, metadata_filter)


def score_pilot_retrieval_results(
    cases: list[PilotRetrievalCase],
    hits_by_case_id: dict[str, list[PilotRetrievalHit]],
    *,
    top_k: int,
) -> PilotRetrievalEvalReport:
    """Score per-case results and compute aggregate metrics."""
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    case_results: list[PilotRetrievalCaseResult] = []
    label_matches = 0
    department_matches = 0
    wrong_label_returns = 0
    empty_results = 0
    top_scores: list[float] = []

    for case in cases:
        hits = hits_by_case_id.get(case.case_id, [])
        result = _score_single_case(case, hits, top_k=top_k)
        case_results.append(result)

        if result.returned_count == 0:
            empty_results += 1
        else:
            top_scores.append(hits[0].score)

        labels = set(result.top_labels)
        departments = set(result.top_departments)
        if case.expected_ticket_label in labels:
            label_matches += 1
        if case.expected_department in departments:
            department_matches += 1
        if case.must_not_return_labels and any(
            label in labels for label in case.must_not_return_labels
        ):
            wrong_label_returns += 1

    total = len(cases)
    passed = sum(1 for result in case_results if result.passed)
    failed = total - passed
    return PilotRetrievalEvalReport(
        total_cases=total,
        passed_cases=passed,
        failed_cases=failed,
        pass_rate=(passed / total) if total else 0.0,
        mean_top_score=(sum(top_scores) / len(top_scores)) if top_scores else 0.0,
        label_match_rate=(label_matches / total) if total else 0.0,
        department_match_rate=(department_matches / total) if total else 0.0,
        wrong_label_return_count=wrong_label_returns,
        empty_result_count=empty_results,
        top_k=top_k,
        namespace="",
        index_version="",
        profile=_PILOT_PROFILE,
        results=tuple(case_results),
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _score_single_case(
    case: PilotRetrievalCase,
    hits: list[PilotRetrievalHit],
    *,
    top_k: int,
) -> PilotRetrievalCaseResult:
    scoped = hits[:top_k]
    top_labels = tuple(hit.ticket_label for hit in scoped)
    top_departments = tuple(hit.department for hit in scoped)
    failure_reasons: list[str] = []

    if not scoped:
        failure_reasons.append("no_results_returned")
    else:
        labels = set(top_labels)
        departments = set(top_departments)
        if case.expected_ticket_label not in labels:
            failure_reasons.append("expected_ticket_label_not_in_top_k")
        if case.expected_department not in departments:
            failure_reasons.append("expected_department_not_in_top_k")
        forbidden = [label for label in case.must_not_return_labels if label in labels]
        if forbidden:
            failure_reasons.append(f"forbidden_labels_in_top_k:{','.join(forbidden)}")

        if case.expected_room_ids:
            returned_rooms = {hit.room_id for hit in scoped if hit.room_id}
            missing_rooms = [room for room in case.expected_room_ids if room not in returned_rooms]
            if missing_rooms:
                failure_reasons.append("expected_room_ids_not_in_top_k")

    return PilotRetrievalCaseResult(
        case_id=case.case_id,
        query_hash=query_hash(case.query),
        expected_ticket_label=case.expected_ticket_label,
        expected_department=case.expected_department,
        returned_count=len(scoped),
        top_labels=top_labels,
        top_departments=top_departments,
        passed=len(failure_reasons) == 0,
        failure_reasons=tuple(failure_reasons),
    )


def assert_eval_profile(profile: str) -> str:
    profile_norm = profile.strip().lower()
    if profile_norm in _FORBIDDEN_PROFILES:
        raise ValueError(f"profile {profile!r} is not allowed for pilot sandbox retrieval eval")
    if profile_norm != _PILOT_PROFILE:
        raise ValueError(f"profile must be {_PILOT_PROFILE!r} for pilot retrieval eval")
    return profile_norm


def _metadata_filter_to_dict(metadata_filter: PilotMetadataFilter | None) -> dict[str, str] | None:
    if metadata_filter is None:
        return None
    payload: dict[str, str] = {}
    if metadata_filter.ticket_label:
        payload["ticket_label"] = metadata_filter.ticket_label
    if metadata_filter.department:
        payload["department"] = metadata_filter.department
    if metadata_filter.route_label:
        payload["route_label"] = metadata_filter.route_label
    if metadata_filter.review_priority:
        payload["review_priority"] = metadata_filter.review_priority
    if metadata_filter.namespace:
        payload["namespace"] = metadata_filter.namespace
    if metadata_filter.index_version:
        payload["index_version"] = metadata_filter.index_version
    return payload or None


def report_to_dict(
    report: PilotRetrievalEvalReport,
    *,
    namespace: str,
    index_version: str,
    profile: str,
) -> dict[str, Any]:
    return {
        "total_cases": report.total_cases,
        "passed_cases": report.passed_cases,
        "failed_cases": report.failed_cases,
        "pass_rate": report.pass_rate,
        "mean_top_score": report.mean_top_score,
        "label_match_rate": report.label_match_rate,
        "department_match_rate": report.department_match_rate,
        "wrong_label_return_count": report.wrong_label_return_count,
        "empty_result_count": report.empty_result_count,
        "top_k": report.top_k,
        "eval_mode": report.eval_mode,
        "namespace": namespace,
        "index_version": index_version,
        "profile": profile,
        "retrieval_activated": False,
        "generated_at": report.generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": [
            {
                "case_id": result.case_id,
                "query_hash": result.query_hash,
                "expected_ticket_label": result.expected_ticket_label,
                "expected_department": result.expected_department,
                "returned_count": result.returned_count,
                "top_labels": list(result.top_labels),
                "top_departments": list(result.top_departments),
                "passed": result.passed,
                "failure_reasons": list(result.failure_reasons),
            }
            for result in report.results
        ],
    }


def comparison_report_to_dict(
    comparison: PilotRetrievalComparisonReport,
    *,
    profile: str,
) -> dict[str, Any]:
    return {
        "vector_only": report_to_dict(
            comparison.vector_only,
            namespace=comparison.namespace,
            index_version=comparison.index_version,
            profile=profile,
        ),
        "metadata_filtered": report_to_dict(
            comparison.metadata_filtered,
            namespace=comparison.namespace,
            index_version=comparison.index_version,
            profile=profile,
        ),
        "comparison": {
            "delta_pass_rate": comparison.delta_pass_rate,
            "delta_wrong_label_return_count": comparison.delta_wrong_label_return_count,
        },
        "namespace": comparison.namespace,
        "index_version": comparison.index_version,
        "profile": profile,
        "retrieval_activated": False,
        "generated_at": comparison.generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _collect_json_keys(value: Any, keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).lower())
            _collect_json_keys(child, keys)
    elif isinstance(value, list):
        for item in value:
            _collect_json_keys(item, keys)


def assert_safe_eval_report(payload: dict[str, Any]) -> None:
    """Reject reports that would leak transcripts, vectors, or raw queries."""
    keys: set[str] = set()
    _collect_json_keys(payload, keys)
    forbidden_keys = keys.intersection(_FORBIDDEN_OUTPUT_KEYS)
    if forbidden_keys:
        joined = ", ".join(sorted(forbidden_keys))
        raise ValueError(f"eval report contains forbidden JSON keys: {joined}")
    if "query" in keys:
        raise ValueError("eval report must not include raw query text")

    serialized = json.dumps(payload, ensure_ascii=False)
    if re.search(r"sk-[a-z0-9]{10,}", serialized):
        raise ValueError("eval report must not include API key material")


def write_pilot_retrieval_eval_report(
    report: PilotRetrievalEvalReport,
    *,
    output_path: Path,
    namespace: str,
    index_version: str,
    profile: str,
) -> Path:
    payload = report_to_dict(
        report,
        namespace=namespace,
        index_version=index_version,
        profile=profile,
    )
    assert_safe_eval_report(payload)
    path = output_path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_pilot_retrieval_comparison_report(
    comparison: PilotRetrievalComparisonReport,
    *,
    output_path: Path,
    profile: str,
) -> Path:
    payload = comparison_report_to_dict(comparison, profile=profile)
    assert_safe_eval_report(payload)
    path = output_path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _active_metadata_filter(
    case: PilotRetrievalCase,
    *,
    force_vector_only: bool,
    apply_metadata_filter: bool = False,
) -> PilotMetadataFilter | None:
    if force_vector_only:
        return None
    if apply_metadata_filter or case.eval_mode == "metadata_filtered":
        return case.metadata_filter
    return None


def build_pilot_retrieve_fn(
    store: VectorStore,
    *,
    embedding_provider: str = _OPENAI_EMBEDDING_PROVIDER,
    embedding_model: str = _OPENAI_EMBEDDING_MODEL,
    force_vector_only: bool = False,
    apply_metadata_filter: bool = False,
) -> Callable[[PilotRetrievalCase, int], list[PilotRetrievalHit]]:
    """Build per-case retrieve using query embeddings + sandbox search (eval only)."""
    if (
        embedding_provider.strip().lower() == _OPENAI_EMBEDDING_PROVIDER
        and not os.environ.get("OPENAI_API_KEY", "").strip()
    ):
        raise ValueError("OPENAI_API_KEY is required for OpenAI query embeddings in pilot eval")

    def retrieve(case: PilotRetrievalCase, top_k: int) -> list[PilotRetrievalHit]:
        text = case.query.strip()
        if not text:
            return []
        embedding = generate_embedding(
            text,
            provider=embedding_provider,
            model=embedding_model,
        )
        metadata_filter = _active_metadata_filter(
            case,
            force_vector_only=force_vector_only,
            apply_metadata_filter=apply_metadata_filter,
        )
        if isinstance(store, PilotScopedVectorStore):
            hits = store.search(
                embedding.vector,
                top_k=top_k,
                metadata_filter=metadata_filter,
            )
        elif metadata_filter is not None:
            raise ValueError("metadata_filtered eval requires PilotScopedVectorStore")
        else:
            hits = store.search(embedding.vector, top_k=top_k)
        return [hit_from_search_result(item) for item in hits]

    return retrieve


def build_default_pilot_retrieve_fn(
    store: VectorStore,
    *,
    embedding_provider: str = _OPENAI_EMBEDDING_PROVIDER,
    embedding_model: str = _OPENAI_EMBEDDING_MODEL,
) -> Callable[[PilotRetrievalCase, int], list[PilotRetrievalHit]]:
    """Backward-compatible retrieve builder (honors per-case eval_mode)."""
    return build_pilot_retrieve_fn(
        store,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        force_vector_only=False,
    )


def _finalize_eval_report(
    scored: PilotRetrievalEvalReport,
    *,
    namespace: str,
    index_version: str,
    profile: str,
    eval_mode: EvalMode,
) -> PilotRetrievalEvalReport:
    return PilotRetrievalEvalReport(
        total_cases=scored.total_cases,
        passed_cases=scored.passed_cases,
        failed_cases=scored.failed_cases,
        pass_rate=scored.pass_rate,
        mean_top_score=scored.mean_top_score,
        label_match_rate=scored.label_match_rate,
        department_match_rate=scored.department_match_rate,
        wrong_label_return_count=scored.wrong_label_return_count,
        empty_result_count=scored.empty_result_count,
        top_k=scored.top_k,
        namespace=namespace,
        index_version=index_version,
        profile=profile,
        eval_mode=eval_mode,
        retrieval_activated=False,
        results=scored.results,
        generated_at=scored.generated_at,
    )


def run_pilot_retrieval_eval(
    cases: list[PilotRetrievalCase],
    *,
    namespace: str,
    index_version: str,
    profile: str,
    top_k: int,
    retrieve_fn: Callable[[PilotRetrievalCase, int], list[PilotRetrievalHit]],
    eval_mode: EvalMode = "vector_only",
) -> PilotRetrievalEvalReport:
    """Run pilot retrieval evaluation (evaluation only; no LangGraph activation)."""
    profile_norm = assert_eval_profile(profile)
    ns = namespace.strip()
    version = index_version.strip()
    if not ns:
        raise ValueError("namespace must be non-empty")
    if not version:
        raise ValueError("index_version must be non-empty")

    hits_by_case_id: dict[str, list[PilotRetrievalHit]] = {}
    for case in cases:
        hits_by_case_id[case.case_id] = retrieve_fn(case, top_k)

    scored = score_pilot_retrieval_results(cases, hits_by_case_id, top_k=top_k)
    return _finalize_eval_report(
        scored,
        namespace=ns,
        index_version=version,
        profile=profile_norm,
        eval_mode=eval_mode,
    )


def cases_with_metadata_filter(cases: list[PilotRetrievalCase]) -> list[PilotRetrievalCase]:
    return [case for case in cases if case.metadata_filter is not None]


def run_pilot_retrieval_comparison_eval(
    cases: list[PilotRetrievalCase],
    *,
    namespace: str,
    index_version: str,
    profile: str,
    top_k: int,
    store: VectorStore,
    embedding_provider: str = _OPENAI_EMBEDDING_PROVIDER,
    embedding_model: str = _OPENAI_EMBEDDING_MODEL,
) -> PilotRetrievalComparisonReport:
    """Compare vector-only vs metadata-filtered retrieval on the same case set."""
    profile_norm = assert_eval_profile(profile)
    filtered_cases = cases_with_metadata_filter(cases)
    if not filtered_cases:
        raise ValueError("compare-modes requires at least one case with metadata_filter")

    vector_retrieve = build_pilot_retrieve_fn(
        store,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        force_vector_only=True,
    )
    vector_report = run_pilot_retrieval_eval(
        filtered_cases,
        namespace=namespace,
        index_version=index_version,
        profile=profile_norm,
        top_k=top_k,
        retrieve_fn=vector_retrieve,
        eval_mode="vector_only",
    )

    filtered_retrieve = build_pilot_retrieve_fn(
        store,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        force_vector_only=False,
        apply_metadata_filter=True,
    )
    metadata_cases = [
        PilotRetrievalCase(
            case_id=case.case_id,
            query=case.query,
            expected_ticket_label=case.expected_ticket_label,
            expected_department=case.expected_department,
            expected_room_ids=case.expected_room_ids,
            must_not_return_labels=case.must_not_return_labels,
            notes=case.notes,
            eval_mode="metadata_filtered",
            metadata_filter=case.metadata_filter,
        )
        for case in filtered_cases
    ]
    metadata_report = run_pilot_retrieval_eval(
        metadata_cases,
        namespace=namespace,
        index_version=index_version,
        profile=profile_norm,
        top_k=top_k,
        retrieve_fn=filtered_retrieve,
        eval_mode="metadata_filtered",
    )

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return PilotRetrievalComparisonReport(
        vector_only=vector_report,
        metadata_filtered=metadata_report,
        delta_pass_rate=metadata_report.pass_rate - vector_report.pass_rate,
        delta_wrong_label_return_count=(
            metadata_report.wrong_label_return_count - vector_report.wrong_label_return_count
        ),
        namespace=namespace.strip(),
        index_version=index_version.strip(),
        profile=profile_norm,
        retrieval_activated=False,
        generated_at=generated_at,
    )


def build_pilot_pgvector_store(
    database_url: str,
    *,
    namespace: str,
    index_version: str,
    table_name: str = "rag_vector_records",
    dimensions: int = 1536,
) -> PilotScopedVectorStore:
    assert_sandbox_database_url(database_url)
    inner = PgVectorStore(
        database_url,
        table_name=table_name,
        dimensions=dimensions,
    )
    return PilotScopedVectorStore(
        inner,
        namespace=namespace,
        index_version=index_version,
    )

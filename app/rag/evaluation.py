"""Offline RAG retrieval evaluation (no LLM, no OpenAI, no vector DB)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.rag.bootstrap import retrieve_semantic_vendor_ticket_context
from app.rag.types import RAGDocument, RAGResult

_DEFAULT_EVAL_CASES_PATH = (
    Path(__file__).resolve().parents[2] / "corpus" / "vendor_ticket" / "eval_cases.json"
)


class RetrievalEvalCase(BaseModel):
    """Single labeled query and expected retrieval targets."""

    case_id: str
    query: str
    expected_document_ids: list[str]
    required_source_types: list[str] = Field(default_factory=list)
    top_k: int = 5
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalEvalCaseFile(BaseModel):
    """On-disk eval suite: versioned header plus ordered ``RetrievalEvalCase`` rows."""

    eval_version: str
    workflow_type: str
    locale: str
    cases: list[RetrievalEvalCase]


class RetrievalEvalResult(BaseModel):
    """Outcome for one case against a concrete ``RAGResult``."""

    case_id: str
    query: str
    passed: bool
    retrieved_document_ids: list[str]
    expected_document_ids: list[str]
    matched_document_ids: list[str]
    missing_document_ids: list[str]
    retrieved_source_types: list[str]
    required_source_types: list[str]
    missing_source_types: list[str]
    top_k: int
    recall_at_k: float = 0.0
    hit_rate: float = 0.0
    mrr: float = 0.0
    first_match_rank: int | None = None
    near_miss_document_ids: list[str] = Field(default_factory=list)
    near_miss_violations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalEvalReport(BaseModel):
    """Aggregate report over many cases."""

    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    mean_recall_at_k: float = 0.0
    mean_hit_rate: float = 0.0
    mean_mrr: float = 0.0
    near_miss_violation_count: int = 0
    cases_with_near_miss_violations: list[str] = Field(default_factory=list)
    results: list[RetrievalEvalResult]
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_retrieval_eval_cases(path: str | Path) -> RetrievalEvalCaseFile:
    """Load and validate ``eval_cases.json`` (UTF-8). Raises on malformed JSON or schema errors."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Eval cases file is not valid JSON: {p}") from exc
    return RetrievalEvalCaseFile.model_validate(data)


def load_vendor_ticket_eval_cases_from_file(
    path: str | Path | None = None,
) -> list[RetrievalEvalCase]:
    """Load vendor-ticket eval cases from ``corpus/vendor_ticket/eval_cases.json`` by default.

    Merges file-level ``workflow_type``, ``locale``, and ``eval_version`` into case metadata.
    """
    resolved = Path(path) if path is not None else _DEFAULT_EVAL_CASES_PATH
    file_model = load_retrieval_eval_cases(resolved)
    merged: list[RetrievalEvalCase] = []
    for case in file_model.cases:
        meta = dict(case.metadata)
        meta.setdefault("workflow_type", file_model.workflow_type)
        meta.setdefault("locale", file_model.locale)
        meta.setdefault("eval_version", file_model.eval_version)
        merged.append(case.model_copy(update={"metadata": meta}))
    return merged


def _compute_ranking_metrics(
    retrieved_document_ids: list[str],
    expected_document_ids: list[str],
) -> tuple[float, float, float, int | None]:
    """Return recall@k, hit_rate, mrr, and 1-based first_match_rank (or None)."""
    if not expected_document_ids:
        return 0.0, 0.0, 0.0, None

    expected_set = set(expected_document_ids)
    matched_count = sum(1 for eid in expected_document_ids if eid in set(retrieved_document_ids))
    recall_at_k = matched_count / len(expected_document_ids)
    hit_rate = 1.0 if matched_count > 0 else 0.0

    first_match_rank: int | None = None
    for rank, doc_id in enumerate(retrieved_document_ids, start=1):
        if doc_id in expected_set:
            first_match_rank = rank
            break

    mrr = (1.0 / first_match_rank) if first_match_rank is not None else 0.0
    return recall_at_k, hit_rate, mrr, first_match_rank


def _mean_metric(results: list[RetrievalEvalResult], field: str) -> float:
    if not results:
        return 0.0
    return sum(getattr(result, field) for result in results) / len(results)


def _parse_near_miss_document_ids(metadata: dict[str, Any]) -> list[str]:
    """Return validated ``near_miss_document_ids`` from case metadata, or empty."""
    raw = metadata.get("near_miss_document_ids")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item)
    return out


def _compute_near_miss_violations(
    retrieved_document_ids: list[str],
    near_miss_document_ids: list[str],
    first_match_rank: int | None,
) -> list[str]:
    """Near-miss docs that appear before the first expected hit (or any if no expected hit)."""
    if not near_miss_document_ids:
        return []
    near_miss_set = set(near_miss_document_ids)
    violations: list[str] = []
    for rank, doc_id in enumerate(retrieved_document_ids, start=1):
        if doc_id not in near_miss_set:
            continue
        if first_match_rank is None or rank < first_match_rank:
            violations.append(doc_id)
    return violations


def _unique_source_types_first_seen(documents: list[RAGDocument]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for doc in documents:
        if doc.source_type not in seen:
            seen.add(doc.source_type)
            out.append(doc.source_type)
    return out


def evaluate_retrieval_case(
    case: RetrievalEvalCase,
    *,
    result: RAGResult,
) -> RetrievalEvalResult:
    """Check whether ``result`` contains all expected ids and required source types."""
    retrieved_document_ids = [doc.document_id for doc in result.documents]
    retrieved_set = set(retrieved_document_ids)
    matched_document_ids = [eid for eid in case.expected_document_ids if eid in retrieved_set]
    missing_document_ids = [eid for eid in case.expected_document_ids if eid not in retrieved_set]

    retrieved_source_types = _unique_source_types_first_seen(result.documents)
    type_set = set(retrieved_source_types)
    missing_source_types = [t for t in case.required_source_types if t not in type_set]

    passed = not missing_document_ids and not missing_source_types
    recall_at_k, hit_rate, mrr, first_match_rank = _compute_ranking_metrics(
        retrieved_document_ids,
        case.expected_document_ids,
    )
    meta = dict(case.metadata)
    near_miss_ids = _parse_near_miss_document_ids(meta)
    near_miss_violations = _compute_near_miss_violations(
        retrieved_document_ids,
        near_miss_ids,
        first_match_rank,
    )
    return RetrievalEvalResult(
        case_id=case.case_id,
        query=case.query,
        passed=passed,
        retrieved_document_ids=retrieved_document_ids,
        expected_document_ids=list(case.expected_document_ids),
        matched_document_ids=matched_document_ids,
        missing_document_ids=missing_document_ids,
        retrieved_source_types=retrieved_source_types,
        required_source_types=list(case.required_source_types),
        missing_source_types=missing_source_types,
        top_k=case.top_k,
        recall_at_k=recall_at_k,
        hit_rate=hit_rate,
        mrr=mrr,
        first_match_rank=first_match_rank,
        near_miss_document_ids=near_miss_ids,
        near_miss_violations=near_miss_violations,
        metadata=meta,
    )


def evaluate_retrieval_cases(
    cases: list[RetrievalEvalCase],
    *,
    retrieve_fn: Callable[[str, int], RAGResult],
) -> RetrievalEvalReport:
    """Run ``retrieve_fn(query, top_k)`` per case and aggregate pass/fail."""
    results: list[RetrievalEvalResult] = []
    for case in cases:
        result = retrieve_fn(case.query, case.top_k)
        results.append(evaluate_retrieval_case(case, result=result))

    total = len(results)
    passed_n = sum(1 for r in results if r.passed)
    failed_n = total - passed_n
    rate = (passed_n / total) if total else 0.0
    cases_with_near_miss = [r.case_id for r in results if r.near_miss_violations]
    near_miss_count = sum(len(r.near_miss_violations) for r in results)

    return RetrievalEvalReport(
        total_cases=total,
        passed_cases=passed_n,
        failed_cases=failed_n,
        pass_rate=rate,
        mean_recall_at_k=_mean_metric(results, "recall_at_k"),
        mean_hit_rate=_mean_metric(results, "hit_rate"),
        mean_mrr=_mean_metric(results, "mrr"),
        near_miss_violation_count=near_miss_count,
        cases_with_near_miss_violations=cases_with_near_miss,
        results=results,
        metadata={"evaluator": "offline_retrieval_eval"},
    )


def default_vendor_ticket_eval_cases() -> list[RetrievalEvalCase]:
    """Deterministic eval cases from ``corpus/vendor_ticket/eval_cases.json``."""
    return load_vendor_ticket_eval_cases_from_file(None)


def run_default_vendor_ticket_retrieval_eval(
    *,
    top_k: int = 5,
) -> RetrievalEvalReport:
    """Run default vendor-ticket cases via ``retrieve_semantic_vendor_ticket_context``."""

    def _retrieve(query: str, k: int) -> RAGResult:
        return retrieve_semantic_vendor_ticket_context(query, top_k=k)

    cases = default_vendor_ticket_eval_cases()
    adjusted = [c.model_copy(update={"top_k": top_k}) for c in cases]
    return evaluate_retrieval_cases(adjusted, retrieve_fn=_retrieve)


def run_same_embedding_in_memory_retrieval_eval(
    *,
    embedding_provider: str,
    embedding_model: str,
    cases: list[RetrievalEvalCase] | None = None,
) -> RetrievalEvalReport:
    """Run eval cases against an in-memory store using explicit embedding settings.

    Uses the default vendor-ticket corpus (same documents as pgvector indexing).
    Intended for manual ``pg-compare`` when ``BASELINE_PROVIDER=same_embedding`` so
    baseline and pgvector share an embedding space (storage parity check).
    """
    from app.rag.bootstrap import default_vendor_ticket_documents
    from app.rag.semantic_retriever import build_in_memory_store_from_documents, semantic_retrieve

    documents = default_vendor_ticket_documents()
    store = build_in_memory_store_from_documents(
        documents,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
    )
    loaded_cases = cases if cases is not None else default_vendor_ticket_eval_cases()

    def _retrieve(query: str, top_k: int) -> RAGResult:
        return semantic_retrieve(
            query,
            store=store,
            top_k=top_k,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )

    report = evaluate_retrieval_cases(loaded_cases, retrieve_fn=_retrieve)
    meta = dict(report.metadata)
    meta["baseline_provider"] = "same_embedding"
    meta["embedding_provider"] = embedding_provider
    meta["embedding_model"] = embedding_model
    return report.model_copy(update={"metadata": meta})


class RetrievalQualityThresholds(BaseModel):
    """Staging/manual quality gates for retrieval eval reports (not used in default CI)."""

    enabled: bool = True
    min_pass_rate: float = 1.0
    min_mean_recall_at_k: float = 1.0
    min_mean_hit_rate: float = 1.0
    min_mean_mrr: float = 1.0
    max_pass_rate_regression: float = 0.0
    max_mean_recall_at_k_regression: float = 0.0
    max_mean_hit_rate_regression: float = 0.0
    max_mean_mrr_regression: float = 0.0
    require_matching_case_results: bool = True
    max_near_miss_violations: int | None = None
    max_near_miss_violation_regression: int | None = None


class QualityGateCheck(BaseModel):
    """Single threshold gate outcome."""

    name: str
    passed: bool
    detail: str


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return float(raw)


def _env_int_optional(name: str) -> int | None:
    """Parse optional non-negative integer env var; unset/empty => None."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip()
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative integer, got {text!r}") from exc
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value}")
    return value


def load_retrieval_quality_thresholds_from_env() -> RetrievalQualityThresholds:
    """Load staging quality gates from environment (safe defaults; no secrets)."""
    return RetrievalQualityThresholds(
        enabled=_env_bool("RETRIEVAL_QUALITY_GATES", default=True),
        min_pass_rate=_env_float("RETRIEVAL_MIN_PASS_RATE", 1.0),
        min_mean_recall_at_k=_env_float("RETRIEVAL_MIN_MEAN_RECALL_AT_K", 1.0),
        min_mean_hit_rate=_env_float("RETRIEVAL_MIN_MEAN_HIT_RATE", 1.0),
        min_mean_mrr=_env_float("RETRIEVAL_MIN_MEAN_MRR", 1.0),
        max_pass_rate_regression=_env_float("RETRIEVAL_MAX_PASS_RATE_REGRESSION", 0.0),
        max_mean_recall_at_k_regression=_env_float(
            "RETRIEVAL_MAX_MEAN_RECALL_AT_K_REGRESSION", 0.0
        ),
        max_mean_hit_rate_regression=_env_float("RETRIEVAL_MAX_MEAN_HIT_RATE_REGRESSION", 0.0),
        max_mean_mrr_regression=_env_float("RETRIEVAL_MAX_MEAN_MRR_REGRESSION", 0.0),
        require_matching_case_results=_env_bool(
            "RETRIEVAL_REQUIRE_MATCHING_CASE_RESULTS", default=True
        ),
        max_near_miss_violations=_env_int_optional("RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS"),
        max_near_miss_violation_regression=_env_int_optional(
            "RETRIEVAL_MAX_NEAR_MISS_VIOLATION_REGRESSION"
        ),
    )


def evaluate_report_quality_gates(
    report: RetrievalEvalReport,
    thresholds: RetrievalQualityThresholds,
) -> list[QualityGateCheck]:
    """Check absolute quality thresholds on a single backend report."""
    if not thresholds.enabled:
        return []

    checks: list[QualityGateCheck] = []

    def _min_gate(name: str, actual: float, minimum: float) -> None:
        passed = actual >= minimum
        checks.append(
            QualityGateCheck(
                name=name,
                passed=passed,
                detail=f"actual={actual:.4f} required>={minimum:.4f}",
            )
        )

    _min_gate("min_pass_rate", report.pass_rate, thresholds.min_pass_rate)
    _min_gate("min_mean_recall_at_k", report.mean_recall_at_k, thresholds.min_mean_recall_at_k)
    _min_gate("min_mean_hit_rate", report.mean_hit_rate, thresholds.min_mean_hit_rate)
    _min_gate("min_mean_mrr", report.mean_mrr, thresholds.min_mean_mrr)

    if thresholds.max_near_miss_violations is not None:
        count = report.near_miss_violation_count
        maximum = thresholds.max_near_miss_violations
        passed = count <= maximum
        checks.append(
            QualityGateCheck(
                name="max_near_miss_violations",
                passed=passed,
                detail=(
                    f"near_miss_violation_count {count} exceeds max_near_miss_violations {maximum}"
                    if not passed
                    else f"near_miss_violation_count={count} max_near_miss_violations={maximum}"
                ),
            )
        )

    return checks


def evaluate_comparison_quality_gates(
    payload: dict[str, Any],
    thresholds: RetrievalQualityThresholds,
) -> list[QualityGateCheck]:
    """Check pgvector report thresholds and regression vs in-memory baseline."""
    if not thresholds.enabled:
        return []

    pgvector_section = payload["pgvector"]
    pgvector_report = RetrievalEvalReport(
        total_cases=int(pgvector_section["total_cases"]),
        passed_cases=int(pgvector_section["passed_cases"]),
        failed_cases=int(pgvector_section["failed_cases"]),
        pass_rate=float(pgvector_section["pass_rate"]),
        mean_recall_at_k=float(pgvector_section["mean_recall_at_k"]),
        mean_hit_rate=float(pgvector_section["mean_hit_rate"]),
        mean_mrr=float(pgvector_section["mean_mrr"]),
        near_miss_violation_count=int(pgvector_section.get("near_miss_violation_count", 0)),
        results=[],
    )
    checks = evaluate_report_quality_gates(pgvector_report, thresholds)

    comparison = payload["comparison"]

    def _regression_gate(name: str, delta: float, max_regression: float) -> None:
        passed = delta >= -max_regression
        checks.append(
            QualityGateCheck(
                name=name,
                passed=passed,
                detail=f"delta={delta:.4f} min_allowed={-max_regression:.4f}",
            )
        )

    _regression_gate(
        "max_pass_rate_regression",
        float(comparison["pass_rate_delta"]),
        thresholds.max_pass_rate_regression,
    )
    _regression_gate(
        "max_mean_recall_at_k_regression",
        float(comparison["mean_recall_at_k_delta"]),
        thresholds.max_mean_recall_at_k_regression,
    )
    _regression_gate(
        "max_mean_hit_rate_regression",
        float(comparison["mean_hit_rate_delta"]),
        thresholds.max_mean_hit_rate_regression,
    )
    _regression_gate(
        "max_mean_mrr_regression",
        float(comparison["mean_mrr_delta"]),
        thresholds.max_mean_mrr_regression,
    )

    if thresholds.require_matching_case_results:
        different = int(comparison["cases_with_different_results"])
        checks.append(
            QualityGateCheck(
                name="require_matching_case_results",
                passed=different == 0,
                detail=f"cases_with_different_results={different} required=0",
            )
        )

    if thresholds.max_near_miss_violation_regression is not None:
        baseline_count = int(payload["baseline"].get("near_miss_violation_count", 0))
        pgvector_count = int(pgvector_section.get("near_miss_violation_count", 0))
        regression = pgvector_count - baseline_count
        maximum = thresholds.max_near_miss_violation_regression
        passed = regression <= maximum
        checks.append(
            QualityGateCheck(
                name="max_near_miss_violation_regression",
                passed=passed,
                detail=(
                    "near_miss_violation_count regression "
                    f"{regression} exceeds max_near_miss_violation_regression {maximum}"
                    if not passed
                    else (
                        f"near_miss_violation_count regression={regression} "
                        f"max_near_miss_violation_regression={maximum}"
                    )
                ),
            )
        )

    return checks


def quality_gates_passed(checks: list[QualityGateCheck]) -> bool:
    return not checks or all(check.passed for check in checks)


def format_quality_gate_lines(checks: list[QualityGateCheck]) -> list[str]:
    if not checks:
        return []
    status = "passed" if quality_gates_passed(checks) else "failed"
    lines = [f"quality gates: {status}"]
    for check in checks:
        gate_status = "passed" if check.passed else "failed"
        lines.append(f"  {check.name}: {gate_status} ({check.detail})")
    return lines


def report_exit_code_for_quality_gates(
    report: RetrievalEvalReport,
    thresholds: RetrievalQualityThresholds | None = None,
) -> int:
    cfg = thresholds or load_retrieval_quality_thresholds_from_env()
    checks = evaluate_report_quality_gates(report, cfg)
    if not cfg.enabled:
        return 0 if report.pass_rate == 1.0 else 1
    return 0 if quality_gates_passed(checks) else 1


def comparison_exit_code_for_quality_gates(
    payload: dict[str, Any],
    thresholds: RetrievalQualityThresholds | None = None,
) -> int:
    cfg = thresholds or load_retrieval_quality_thresholds_from_env()
    checks = evaluate_comparison_quality_gates(payload, cfg)
    if not cfg.enabled:
        baseline_rate = float(payload["baseline"]["pass_rate"])
        pgvector_rate = float(payload["pgvector"]["pass_rate"])
        if baseline_rate == pgvector_rate and pgvector_rate == 1.0:
            return 0
        return 1
    return 0 if quality_gates_passed(checks) else 1

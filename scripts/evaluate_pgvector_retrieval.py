#!/usr/bin/env python3
"""Manual/staging: run retrieval eval cases against PgVectorStore (no indexing, no CI)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable

from app.config import AppSettings, get_settings
from app.rag.evaluation import (
    RetrievalEvalCase,
    RetrievalEvalReport,
    default_vendor_ticket_eval_cases,
    evaluate_report_quality_gates,
    evaluate_retrieval_cases,
    format_quality_gate_lines,
    load_retrieval_quality_thresholds_from_env,
    report_exit_code_for_quality_gates,
)
from app.rag.semantic_retriever import semantic_retrieve
from app.rag.types import RAGResult
from app.rag.vector_store import VectorStore
from app.rag.vector_store_factory import (
    VectorStoreConfig,
    build_vector_store_config_from_settings,
    create_vector_store,
)


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def pgvector_provider_error(config: VectorStoreConfig) -> str | None:
    """Return an error message when ``config`` is not pgvector."""
    if config.normalized_provider() != "pgvector":
        return "VECTOR_STORE_PROVIDER must be 'pgvector' for this evaluation."
    return None


def format_eval_report_lines(report: RetrievalEvalReport) -> list[str]:
    """Human-readable summary lines (no secrets)."""
    status = "passed" if report.pass_rate == 1.0 else "failed"
    lines = [
        f"pgvector retrieval eval: {status}",
        f"  total_cases={report.total_cases}",
        f"  passed_cases={report.passed_cases}",
        f"  failed_cases={report.failed_cases}",
        f"  pass_rate={report.pass_rate:.4f}",
        f"  mean_recall_at_k={report.mean_recall_at_k:.4f}",
        f"  mean_hit_rate={report.mean_hit_rate:.4f}",
        f"  mean_mrr={report.mean_mrr:.4f}",
        f"  near_miss_violation_count={report.near_miss_violation_count}",
    ]
    if report.cases_with_near_miss_violations:
        lines.append(f"  cases_with_near_miss_violations={report.cases_with_near_miss_violations}")
    if report.pass_rate == 1.0:
        lines.append("all retrieval eval cases passed")
        return lines

    for result in report.results:
        if result.passed:
            continue
        lines.append(f"  case_id={result.case_id}")
        lines.append(f"    missing_document_ids={result.missing_document_ids}")
        lines.append(f"    missing_source_types={result.missing_source_types}")
        lines.append(f"    retrieved_document_ids={result.retrieved_document_ids}")
    return lines


def print_eval_report(report: RetrievalEvalReport, *, output_json: bool = False) -> None:
    if output_json:
        print(report.model_dump_json(indent=2))
        return
    for line in format_eval_report_lines(report):
        print(line)


def run_pgvector_retrieval_eval(
    settings: AppSettings,
    store: VectorStore,
    cases: list[RetrievalEvalCase],
    *,
    retrieve_fn: Callable[[str, int], RAGResult] | None = None,
) -> RetrievalEvalReport:
    """Evaluate ``cases`` via ``semantic_retrieve`` on ``store`` (or custom ``retrieve_fn``)."""

    def _retrieve(query: str, top_k: int) -> RAGResult:
        return semantic_retrieve(
            query,
            store=store,
            top_k=top_k,
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
        )

    fn = retrieve_fn or _retrieve
    return evaluate_retrieval_cases(cases, retrieve_fn=fn)


def run_eval(
    settings: AppSettings | None = None,
    *,
    store_factory: Callable[[VectorStoreConfig], VectorStore] | None = None,
    cases_loader: Callable[[], list[RetrievalEvalCase]] | None = None,
) -> tuple[RetrievalEvalReport, VectorStoreConfig]:
    """Load settings, validate pgvector config, build store, and run eval cases."""
    resolved_settings = settings or get_settings()
    vector_store_config = build_vector_store_config_from_settings(resolved_settings)
    provider_err = pgvector_provider_error(vector_store_config)
    if provider_err:
        raise ValueError(provider_err)

    factory = store_factory or create_vector_store
    store = factory(vector_store_config)
    cases = (cases_loader or default_vendor_ticket_eval_cases)()
    report = run_pgvector_retrieval_eval(resolved_settings, store, cases)
    meta = dict(report.metadata)
    meta["pgvector_table"] = vector_store_config.table_name
    meta["pgvector_dimensions"] = vector_store_config.dimensions
    meta["embedding_provider"] = resolved_settings.embedding_provider
    meta["embedding_model"] = resolved_settings.embedding_model
    return report.model_copy(update={"metadata": meta}), vector_store_config


def main() -> int:
    try:
        report, vector_store_config = run_eval()
    except ValueError as exc:
        print("pgvector retrieval eval: failed", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print("pgvector retrieval eval: failed", file=sys.stderr)
        print(f"  {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    thresholds = load_retrieval_quality_thresholds_from_env()
    gate_checks = evaluate_report_quality_gates(report, thresholds)

    if _env_bool("OUTPUT_JSON"):
        payload = report.model_dump()
        payload["quality_gates"] = [check.model_dump() for check in gate_checks]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print_eval_report(report, output_json=False)
        if gate_checks:
            print("")
            for line in format_quality_gate_lines(gate_checks):
                print(line)

    _ = vector_store_config  # used for metadata only; never printed
    return report_exit_code_for_quality_gates(report, thresholds)


if __name__ == "__main__":
    raise SystemExit(main())

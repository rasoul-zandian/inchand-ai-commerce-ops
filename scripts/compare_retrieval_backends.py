#!/usr/bin/env python3
"""Manual/staging: compare in-memory semantic baseline vs PgVector retrieval eval."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any, Literal

from app.config import AppSettings, get_settings
from app.rag.evaluation import (
    RetrievalEvalCase,
    RetrievalEvalReport,
    RetrievalEvalResult,
    comparison_exit_code_for_quality_gates,
    default_vendor_ticket_eval_cases,
    evaluate_comparison_quality_gates,
    format_quality_gate_lines,
    load_retrieval_quality_thresholds_from_env,
    run_default_vendor_ticket_retrieval_eval,
    run_same_embedding_in_memory_retrieval_eval,
)
from app.rag.vector_store import VectorStore
from app.rag.vector_store_factory import VectorStoreConfig, build_vector_store_config_from_settings
from scripts.evaluate_pgvector_retrieval import (
    create_vector_store as _create_vector_store,
)
from scripts.evaluate_pgvector_retrieval import (
    pgvector_provider_error,
    run_pgvector_retrieval_eval,
)

BaselineProviderMode = Literal["default", "same_embedding"]


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_baseline_provider_mode(
    raw: str | None = None,
) -> BaselineProviderMode:
    """Resolve ``BASELINE_PROVIDER`` (default: mock in-memory baseline)."""
    value = (raw if raw is not None else os.environ.get("BASELINE_PROVIDER", "default")).strip()
    if not value or value.lower() == "default":
        return "default"
    if value.lower() == "same_embedding":
        return "same_embedding"
    raise ValueError(f"BASELINE_PROVIDER must be 'default' or 'same_embedding', got {value!r}")


def eval_results_differ(
    baseline: RetrievalEvalResult,
    pgvector: RetrievalEvalResult,
) -> bool:
    """True when pass status, misses, or retrieved ids differ between backends."""
    if baseline.passed != pgvector.passed:
        return True
    if baseline.missing_document_ids != pgvector.missing_document_ids:
        return True
    if baseline.retrieved_document_ids != pgvector.retrieved_document_ids:
        return True
    return False


def _results_by_case_id(report: RetrievalEvalReport) -> dict[str, RetrievalEvalResult]:
    return {result.case_id: result for result in report.results}


def build_comparison_payload(
    baseline_report: RetrievalEvalReport,
    pgvector_report: RetrievalEvalReport,
    *,
    baseline_provider_mode: BaselineProviderMode = "default",
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
    label_pgvector_embeddings: bool = True,
) -> dict[str, Any]:
    """Structured comparison (no secrets)."""
    baseline_by_id = _results_by_case_id(baseline_report)
    pgvector_by_id = _results_by_case_id(pgvector_report)
    all_case_ids = sorted(set(baseline_by_id) | set(pgvector_by_id))

    different_cases: list[dict[str, Any]] = []
    for case_id in all_case_ids:
        baseline_result = baseline_by_id[case_id]
        pgvector_result = pgvector_by_id[case_id]
        if eval_results_differ(baseline_result, pgvector_result):
            different_cases.append(
                {
                    "case_id": case_id,
                    "baseline_passed": baseline_result.passed,
                    "pgvector_passed": pgvector_result.passed,
                    "baseline_missing_document_ids": baseline_result.missing_document_ids,
                    "pgvector_missing_document_ids": pgvector_result.missing_document_ids,
                    "baseline_retrieved_document_ids": baseline_result.retrieved_document_ids,
                    "pgvector_retrieved_document_ids": pgvector_result.retrieved_document_ids,
                }
            )

    pass_rate_delta = pgvector_report.pass_rate - baseline_report.pass_rate
    baseline_section: dict[str, Any] = {
        "provider": "in_memory",
        "baseline_provider": baseline_provider_mode,
        "pass_rate": baseline_report.pass_rate,
        "passed_cases": baseline_report.passed_cases,
        "failed_cases": baseline_report.failed_cases,
        "total_cases": baseline_report.total_cases,
        "mean_recall_at_k": baseline_report.mean_recall_at_k,
        "mean_hit_rate": baseline_report.mean_hit_rate,
        "mean_mrr": baseline_report.mean_mrr,
        "near_miss_violation_count": baseline_report.near_miss_violation_count,
    }
    if baseline_provider_mode == "same_embedding" and embedding_provider is not None:
        baseline_section["embedding_provider"] = embedding_provider
        baseline_section["embedding_model"] = embedding_model

    pgvector_section: dict[str, Any] = {
        "provider": "pgvector",
        "pass_rate": pgvector_report.pass_rate,
        "passed_cases": pgvector_report.passed_cases,
        "failed_cases": pgvector_report.failed_cases,
        "total_cases": pgvector_report.total_cases,
        "mean_recall_at_k": pgvector_report.mean_recall_at_k,
        "mean_hit_rate": pgvector_report.mean_hit_rate,
        "mean_mrr": pgvector_report.mean_mrr,
        "near_miss_violation_count": pgvector_report.near_miss_violation_count,
    }
    if label_pgvector_embeddings and embedding_provider is not None:
        pgvector_section["embedding_provider"] = embedding_provider
        pgvector_section["embedding_model"] = embedding_model

    payload: dict[str, Any] = {
        "baseline_provider": baseline_provider_mode,
        "baseline": baseline_section,
        "pgvector": pgvector_section,
        "comparison": {
            "pass_rate_delta": pass_rate_delta,
            "mean_recall_at_k_delta": (
                pgvector_report.mean_recall_at_k - baseline_report.mean_recall_at_k
            ),
            "mean_hit_rate_delta": pgvector_report.mean_hit_rate - baseline_report.mean_hit_rate,
            "mean_mrr_delta": pgvector_report.mean_mrr - baseline_report.mean_mrr,
            "cases_with_different_results": len(different_cases),
            "near_miss_violation_count_delta": (
                pgvector_report.near_miss_violation_count
                - baseline_report.near_miss_violation_count
            ),
            "different_cases": different_cases,
        },
    }
    if baseline_provider_mode == "same_embedding" and embedding_provider is not None:
        payload["embedding_provider"] = embedding_provider
        payload["embedding_model"] = embedding_model
    return payload


def format_comparison_lines(payload: dict[str, Any]) -> list[str]:
    baseline = payload["baseline"]
    pgvector = payload["pgvector"]
    comparison = payload["comparison"]
    lines = [
        "retrieval backend comparison",
        "",
        "baseline:",
        f"  provider={baseline['provider']}",
        f"  baseline_provider={baseline['baseline_provider']}",
    ]
    if baseline.get("embedding_provider") is not None:
        lines.append(f"  embedding_provider={baseline['embedding_provider']}")
        lines.append(f"  embedding_model={baseline['embedding_model']}")
    lines.extend(
        [
            f"  pass_rate={baseline['pass_rate']:.4f}",
            f"  mean_recall_at_k={baseline['mean_recall_at_k']:.4f}",
            f"  mean_hit_rate={baseline['mean_hit_rate']:.4f}",
            f"  mean_mrr={baseline['mean_mrr']:.4f}",
            f"  passed_cases={baseline['passed_cases']}",
            f"  failed_cases={baseline['failed_cases']}",
            f"  near_miss_violation_count={baseline['near_miss_violation_count']}",
            "",
            "pgvector:",
            f"  provider={pgvector['provider']}",
        ]
    )
    if pgvector.get("embedding_provider") is not None:
        lines.append(f"  embedding_provider={pgvector['embedding_provider']}")
        lines.append(f"  embedding_model={pgvector['embedding_model']}")
    lines.extend(
        [
            f"  pass_rate={pgvector['pass_rate']:.4f}",
            f"  mean_recall_at_k={pgvector['mean_recall_at_k']:.4f}",
            f"  mean_hit_rate={pgvector['mean_hit_rate']:.4f}",
            f"  mean_mrr={pgvector['mean_mrr']:.4f}",
            f"  passed_cases={pgvector['passed_cases']}",
            f"  failed_cases={pgvector['failed_cases']}",
            f"  near_miss_violation_count={pgvector['near_miss_violation_count']}",
            "",
            "comparison:",
            f"  pass_rate_delta={comparison['pass_rate_delta']:.4f}",
            f"  mean_recall_at_k_delta={comparison['mean_recall_at_k_delta']:.4f}",
            f"  mean_hit_rate_delta={comparison['mean_hit_rate_delta']:.4f}",
            f"  mean_mrr_delta={comparison['mean_mrr_delta']:.4f}",
            f"  cases_with_different_results={comparison['cases_with_different_results']}",
            f"  near_miss_violation_count_delta={comparison['near_miss_violation_count_delta']}",
        ]
    )
    for diff in comparison["different_cases"]:
        lines.append("")
        lines.append(f"  case_id={diff['case_id']}")
        lines.append(f"    baseline_passed={diff['baseline_passed']}")
        lines.append(f"    pgvector_passed={diff['pgvector_passed']}")
        lines.append(f"    baseline_missing_document_ids={diff['baseline_missing_document_ids']}")
        lines.append(f"    pgvector_missing_document_ids={diff['pgvector_missing_document_ids']}")
        lines.append(
            f"    baseline_retrieved_document_ids={diff['baseline_retrieved_document_ids']}"
        )
        pg_ids = diff["pgvector_retrieved_document_ids"]
        lines.append(f"    pgvector_retrieved_document_ids={pg_ids}")
    return lines


comparison_exit_code = comparison_exit_code_for_quality_gates


def _run_baseline_report(
    *,
    mode: BaselineProviderMode,
    settings: AppSettings,
    cases: list[RetrievalEvalCase],
    baseline_runner: Callable[[], RetrievalEvalReport] | None,
) -> RetrievalEvalReport:
    if baseline_runner is not None:
        return baseline_runner()
    if mode == "same_embedding":
        return run_same_embedding_in_memory_retrieval_eval(
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
            cases=cases,
        )
    return run_default_vendor_ticket_retrieval_eval()


def run_comparison(
    settings: AppSettings | None = None,
    *,
    baseline_provider_mode: BaselineProviderMode | None = None,
    baseline_runner: Callable[[], RetrievalEvalReport] | None = None,
    pgvector_runner: Callable[[AppSettings, list[RetrievalEvalCase]], RetrievalEvalReport]
    | None = None,
    store_factory: Callable[[VectorStoreConfig], VectorStore] | None = None,
    cases_loader: Callable[[], list[RetrievalEvalCase]] | None = None,
) -> dict[str, Any]:
    """Run baseline and pgvector evals and return comparison payload."""
    resolved_settings = settings or get_settings()
    mode = baseline_provider_mode or resolve_baseline_provider_mode()
    vector_store_config = build_vector_store_config_from_settings(resolved_settings)
    provider_err = pgvector_provider_error(vector_store_config)
    if provider_err:
        raise ValueError(provider_err)

    cases = (cases_loader or default_vendor_ticket_eval_cases)()
    baseline_report = _run_baseline_report(
        mode=mode,
        settings=resolved_settings,
        cases=cases,
        baseline_runner=baseline_runner,
    )

    if pgvector_runner is not None:
        pgvector_report = pgvector_runner(resolved_settings, cases)
    else:
        factory = store_factory or _create_vector_store
        store = factory(vector_store_config)
        pgvector_report = run_pgvector_retrieval_eval(resolved_settings, store, cases)

    embedding_provider = resolved_settings.embedding_provider
    embedding_model = resolved_settings.embedding_model
    return build_comparison_payload(
        baseline_report,
        pgvector_report,
        baseline_provider_mode=mode,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        label_pgvector_embeddings=True,
    )


def main() -> int:
    try:
        payload = run_comparison()
    except ValueError as exc:
        print("retrieval backend comparison: failed", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print("retrieval backend comparison: failed", file=sys.stderr)
        print(f"  {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    thresholds = load_retrieval_quality_thresholds_from_env()
    gate_checks = evaluate_comparison_quality_gates(payload, thresholds)

    if _env_bool("OUTPUT_JSON"):
        out = dict(payload)
        out["quality_gates"] = [check.model_dump() for check in gate_checks]
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        for line in format_comparison_lines(payload):
            print(line)
        if gate_checks:
            print("")
            for line in format_quality_gate_lines(gate_checks):
                print(line)

    return comparison_exit_code_for_quality_gates(payload, thresholds)


if __name__ == "__main__":
    raise SystemExit(main())

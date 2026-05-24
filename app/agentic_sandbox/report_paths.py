"""Default output paths for agentic sandbox reports (shared to avoid import cycles)."""

from __future__ import annotations

from pathlib import Path

DEFAULT_BATCH_RUNS_JSONL = Path("reports/agentic_sandbox_batch_runs.jsonl")
DEFAULT_BATCH_SUMMARY_JSON = Path("reports/agentic_sandbox_batch_summary.json")
DEFAULT_BATCH_REPORT_MD = Path("reports/agentic_sandbox_batch_report.md")
DEFAULT_READINESS_SUMMARY_PATH = Path("reports/agentic_sandbox_readiness_summary.json")
DEFAULT_READINESS_REPORT_PATH = Path("reports/agentic_sandbox_readiness_report.md")
DEFAULT_COVERAGE_SUMMARY_PATH = Path("reports/agentic_knowledge_hint_coverage_summary.json")
DEFAULT_COVERAGE_REPORT_PATH = Path("reports/agentic_knowledge_hint_coverage_report.md")
DEFAULT_PREVIEW_REVIEW_METRICS_SUMMARY_PATH = Path(
    "reports/agentic_preview_review_metrics_summary.json",
)
DEFAULT_PREVIEW_REVIEW_METRICS_REPORT_PATH = Path(
    "reports/agentic_preview_review_metrics_report.md",
)

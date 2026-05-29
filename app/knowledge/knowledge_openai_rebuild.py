"""Orchestrate OpenAI knowledge chunk embedding + sandbox pgvector rebuild (local only)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.knowledge.knowledge_chunking import (
    build_combined_knowledge_chunks,
    summarize_knowledge_chunks,
    write_chunks_jsonl,
)
from app.knowledge.knowledge_embedding_index import (
    assert_safe_knowledge_output,
    build_knowledge_vector_records,
    delete_knowledge_sandbox_index,
    generate_knowledge_embeddings,
    index_knowledge_chunks_pgvector,
    load_knowledge_chunks,
    summarize_knowledge_indexing,
)
from app.knowledge.knowledge_retrieval_smoke import (
    run_knowledge_retrieval_smoke,
    write_knowledge_retrieval_smoke_reports,
)
from app.knowledge.policy_fact_extraction_check import (
    run_policy_fact_extraction_check,
    write_policy_fact_extraction_check_reports,
)
from app.rag.corpus_integrity import default_vendor_ticket_corpus_integrity

DEFAULT_OFFICIAL_PATH = Path("data/private/knowledge/operations")
DEFAULT_HISTORICAL_SUMMARY = Path("reports/historical_reply_benchmark_summary.json")
DEFAULT_CHUNKS_JSONL = Path("reports/knowledge_chunks_preview.jsonl")
DEFAULT_REBUILD_SUMMARY_JSON = Path("reports/knowledge_openai_rebuild_summary.json")
DEFAULT_REBUILD_REPORT_MD = Path("reports/knowledge_openai_rebuild_report.md")
DEFAULT_NAMESPACE = "knowledge_operations_sandbox"
DEFAULT_INDEX_VERSION = "knowledge_v1_openai"
DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSIONS = 1536
INDEX_PROFILE = "sandbox"


@dataclass(frozen=True)
class KnowledgeOpenaiRebuildResult:
    """Outcome of a full knowledge OpenAI rebuild orchestration."""

    status: str
    chunk_count: int
    indexed_count: int
    corpus_doc_count: int
    corpus_source_hash: str
    namespace: str
    index_version: str
    retrieval_smoke_status: str
    policy_fact_check_status: str
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "embedding_provider": "openai",
            "embedding_model": DEFAULT_OPENAI_MODEL,
            "dimensions": DEFAULT_DIMENSIONS,
            "index_profile": INDEX_PROFILE,
            "corpus_source": str(DEFAULT_OFFICIAL_PATH),
            "corpus_doc_count": self.corpus_doc_count,
            "corpus_source_hash": self.corpus_source_hash,
            "chunk_count": self.chunk_count,
            "indexed_count": self.indexed_count,
            "namespace": self.namespace,
            "index_version": self.index_version,
            "retrieval_smoke_status": self.retrieval_smoke_status,
            "policy_fact_check_status": self.policy_fact_check_status,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def compute_official_corpus_hash(official_path: Path) -> tuple[str, int, list[str]]:
    """Hash official markdown files (names + content) for rebuild metadata."""
    if not official_path.is_dir():
        return "", 0, []
    digest = hashlib.sha256()
    doc_names: list[str] = []
    for path in sorted(official_path.glob("*.md")):
        doc_names.append(path.name)
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16], len(doc_names), doc_names


def assert_rebuild_summary_safe(summary: dict[str, Any]) -> None:
    """Reports must not include raw private document bodies."""
    text = json.dumps(summary, ensure_ascii=False)
    assert_safe_knowledge_output(text)
    forbidden = ("conversation_transcript", "gold_reference_reply", "user_input")
    for token in forbidden:
        if token in text.lower():
            raise RuntimeError(f"rebuild summary contains forbidden token: {token}")


def render_rebuild_report_markdown(summary: dict[str, Any], *, doc_names: list[str]) -> str:
    lines = [
        "# Knowledge OpenAI rebuild report",
        "",
        f"_Generated (UTC): {summary.get('generated_at_utc', '—')}_",
        "",
        f"**Status:** {summary.get('status')}",
        "",
        "## Index metadata",
        "",
        f"- **embedding_provider:** {summary.get('embedding_provider')}",
        f"- **embedding_model:** {summary.get('embedding_model')}",
        f"- **index_profile:** {summary.get('index_profile')}",
        f"- **namespace:** {summary.get('namespace')}",
        f"- **index_version:** {summary.get('index_version')}",
        f"- **corpus_source:** {summary.get('corpus_source')}",
        f"- **corpus_doc_count:** {summary.get('corpus_doc_count')}",
        f"- **corpus_source_hash:** {summary.get('corpus_source_hash')}",
        f"- **chunk_count:** {summary.get('chunk_count')}",
        f"- **indexed_count:** {summary.get('indexed_count')}",
        "",
        "## Official document files (names only)",
        "",
    ]
    for name in doc_names:
        lines.append(f"- `{name}`")
    lines.extend(
        [
            "",
            "## Downstream checks",
            "",
            f"- **retrieval_smoke_status:** {summary.get('retrieval_smoke_status')}",
            f"- **policy_fact_check_status:** {summary.get('policy_fact_check_status')}",
            "",
        ],
    )
    if summary.get("warnings"):
        lines.append("## Warnings")
        lines.append("")
        for warning in summary["warnings"]:
            lines.append(f"- `{warning}`")
        lines.append("")
    if summary.get("errors"):
        lines.append("## Errors")
        lines.append("")
        for error in summary["errors"]:
            lines.append(f"- `{error}`")
        lines.append("")
    lines.append("_Sandbox/dev index only — no production mutation._")
    lines.append("")
    return "\n".join(lines)


def write_rebuild_reports(
    summary: dict[str, Any],
    *,
    doc_names: list[str],
    summary_json: Path = DEFAULT_REBUILD_SUMMARY_JSON,
    report_md: Path = DEFAULT_REBUILD_REPORT_MD,
) -> None:
    assert_rebuild_summary_safe(summary)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown = render_rebuild_report_markdown(summary, doc_names=doc_names)
    assert_safe_knowledge_output(markdown)
    report_md.write_text(markdown, encoding="utf-8")


def run_knowledge_openai_rebuild(
    *,
    official_path: Path = DEFAULT_OFFICIAL_PATH,
    historical_summary_path: Path = DEFAULT_HISTORICAL_SUMMARY,
    chunks_jsonl: Path = DEFAULT_CHUNKS_JSONL,
    namespace: str = DEFAULT_NAMESPACE,
    index_version: str = DEFAULT_INDEX_VERSION,
    database_url: str,
    table_name: str = "rag_vector_records",
    confirm_real_openai: bool = False,
    confirm_sandbox: bool = False,
    overwrite: bool = False,
    skip_smoke: bool = False,
    skip_policy_check: bool = False,
    dry_run: bool = False,
) -> KnowledgeOpenaiRebuildResult:
    """Rebuild chunks, embed with OpenAI, re-index sandbox pgvector, run smoke checks."""
    warnings: list[str] = []
    errors: list[str] = []

    if not confirm_real_openai:
        raise ValueError("confirm_real_openai=True is required for OpenAI knowledge rebuild")
    if not confirm_sandbox:
        raise ValueError("confirm_sandbox=True is required for sandbox pgvector writes")

    for path in (DEFAULT_REBUILD_SUMMARY_JSON, DEFAULT_REBUILD_REPORT_MD):
        if path.exists() and not overwrite:
            raise FileExistsError(f"output exists: {path} (use --overwrite)")

    corpus_hash, doc_count, doc_names = compute_official_corpus_hash(official_path)
    if doc_count == 0:
        warnings.append("official_corpus_empty_or_missing")

    integrity = default_vendor_ticket_corpus_integrity()
    if not integrity.passed:
        warnings.append(f"vendor_corpus_integrity_issues:{integrity.issue_count}")

    chunks, skipped_unsafe = build_combined_knowledge_chunks(
        official_path=official_path,
        historical_summary_path=historical_summary_path,
    )
    if not chunks:
        raise ValueError("no knowledge chunks produced; check official/historical inputs")

    chunk_summary = summarize_knowledge_chunks(
        chunks,
        skipped_unsafe=skipped_unsafe,
        official_path=str(official_path),
        historical_summary_path=str(historical_summary_path),
    )
    write_chunks_jsonl(chunks, chunks_jsonl)

    loaded = load_knowledge_chunks(chunks_jsonl)
    batch = generate_knowledge_embeddings(
        loaded,
        provider="openai",
        model=DEFAULT_OPENAI_MODEL,
        dimensions=DEFAULT_DIMENSIONS,
        confirm_real_openai=True,
    )
    records = build_knowledge_vector_records(
        batch,
        namespace=namespace,
        index_version=index_version,
    )
    by_lane = Counter(c.chunk.source_lane.value for c in loaded)

    indexed = 0
    if not dry_run:
        deleted = delete_knowledge_sandbox_index(
            namespace=namespace,
            index_version=index_version,
            database_url=database_url,
            table_name=table_name,
        )
        if deleted:
            warnings.append(f"deleted_prior_records:{deleted}")
        indexed = index_knowledge_chunks_pgvector(
            records,
            database_url=database_url,
            table_name=table_name,
            dimensions=DEFAULT_DIMENSIONS,
        )

    indexing_summary = summarize_knowledge_indexing(
        indexed_count=indexed,
        namespace=namespace,
        index_version=index_version,
        provider=batch.provider,
        model=batch.model,
        dimensions=batch.dimensions,
        chunk_count=len(loaded),
        skipped_unsafe=skipped_unsafe,
        chunks_by_source_lane=dict(by_lane),
    )
    indexing_summary["corpus_source"] = str(official_path)
    indexing_summary["corpus_doc_count"] = doc_count
    indexing_summary["corpus_source_hash"] = corpus_hash
    indexing_summary["index_profile"] = INDEX_PROFILE
    indexing_summary["document_names"] = doc_names
    indexing_summary["chunks_by_document_type"] = chunk_summary.get("chunks_by_document_type", {})
    indexing_summary["dry_run"] = dry_run

    smoke_status = "skipped"
    policy_status = "skipped"
    if not dry_run and not skip_smoke:
        smoke = run_knowledge_retrieval_smoke(
            namespace=namespace,
            index_version=index_version,
            database_url=database_url,
            table_name=table_name,
            provider="openai",
            confirm_real_openai=True,
        )
        write_knowledge_retrieval_smoke_reports(smoke, overwrite=overwrite)
        smoke_status = smoke.status
        if smoke.status != "passed":
            errors.append("retrieval_smoke_failed")
    if not dry_run and not skip_policy_check and smoke_status != "failed":
        policy = run_policy_fact_extraction_check(
            namespace=namespace,
            index_version=index_version,
            database_url=database_url,
            table_name=table_name,
            provider="openai",
            confirm_real_openai=True,
        )
        write_policy_fact_extraction_check_reports(policy, overwrite=overwrite)
        policy_status = policy.status
        if policy.status != "passed":
            errors.append("policy_fact_extraction_check_failed")

    status = "passed" if not errors else "failed"
    result = KnowledgeOpenaiRebuildResult(
        status=status,
        chunk_count=len(loaded),
        indexed_count=indexed,
        corpus_doc_count=doc_count,
        corpus_source_hash=corpus_hash,
        namespace=namespace,
        index_version=index_version,
        retrieval_smoke_status=smoke_status,
        policy_fact_check_status=policy_status,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    summary = {**indexing_summary, **result.to_json_dict()}
    write_rebuild_reports(summary, doc_names=doc_names)
    return result

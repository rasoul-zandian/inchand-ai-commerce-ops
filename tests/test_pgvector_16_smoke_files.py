"""Filesystem checks for 16-D pgvector local smoke (no Docker, no live Postgres)."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION_16 = _REPO_ROOT / "db" / "migrations" / "0002_create_rag_vector_records_16.sql"
_INIT_SCRIPT_16 = _REPO_ROOT / "scripts" / "db_init_pgvector_16.sh"
_SMOKE_SCRIPT = _REPO_ROOT / "scripts" / "smoke_pgvector_16.py"
_MAKEFILE = _REPO_ROOT / "Makefile"
_README = _REPO_ROOT / "README.md"
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"


def test_migration_0002_exists_with_16d_table() -> None:
    sql = _MIGRATION_16.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE TABLE IF NOT EXISTS rag_vector_records_16" in sql
    assert "VECTOR(16)" in sql
    assert "idx_rag_vector_records_16_document_id" in sql
    assert "idx_rag_vector_records_16_source_type" in sql
    assert "local smoke" in sql.lower() or "Local dev smoke" in sql
    assert "mock" in sql.lower()


def test_db_init_16_script_does_not_print_database_url() -> None:
    text = _INIT_SCRIPT_16.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "0002_create_rag_vector_records_16.sql" in text
    assert 'echo "$_database_url"' not in text
    assert 'echo "$DATABASE_URL"' not in text


def test_smoke_script_uses_16d_table_and_dimensions() -> None:
    text = _SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "rag_vector_records_16" in text
    assert "dimensions=16" in text or "_DIMENSIONS = 16" in text
    assert "semantic_retrieve" in text
    assert "PgVectorStore" in text
    assert "mock-embedding-small" in text
    for line in text.splitlines():
        if line.strip().startswith("print("):
            assert "postgresql://" not in line
            assert "inchand_dev_password" not in line


def test_makefile_has_pg_smoke_16_targets() -> None:
    makefile = _MAKEFILE.read_text(encoding="utf-8")
    assert "pg-init-16:" in makefile
    assert "pg-index-16-dry-run:" in makefile
    assert "pg-index-16:" in makefile
    assert "pg-smoke-16:" in makefile
    assert "rag_vector_records_16" in makefile
    assert "PGVECTOR_DIMENSIONS=16" in makefile


def test_readme_documents_pgvector_16d_local_smoke() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "## PgVector 16-D Local Smoke" in readme
    assert "rag_vector_records_16" in readme
    assert "make pg-smoke-16" in readme
    assert "runtime retrieval" in readme.lower() or "retrieve_context" in readme


def test_readme_no_stale_pgvector_not_wired_claims() -> None:
    readme = _README.read_text(encoding="utf-8")
    stale = [
        "not wired into runtime retrieval",
        "not implemented yet",
        "Planned integrations (not wired",
        "remain future work",
    ]
    for phrase in stale:
        assert phrase not in readme, f"stale doc phrase still in README: {phrase!r}"
    assert "semantic_pgvector_16" in readme
    assert "opt-in" in readme.lower()


def test_readme_documents_pgvector_retrieval_eval_run() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "## PgVector Retrieval Evaluation Run" in readme
    assert "make pg-eval" in readme
    assert "eval_cases.json" in readme
    assert "pass_rate" in readme


def test_readme_documents_retrieval_backend_comparison() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "## Retrieval Backend Baseline Comparison" in readme
    assert "make pg-compare" in readme
    assert "cases_with_different_results" in readme
    assert "in_memory" in readme or "in-memory" in readme


def test_readme_documents_1536_pgvector_staging_profile() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "## 1536-D PgVector Staging Profile" in readme
    assert "semantic_pgvector" in readme
    assert "rag_vector_records" in readme
    assert "text-embedding-3-small" in readme
    assert "make pg-index" in readme
    assert "retrieval_summary.rag_profile" in readme


def test_readme_documents_pgvector_retrieval_profile_smoke() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "## PgVector Retrieval Profile Smoke Test" in readme
    assert "semantic_pgvector_16" in readme
    assert "retrieval_summary.vector_store_provider" in readme
    assert "make pg-index-16" in readme
    assert "make smoke-semantic" in readme
    assert "rag_vector_records_16" in readme
    assert "awaiting_approval" in readme


def test_readme_documents_staging_retrieval_evaluation_runbook() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "## Staging Retrieval Evaluation Runbook" in readme
    assert "make config-check" in readme
    assert "make pg-eval" in readme
    assert "make pg-compare" in readme
    assert "pass_rate_delta" in readme
    assert "mean_mrr_delta" in readme
    assert "cases_with_different_results" in readme
    assert "quality gates" in readme.lower()
    assert "not part of **`make ci`**" in readme or "not part of `make ci`" in readme


def test_readme_documents_strict_staging_retrieval_quality_profile() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "## Strict Staging Retrieval Quality Profile" in readme
    assert "RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS" in readme
    assert "RETRIEVAL_REQUIRE_MATCHING_CASE_RESULTS" in readme
    assert "make pg-compare" in readme
    assert "RETRIEVAL_MAX_MEAN_RECALL_AT_K_REGRESSION" in readme


def test_env_example_documents_strict_staging_retrieval_block() -> None:
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "Strict staging retrieval quality profile" in text
    assert "RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS" in text
    assert "RETRIEVAL_REQUIRE_MATCHING_CASE_RESULTS" in text
    assert "RETRIEVAL_MIN_MEAN_MRR=0.8" in text


def test_adr_pgvector_status_not_proposed_only() -> None:
    adr_path = _REPO_ROOT / "docs" / "adr" / "0001-pgvector-store-design.md"
    adr = adr_path.read_text(encoding="utf-8")
    assert "Partially implemented" in adr
    assert "runtime wiring exist yet" not in adr

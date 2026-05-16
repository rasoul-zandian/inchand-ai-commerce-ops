"""Filesystem checks for pgvector migration stub (no Docker, no live Postgres)."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = _REPO_ROOT / "db" / "migrations" / "0001_create_rag_vector_records.sql"
_INIT_SCRIPT = _REPO_ROOT / "scripts" / "db_init_pgvector.sh"
_COMPOSE = _REPO_ROOT / "docker-compose.yml"


def test_migration_file_exists_and_defines_table() -> None:
    sql = _MIGRATION.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE TABLE IF NOT EXISTS rag_vector_records" in sql
    assert "VECTOR(1536)" in sql
    assert "metadata JSONB NOT NULL DEFAULT '{}'::jsonb" in sql
    assert "idx_rag_vector_records_document_id" in sql
    assert "idx_rag_vector_records_source_type" in sql
    assert "USING hnsw" not in sql.lower()
    assert "USING ivfflat" not in sql.lower()


def test_db_init_script_does_not_print_database_url() -> None:
    text = _INIT_SCRIPT.read_text(encoding="utf-8")
    assert "DATABASE_URL" in text
    assert "echo" in text
    assert 'echo "$_database_url"' not in text
    assert 'echo "$DATABASE_URL"' not in text


def test_docker_compose_uses_pgvector_image() -> None:
    compose = _COMPOSE.read_text(encoding="utf-8")
    assert "pgvector/pgvector:pg16" in compose
    assert "inchand_pgvector" in compose
    assert "Local development only" in compose

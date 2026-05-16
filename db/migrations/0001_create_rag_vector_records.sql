-- Migration 0001: rag_vector_records (MVP)
-- Matches ADR 0001 (docs/adr/0001-pgvector-store-design.md).
--
-- Fixed VECTOR(1536) for MVP (e.g. text-embedding-3-small).
-- Changing embedding model/dimension requires a new table or full reindex migration;
-- do not ALTER vector width in place.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_vector_records (
    record_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector VECTOR(1536) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_vector_records_document_id
    ON rag_vector_records (document_id);

CREATE INDEX IF NOT EXISTS idx_rag_vector_records_source_type
    ON rag_vector_records (source_type);

-- No HNSW/IVFFlat index in this migration (exact search / small corpus MVP).
-- No triggers; updated_at maintenance is application responsibility for now.

-- Migration 0002: rag_vector_records_16 (local smoke only)
--
-- Separate table for mock 16-D embeddings end-to-end smoke (corpus → PgVectorStore → search).
-- NOT the production schema; production-like indexing uses rag_vector_records VECTOR(1536).
-- Do not use this table for OpenAI / 1536-D production embeddings.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_vector_records_16 (
    record_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector VECTOR(16) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE rag_vector_records_16 IS
    'Local dev smoke only: mock 16-D embeddings. Not production schema.';

CREATE INDEX IF NOT EXISTS idx_rag_vector_records_16_document_id
    ON rag_vector_records_16 (document_id);

CREATE INDEX IF NOT EXISTS idx_rag_vector_records_16_source_type
    ON rag_vector_records_16 (source_type);

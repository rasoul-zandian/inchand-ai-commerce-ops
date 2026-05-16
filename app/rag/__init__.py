"""RAG package surface (types, retriever, ingestion, vector store; no external DB)."""

from app.rag.bootstrap import (
    build_default_vendor_ticket_vector_store,
    default_vendor_ticket_documents,
    retrieve_semantic_vendor_ticket_context,
)
from app.rag.config import RetrievalConfig, build_retrieval_config_from_settings
from app.rag.consistency import (
    CorpusEvalConsistencyIssue,
    CorpusEvalConsistencyReport,
    assert_corpus_eval_consistency,
    check_corpus_eval_consistency,
    check_default_vendor_ticket_corpus_eval_consistency,
)
from app.rag.corpus_integrity import (
    CorpusFileHash,
    CorpusHashLockfile,
    CorpusIntegrityReport,
    collect_corpus_files,
    default_vendor_ticket_corpus_integrity,
    default_vendor_ticket_corpus_lockfile_path,
    load_corpus_lockfile,
    sha256_file,
    verify_corpus_against_lockfile,
    verify_corpus_integrity,
    verify_default_vendor_ticket_corpus_lockfile,
    write_corpus_lockfile,
)
from app.rag.corpus_manifest import (
    CorpusManifest,
    CorpusManifestDocument,
    load_corpus_manifest,
    load_manifest_documents,
)
from app.rag.evaluation import (
    RetrievalEvalCase,
    RetrievalEvalCaseFile,
    RetrievalEvalReport,
    RetrievalEvalResult,
    default_vendor_ticket_eval_cases,
    evaluate_retrieval_case,
    evaluate_retrieval_cases,
    load_retrieval_eval_cases,
    load_vendor_ticket_eval_cases_from_file,
    run_default_vendor_ticket_retrieval_eval,
)
from app.rag.ingestion import (
    chunk_text,
    evaluation_example_to_rag_document,
    rag_document_to_chunks,
    ticket_record_to_rag_document,
)
from app.rag.pgvector_store import PgVectorStore
from app.rag.retriever import retrieve_documents
from app.rag.semantic_retriever import (
    build_in_memory_store_from_documents,
    semantic_retrieve,
)
from app.rag.strategy import RetrievalStrategyName, retrieve_for_workflow
from app.rag.types import RAGDocument, RAGQuery, RAGResult
from app.rag.vector_records import (
    VectorRecord,
    rag_document_to_vector_record,
    rag_documents_to_vector_records,
)
from app.rag.vector_store import (
    InMemoryVectorStore,
    VectorSearchResult,
    VectorStore,
    cosine_similarity,
    vector_record_to_rag_document,
)
from app.rag.vector_store_factory import (
    VectorStoreConfig,
    VectorStoreProviderName,
    build_vector_store_config_from_settings,
    create_vector_store,
)

__all__ = [
    "RAGDocument",
    "RAGQuery",
    "RAGResult",
    "CorpusManifest",
    "CorpusManifestDocument",
    "CorpusEvalConsistencyIssue",
    "CorpusEvalConsistencyReport",
    "CorpusFileHash",
    "CorpusHashLockfile",
    "CorpusIntegrityReport",
    "RetrievalEvalCase",
    "RetrievalEvalCaseFile",
    "RetrievalEvalReport",
    "RetrievalEvalResult",
    "RetrievalConfig",
    "RetrievalStrategyName",
    "build_retrieval_config_from_settings",
    "build_default_vendor_ticket_vector_store",
    "build_in_memory_store_from_documents",
    "assert_corpus_eval_consistency",
    "check_corpus_eval_consistency",
    "check_default_vendor_ticket_corpus_eval_consistency",
    "collect_corpus_files",
    "default_vendor_ticket_corpus_integrity",
    "default_vendor_ticket_corpus_lockfile_path",
    "default_vendor_ticket_documents",
    "default_vendor_ticket_eval_cases",
    "VectorRecord",
    "VectorSearchResult",
    "VectorStore",
    "InMemoryVectorStore",
    "PgVectorStore",
    "VectorStoreConfig",
    "VectorStoreProviderName",
    "build_vector_store_config_from_settings",
    "create_vector_store",
    "chunk_text",
    "cosine_similarity",
    "evaluation_example_to_rag_document",
    "evaluate_retrieval_case",
    "evaluate_retrieval_cases",
    "load_corpus_manifest",
    "load_manifest_documents",
    "load_corpus_lockfile",
    "load_retrieval_eval_cases",
    "load_vendor_ticket_eval_cases_from_file",
    "rag_document_to_chunks",
    "rag_document_to_vector_record",
    "rag_documents_to_vector_records",
    "retrieve_documents",
    "retrieve_for_workflow",
    "retrieve_semantic_vendor_ticket_context",
    "run_default_vendor_ticket_retrieval_eval",
    "semantic_retrieve",
    "sha256_file",
    "ticket_record_to_rag_document",
    "verify_corpus_against_lockfile",
    "verify_corpus_integrity",
    "verify_default_vendor_ticket_corpus_lockfile",
    "write_corpus_lockfile",
    "vector_record_to_rag_document",
]

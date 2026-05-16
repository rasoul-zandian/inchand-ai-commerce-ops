"""Bootstrap default vendor-ticket corpus into an in-memory vector store (no globals, no DB)."""

from __future__ import annotations

from pathlib import Path

from app.rag.corpus_manifest import load_corpus_manifest, load_manifest_documents
from app.rag.strategy import RetrievalStrategyName, retrieve_for_workflow
from app.rag.types import RAGDocument, RAGResult
from app.rag.vector_records import rag_documents_to_vector_records
from app.rag.vector_store import InMemoryVectorStore

_VENDOR_TICKET_CORPUS_ROOT = Path(__file__).resolve().parents[2] / "corpus" / "vendor_ticket"
_DEFAULT_MANIFEST_PATH = _VENDOR_TICKET_CORPUS_ROOT / "manifest.json"


def default_vendor_ticket_documents() -> list[RAGDocument]:
    """Deterministic offline corpus for vendor-ticket semantic demos (Persian, mock-friendly).

    Documents are loaded from ``corpus/vendor_ticket/manifest.json`` and sibling UTF-8 text files.
    """
    manifest = load_corpus_manifest(_DEFAULT_MANIFEST_PATH)
    return load_manifest_documents(manifest, base_dir=_VENDOR_TICKET_CORPUS_ROOT)


def build_default_vendor_ticket_vector_store(
    *,
    embedding_provider: str = "mock",
    embedding_model: str = "mock-embedding-small",
) -> InMemoryVectorStore:
    """Build a fresh in-memory index from the default vendor-ticket corpus."""
    store = InMemoryVectorStore()
    docs = default_vendor_ticket_documents()
    records = rag_documents_to_vector_records(
        docs,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
    )
    if records:
        store.upsert(records)
    return store


def retrieve_semantic_vendor_ticket_context(
    query: str,
    *,
    top_k: int = 5,
    embedding_provider: str = "mock",
    embedding_model: str = "mock-embedding-small",
) -> RAGResult:
    """Demo helper: new default store each call, then semantic retrieval."""
    store = build_default_vendor_ticket_vector_store(
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
    )
    return retrieve_for_workflow(
        query,
        workflow_type="vendor_ticket",
        strategy=RetrievalStrategyName.SEMANTIC,
        top_k=top_k,
        vector_store=store,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
    )

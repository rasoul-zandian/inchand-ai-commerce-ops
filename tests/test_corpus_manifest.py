"""Tests for corpus manifest loading (filesystem, UTF-8, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.rag.bootstrap import default_vendor_ticket_documents
from app.rag.corpus_manifest import (
    CorpusManifest,
    CorpusManifestDocument,
    load_corpus_manifest,
    load_manifest_documents,
)
from pydantic import ValidationError


def _project_vendor_ticket_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "corpus" / "vendor_ticket"


def test_load_vendor_ticket_manifest_parses() -> None:
    manifest = load_corpus_manifest(_project_vendor_ticket_dir() / "manifest.json")
    assert manifest.manifest_version == "1"
    assert manifest.workflow_type == "vendor_ticket"
    assert manifest.locale == "fa-IR"
    assert len(manifest.documents) == 5


def test_load_manifest_documents_order_and_content() -> None:
    root = _project_vendor_ticket_dir()
    manifest = load_corpus_manifest(root / "manifest.json")
    docs = load_manifest_documents(manifest, base_dir=root)
    assert [d.document_id for d in docs] == [e.document_id for e in manifest.documents]
    assert docs[0].source_type == "policy"
    assert "تسویه" in docs[0].content or "فاکتور" in docs[0].content


def test_workflow_type_and_locale_propagated_to_metadata() -> None:
    root = _project_vendor_ticket_dir()
    manifest = load_corpus_manifest(root / "manifest.json")
    docs = load_manifest_documents(manifest, base_dir=root)
    for doc in docs:
        assert doc.metadata["workflow_type"] == "vendor_ticket"
        assert doc.metadata["locale"] == "fa-IR"
    approved = next(d for d in docs if d.document_id.endswith("003"))
    assert approved.metadata.get("intent") == "billing_discrepancy"


def test_per_document_metadata_preserved() -> None:
    root = _project_vendor_ticket_dir()
    manifest = load_corpus_manifest(root / "manifest.json")
    docs = load_manifest_documents(manifest, base_dir=root)
    seller = next(d for d in docs if d.document_id.endswith("001"))
    assert seller.metadata.get("domain") == "seller_support"


def test_malformed_json_raises_value_error(tmp_path: Path) -> None:
    bad = tmp_path / "manifest.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="valid JSON"):
        load_corpus_manifest(bad)


def test_invalid_schema_raises_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "manifest.json"
    bad.write_text(json.dumps({"manifest_version": 1}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_corpus_manifest(bad)


def test_missing_body_file_raises_file_not_found(tmp_path: Path) -> None:
    manifest = CorpusManifest(
        manifest_version="1",
        workflow_type="vendor_ticket",
        locale="fa-IR",
        documents=[
            CorpusManifestDocument(
                document_id="x",
                source_type="policy",
                path="policies/nope.txt",
                title="t",
                metadata={},
            )
        ],
    )
    with pytest.raises(FileNotFoundError, match="nope"):
        load_manifest_documents(manifest, base_dir=tmp_path)


def test_manifest_path_with_parent_segments_rejected() -> None:
    with pytest.raises(ValidationError):
        CorpusManifestDocument(
            document_id="bad",
            source_type="policy",
            path="policies/../../../etc/passwd",
            title="t",
            metadata={},
        )


def test_manifest_document_rejects_absolute_path() -> None:
    with pytest.raises(ValidationError):
        CorpusManifestDocument(
            document_id="a",
            source_type="policy",
            path="/etc/passwd",
            title="t",
            metadata={},
        )


def test_default_vendor_ticket_documents_integration() -> None:
    docs = default_vendor_ticket_documents()
    assert len(docs) == 5
    assert {d.source_type for d in docs} == {"policy", "approved_pattern", "style_guide"}

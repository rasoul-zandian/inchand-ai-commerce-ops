"""Filesystem checks for retrieval evaluation snapshots (no secrets, no network)."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SNAPSHOTS_DIR = _REPO_ROOT / "docs" / "retrieval_snapshots"
_GOLDEN_MD = _SNAPSHOTS_DIR / "golden_snapshot_1536_openai_pgvector.md"
_GOLDEN_JSON = _SNAPSHOTS_DIR / "golden_snapshot_1536_openai_pgvector.json"
_README = _REPO_ROOT / "README.md"


def test_golden_snapshot_files_exist() -> None:
    assert _GOLDEN_MD.is_file()
    assert _GOLDEN_JSON.is_file()
    assert (_SNAPSHOTS_DIR / "README.md").is_file()


def test_golden_snapshot_markdown_has_required_sections() -> None:
    text = _GOLDEN_MD.read_text(encoding="utf-8")
    assert "Golden Retrieval Evaluation Snapshot" in text
    assert "## A. Snapshot identity" in text
    assert "## B. Evaluation results" in text
    assert "## C. API smoke confirmation" in text
    assert "semantic_pgvector" in text
    assert "cases_with_different_results" in text
    assert "near_miss_violation_count" in text
    assert "OPENAI_API_KEY" not in text
    assert "postgresql://" not in text


def test_golden_snapshot_json_structure_and_no_secrets() -> None:
    data = json.loads(_GOLDEN_JSON.read_text(encoding="utf-8"))
    assert data["snapshot_id"] == "golden-1536-openai-pgvector-v1"
    assert data["identity"]["rag_profile"] == "semantic_pgvector"
    assert data["pg_compare"]["cases_with_different_results"] == 0
    assert data["pg_eval"]["near_miss_violation_count"] == 0
    assert data["api_smoke"]["mock_retrieval_fallback"] is False
    raw = _GOLDEN_JSON.read_text(encoding="utf-8")
    assert "sk-" not in raw
    assert "postgresql://" not in raw
    assert "inchand_dev_password" not in raw


def test_readme_links_retrieval_snapshots() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "## Retrieval evaluation snapshots" in readme
    assert "docs/retrieval_snapshots/" in readme
    assert "golden_snapshot_1536_openai_pgvector" in readme

"""Tests for operational knowledge foundation (Step 162; inventory only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.knowledge.historical_ticket_memory import (
    build_historical_ticket_memory_inventory,
    load_historical_reply_benchmark_summary,
)
from app.knowledge.knowledge_loader import (
    build_knowledge_inventory,
    knowledge_document_to_dict,
    parse_knowledge_document,
    validate_knowledge_document,
)


def _valid_official_md(
    *,
    doc_id: str = "test_rules_v1",
    title: str = "Test Rules",
    doc_type: str = "settlement_rules",
) -> str:
    return f"""---
doc_id: {doc_id}
title: {title}
document_type: {doc_type}
visibility: private_internal
source_lane: official_policy
owner: operations
language: fa
version: 1
last_reviewed_at: 2026-05-20
---

# Section one

Body text for testing. No business rules.

## Subsection

More placeholder content.
"""


def test_parse_valid_official_markdown_metadata(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(_valid_official_md(), encoding="utf-8")
    doc, body = parse_knowledge_document(path)
    validate_knowledge_document(doc, body)
    assert doc.doc_id == "test_rules_v1"
    assert doc.title == "Test Rules"
    assert doc.section_count >= 1
    assert doc.char_count > 0


def test_reject_missing_frontmatter_key(tmp_path: Path) -> None:
    text = _valid_official_md().replace("owner: operations\n", "")
    path = tmp_path / "bad.md"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="missing required frontmatter"):
        parse_knowledge_document(path)


def test_reject_secret_like_token(tmp_path: Path) -> None:
    path = tmp_path / "sec.md"
    path.write_text(
        _valid_official_md() + "\n\nDo not paste secrets like sk-test123here in docs.\n",
        encoding="utf-8",
    )
    doc, body = parse_knowledge_document(path)
    with pytest.raises(ValueError, match="secret"):
        validate_knowledge_document(doc, body)


def test_reject_customer_data_marker(tmp_path: Path) -> None:
    path = tmp_path / "leak.md"
    path.write_text(
        _valid_official_md() + '\n\nBad: "messages": [ should not appear.\n',
        encoding="utf-8",
    )
    doc, body = parse_knowledge_document(path)
    with pytest.raises(ValueError, match="customer-data"):
        validate_knowledge_document(doc, body)


def test_reject_pii_phone_pattern(tmp_path: Path) -> None:
    path = tmp_path / "pii.md"
    path.write_text(
        _valid_official_md() + "\n\nCall 09121234567 for help.\n",
        encoding="utf-8",
    )
    doc, body = parse_knowledge_document(path)
    with pytest.raises(ValueError, match="PII"):
        validate_knowledge_document(doc, body)


def test_reject_wrong_source_lane(tmp_path: Path) -> None:
    text = _valid_official_md().replace(
        "source_lane: official_policy",
        "source_lane: historical_memory",
    )
    path = tmp_path / "lane.md"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="official_policy"):
        parse_knowledge_document(path)


def test_reject_historical_document_type_in_markdown(tmp_path: Path) -> None:
    text = _valid_official_md().replace(
        "document_type: settlement_rules",
        "document_type: historical_ticket_memory",
    )
    path = tmp_path / "hist.md"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="official policy type"):
        parse_knowledge_document(path)


def test_inventory_counts_official_docs(tmp_path: Path) -> None:
    d = tmp_path / "ops"
    d.mkdir()
    (d / "a.md").write_text(_valid_official_md(doc_id="a_v1", title="A"), encoding="utf-8")
    (d / "b.md").write_text(
        _valid_official_md(
            doc_id="b_v1",
            title="B",
            doc_type="support_faq",
        ),
        encoding="utf-8",
    )
    inv = build_knowledge_inventory(d)
    assert len(inv.documents) == 2
    assert not inv.warnings


def test_historical_summary_inventory_aggregate_only(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "total_cases": 42,
                "cases_by_label": {"support": 40, "fund": 2},
                "cases_by_responder_role": {"support_agent": 42},
                "skipped_unsafe": 3,
                "skipped_no_support_reply": 1,
                "tickets_processed": 10,
                "generated_at_utc": "2026-05-20T00:00:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    raw = load_historical_reply_benchmark_summary(summary_path)
    assert raw is not None
    inv = build_historical_ticket_memory_inventory(
        raw,
        source_summary_path=str(summary_path),
    )
    assert inv.total_cases == 42
    assert inv.cases_by_label["support"] == 40
    assert inv.skipped_unsafe == 3
    dumped = json.dumps(inv.to_json_dict(), ensure_ascii=False)
    assert "gold_reference_reply" not in dumped


def test_inventory_json_has_no_gold_or_ticket_bodies(tmp_path: Path) -> None:
    """Simulate CLI payload shape: no benchmark case text in output."""
    official_dir = tmp_path / "ops"
    official_dir.mkdir()
    (official_dir / "one.md").write_text(_valid_official_md(), encoding="utf-8")
    official_inv = build_knowledge_inventory(official_dir)
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps({"total_cases": 5, "cases_by_label": {"support": 5}}),
        encoding="utf-8",
    )
    hist = build_historical_ticket_memory_inventory(
        load_historical_reply_benchmark_summary(summary_path),
        source_summary_path=str(summary_path),
    )

    payload = {
        "lanes": {
            "official_policy": {
                "documents": [knowledge_document_to_dict(official_inv.documents[0])],
            },
            "historical_memory": hist.to_json_dict(),
        },
    }
    s = json.dumps(payload, ensure_ascii=False)
    assert "gold_reference_reply" not in s
    assert "snapshot_before_reply" not in s

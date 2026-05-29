"""Tests for knowledge OpenAI rebuild, retrieval smoke, policy check, and live API pagination."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.knowledge.knowledge_models import KnowledgeDocumentType
from app.knowledge.knowledge_openai_rebuild import (
    assert_rebuild_summary_safe,
    compute_official_corpus_hash,
    run_knowledge_openai_rebuild,
)
from app.knowledge.knowledge_retrieval_smoke import (
    SETTLEMENT_BANK_QUERY,
    evaluate_settlement_bank_smoke,
    evaluate_settlement_smoke,
    run_knowledge_retrieval_smoke,
)
from app.knowledge.policy_fact_extraction_check import (
    retrieval_hits_to_hints,
    run_policy_fact_extraction_check,
)
from app.live_shadow.live_rooms_api_client import extract_rooms_from_payload, fetch_live_rooms


def _settlement_hits() -> list[dict[str, object]]:
    text = (
        "مبلغ فروش در کیف پول فروشنده بلاک می‌شود. "
        "۳ روز بعد از نهایی شدن سفارش قابل تسویه است. "
        "در اولین بازه تسویه واریز می‌شود."
    )
    return [
        {
            "document_type": KnowledgeDocumentType.SETTLEMENT_RULES.value,
            "section_title": "زمان تسویه",
            "source_lane": "official_policy",
            "priority_rank": 10,
            "text_snippet": text,
            "score": 0.9,
        },
    ]


def _settlement_bank_hits() -> list[dict[str, object]]:
    text = (
        "به دلیل محدودیت‌های اعمال‌شده از سوی بانک مرکزی، از ابتدای بهمن "
        "تمامی تسویه‌حساب‌ها صرفاً از طریق حساب‌های بانک سامان انجام می‌شود."
    )
    return [
        {
            "document_type": KnowledgeDocumentType.SETTLEMENT_RULES.value,
            "section_title": "بانک تسویه",
            "source_lane": "official_policy",
            "priority_rank": 10,
            "text_snippet": text,
            "score": 0.9,
        },
    ]


def test_rebuild_requires_confirm_real_openai() -> None:
    with pytest.raises(ValueError, match="confirm_real_openai"):
        run_knowledge_openai_rebuild(
            database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
            confirm_real_openai=False,
            confirm_sandbox=True,
        )


def test_rebuild_summary_excludes_raw_docs(tmp_path: Path) -> None:
    official = tmp_path / "ops"
    official.mkdir()
    (official / "settlement_rules.md").write_text(
        "---\ndoc_id: s1\ntitle: t\ndocument_type: settlement_rules\n"
        "visibility: private_internal\nsource_lane: official_policy\n"
        "owner: ops\nlanguage: fa\nversion: 1\nlast_reviewed_at: 2026-05-20\n---\n\n"
        "# بخش\n\nمتن تسویه کیف پول بلاک ۳ روز نهایی اولین بازه.\n",
        encoding="utf-8",
    )
    summary = {
        "status": "passed",
        "corpus_doc_count": 1,
        "document_names": ["settlement_rules.md"],
        "chunk_count": 2,
    }
    assert_rebuild_summary_safe(summary)
    digest, count, names = compute_official_corpus_hash(official)
    assert count == 1
    assert names == ["settlement_rules.md"]
    assert digest


def test_settlement_retrieval_smoke_success() -> None:
    case = evaluate_settlement_smoke(_settlement_hits())
    assert case.passed
    assert case.name == "settlement_timing"


def test_settlement_bank_retrieval_smoke_success() -> None:
    case = evaluate_settlement_bank_smoke(_settlement_bank_hits())
    assert case.passed
    assert case.name == "settlement_bank"
    assert case.query == SETTLEMENT_BANK_QUERY


def test_settlement_smoke_failure_when_missing_rules() -> None:
    case = evaluate_settlement_smoke(
        [{"document_type": "support_faq", "text_snippet": "other", "section_title": "x"}],
    )
    assert not case.passed


def test_run_retrieval_smoke_mock_passes() -> None:
    def query_fn(query: str, **kwargs: object) -> list[dict[str, object]]:
        if "کدام بانک" in query or "شماره حساب یا شبا" in query:
            return _settlement_bank_hits()
        if "تسویه" in query:
            return _settlement_hits()
        if "مرجوع" in query:
            return [
                {
                    "document_type": KnowledgeDocumentType.REFUND_RETURN_RULES.value,
                    "section_title": "مرجوعی",
                    "text_snippet": "قوانین مرجوعی",
                    "priority_rank": 10,
                },
            ]
        return [
            {
                "document_type": KnowledgeDocumentType.PRODUCT_PUBLISHING_RULES.value,
                "section_title": "انتشار",
                "text_snippet": "قوانین انتشار محصول",
                "priority_rank": 10,
            },
        ]

    result = run_knowledge_retrieval_smoke(
        namespace="knowledge_operations_sandbox",
        index_version="knowledge_v1_openai",
        database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
        query_fn=query_fn,
    )
    assert result.status == "passed"
    assert result.cases[0].passed
    assert result.cases[1].passed


def test_policy_fact_extraction_returns_settlement_fact() -> None:
    def query_fn(_query: str, **kwargs: object) -> list[dict[str, object]]:
        return _settlement_hits()

    result = run_policy_fact_extraction_check(
        namespace="knowledge_operations_sandbox",
        index_version="knowledge_v1_openai",
        database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
        query_fn=query_fn,
    )
    assert result.status == "passed"
    assert result.settlement_fact_present
    hints = retrieval_hits_to_hints(_settlement_hits())
    assert result.canonical_fact_reachable
    assert "کیف پول" in hints[0].snippet


def _fake_page_fetch(pages: dict[int, list[dict[str, object]]]):
    def fake_fetch(
        url: str,
        *,
        params: dict[str, str] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        page_num = int((params or {})["page"])
        return {"data": pages[page_num], "meta": {"next_page": str(page_num + 1)}}

    return fake_fetch


def test_fetch_live_rooms_400_via_four_pages() -> None:
    pages: dict[int, list[dict[str, object]]] = {}
    for page in range(1, 5):
        pages[page] = [{"id": f"room-{page}-{i}", "category": "support"} for i in range(100)]

    rooms, _raw, warnings = fetch_live_rooms(limit=400, fetch_page_fn=_fake_page_fetch(pages))
    assert len(rooms) == 400
    assert any("pagination_pages_fetched" in warning for warning in warnings)


def test_fetch_live_rooms_dedupes_across_pages() -> None:
    def fake_fetch(
        url: str,
        *,
        params: dict[str, str] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        page_num = int((params or {})["page"])
        if page_num == 1:
            return {"data": [{"id": "1"}, {"id": "2"}], "meta": {"next_page": "2"}}
        return {"data": [{"id": "2"}, {"id": "3"}]}

    rooms, _, _ = fetch_live_rooms(limit=10, fetch_page_fn=fake_fetch)
    assert len(rooms) == 3
    assert {str(r["id"]) for r in rooms} == {"1", "2", "3"}


def test_fetch_stops_when_no_next_page() -> None:
    calls: list[int] = []

    def fake_fetch(
        url: str,
        *,
        params: dict[str, str] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        calls.append(int((params or {})["page"]))
        return {"data": [{"id": "only"}], "meta": {}}

    rooms, _, _ = fetch_live_rooms(fetch_page_fn=fake_fetch)
    assert len(rooms) == 1
    assert calls == [1]


def test_fetch_summary_style_archive_multiple_pages() -> None:
    def fake_fetch(
        url: str,
        *,
        params: dict[str, str] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        page_num = int((params or {})["page"])
        if page_num > 2:
            return {"data": []}
        return {"data": [{"id": f"p{page_num}"}], "meta": {"next_page": str(page_num + 1)}}

    _rooms, raw, _ = fetch_live_rooms(limit=5, fetch_page_fn=fake_fetch)
    assert isinstance(raw, dict)
    assert "pages" in raw


def test_rebuild_cli_requires_confirm_real_openai() -> None:
    from scripts import rebuild_knowledge_openai_index as cli

    assert cli.main(["--confirm-sandbox"]) == 1


def test_extract_rooms_list_and_data_shapes() -> None:
    list_payload = [{"id": 1}]
    rooms, _ = extract_rooms_from_payload(list_payload)
    assert len(rooms) == 1
    wrapped, _ = extract_rooms_from_payload({"rooms": list_payload})
    assert len(wrapped) == 1

"""Tests for offline draft suggestion generation (mock LLM; no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.offline_draft_generation import (
    OfflineDraftGenerationStats,
    assert_draft_reply_safe,
    assert_output_row_safe,
    assert_prompt_excludes_gold_reference,
    build_offline_draft_messages,
    generate_offline_draft_suggestions,
    gold_reference_reply_hash,
    process_benchmark_case,
)
from app.knowledge.knowledge_models import KnowledgeDocumentType
from app.knowledge.knowledge_retrieval_tool import (
    KnowledgeRetrievalHit,
    KnowledgeRetrievalResponse,
)
from app.llm.types import LLMMessage, LLMResponse
from app.operator_console.knowledge_hints import KnowledgeHint
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent


def _benchmark_case() -> dict[str, object]:
    return {
        "case_id": "ROOM_1__m0",
        "room_id": "ROOM_1",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": "تسویه من واریز نشده",
            "latest_vendor_message": "لطفاً وضعیت واریز را بگویید",
            "recent_context_preview": "vendor: تسویه من واریز نشده",
        },
        "gold_reference_reply": "سلام — واحد مالی در حال بررسی است و تا ۴۸ ساعت اطلاع می‌دهیم.",
        "responder_role": "support_agent",
    }


def _mock_hint() -> KnowledgeHint:
    return KnowledgeHint(
        document_type=KnowledgeDocumentType.SETTLEMENT_RULES.value,
        section_title="زمان‌بندی تسویه",
        source_lane="official_policy",
        priority_rank=10,
        snippet="تسویه پس از تأیید سفارشات طبق بازه اعلام‌شده انجام می‌شود.",
        score=0.9,
    )


def _mock_retrieve(
    _request: object,
    _store: object,
    _embed: object,
) -> KnowledgeRetrievalResponse:
    hit = KnowledgeRetrievalHit(
        chunk_id="knowledge::settlement::1",
        document_type=KnowledgeDocumentType.SETTLEMENT_RULES.value,
        section_title="زمان‌بندی تسویه",
        source_lane="official_policy",
        priority_rank=10,
        snippet="تسویه پس از تأیید سفارشات طبق بازه اعلام‌شده انجام می‌شود.",
        score=0.9,
    )
    return KnowledgeRetrievalResponse(
        hits=[hit],
        result_count=1,
        official_policy_hit_count=1,
        historical_memory_hit_count=0,
    )


def _mock_generate(messages: list[LLMMessage], *, provider: str, model: str) -> LLMResponse:
    combined = "\n".join(m.content for m in messages)
    assert "سلام — واحد مالی" not in combined
    assert "gold_reference_reply" not in combined.lower()
    assert "settlement_status_inquiry" in combined or "تسویه" in combined
    assert "بند راهنما" in combined or "راهنمای سیاست" in combined
    assert "conceptual_intent_fa" in combined
    return LLMResponse(
        content=json.dumps(
            {
                "conceptual_intent_fa": "پیگیری تسویه حساب",
                "draft_reply": (
                    "سلام وقت بخیر. درخواست شما درباره تسویه در صف بررسی است؛ "
                    "پس از تأیید واحد مالی، نتیجه از همین تیکت اطلاع‌رسانی می‌شود. "
                    "لطفاً شماره سفارش مرتبط را اگر هنوز نفرستاده‌اید ارسال کنید."
                ),
            },
            ensure_ascii=False,
        ),
        provider=provider,
        model=model,
        metadata={},
    )


def test_prompt_builder_excludes_gold_and_includes_intent_and_hints() -> None:
    case = _benchmark_case()
    from app.workflows.vendor_ticket_intent_detection import detect_vendor_ticket_intent

    intent_result = detect_vendor_ticket_intent(
        "تسویه من واریز نشده لطفاً وضعیت واریز را بگویید",
        ticket_label="fund",
        route_label="billing_review",
    )
    messages = build_offline_draft_messages(
        case,
        intent_result=intent_result,
        suggested_action="billing_review",
        policy_hints=[_mock_hint()],
    )
    assert intent_result.detected_intent == VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value
    assert_prompt_excludes_gold_reference(messages, str(case["gold_reference_reply"]))
    user = messages[1].content
    assert intent_result.detected_intent in user
    assert "Relevant official policy facts" in user
    assert _mock_hint().snippet in user
    assert str(case["gold_reference_reply"]) not in user


def test_rejects_unsafe_draft_with_iban() -> None:
    with pytest.raises(ValueError, match="PII"):
        assert_draft_reply_safe("لطفاً به شماره کارت 6037991234567890 واریز کنید.")


def test_rejects_draft_with_internal_document_type_name() -> None:
    with pytest.raises(ValueError, match="internal document type"):
        assert_draft_reply_safe("طبق settlement_rules باید صبر کنید.")


def test_process_case_mock_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_HINTS_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings().model_copy(update={"knowledge_hints_enabled": True})
    row = process_benchmark_case(
        _benchmark_case(),
        settings=settings,
        provider="mock",
        model="mock-vendor-ticket-drafter",
        generate_fn=_mock_generate,
        retrieve_fn=_mock_retrieve,
        query_embedding_fn=lambda _text: [0.0] * settings.pgvector_dimensions,
        store=object(),
    )
    assert row["draft_generated"] is True
    assert row["detected_intent"] == "settlement_status_inquiry"
    assert row["conceptual_intent_fa"] == "پیگیری تسویه حساب"
    assert row["suggested_action"] == "check_settlement_status"
    assert row["draft_reply"]
    assert row["knowledge_hint_document_types"] == ["settlement_rules"]
    assert row["gold_reference_reply_hash"]
    assert "gold_reference_reply" not in row
    assert_output_row_safe(row)


def test_summary_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_HINTS_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings().model_copy(update={"knowledge_hints_enabled": True})
    inp = tmp_path / "bench.jsonl"
    out_jsonl = tmp_path / "drafts.jsonl"
    out_summary = tmp_path / "summary.json"
    inp.write_text(json.dumps(_benchmark_case(), ensure_ascii=False) + "\n", encoding="utf-8")

    stats = generate_offline_draft_suggestions(
        inp,
        output_jsonl_path=out_jsonl,
        output_summary_path=out_summary,
        provider="mock",
        settings=settings,
        generate_fn=_mock_generate,
        retrieve_fn=_mock_retrieve,
        query_embedding_fn=lambda _text: [0.0] * settings.pgvector_dimensions,
        store=object(),
    )
    assert isinstance(stats, OfflineDraftGenerationStats)
    assert stats.total_cases == 1
    assert stats.drafts_generated == 1
    assert stats.drafts_failed == 0
    row = json.loads(out_jsonl.read_text(encoding="utf-8").strip())
    assert row["draft_generated"] is True
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert summary["drafts_generated"] == 1


def test_old_style_row_without_crash_on_missing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_HINTS_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    case = {
        "case_id": "X",
        "room_id": "X",
        "ticket_label": "support",
        "route_label": None,
        "snapshot_before_reply": {
            "latest_vendor_message": "سلام",
        },
        "gold_reference_reply": "پاسخ انسانی",
    }
    row = process_benchmark_case(
        case,
        settings=get_settings(),
        provider="mock",
        model="mock-vendor-ticket-drafter",
    )
    assert "draft_generated" in row
    assert row["gold_reference_reply_hash"] == gold_reference_reply_hash("پاسخ انسانی")


def test_cli_honors_custom_input_path(tmp_path: Path) -> None:
    from scripts.generate_offline_draft_suggestions import main

    custom = tmp_path / "custom_first_turn.jsonl"
    custom.write_text(json.dumps(_benchmark_case(), ensure_ascii=False) + "\n", encoding="utf-8")
    out_jsonl = tmp_path / "drafts_custom.jsonl"
    out_summary = tmp_path / "summary_custom.json"

    rc = main(
        [
            "--input",
            str(custom),
            "--output",
            str(out_jsonl),
            "--summary-output",
            str(out_summary),
            "--overwrite",
            "--limit",
            "1",
        ],
    )
    assert rc == 0
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    source = summary["source_path"]
    assert source.endswith("custom_first_turn.jsonl")
    assert "historical_reply_benchmark_v1.jsonl" not in source


def test_resolve_benchmark_input_path_prefers_positional() -> None:
    from scripts.generate_offline_draft_suggestions import resolve_benchmark_input_path

    default = Path("reports/historical_reply_benchmark_v1.jsonl")
    custom = Path("reports/custom.jsonl")
    assert resolve_benchmark_input_path(input_flag=default, positional=custom) == custom
    assert resolve_benchmark_input_path(input_flag=default, positional=None) == default


def test_gold_hash_only_not_in_output() -> None:
    gold = "پاسخ مرجع محرمانه"
    digest = gold_reference_reply_hash(gold)
    assert len(digest) == 64
    assert gold not in digest

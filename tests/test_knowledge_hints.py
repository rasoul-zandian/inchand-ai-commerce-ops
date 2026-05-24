"""Tests for operator-console sandbox knowledge hints (no network)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.config import AppSettings, get_settings
from app.knowledge.knowledge_retrieval_tool import (
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalResponse,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.knowledge_hints import (
    KnowledgeHint,
    assert_query_built_from_safe_ticket_fields,
    build_knowledge_hint_query,
    fetch_knowledge_hints_for_ticket,
    render_knowledge_hints_markdown,
    sanitize_knowledge_hint,
    ticket_safe_fields_for_query,
)
from app.rag.vector_store import InMemoryVectorStore


def _ticket(**overrides: object) -> OperatorTicket:
    base = {
        "room_id": "ROOM_HINT",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "assigned_department": "billing",
        "review_priority": "LOW",
        "suggested_action": "billing_review",
        "suggested_priority": "medium",
        "escalation_recommended": False,
        "duplicate_possible": False,
        "confidence_band": "high",
        "retrieval_gate_decision": "allow",
        "retrieval_result_count": 3,
        "ticket_text_preview": "SECRET historical transcript line must not leak.",
        "open_ticket_preview": "Combined open preview must not leak.",
        "original_vendor_issue_preview": "Vendor asks about settlement delay.",
        "latest_vendor_message": "When will payout arrive?",
        "recent_context_preview": "vendor: waiting since Monday",
    }
    base.update(overrides)
    return OperatorTicket(**base)  # type: ignore[arg-type]


def _fake_response() -> KnowledgeRetrievalResponse:
    return KnowledgeRetrievalResponse(
        hits=[
            KnowledgeRetrievalHit(
                chunk_id="settle-1",
                source_lane="official_policy",
                document_type="settlement_rules",
                section_title="Payout timing",
                score=0.91,
                priority_rank=10,
                snippet="Official settlement SLA for vendor payouts.",
            ),
        ],
        result_count=1,
        official_policy_hit_count=1,
        historical_memory_hit_count=0,
        retrieval_activated=False,
        sandbox_only=True,
    )


def test_build_knowledge_hint_query_uses_safe_snapshot_fields() -> None:
    ticket = _ticket()
    query = build_knowledge_hint_query(ticket)
    assert "ticket_label: fund" in query
    assert "route_label: billing_review" in query
    assert "Vendor asks about settlement delay." in query
    assert "| boost:" in query
    assert "SECRET historical" not in query
    assert "Combined open preview" not in query
    assert_query_built_from_safe_ticket_fields(ticket, query)
    safe = ticket_safe_fields_for_query(ticket)
    assert set(safe) == {
        "original_vendor_issue_preview",
        "latest_vendor_message",
        "recent_context_preview",
        "ticket_label",
        "route_label",
    }


def test_hints_disabled_skips_retrieval_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_HINTS_ENABLED", "false")
    get_settings.cache_clear()
    ticket = _ticket()
    retrieve = MagicMock()
    hints = fetch_knowledge_hints_for_ticket(
        ticket,
        settings=get_settings(),
        store=InMemoryVectorStore(),
        query_embedding_fn=lambda _text: [1.0],
        retrieve_fn=retrieve,
    )
    assert hints == ()
    retrieve.assert_not_called()


def test_hints_enabled_uses_fake_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_HINTS_ENABLED", "true")
    get_settings.cache_clear()
    settings = get_settings()
    ticket = _ticket()
    calls: list[KnowledgeRetrievalRequest] = []

    def _fake_retrieve(
        request: KnowledgeRetrievalRequest,
        _store: object,
        _embed_fn: object,
    ) -> KnowledgeRetrievalResponse:
        calls.append(request)
        return _fake_response()

    hints = fetch_knowledge_hints_for_ticket(
        ticket,
        settings=settings,
        store=InMemoryVectorStore(),
        query_embedding_fn=lambda _text: [1.0],
        retrieve_fn=_fake_retrieve,
    )
    assert len(calls) == 1
    assert calls[0].namespace == "knowledge_operations_sandbox"
    assert calls[0].index_version == "knowledge_v1_openai"
    assert calls[0].top_k == settings.knowledge_hints_top_k
    assert len(hints) == 1
    assert hints[0].document_type == "settlement_rules"
    assert hints[0].source_lane == "official_policy"
    assert len(hints[0].snippet) <= 300


def test_unsafe_fields_are_not_passed_to_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_HINTS_ENABLED", "true")
    get_settings.cache_clear()
    unsafe_preview = 'bad "messages": leak must stay out of retrieval'
    ticket = _ticket(ticket_text_preview=unsafe_preview)
    query = build_knowledge_hint_query(ticket)
    assert unsafe_preview not in query
    assert_query_built_from_safe_ticket_fields(ticket, query)

    captured: list[str] = []

    def _fake_retrieve(
        request: KnowledgeRetrievalRequest,
        _store: object,
        _embed_fn: object,
    ) -> KnowledgeRetrievalResponse:
        captured.append(request.query)
        return _fake_response()

    fetch_knowledge_hints_for_ticket(
        ticket,
        settings=get_settings(),
        store=InMemoryVectorStore(),
        query_embedding_fn=lambda _text: [1.0],
        retrieve_fn=_fake_retrieve,
    )
    assert captured
    assert unsafe_preview not in captured[0]


def test_operator_ticket_can_hold_hints() -> None:
    hint = KnowledgeHint(
        document_type="settlement_rules",
        section_title="SLA",
        source_lane="official_policy",
        priority_rank=10,
        snippet="Short official snippet.",
        score=0.8,
    )
    ticket = _ticket().with_knowledge_hints((hint,))
    assert ticket.knowledge_hints == (hint,)


def test_ui_helper_renders_hints_safely() -> None:
    hint = sanitize_knowledge_hint(_fake_response().hits[0])
    markdown = render_knowledge_hints_markdown([hint])
    assert "Relevant official policy hints" in markdown
    assert "settlement_rules" in markdown
    assert "Official settlement SLA" in markdown
    assert "No policy hint found." not in markdown
    empty = render_knowledge_hints_markdown(())
    assert "No policy hint found." in empty


def test_fund_ticket_query_prefers_settlement_document_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_HINTS_ENABLED", "true")
    get_settings.cache_clear()
    ticket = _ticket(
        original_vendor_issue_preview="قسمت تصفیه پنل هنوز بسته هستش",
    )
    captured: list[KnowledgeRetrievalRequest] = []

    def _fake_retrieve(
        request: KnowledgeRetrievalRequest,
        _store: object,
        _embed_fn: object,
    ) -> KnowledgeRetrievalResponse:
        captured.append(request)
        return _fake_response()

    fetch_knowledge_hints_for_ticket(
        ticket,
        settings=get_settings(),
        store=InMemoryVectorStore(),
        query_embedding_fn=lambda _text: [1.0],
        retrieve_fn=_fake_retrieve,
    )
    assert captured
    assert captured[0].allowed_document_types == [
        "settlement_rules",
        "vendor_general_policy",
        "support_faq",
    ]
    assert "تسویه" in captured[0].query
    assert "تصفیه" not in captured[0].query


def test_knowledge_hints_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KNOWLEDGE_HINTS_ENABLED", raising=False)
    get_settings.cache_clear()
    settings = AppSettings()
    assert settings.knowledge_hints_enabled is False
    assert settings.knowledge_retrieval_namespace == "knowledge_operations_sandbox"
    assert settings.knowledge_retrieval_index_version == "knowledge_v1_openai"
    assert settings.knowledge_hints_top_k == 3

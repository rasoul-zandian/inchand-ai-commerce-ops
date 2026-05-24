"""Draft preview entity isolation — first-turn only vs AI assist globals."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import AppSettings
from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.draft_prompt_leakage import prompt_text_from_messages
from app.evals.first_turn_draft_context import build_first_turn_draft_context_from_ticket
from app.evals.offline_draft_generation import build_offline_draft_messages
from app.llm.types import LLMResponse
from app.operator_console.console_models import OperatorTicket
from app.operator_console.draft_preview import (
    build_draft_preview_record,
    enrich_draft_preview_with_first_turn_entities,
    generate_draft_for_operator_ticket,
    load_draft_preview_for_ticket,
)

_INITIAL_NO_ORDER = "تسویه اولیه فروشنده — بدون شماره سفارش"
_LATEST_WITH_ORDER = "لطفاً سفارش 7654321 را پیگیری کنید"
_ORDER_IN_ORIGINAL = "1234567"
_ORDER_LATEST_ONLY = "7654321"


def _ticket(
    *,
    original: str,
    latest: str,
    extracted_order_ids: str | None = _ORDER_LATEST_ONLY,
) -> OperatorTicket:
    return OperatorTicket(
        room_id="ROOM_DPE",
        ticket_label="fund",
        route_label="billing_review",
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview=original,
        latest_vendor_message=latest,
        recent_context_preview="vendor: follow-up",
        extracted_order_ids=extracted_order_ids,
        extracted_order_id=extracted_order_ids,
    )


def test_draft_preview_entities_empty_when_order_only_in_latest() -> None:
    ticket = _ticket(original=_INITIAL_NO_ORDER, latest=_LATEST_WITH_ORDER)
    row = {
        "room_id": ticket.room_id,
        "draft_reply": "پیش‌نویس داخلی",
        "draft_generated": True,
        "extracted_order_ids": _ORDER_LATEST_ONLY,
        "entity_source": "open_ticket_preview",
    }
    record = build_draft_preview_record(row)
    assert record is not None
    enriched = enrich_draft_preview_with_first_turn_entities(
        record,
        ticket,
        settings=AppSettings(draft_generation_mode="first_turn_only"),
    )
    assert enriched is not None
    assert enriched.draft_entity_source == "original_vendor_issue_preview"
    assert enriched.draft_extracted_order_ids is None
    assert _ORDER_LATEST_ONLY not in (enriched.draft_extracted_order_ids or "")


def test_draft_preview_entities_include_order_from_original() -> None:
    original = f"سفارش {_ORDER_IN_ORIGINAL} هنوز تسویه نشده"
    ticket = _ticket(
        original=original,
        latest="پیام بعدی",
        extracted_order_ids=_ORDER_IN_ORIGINAL,
    )
    enriched = enrich_draft_preview_with_first_turn_entities(
        build_draft_preview_record(
            {
                "room_id": ticket.room_id,
                "draft_reply": "پیش‌نویس",
                "draft_generated": True,
            },
        ),
        ticket,
        settings=AppSettings(draft_generation_mode="first_turn_only"),
    )
    assert enriched is not None
    assert enriched.draft_extracted_order_ids == _ORDER_IN_ORIGINAL


def test_load_draft_preview_reextracts_from_ticket(tmp_path: Path) -> None:
    ticket = _ticket(original=_INITIAL_NO_ORDER, latest=_LATEST_WITH_ORDER)
    path = tmp_path / "drafts.jsonl"
    path.write_text(
        json.dumps(
            {
                "room_id": ticket.room_id,
                "case_id": f"{ticket.room_id}__first_vendor_turn",
                "draft_reply": "پیش‌نویس",
                "draft_generated": True,
                "extracted_order_ids": _ORDER_LATEST_ONLY,
            },
        )
        + "\n",
        encoding="utf-8",
    )
    settings = AppSettings(
        operator_draft_preview_enabled=True,
        draft_generation_mode="first_turn_only",
    )
    preview = load_draft_preview_for_ticket(
        ticket,
        suggestions_path=path,
        settings=settings,
    )
    assert preview is not None
    assert preview.draft_extracted_order_ids is None


def test_generate_draft_prompt_excludes_latest_only_order_id() -> None:
    ticket = _ticket(original=_INITIAL_NO_ORDER, latest=_LATEST_WITH_ORDER)
    settings = AppSettings(
        operator_draft_generation_enabled=True,
        knowledge_hints_enabled=False,
        draft_generation_mode="first_turn_only",
    )
    captured: list[str] = []

    def _mock_generate(messages, *, provider: str, model: str) -> LLMResponse:
        prompt = "\n".join(m.content for m in messages)
        captured.append(prompt)
        assert _ORDER_LATEST_ONLY not in prompt
        return LLMResponse(
            content=(
                '{"conceptual_intent_fa": "پیگیری تسویه", '
                '"draft_reply": "برای بررسی به تیم مالی ارجاع شد."}'
            ),
            provider=provider,
            model=model,
            metadata={},
        )

    record = generate_draft_for_operator_ticket(
        ticket,
        settings=settings,
        generate_fn=_mock_generate,
    )
    assert record.draft_extracted_order_ids is None
    assert captured


def test_first_turn_context_matches_draft_preview_entities() -> None:
    ticket = _ticket(
        original=f"سفارش {_ORDER_IN_ORIGINAL}",
        latest=_LATEST_WITH_ORDER,
        extracted_order_ids=_ORDER_LATEST_ONLY,
    )
    ctx = build_first_turn_draft_context_from_ticket(
        ticket,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    enriched = enrich_draft_preview_with_first_turn_entities(
        build_draft_preview_record(
            {"room_id": ticket.room_id, "draft_reply": "x", "draft_generated": True},
        ),
        ticket,
        settings=AppSettings(draft_generation_mode="first_turn_only"),
    )
    assert enriched is not None
    assert _ORDER_IN_ORIGINAL in (enriched.draft_extracted_order_ids or "")
    assert _ORDER_LATEST_ONLY not in (enriched.draft_extracted_order_ids or "")
    messages = build_offline_draft_messages(
        {
            "ticket_label": ticket.ticket_label,
            "route_label": ticket.route_label,
            "snapshot_before_reply": {
                "original_vendor_issue_preview": ticket.original_vendor_issue_preview,
                "latest_vendor_message": ticket.latest_vendor_message,
            },
        },
        intent_result=ctx.first_turn_intent,
        suggested_action=ctx.suggested_action,
        policy_hints=(),
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
        first_turn_context=ctx,
    )
    assert _ORDER_IN_ORIGINAL in prompt_text_from_messages(messages)


def test_precomputed_ticket_order_id_marked_forbidden() -> None:
    from app.evals.draft_prompt_leakage import extract_forbidden_values_from_operator_ticket

    ticket = _ticket(original=_INITIAL_NO_ORDER, latest=_LATEST_WITH_ORDER)
    forbidden = extract_forbidden_values_from_operator_ticket(
        ticket,
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
    )
    assert _ORDER_LATEST_ONLY in forbidden

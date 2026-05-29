"""Tests for operator-console reflection before/after comparison (session-only)."""

from __future__ import annotations

import json
from dataclasses import replace

from app.agentic_sandbox.final_draft_reflection import (
    FinalDraftReflectionResult,
    reflection_comparison_session_row,
    reflection_metadata_row,
)
from app.config import AppSettings
from app.operator_console.agentic_assisted_mode import (
    AgenticAssistedPackage,
    sanitize_agentic_assisted_package,
)
from app.operator_console.agentic_assisted_work_package import (
    build_assisted_work_package_debug_lines,
)
from app.operator_console.agentic_sandbox_preview import (
    AgenticSandboxPreviewResult,
    sanitize_agentic_preview_result,
)
from app.operator_console.reflection_comparison import (
    build_reflection_comparison_metadata_lines,
    reflection_comparison_available,
    reflection_disabled_debug_line,
    reflection_draft_diff_lines,
)

_FORBIDDEN_PUBLIC_MARKERS = (
    "pre_reflection_draft",
    "final_reflected_draft",
    "raw_generated_draft",
    "chain of thought",
    "hidden reasoning",
    "reviewer thoughts",
)


def _graph_with_comparison(
    *,
    pre: str,
    after: str,
    rewrite_applied: bool,
    issue_types: tuple[str, ...] = (),
    reflection_enabled: bool = True,
) -> AgenticSandboxPreviewResult:
    reflection_result = FinalDraftReflectionResult(
        original_draft=pre,
        final_draft=after,
        reviewed=reflection_enabled,
        rewrite_applied=rewrite_applied,
    )
    comparison = reflection_comparison_session_row(
        raw_generated_draft=pre,
        pre_reflection_draft=pre,
        final_reflected_draft=after,
        result=reflection_result,
        reflection_enabled=reflection_enabled,
        reflection_provider="rule_based",
    )
    return sanitize_agentic_preview_result(
        {
            "room_id": "7743",
            "detected_intent": "delivery_confirmation_request",
            "suggested_action": "update_delivery_status",
            "draft_reply": after,
            "safety_status": "passed",
            "human_review_required": True,
            "execution_allowed": False,
            "customer_send_allowed": False,
            "errors": [],
            "final_draft_reflection_metrics": reflection_metadata_row(reflection_result),
            "final_draft_reflection_comparison": comparison,
        },
        knowledge_hints_enabled=False,
        llm_provider="mock",
    )


def test_comparison_available_without_rewrite_when_before_equals_after() -> None:
    draft = "درخواست تحویل سفارش شما ثبت شد."
    graph = _graph_with_comparison(pre=draft, after=draft, rewrite_applied=False)
    assert graph.pre_reflection_draft == draft
    assert graph.final_reflected_draft == draft
    assert graph.reflection_rewrite_applied is False
    assert reflection_comparison_available(graph)
    assert graph.reflection_comparison_available is True
    assert reflection_draft_diff_lines(draft, draft) == []


def test_sanitize_fallback_populates_comparison_from_draft_only() -> None:
    draft = "پاسخ کوتاه برای بررسی"
    graph = sanitize_agentic_preview_result(
        {
            "room_id": "7743",
            "draft_reply": draft,
            "safety_status": "passed",
            "human_review_required": True,
            "execution_allowed": False,
            "customer_send_allowed": False,
            "errors": [],
        },
        knowledge_hints_enabled=False,
        settings=AppSettings(final_draft_reflection_enabled=True),
        llm_provider="mock",
    )
    assert graph.pre_reflection_draft == draft
    assert graph.final_reflected_draft == draft
    assert reflection_comparison_available(graph)
    assert graph.reflection_enabled is True
    assert graph.reflection_provider == "rule_based"


def test_reflection_rewrite_before_differs_from_after() -> None:
    before = "لطفاً شماره سفارش را ارسال کنید."
    after = "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    graph = _graph_with_comparison(
        pre=before,
        after=after,
        rewrite_applied=True,
        issue_types=("repeated_identifier_request",),
    )
    assert graph.pre_reflection_draft != graph.final_reflected_draft
    assert graph.reflection_rewrite_applied is True
    assert reflection_draft_diff_lines(before, after)


def test_issue_labels_visible_in_metadata_lines() -> None:
    graph = _graph_with_comparison(
        pre="لطفاً شناسه پنل را ارسال کنید.",
        after="پنل در دست بررسی ناظر است.",
        rewrite_applied=True,
        issue_types=("panel_identifier_request",),
    )
    graph = replace(
        graph,
        reflection_issue_types=("panel_identifier_request",),
        reflection_issue_count=1,
    )
    lines = build_reflection_comparison_metadata_lines(graph, lang="en")
    joined = "\n".join(lines)
    assert "panel_identifier_request" in joined
    assert "Issue count: 1" in joined
    assert "Reflection enabled: yes" in joined
    assert "Reflection provider: rule_based" in joined


def test_disabled_reflection_shows_technical_warning() -> None:
    graph = _graph_with_comparison(
        pre="test",
        after="test",
        rewrite_applied=False,
        reflection_enabled=False,
    )
    assert graph.reflection_enabled is False
    warning = reflection_disabled_debug_line(graph, lang="en")
    assert warning is not None
    assert "disabled" in warning.lower()
    debug = "\n".join(
        build_assisted_work_package_debug_lines(
            AgenticAssistedPackage(
                room_id="7743",
                graph=graph,
                operator_checklist=(),
                graduation_overall_status=None,
                graduation_gate_passed=True,
            ),
            lang="en",
        ),
    )
    assert "reflection_comparison_available" in debug
    assert "Final draft reflection is disabled" in debug


def test_no_hidden_reasoning_leaked_in_public_export() -> None:
    graph = _graph_with_comparison(
        pre="لطفاً کد رهگیری را ارسال کنید.",
        after="اطلاعات ارسال دریافت شد.",
        rewrite_applied=True,
        issue_types=("repeated_identifier_request",),
    )
    public = json.dumps(graph.to_public_dict(), ensure_ascii=False)
    for marker in _FORBIDDEN_PUBLIC_MARKERS:
        assert marker not in public
    assert graph.reflection_comparison_available is True
    package = AgenticAssistedPackage(
        room_id="7743",
        graph=graph,
        operator_checklist=("check",),
        graduation_overall_status=None,
        graduation_gate_passed=True,
    )
    assisted_public = json.dumps(sanitize_agentic_assisted_package(package), ensure_ascii=False)
    for marker in _FORBIDDEN_PUBLIC_MARKERS:
        assert marker not in assisted_public


def test_session_only_storage_has_comparison_on_graph_object() -> None:
    graph = _graph_with_comparison(
        pre="before",
        after="after",
        rewrite_applied=True,
    )
    assert graph.pre_reflection_draft == "before"
    assert graph.final_reflected_draft == "after"
    assert graph.draft_reply == "after"


def test_reflection_comparison_row_rejects_forbidden_keys() -> None:
    import pytest

    result = FinalDraftReflectionResult(
        original_draft="x",
        final_draft="y",
        reviewed=True,
    )
    row = reflection_comparison_session_row(
        raw_generated_draft="x",
        pre_reflection_draft="x",
        final_reflected_draft="y",
        result=result,
    )
    row["hidden_reasoning"] = "do not leak"
    from app.agentic_sandbox.final_draft_reflection import assert_reflection_comparison_session_safe

    with pytest.raises(ValueError, match="forbidden"):
        assert_reflection_comparison_session_safe(row)


def test_integration_reflection_review_produces_comparison() -> None:
    from app.agentic_sandbox.final_draft_reflection import apply_final_draft_reflection_review

    before = "لطفاً شماره سفارش را ارسال کنید."
    after, result = apply_final_draft_reflection_review(
        before,
        seller_text="سفارش 1234567 تحویل مشتری شده",
        suggested_action="update_delivery_status",
        order_ids=("1234567",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    row = reflection_comparison_session_row(
        raw_generated_draft=before,
        pre_reflection_draft=before,
        final_reflected_draft=after,
        result=result,
    )
    assert row["pre_reflection_draft"] == before
    assert row["final_reflected_draft"] == after
    assert row["reflection_enabled"] is True
    assert "chain" not in json.dumps(row).lower()

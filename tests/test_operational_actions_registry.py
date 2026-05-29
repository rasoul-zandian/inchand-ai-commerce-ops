"""Tests for operational actions registry (Step 234)."""

from __future__ import annotations

from app.config import AppSettings
from app.operator_console.manual_sandbox_auto_tracking import (
    should_run_manual_sandbox_auto_tracking,
)
from app.operator_console.manual_sandbox_shipment_decision import (
    should_trigger_manual_sandbox_auto_order_lookup,
)
from app.tools.operational_actions_registry import (
    OperationalToolCapability,
    OperationalToolExecutionMode,
    OperationalToolId,
    OperationalToolRiskLevel,
    build_inchand_eligibility_context,
    build_iran_post_eligibility_context,
    evaluate_tool_eligibility,
    get_operational_tool_registry,
)


def _settings(**overrides: object) -> AppSettings:
    base = {
        "inchand_order_lookup_enabled": True,
        "iran_post_tracking_enabled": True,
        "inchand_api_key_value": "inchand-token",
        "iran_post_tracking_token": "post-token",
        "manual_sandbox_auto_order_lookup_enabled": True,
        "manual_sandbox_auto_tracking_verify_enabled": True,
    }
    base.update(overrides)
    return AppSettings(**base)


def test_registry_includes_inchand_order_lookup() -> None:
    registry = get_operational_tool_registry()
    definition = registry.get(OperationalToolId.INCHAND_ORDER_LOOKUP)
    assert definition.read_only is True
    assert OperationalToolCapability.READ_ORDER_STATUS in definition.capabilities


def test_registry_includes_iran_post_tracking_verification() -> None:
    registry = get_operational_tool_registry()
    definition = registry.get(OperationalToolId.IRAN_POST_TRACKING_VERIFICATION)
    assert definition.read_only is True
    assert OperationalToolCapability.VERIFY_TRACKING_CODE in definition.capabilities


def test_order_lookup_eligible_manually_with_order_id_and_token() -> None:
    result = evaluate_tool_eligibility(
        OperationalToolId.INCHAND_ORDER_LOOKUP,
        build_inchand_eligibility_context(
            _settings(),
            source_mode="live_api_feed",
            order_id_present=True,
            manual_trigger=True,
        ),
    )
    assert result.eligible is True
    assert result.manual_allowed is True


def test_order_lookup_blocked_without_token() -> None:
    result = evaluate_tool_eligibility(
        OperationalToolId.INCHAND_ORDER_LOOKUP,
        build_inchand_eligibility_context(
            _settings(inchand_api_key_value=""),
            source_mode="manual_sandbox_chat",
            order_id_present=True,
            manual_trigger=True,
            sandbox_auto_enabled=True,
            token_present=False,
        ),
    )
    assert result.eligible is False
    assert "missing_token" in (result.blocked_reason or "")


def test_order_lookup_sandbox_auto_only_manual_sandbox() -> None:
    settings = _settings()
    manual = evaluate_tool_eligibility(
        OperationalToolId.INCHAND_ORDER_LOOKUP,
        build_inchand_eligibility_context(
            settings,
            source_mode="manual_sandbox_chat",
            order_id_present=True,
            sandbox_auto_enabled=True,
            scenario_auto_eligible=True,
        ),
    )
    live = evaluate_tool_eligibility(
        OperationalToolId.INCHAND_ORDER_LOOKUP,
        build_inchand_eligibility_context(
            settings,
            source_mode="live_api_feed",
            order_id_present=True,
            sandbox_auto_enabled=True,
            scenario_auto_eligible=True,
        ),
    )
    assert manual.sandbox_auto_allowed is True
    assert live.sandbox_auto_allowed is False


def test_order_lookup_live_auto_blocked() -> None:
    result = evaluate_tool_eligibility(
        OperationalToolId.INCHAND_ORDER_LOOKUP,
        build_inchand_eligibility_context(
            _settings(),
            source_mode="live_api_feed",
            order_id_present=True,
            sandbox_auto_enabled=True,
            live_auto_enabled=True,
            scenario_auto_eligible=True,
        ),
    )
    assert result.live_auto_allowed is False
    assert result.sandbox_auto_allowed is False


def test_iran_post_eligible_for_iran_post_tracking_when_not_delivered() -> None:
    result = evaluate_tool_eligibility(
        OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        build_iran_post_eligibility_context(
            _settings(),
            source_mode="manual_sandbox_chat",
            tracking_code_present=True,
            carrier_candidate="iran_post",
            order_delivered_in_inchand=False,
            sandbox_auto_enabled=True,
        ),
    )
    assert result.sandbox_auto_allowed is True


def test_iran_post_blocked_when_order_already_delivered_in_inchand() -> None:
    result = evaluate_tool_eligibility(
        OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        build_iran_post_eligibility_context(
            _settings(),
            source_mode="manual_sandbox_chat",
            tracking_code_present=True,
            carrier_candidate="iran_post",
            order_delivered_in_inchand=True,
            sandbox_auto_enabled=True,
        ),
    )
    assert result.eligible is False
    assert "order_already_delivered_in_inchand" in (result.blocked_reason or "")


def test_iran_post_blocked_without_token() -> None:
    result = evaluate_tool_eligibility(
        OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        build_iran_post_eligibility_context(
            _settings(iran_post_tracking_token=""),
            source_mode="manual_sandbox_chat",
            tracking_code_present=True,
            manual_trigger=True,
            token_present=False,
        ),
    )
    assert result.eligible is False
    assert "missing_token" in (result.blocked_reason or "")


def test_risk_levels_correct() -> None:
    registry = get_operational_tool_registry()
    assert (
        registry.get(OperationalToolId.INCHAND_ORDER_LOOKUP).risk_level
        == OperationalToolRiskLevel.LOW
    )
    assert (
        registry.get(OperationalToolId.IRAN_POST_TRACKING_VERIFICATION).risk_level
        == OperationalToolRiskLevel.MEDIUM
    )


def test_safe_output_fields_exclude_pii() -> None:
    registry = get_operational_tool_registry()
    inchand = registry.get(OperationalToolId.INCHAND_ORDER_LOOKUP)
    iran = registry.get(OperationalToolId.IRAN_POST_TRACKING_VERIFICATION)
    assert "receiver_name" in inchand.pii_excluded_fields
    assert "user_id" in inchand.pii_excluded_fields
    assert "receiver_name" in iran.pii_excluded_fields
    assert "receiver_zip" in iran.pii_excluded_fields
    assert "order_status" in inchand.safe_output_fields
    assert "verified" in iran.safe_output_fields


def test_manual_sandbox_orchestration_consults_registry() -> None:
    settings = _settings()
    assert should_trigger_manual_sandbox_auto_order_lookup(
        source_mode="manual_sandbox_chat",
        order_id="INC-1234567",
        seller_text="سفارش INC-1234567 ارسال شد",
        detected_scenario="shipment_reshipment",
        settings=settings,
    )
    assert should_run_manual_sandbox_auto_tracking(
        source_mode="manual_sandbox_chat",
        role="seller",
        settings=settings,
        tracking_code_present=True,
        order_delivered_in_inchand=False,
    )


def test_live_replay_auto_execution_remains_blocked() -> None:
    settings = _settings()
    assert not should_trigger_manual_sandbox_auto_order_lookup(
        source_mode="historical_replay",
        order_id="INC-1234567",
        seller_text="سفارش INC-1234567 ارسال شد",
        detected_scenario="shipment_reshipment",
        settings=settings,
    )
    assert not should_run_manual_sandbox_auto_tracking(
        source_mode="live_api_feed",
        role="seller",
        settings=settings,
        tracking_code_present=True,
    )


def test_execution_modes_include_live_auto_disallowed() -> None:
    registry = get_operational_tool_registry()
    for tool_id in registry.list_active_tools():
        modes = registry.get(tool_id).execution_modes
        assert OperationalToolExecutionMode.LIVE_AUTO_DISALLOWED in modes

"""Central registry for read-only operational tools (eligibility, risk, execution modes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.config import AppSettings, get_settings

SOURCE_MANUAL_SANDBOX_CHAT = "manual_sandbox_chat"
SOURCE_LIVE_API_FEED = "live_api_feed"
SOURCE_HISTORICAL_REPLAY = "historical_replay"

_OPERATOR_SOURCE_MODES = frozenset(
    {
        SOURCE_MANUAL_SANDBOX_CHAT,
        SOURCE_LIVE_API_FEED,
        SOURCE_HISTORICAL_REPLAY,
    },
)


class OperationalToolId(StrEnum):
    INCHAND_ORDER_LOOKUP = "inchand_order_lookup"
    IRAN_POST_TRACKING_VERIFICATION = "iran_post_tracking_verification"
    # Reserved — not registered yet
    SHEBA_VERIFICATION = "sheba_verification"
    SETTLEMENT_STATUS_LOOKUP = "settlement_status_lookup"
    SELLER_PANEL_STATUS_LOOKUP = "seller_panel_status_lookup"
    PRODUCT_REVIEW_LOOKUP = "product_review_lookup"
    TICKET_STATUS_LOOKUP = "ticket_status_lookup"
    CARRIER_TRACKING_GENERIC = "carrier_tracking_generic"


class OperationalToolCapability(StrEnum):
    READ_ORDER_STATUS = "read_order_status"
    READ_PARCEL_TRACKING = "read_parcel_tracking"
    READ_DELIVERY_STATE = "read_delivery_state"
    READ_PROVIDER_STATUS = "read_provider_status"
    VERIFY_TRACKING_CODE = "verify_tracking_code"
    READ_CARRIER_EVENTS = "read_carrier_events"
    READ_LAST_TRACKING_STATUS = "read_last_tracking_status"


class OperationalToolRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OperationalToolExecutionMode(StrEnum):
    MANUAL_ONLY = "manual_only"
    SANDBOX_AUTO_ALLOWED = "sandbox_auto_allowed"
    LIVE_AUTO_DISALLOWED = "live_auto_disallowed"
    LIVE_MANUAL_ALLOWED = "live_manual_allowed"
    FUTURE_PRODUCTION_AUTO_CANDIDATE = "future_production_auto_candidate"


_ACTIVE_TOOL_IDS: tuple[OperationalToolId, ...] = (
    OperationalToolId.INCHAND_ORDER_LOOKUP,
    OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
)

_INCHAND_SAFE_OUTPUT_FIELDS: tuple[str, ...] = (
    "order_status",
    "provider_status",
    "parcel_tracking_code",
    "parcel_status_name",
    "delivered_at",
    "is_delivered_in_inchand",
)

_INCHAND_PII_EXCLUDED: tuple[str, ...] = (
    "receiver_name",
    "sender_name",
    "user_id",
    "address",
    "phone",
)

_IRAN_POST_SAFE_OUTPUT_FIELDS: tuple[str, ...] = (
    "verified",
    "status_description",
    "last_event_description",
    "last_event_datetime",
    "last_event_province",
    "event_count",
)

_IRAN_POST_PII_EXCLUDED: tuple[str, ...] = (
    "receiver_name",
    "sender_name",
    "receiver_zip",
    "sender_zip",
    "mail_carrier_name",
    "mail_person_name",
)


@dataclass(frozen=True)
class OperationalToolDefinition:
    """Static metadata for one operational tool."""

    tool_id: OperationalToolId
    read_only: bool
    risk_level: OperationalToolRiskLevel
    execution_modes: tuple[OperationalToolExecutionMode, ...]
    capabilities: tuple[OperationalToolCapability, ...]
    required_inputs: tuple[str, ...]
    safe_output_fields: tuple[str, ...]
    pii_excluded_fields: tuple[str, ...]
    can_affect_draft_generation: bool
    description_fa: str = ""


@dataclass(frozen=True)
class OperationalToolEligibilityInput:
    """Runtime context for eligibility evaluation (no secrets)."""

    source_mode: str = SOURCE_MANUAL_SANDBOX_CHAT
    detected_scenario: str | None = None
    order_id_present: bool = False
    tracking_code_present: bool = False
    carrier_candidate: str | None = None
    order_delivered_in_inchand: bool = False
    manual_trigger: bool = False
    sandbox_auto_enabled: bool = False
    live_auto_enabled: bool = False
    tool_enabled: bool = True
    token_present: bool = False
    scenario_auto_eligible: bool = True


@dataclass(frozen=True)
class OperationalToolEligibilityResult:
    """Outcome of eligibility evaluation for one tool."""

    tool_id: OperationalToolId
    eligible: bool
    blocked_reason: str | None = None
    manual_allowed: bool = False
    sandbox_auto_allowed: bool = False
    live_auto_allowed: bool = False
    tool_execution_mode: OperationalToolExecutionMode | None = None
    tool_risk_level: OperationalToolRiskLevel | None = None


@dataclass(frozen=True)
class OperationalToolRegistry:
    """In-memory registry of operational tool definitions."""

    definitions: dict[OperationalToolId, OperationalToolDefinition] = field(default_factory=dict)

    def get(self, tool_id: OperationalToolId) -> OperationalToolDefinition:
        definition = self.definitions.get(tool_id)
        if definition is None:
            raise KeyError(f"unknown operational tool: {tool_id}")
        return definition

    def list_active_tools(self) -> tuple[OperationalToolId, ...]:
        return _ACTIVE_TOOL_IDS


def _inchand_definition() -> OperationalToolDefinition:
    return OperationalToolDefinition(
        tool_id=OperationalToolId.INCHAND_ORDER_LOOKUP,
        read_only=True,
        risk_level=OperationalToolRiskLevel.LOW,
        execution_modes=(
            OperationalToolExecutionMode.MANUAL_ONLY,
            OperationalToolExecutionMode.SANDBOX_AUTO_ALLOWED,
            OperationalToolExecutionMode.LIVE_MANUAL_ALLOWED,
            OperationalToolExecutionMode.LIVE_AUTO_DISALLOWED,
        ),
        capabilities=(
            OperationalToolCapability.READ_ORDER_STATUS,
            OperationalToolCapability.READ_PARCEL_TRACKING,
            OperationalToolCapability.READ_DELIVERY_STATE,
            OperationalToolCapability.READ_PROVIDER_STATUS,
        ),
        required_inputs=("order_id",),
        safe_output_fields=_INCHAND_SAFE_OUTPUT_FIELDS,
        pii_excluded_fields=_INCHAND_PII_EXCLUDED,
        can_affect_draft_generation=True,
        description_fa="استعلام read-only وضعیت سفارش از API اینچند",
    )


def _iran_post_definition() -> OperationalToolDefinition:
    return OperationalToolDefinition(
        tool_id=OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        read_only=True,
        risk_level=OperationalToolRiskLevel.MEDIUM,
        execution_modes=(
            OperationalToolExecutionMode.MANUAL_ONLY,
            OperationalToolExecutionMode.SANDBOX_AUTO_ALLOWED,
            OperationalToolExecutionMode.LIVE_MANUAL_ALLOWED,
            OperationalToolExecutionMode.LIVE_AUTO_DISALLOWED,
        ),
        capabilities=(
            OperationalToolCapability.VERIFY_TRACKING_CODE,
            OperationalToolCapability.READ_CARRIER_EVENTS,
            OperationalToolCapability.READ_LAST_TRACKING_STATUS,
        ),
        required_inputs=("tracking_code",),
        safe_output_fields=_IRAN_POST_SAFE_OUTPUT_FIELDS,
        pii_excluded_fields=_IRAN_POST_PII_EXCLUDED,
        can_affect_draft_generation=True,
        description_fa="استعلام read-only وضعیت رهگیری پست (API خارجی)",
    )


def get_operational_tool_registry() -> OperationalToolRegistry:
    """Return the singleton-style registry with current active tools."""
    return OperationalToolRegistry(
        definitions={
            OperationalToolId.INCHAND_ORDER_LOOKUP: _inchand_definition(),
            OperationalToolId.IRAN_POST_TRACKING_VERIFICATION: _iran_post_definition(),
        },
    )


def _normalize_source_mode(source_mode: str) -> str:
    normalized = (source_mode or "").strip()
    if normalized in _OPERATOR_SOURCE_MODES:
        return normalized
    return normalized or SOURCE_MANUAL_SANDBOX_CHAT


def _is_iran_post_carrier(carrier_candidate: str | None) -> bool:
    if not carrier_candidate:
        return True
    lowered = carrier_candidate.strip().lower().replace(" ", "_")
    return lowered in {"iran_post", "iranpost", "post", "پست"}


def _evaluate_inchand_order_lookup(
    definition: OperationalToolDefinition,
    context: OperationalToolEligibilityInput,
) -> OperationalToolEligibilityResult:
    blocked: list[str] = []
    if not context.tool_enabled:
        blocked.append("tool_disabled")
    if not context.token_present:
        blocked.append("missing_token")
    if not context.order_id_present:
        blocked.append("missing_order_id")

    source = _normalize_source_mode(context.source_mode)
    manual_allowed = (
        OperationalToolExecutionMode.LIVE_MANUAL_ALLOWED in definition.execution_modes
        and context.manual_trigger
        and not blocked
    )
    sandbox_auto_allowed = (
        source == SOURCE_MANUAL_SANDBOX_CHAT
        and context.sandbox_auto_enabled
        and context.scenario_auto_eligible
        and not blocked
        and OperationalToolExecutionMode.SANDBOX_AUTO_ALLOWED in definition.execution_modes
    )
    live_auto_allowed = False
    if context.live_auto_enabled:
        blocked.append("live_auto_disallowed")

    eligible = manual_allowed or sandbox_auto_allowed
    if not eligible and not blocked:
        if source != SOURCE_MANUAL_SANDBOX_CHAT and not context.manual_trigger:
            blocked.append("manual_trigger_required")
        elif source == SOURCE_MANUAL_SANDBOX_CHAT and not context.sandbox_auto_enabled:
            blocked.append("sandbox_auto_disabled")
        elif not context.scenario_auto_eligible:
            blocked.append("scenario_not_eligible")

    execution_mode: OperationalToolExecutionMode | None = None
    if sandbox_auto_allowed:
        execution_mode = OperationalToolExecutionMode.SANDBOX_AUTO_ALLOWED
    elif manual_allowed:
        execution_mode = OperationalToolExecutionMode.MANUAL_ONLY

    return OperationalToolEligibilityResult(
        tool_id=OperationalToolId.INCHAND_ORDER_LOOKUP,
        eligible=eligible,
        blocked_reason=";".join(blocked) if blocked and not eligible else None,
        manual_allowed=manual_allowed,
        sandbox_auto_allowed=sandbox_auto_allowed,
        live_auto_allowed=live_auto_allowed,
        tool_execution_mode=execution_mode,
        tool_risk_level=definition.risk_level,
    )


def _evaluate_iran_post_tracking(
    definition: OperationalToolDefinition,
    context: OperationalToolEligibilityInput,
) -> OperationalToolEligibilityResult:
    blocked: list[str] = []
    if not context.tool_enabled:
        blocked.append("tool_disabled")
    if not context.token_present:
        blocked.append("missing_token")
    if not context.tracking_code_present:
        blocked.append("missing_tracking_code")
    if not _is_iran_post_carrier(context.carrier_candidate):
        blocked.append("carrier_not_iran_post")
    if context.order_delivered_in_inchand:
        blocked.append("order_already_delivered_in_inchand")

    source = _normalize_source_mode(context.source_mode)
    manual_allowed = (
        context.manual_trigger
        and not blocked
        and OperationalToolExecutionMode.LIVE_MANUAL_ALLOWED in definition.execution_modes
    )
    sandbox_auto_allowed = (
        source == SOURCE_MANUAL_SANDBOX_CHAT
        and context.sandbox_auto_enabled
        and not blocked
        and OperationalToolExecutionMode.SANDBOX_AUTO_ALLOWED in definition.execution_modes
    )
    live_auto_allowed = False
    if context.live_auto_enabled:
        blocked.append("live_auto_disallowed")

    eligible = manual_allowed or sandbox_auto_allowed
    if not eligible and not blocked:
        if not context.manual_trigger and source != SOURCE_MANUAL_SANDBOX_CHAT:
            blocked.append("manual_trigger_required")
        elif source == SOURCE_MANUAL_SANDBOX_CHAT and not context.sandbox_auto_enabled:
            blocked.append("sandbox_auto_disabled")

    execution_mode: OperationalToolExecutionMode | None = None
    if sandbox_auto_allowed:
        execution_mode = OperationalToolExecutionMode.SANDBOX_AUTO_ALLOWED
    elif manual_allowed:
        execution_mode = OperationalToolExecutionMode.MANUAL_ONLY

    return OperationalToolEligibilityResult(
        tool_id=OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        eligible=eligible,
        blocked_reason=";".join(blocked) if blocked and not eligible else None,
        manual_allowed=manual_allowed,
        sandbox_auto_allowed=sandbox_auto_allowed,
        live_auto_allowed=live_auto_allowed,
        tool_execution_mode=execution_mode,
        tool_risk_level=definition.risk_level,
    )


def evaluate_tool_eligibility(
    tool_id: OperationalToolId | str,
    context: OperationalToolEligibilityInput,
) -> OperationalToolEligibilityResult:
    """Evaluate whether a tool may run under the given context."""
    registry = get_operational_tool_registry()
    resolved = OperationalToolId(str(tool_id))
    definition = registry.get(resolved)
    if resolved == OperationalToolId.INCHAND_ORDER_LOOKUP:
        return _evaluate_inchand_order_lookup(definition, context)
    if resolved == OperationalToolId.IRAN_POST_TRACKING_VERIFICATION:
        return _evaluate_iran_post_tracking(definition, context)
    raise KeyError(f"tool not registered for eligibility: {resolved}")


def evaluate_all_tool_eligibility(
    context: OperationalToolEligibilityInput,
) -> dict[OperationalToolId, OperationalToolEligibilityResult]:
    """Evaluate every active tool."""
    return {
        tool_id: evaluate_tool_eligibility(tool_id, context)
        for tool_id in get_operational_tool_registry().list_active_tools()
    }


def operational_tools_debug_row(
    context: OperationalToolEligibilityInput,
) -> dict[str, Any]:
    """Safe debug metadata for UI/reporting (no secrets, no raw API payloads)."""
    results = evaluate_all_tool_eligibility(context)
    eligible_tools: list[str] = []
    blocked_tools: list[str] = []
    blocked_reasons: dict[str, str] = {}
    execution_modes: dict[str, str | None] = {}
    risk_levels: dict[str, str] = {}
    for tool_id, result in results.items():
        key = tool_id.value
        risk_levels[key] = result.tool_risk_level.value if result.tool_risk_level else None
        execution_modes[key] = (
            result.tool_execution_mode.value if result.tool_execution_mode else None
        )
        if result.eligible:
            eligible_tools.append(key)
        else:
            blocked_tools.append(key)
            if result.blocked_reason:
                blocked_reasons[key] = result.blocked_reason
    return {
        "eligible_tools": eligible_tools,
        "blocked_tools": blocked_tools,
        "blocked_reason": blocked_reasons,
        "tool_execution_mode": execution_modes,
        "tool_risk_level": risk_levels,
    }


def build_eligibility_input_from_settings(
    settings: AppSettings | None = None,
    *,
    source_mode: str = SOURCE_MANUAL_SANDBOX_CHAT,
    detected_scenario: str | None = None,
    order_id_present: bool = False,
    tracking_code_present: bool = False,
    carrier_candidate: str | None = "iran_post",
    order_delivered_in_inchand: bool = False,
    manual_trigger: bool = False,
    sandbox_auto_enabled: bool | None = None,
    live_auto_enabled: bool = False,
    scenario_auto_eligible: bool = True,
    inchand_tool_enabled: bool | None = None,
    iran_post_tool_enabled: bool | None = None,
    inchand_token_present: bool | None = None,
    iran_post_token_present: bool | None = None,
) -> OperationalToolEligibilityInput:
    """Build a shared eligibility context; token/tool flags default from settings."""
    cfg = settings or get_settings()
    from app.tools.inchand.order_lookup import resolve_inchand_api_token

    inchand_token = (
        inchand_token_present
        if inchand_token_present is not None
        else bool(resolve_inchand_api_token(cfg))
    )
    iran_token = (
        iran_post_token_present
        if iran_post_token_present is not None
        else bool((cfg.iran_post_tracking_token or "").strip())
    )
    _ = iran_token  # per-tool checks use tool_enabled + token on evaluate path
    if sandbox_auto_enabled is None:
        sandbox_auto_enabled = bool(
            cfg.manual_sandbox_auto_order_lookup_enabled
            or cfg.manual_sandbox_auto_tracking_verify_enabled,
        )
    return OperationalToolEligibilityInput(
        source_mode=source_mode,
        detected_scenario=detected_scenario,
        order_id_present=order_id_present,
        tracking_code_present=tracking_code_present,
        carrier_candidate=carrier_candidate,
        order_delivered_in_inchand=order_delivered_in_inchand,
        manual_trigger=manual_trigger,
        sandbox_auto_enabled=sandbox_auto_enabled,
        live_auto_enabled=live_auto_enabled,
        tool_enabled=True,
        token_present=inchand_token,
        scenario_auto_eligible=scenario_auto_eligible,
    )


def build_inchand_eligibility_context(
    settings: AppSettings | None = None,
    *,
    source_mode: str,
    order_id_present: bool,
    manual_trigger: bool = False,
    sandbox_auto_enabled: bool | None = None,
    live_auto_enabled: bool = False,
    detected_scenario: str | None = None,
    scenario_auto_eligible: bool = True,
    token_present: bool | None = None,
) -> OperationalToolEligibilityInput:
    cfg = settings or get_settings()
    from app.tools.inchand.order_lookup import resolve_inchand_api_token

    if sandbox_auto_enabled is None:
        sandbox_auto_enabled = bool(cfg.manual_sandbox_auto_order_lookup_enabled)
    resolved_token = (
        token_present if token_present is not None else bool(resolve_inchand_api_token(cfg))
    )
    return OperationalToolEligibilityInput(
        source_mode=source_mode,
        detected_scenario=detected_scenario,
        order_id_present=order_id_present,
        manual_trigger=manual_trigger,
        sandbox_auto_enabled=sandbox_auto_enabled,
        live_auto_enabled=live_auto_enabled,
        tool_enabled=bool(cfg.inchand_order_lookup_enabled),
        token_present=resolved_token,
        scenario_auto_eligible=scenario_auto_eligible,
    )


def build_iran_post_eligibility_context(
    settings: AppSettings | None = None,
    *,
    source_mode: str,
    tracking_code_present: bool,
    carrier_candidate: str | None = "iran_post",
    order_delivered_in_inchand: bool = False,
    manual_trigger: bool = False,
    sandbox_auto_enabled: bool | None = None,
    live_auto_enabled: bool = False,
    token_present: bool | None = None,
) -> OperationalToolEligibilityInput:
    cfg = settings or get_settings()
    if sandbox_auto_enabled is None:
        sandbox_auto_enabled = bool(cfg.manual_sandbox_auto_tracking_verify_enabled)
    resolved_token = (
        token_present
        if token_present is not None
        else bool((cfg.iran_post_tracking_token or "").strip())
    )
    return OperationalToolEligibilityInput(
        source_mode=source_mode,
        tracking_code_present=tracking_code_present,
        carrier_candidate=carrier_candidate,
        order_delivered_in_inchand=order_delivered_in_inchand,
        manual_trigger=manual_trigger,
        sandbox_auto_enabled=sandbox_auto_enabled,
        live_auto_enabled=live_auto_enabled,
        tool_enabled=bool(cfg.iran_post_tracking_enabled),
        token_present=resolved_token,
    )


def tool_registry_metadata_captions_fa(
    result: OperationalToolEligibilityResult,
    *,
    definition: OperationalToolDefinition | None = None,
) -> list[str]:
    """Short FA captions for operator UI (execution mode, risk, availability)."""
    registry = get_operational_tool_registry()
    defn = definition or registry.get(result.tool_id)
    lines: list[str] = []
    if result.eligible:
        if result.sandbox_auto_allowed:
            lines.append("حالت اجرا: خودکار (فقط sandbox)")
        elif result.manual_allowed:
            lines.append("حالت اجرا: دستی")
    else:
        lines.append("ابزار در این زمینه غیرفعال است")
        if result.blocked_reason:
            lines.append(f"دلیل: {result.blocked_reason}")
    risk_label = "پایین" if defn.risk_level == OperationalToolRiskLevel.LOW else "متوسط"
    lines.append(f"سطح ریسک: {risk_label} (خواندنی)")
    if OperationalToolExecutionMode.LIVE_AUTO_DISALLOWED in defn.execution_modes:
        lines.append("اجرای خودکار در API زنده غیرفعال است")
    return lines

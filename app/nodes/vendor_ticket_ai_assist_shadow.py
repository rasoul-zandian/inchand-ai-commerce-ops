"""Shadow LangGraph node: vendor-ticket AI operational assist metadata only (feature-flagged)."""

from __future__ import annotations

from app.config import get_settings
from app.schemas.workflow import ToolError
from app.state.ai_assist_state import (
    apply_ai_assist_result_to_state,
    build_sanitized_ai_assist_payload,
    sanitize_ai_assist_state_snapshot,
)
from app.state.commerce_state import CommerceAIState
from app.workflows.vendor_ticket_ai_assist_shadow import evaluate_vendor_ticket_ai_assist_shadow

from .common import _append_audit

_NODE_NAME = "vendor_ticket_ai_assist_shadow"


def vendor_ticket_ai_assist_shadow(state: CommerceAIState) -> CommerceAIState:
    """Run shadow AI assist when VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=true."""
    settings = get_settings()
    if not settings.vendor_ticket_ai_assist_shadow_enabled:
        return state

    try:
        payload = build_sanitized_ai_assist_payload(state)
        result = evaluate_vendor_ticket_ai_assist_shadow(payload)
        apply_ai_assist_result_to_state(state, result)
        snapshot = sanitize_ai_assist_state_snapshot(state)
        state["audit_log"] = _append_audit(
            state.get("audit_log") or [],
            node_name=_NODE_NAME,
            message="vendor ticket AI assist shadow completed",
            metadata={"ai_assist_snapshot": snapshot},
        )
        return state
    except ValueError as exc:
        state["ai_assist_shadow_generated"] = False
        state["ai_assist_human_review_required"] = True
        state["ai_assist_shadow_only"] = True
        state["errors"] = [
            *(state.get("errors") or []),
            ToolError(
                tool_name=_NODE_NAME,
                error_type="ai_assist_shadow_rejected",
                message="AI assist shadow input rejected; workflow continues",
            ),
        ]
        state["audit_log"] = _append_audit(
            state.get("audit_log") or [],
            node_name=_NODE_NAME,
            message="vendor ticket AI assist shadow rejected",
            metadata={"reason": str(exc)},
        )
        return state
    except Exception as exc:  # noqa: BLE001 — fail closed; workflow continues
        state["ai_assist_shadow_generated"] = False
        state["ai_assist_human_review_required"] = True
        state["ai_assist_shadow_only"] = True
        state["errors"] = [
            *(state.get("errors") or []),
            ToolError(
                tool_name=_NODE_NAME,
                error_type="ai_assist_shadow_failed",
                message="AI assist shadow failed; workflow continues",
            ),
        ]
        state["audit_log"] = _append_audit(
            state.get("audit_log") or [],
            node_name=_NODE_NAME,
            message="vendor ticket AI assist shadow failed",
            metadata={"error_type": type(exc).__name__},
        )
        return state

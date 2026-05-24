"""Read-only HITL panel markdown preview renderer (local mock; no web UI)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.hitl.hitl_payload_builder import assert_hitl_payload_ready
from app.hitl.hitl_visibility_contract import FORBIDDEN_HITL_VISIBLE_FIELDS

_READ_ONLY_SAFETY_FOOTER = "_Read-only. No customer response generated. No auto-send._"
_HUMAN_REVIEW_NOTE = (
    "Operator review is required. This panel shows aggregate assist and retrieval "
    "metadata only — not message text, retrieved hits, or draft/final responses."
)

_FORBIDDEN_MARKDOWN_TOKENS = tuple(
    sorted(
        f'"{key}"'
        for key in FORBIDDEN_HITL_VISIBLE_FIELDS
        if key
        not in {
            "content",
        }
    ),
)


def _display(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        if not value:
            return "—"
        parts = [f"{key}={value[key]}" for key in sorted(value)]
        return ", ".join(parts)
    return str(value)


def assert_hitl_preview_markdown_safe(markdown: str) -> None:
    """Fail closed if preview output may reference forbidden HITL fields."""
    lowered = markdown.lower()
    for token in _FORBIDDEN_MARKDOWN_TOKENS:
        if token in lowered:
            field_name = token.strip('"')
            raise ValueError(
                f"HITL preview must not reference forbidden field: {field_name}",
            )
    for phrase in (
        "sk-",
        "begin private key",
        "openai_api_key",
        "postgresql://",
    ):
        if phrase in lowered:
            raise ValueError(f"HITL preview must not contain forbidden token: {phrase}")


def render_hitl_payload_markdown(payload: Mapping[str, Any]) -> str:
    """Render one HITL read-only panel preview as Markdown."""
    ready_payload = dict(payload)
    assert_hitl_payload_ready(ready_payload)

    room_id = _display(payload.get("room_id"))
    lines = [
        f"## Ticket {room_id}",
        "",
        "### Ticket metadata",
        "",
        f"- **room_id:** {room_id}",
        f"- **ticket_label:** {_display(payload.get('ticket_label'))}",
        f"- **route_label:** {_display(payload.get('route_label'))}",
        f"- **review_priority:** {_display(payload.get('review_priority'))}",
        f"- **assigned_department:** {_display(payload.get('assigned_department'))}",
        "",
        "### Ticket text preview",
        "",
        f"{_display(payload.get('ticket_text_preview'))}",
        "",
        "_Redacted truncated preview only — not the full transcript._",
        "",
        "### Open ticket snapshot",
        "",
        (
            "- **original_vendor_issue_preview:** "
            f"{_display(payload.get('original_vendor_issue_preview'))}"
        ),
        f"- **latest_vendor_message:** {_display(payload.get('latest_vendor_message'))}",
        f"- **recent_context_preview:** {_display(payload.get('recent_context_preview'))}",
        f"- **open_ticket_preview:** {_display(payload.get('open_ticket_preview'))}",
        "",
        (
            "_Operational slice at the latest vendor turn — no post-vendor support lines, "
            "no messages array._"
        ),
        "",
        "### AI assist summary",
        "",
        f"- **shadow_generated:** {_display(payload.get('ai_assist_shadow_generated'))}",
        f"- **suggested_priority:** {_display(payload.get('ai_assist_suggested_priority'))}",
        (
            "- **escalation_recommended:** "
            f"{_display(payload.get('ai_assist_escalation_recommended'))}"
        ),
        f"- **duplicate_possible:** {_display(payload.get('ai_assist_duplicate_possible'))}",
        f"- **suggested_action:** {_display(payload.get('ai_assist_suggested_action'))}",
        f"- **confidence_band:** {_display(payload.get('ai_assist_confidence_band'))}",
        (
            "- **human_review_required:** "
            f"{_display(payload.get('ai_assist_human_review_required'))}"
        ),
        f"- **shadow_only:** {_display(payload.get('ai_assist_shadow_only'))}",
        "",
        "### Retrieval aggregate summary",
        "",
        f"- **gate_decision:** {_display(payload.get('retrieval_gate_decision'))}",
        f"- **scenario:** {_display(payload.get('retrieval_scenario'))}",
        f"- **result_count:** {_display(payload.get('retrieval_result_count'))}",
        f"- **metadata_filter:** {_display(payload.get('retrieval_metadata_filter'))}",
        f"- **sandbox_only:** {_display(payload.get('retrieval_sandbox_only'))}",
        f"- **retrieval_activated:** {_display(payload.get('retrieval_activated'))}",
        "",
        "### Human review note",
        "",
        _HUMAN_REVIEW_NOTE,
        "",
        _READ_ONLY_SAFETY_FOOTER,
        "",
    ]
    markdown = "\n".join(lines)
    assert_hitl_preview_markdown_safe(markdown)
    return markdown


def render_hitl_payloads_markdown(payloads: Sequence[Mapping[str, Any]]) -> str:
    """Render multiple HITL read-only panel previews as one Markdown document."""
    if not payloads:
        raise ValueError("at least one HITL payload is required for preview")

    sections = [render_hitl_payload_markdown(payload) for payload in payloads]
    header = [
        "# HITL Read-Only Panel Preview",
        "",
        "Local mock preview only. Aggregate metadata — no customer-facing behavior.",
        "",
        "---",
        "",
    ]
    body = "\n\n---\n\n".join(sections)
    markdown = "\n".join(header) + body
    assert_hitl_preview_markdown_safe(markdown)
    return markdown

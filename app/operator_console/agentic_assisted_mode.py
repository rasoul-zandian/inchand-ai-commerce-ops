"""Operator-assisted agentic mode — structured HITL review package (session-only)."""

from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agentic_sandbox.graduation_criteria import (
    DEFAULT_GRADUATION_SUMMARY_PATH,
    OverallGraduationStatus,
)
from app.config import AppSettings, get_settings
from app.operator_console.agentic_sandbox_preview import (
    _FORBIDDEN_PREVIEW_KEYS,
    _FORBIDDEN_PREVIEW_SUBSTRINGS,
    AgenticSandboxPreviewResult,
    _collect_mapping_keys,
    _iter_string_values,
    render_agentic_preview_markdown_or_lines,
    run_agentic_preview_for_ticket,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.i18n import (
    DEFAULT_CONSOLE_LANG,
    assisted_checklist_for_lang,
    t,
)

SESSION_AGENTIC_ASSISTED_KEY = "operator_agentic_assisted_packages"

_FORBIDDEN_ASSISTED_KEYS = _FORBIDDEN_PREVIEW_KEYS | frozenset({"customer_send"})

OPERATOR_ASSISTED_CHECKLIST: tuple[str, ...] = (
    "Verify detected intent matches the first seller message.",
    "Verify extracted entities (order/product IDs, tracking, masked IBAN).",
    "Verify actionability and any missing identifiers before operational steps.",
    "Verify draft text in the internal draft block below before use.",
    "Do not send customer replies from this mode; execution and send remain disabled.",
)

_FEEDBACK_NOTE = (
    "Review this graph output using **Sandbox preview review** below "
    "(same `agentic_preview_review_feedback.jsonl` schema)."
)


@dataclass(frozen=True)
class AgenticAssistedPackage:
    """Structured operator work package from the sandbox graph (HITL-only)."""

    room_id: str
    graph: AgenticSandboxPreviewResult
    operator_checklist: tuple[str, ...]
    graduation_overall_status: str | None
    graduation_gate_passed: bool

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "graph": self.graph.to_public_dict(),
            "operator_checklist": list(self.operator_checklist),
            "graduation_overall_status": self.graduation_overall_status,
            "graduation_gate_passed": self.graduation_gate_passed,
            "feedback_note": _FEEDBACK_NOTE,
        }


def load_graduation_status(
    path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Load graduation summary JSON; return None if missing or invalid."""
    summary_path = Path(path) if path is not None else DEFAULT_GRADUATION_SUMMARY_PATH
    if not summary_path.is_file():
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def is_graduation_ready_for_assisted(status: Mapping[str, Any] | None) -> bool:
    if status is None:
        return False
    return (
        str(status.get("overall_status") or "")
        == OverallGraduationStatus.READY_FOR_OPERATOR_ASSISTED_PHASE.value
    )


def is_agentic_assisted_mode_allowed(
    settings: AppSettings,
    *,
    graduation_path: Path | str | None = None,
) -> tuple[bool, str | None]:
    """Return (allowed, reason). Disabled flag or graduation gate yields not allowed."""
    if not settings.operator_agentic_assisted_mode_enabled:
        return False, "operator-assisted agentic mode is disabled"
    if settings.operator_agentic_assisted_require_graduation_ready:
        status = load_graduation_status(graduation_path)
        if not is_graduation_ready_for_assisted(status):
            overall = (status or {}).get("overall_status", "missing")
            return (
                False,
                "graduation gate not satisfied: overall_status must be "
                f"ready_for_operator_assisted_phase (observed: {overall})",
            )
    return True, None


def _assisted_runtime_settings(settings: AppSettings) -> AppSettings:
    return settings.model_copy(
        update={
            "operator_agentic_sandbox_provider": settings.operator_agentic_assisted_provider,
            "operator_agentic_sandbox_knowledge_hints_enabled": (
                settings.operator_agentic_assisted_knowledge_hints_enabled
            ),
            "knowledge_hints_enabled": settings.operator_agentic_assisted_knowledge_hints_enabled,
        },
    )


def build_agentic_assisted_package(
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
    graduation_path: Path | str | None = None,
    conversation_snapshot: Any | None = None,
    source_mode: str = "historical_replay",
) -> AgenticAssistedPackage:
    """Run sandbox graph and wrap results in an operator-assisted review package."""
    cfg = settings or get_settings()
    allowed, reason = is_agentic_assisted_mode_allowed(cfg, graduation_path=graduation_path)
    if not allowed:
        raise ValueError(reason or "operator-assisted agentic mode not allowed")

    runtime = _assisted_runtime_settings(cfg)
    graph = run_agentic_preview_for_ticket(
        ticket,
        settings=runtime,
        conversation_snapshot=conversation_snapshot,
        source_mode=source_mode,
    )
    graduation = load_graduation_status(graduation_path)
    package = AgenticAssistedPackage(
        room_id=ticket.room_id,
        graph=graph,
        operator_checklist=OPERATOR_ASSISTED_CHECKLIST,
        graduation_overall_status=(str(graduation.get("overall_status")) if graduation else None),
        graduation_gate_passed=is_graduation_ready_for_assisted(graduation),
    )
    assert_agentic_assisted_package_safe(package)
    return package


def sanitize_agentic_assisted_package(package: AgenticAssistedPackage) -> dict[str, Any]:
    """Return a JSON-serializable public dict (no draft body or forbidden keys)."""
    return package.to_public_dict()


def assert_agentic_assisted_package_safe(package: AgenticAssistedPackage) -> None:
    """Fail closed if assisted package violates HITL safety or leaks forbidden fields."""
    graph = package.graph
    if graph.execution_allowed is not False:
        raise ValueError("agentic assisted package requires execution_allowed=false")
    if graph.customer_send_allowed is not False:
        raise ValueError("agentic assisted package requires customer_send_allowed=false")
    if graph.human_review_required is not True:
        raise ValueError("agentic assisted package requires human_review_required=true")

    public = package.to_public_dict()
    for key in _collect_mapping_keys(public):
        if key in _FORBIDDEN_ASSISTED_KEYS:
            raise ValueError(f"agentic assisted package must not contain forbidden key: {key}")
    for text in _iter_string_values(public):
        lowered = text.lower()
        for token in _FORBIDDEN_PREVIEW_SUBSTRINGS:
            if token.lower() in lowered:
                raise ValueError(
                    f"agentic assisted package must not contain forbidden token: {token}",
                )


def render_agentic_assisted_package_lines(
    package: AgenticAssistedPackage,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
) -> list[str]:
    """Markdown lines for Streamlit assisted-mode section."""
    lines = [t("operator_checklist_heading", lang)]
    for item in assisted_checklist_for_lang(lang):
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            (
                f"- **Graduation gate:** "
                f"{'passed' if package.graduation_gate_passed else 'not passed'}"
            ),
            f"- **graduation_overall_status:** {package.graduation_overall_status or '—'}",
            "",
            t("structured_assistance_heading", lang),
        ],
    )
    lines.extend(render_agentic_preview_markdown_or_lines(package.graph, lang=lang))
    lines.extend(["", f"_{t('assisted_feedback_note', lang)}_"])
    return lines


def get_session_agentic_assisted_package(
    session_state: Mapping[str, Any],
    room_id: str,
) -> AgenticAssistedPackage | None:
    bucket = session_state.get(SESSION_AGENTIC_ASSISTED_KEY, {})
    if not isinstance(bucket, dict):
        return None
    value = bucket.get(room_id)
    if isinstance(value, AgenticAssistedPackage):
        return value
    return None


def store_session_agentic_assisted_package(
    session_state: MutableMapping[str, Any],
    package: AgenticAssistedPackage,
) -> None:
    bucket = session_state.setdefault(SESSION_AGENTIC_ASSISTED_KEY, {})
    if not isinstance(bucket, dict):
        bucket = {}
        session_state[SESSION_AGENTIC_ASSISTED_KEY] = bucket
    bucket[package.room_id] = package

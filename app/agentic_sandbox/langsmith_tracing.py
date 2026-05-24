"""Optional LangSmith tracing for agentic sandbox runs (observability only)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

from app.config import AppSettings, get_settings

DEFAULT_AGENTIC_SANDBOX_LANGSMITH_PROJECT = "inchand-agentic-sandbox"


@dataclass(frozen=True)
class LangSmithTracingStatus:
    """Outcome of sandbox tracing configuration (no secrets in repr)."""

    enabled: bool
    project: str
    api_key_present: bool
    warning: str | None = None
    langsmith_run_note: str | None = None

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "langsmith_tracing_enabled": self.enabled,
            "langsmith_project": self.project,
            "langsmith_api_key_present": self.api_key_present,
            "langsmith_warning": self.warning,
            "langsmith_run_note": self.langsmith_run_note,
        }


def resolve_langsmith_api_key(
    *,
    settings: AppSettings | None = None,
    explicit_key: str | None = None,
) -> str | None:
    """Resolve API key from explicit arg, env, or settings (never log the value)."""
    if explicit_key and str(explicit_key).strip():
        return str(explicit_key).strip()
    env_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    if env_key and str(env_key).strip():
        return str(env_key).strip()
    cfg = settings or get_settings()
    if cfg.langsmith_api_key and str(cfg.langsmith_api_key).strip():
        return str(cfg.langsmith_api_key).strip()
    return None


def configure_agentic_sandbox_langsmith_tracing(
    *,
    enabled: bool | None = None,
    project: str | None = None,
    settings: AppSettings | None = None,
    emit_warnings: bool = True,
) -> LangSmithTracingStatus:
    """
    Configure LangChain/LangSmith tracing env vars for a sandbox run.

    Does not require LangSmith when disabled. When enabled without API key,
    prints a warning and continues with tracing off.
    """
    cfg = settings or get_settings()
    want_enabled = (
        bool(enabled)
        if enabled is not None
        else bool(cfg.langsmith_tracing_enabled or cfg.langsmith_tracing)
    )
    project_name = (
        project or cfg.langsmith_project or DEFAULT_AGENTIC_SANDBOX_LANGSMITH_PROJECT
    ).strip() or DEFAULT_AGENTIC_SANDBOX_LANGSMITH_PROJECT

    if not want_enabled:
        return LangSmithTracingStatus(
            enabled=False,
            project=project_name,
            api_key_present=bool(resolve_langsmith_api_key(settings=cfg)),
            langsmith_run_note=None,
        )

    api_key = resolve_langsmith_api_key(settings=cfg)
    if not api_key:
        warning = (
            "LangSmith tracing requested but LANGSMITH_API_KEY (or LANGCHAIN_API_KEY) "
            "is not set — continuing without tracing."
        )
        if emit_warnings:
            print(f"agentic_sandbox: warning: {warning}", file=sys.stderr)
        return LangSmithTracingStatus(
            enabled=False,
            project=project_name,
            api_key_present=False,
            warning=warning,
        )

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = project_name
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = project_name

    return LangSmithTracingStatus(
        enabled=True,
        project=project_name,
        api_key_present=True,
        langsmith_run_note="Open LangSmith dashboard if configured",
    )

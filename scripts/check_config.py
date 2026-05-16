#!/usr/bin/env python3
"""Validate local AppSettings / .env without network, workflows, or secret output."""

from __future__ import annotations

import sys

from app.config import AppSettings
from pydantic import ValidationError

_SECRET_FIELD_NAMES = frozenset(
    {
        "openai_api_key",
        "langsmith_api_key",
    }
)


def format_rag_profile(value: str | None) -> str:
    """Display helper for optional profile (never a secret)."""
    return "<none>" if value is None else value


def build_safe_config_lines(settings: AppSettings) -> list[str]:
    """Return safe, non-secret config lines for human-readable output."""
    return [
        f"  environment={settings.environment}",
        f"  llm_provider={settings.llm_provider}",
        f"  embedding_provider={settings.embedding_provider}",
        f"  rag_profile={format_rag_profile(settings.rag_profile)}",
        f"  rag_strategy={settings.rag_strategy}",
        f"  rag_top_k={settings.rag_top_k}",
    ]


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = str(err.get("msg", "validation error"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else str(exc)


def run_config_check() -> int:
    """Load AppSettings and print a safe summary. Returns 0 on success, 1 on failure."""
    try:
        settings = AppSettings()
    except ValidationError as exc:
        print("config check: failed", file=sys.stderr)
        print(f"  {_format_validation_error(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:
        print("config check: failed", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    print("config check: passed")
    for line in build_safe_config_lines(settings):
        print(line)
    return 0


def main() -> int:
    return run_config_check()


if __name__ == "__main__":
    raise SystemExit(main())

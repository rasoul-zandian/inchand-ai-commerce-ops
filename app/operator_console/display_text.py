"""Display-only text cleanup for operator console (does not alter redaction or prompts)."""

from __future__ import annotations

import re

_REDACTION_PLACEHOLDER_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("[PHONE_NUMBER]", "«شماره تماس حذف شده»"),
    ("[IBAN]", "«شماره شبا حذف شده»"),
    ("[EMAIL]", "«ایمیل حذف شده»"),
    ("[CARD_NUMBER]", "«شماره کارت حذف شده»"),
    ("[ADDRESS]", "«آدرس حذف شده»"),
)

_MULTI_SPACE = re.compile(r"[^\S\n]+")


def clean_redaction_placeholders_for_display(text: str) -> str:
    """Replace PII redaction tokens with short Persian labels for operator UI."""
    if not text:
        return text
    cleaned = text
    for placeholder, label in _REDACTION_PLACEHOLDER_REPLACEMENTS:
        cleaned = cleaned.replace(placeholder, label)
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    lines = [line.strip() for line in cleaned.splitlines()]
    return "\n".join(lines).strip() if lines else cleaned.strip()

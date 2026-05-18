"""Deterministic regex-based PII redaction for conversation ticket exports (offline only)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot

_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
)
_IBAN_IR_PATTERN = re.compile(r"\bIR(?:[\s\-]*\d){22,26}\b", re.IGNORECASE)
_IBAN_GENERIC_PATTERN = re.compile(r"\b[A-Z]{2}[\s\-]*\d{2}[\s\-]*(?:[A-Z0-9][\s\-]*){11,30}\b")
_PHONE_IR_MOBILE_PATTERN = re.compile(
    r"\b(?:\+?98[\s\-]?)?0?9[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b",
)
_PHONE_GENERIC_PATTERN = re.compile(
    r"\b(?:\+?\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]?\d{3}[\s\-]?\d{4,7}\b",
)
_CARD_PATTERN = re.compile(r"\b(?:\d[\s\-]?){13,19}\b")

_FORBIDDEN_OUTPUT_SUBSTRINGS = (
    "sk-",
    "OPENAI_API_KEY",
    "BEGIN PRIVATE KEY",
    "postgresql://",
)


class PIIRedactionType(StrEnum):
    PHONE_NUMBER = "phone_number"
    CARD_NUMBER = "card_number"
    IBAN = "iban"
    EMAIL = "email"


_PLACEHOLDERS = {
    PIIRedactionType.EMAIL: "[EMAIL]",
    PIIRedactionType.IBAN: "[IBAN]",
    PIIRedactionType.PHONE_NUMBER: "[PHONE_NUMBER]",
    PIIRedactionType.CARD_NUMBER: "[CARD_NUMBER]",
}


@dataclass(frozen=True)
class PIIRedactionResult:
    redacted_text: str
    redaction_counts: dict[str, int]
    changed: bool


def _digit_count(value: str) -> int:
    return sum(1 for char in value if char.isdigit())


def _apply_pattern(
    text: str,
    pattern: re.Pattern[str],
    *,
    redaction_type: PIIRedactionType,
    counts: Counter[str],
    min_digits: int | None = None,
    max_digits: int | None = None,
) -> str:
    placeholder = _PLACEHOLDERS[redaction_type]

    def _replacer(match: re.Match[str]) -> str:
        matched = match.group(0)
        if min_digits is not None or max_digits is not None:
            digits = _digit_count(matched)
            if min_digits is not None and digits < min_digits:
                return matched
            if max_digits is not None and digits > max_digits:
                return matched
        counts[redaction_type.value] += 1
        return placeholder

    return pattern.sub(_replacer, text)


def redact_pii_text(text: str) -> PIIRedactionResult:
    """Redact phone, card, IBAN, and email patterns; never returns matched values."""
    counts: Counter[str] = Counter()
    redacted = text

    redacted = _apply_pattern(
        redacted,
        _IBAN_IR_PATTERN,
        redaction_type=PIIRedactionType.IBAN,
        counts=counts,
    )
    redacted = _apply_pattern(
        redacted,
        _IBAN_GENERIC_PATTERN,
        redaction_type=PIIRedactionType.IBAN,
        counts=counts,
        min_digits=15,
    )
    redacted = _apply_pattern(
        redacted,
        _EMAIL_PATTERN,
        redaction_type=PIIRedactionType.EMAIL,
        counts=counts,
    )
    redacted = _apply_pattern(
        redacted,
        _PHONE_IR_MOBILE_PATTERN,
        redaction_type=PIIRedactionType.PHONE_NUMBER,
        counts=counts,
    )
    redacted = _apply_pattern(
        redacted,
        _PHONE_GENERIC_PATTERN,
        redaction_type=PIIRedactionType.PHONE_NUMBER,
        counts=counts,
        min_digits=10,
        max_digits=15,
    )
    redacted = _apply_pattern(
        redacted,
        _CARD_PATTERN,
        redaction_type=PIIRedactionType.CARD_NUMBER,
        counts=counts,
        min_digits=13,
        max_digits=19,
    )

    return PIIRedactionResult(
        redacted_text=redacted,
        redaction_counts=dict(counts),
        changed=redacted != text,
    )


def redact_conversation_snapshot(
    snapshot: ConversationTicketSnapshot,
) -> tuple[ConversationTicketSnapshot, dict[str, int]]:
    """Redact message text only; preserve order and non-message fields."""
    aggregate: Counter[str] = Counter()
    redacted_messages: list[ConversationMessage] = []

    for message in snapshot.messages:
        result = redact_pii_text(message.text)
        aggregate.update(result.redaction_counts)
        redacted_messages.append(message.model_copy(update={"text": result.redacted_text}))

    redacted_snapshot = snapshot.model_copy(update={"messages": redacted_messages})
    return redacted_snapshot, dict(aggregate)


def assert_redacted_export_safe(serialized: str) -> None:
    """Reject redacted output that accidentally contains secret-like tokens."""
    lowered = serialized.lower()
    for token in _FORBIDDEN_OUTPUT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"redacted output must not contain forbidden token: {token}")

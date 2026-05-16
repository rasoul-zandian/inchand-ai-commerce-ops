"""Deterministic, local-only anonymization helpers (no I/O, network, or database)."""

from __future__ import annotations

import hashlib
import re

from app.schemas.ticket_data import VendorTicketRecord

_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
)
_IBAN_IR_PATTERN = re.compile(r"\bIR\d{22,26}\b", re.IGNORECASE)
_MOBILE_IR_PATTERN = re.compile(r"\b09\d{9}\b")
_LONG_DIGITS_PATTERN = re.compile(r"\b\d{10,}\b")


def hash_identifier(value: str, *, salt: str = "inchand-local-dev") -> str:
    """Return a short deterministic SHA-256 digest prefix (hex, first 16 chars)."""
    payload = f"{salt}:{value}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def mask_sensitive_text(text: str) -> str:
    """Mask common sensitive patterns; return input unchanged if empty."""
    if not text:
        return text

    masked = text
    masked = _EMAIL_PATTERN.sub("[MASKED_EMAIL]", masked)
    masked = _IBAN_IR_PATTERN.sub("[MASKED_IBAN]", masked)
    masked = _MOBILE_IR_PATTERN.sub("[MASKED_PHONE]", masked)
    masked = _LONG_DIGITS_PATTERN.sub("[MASKED_NUMBER]", masked)
    return masked


def anonymize_ticket_record(record: VendorTicketRecord) -> VendorTicketRecord:
    """Return a new ticket record with hashed vendor id field, masked text fields, and flag."""
    new_metadata = {**record.metadata, "anonymized": True}
    vendor_hashed = hash_identifier(record.vendor_id_hash) if record.vendor_id_hash else None
    return record.model_copy(
        update={
            "vendor_id_hash": vendor_hashed,
            "subject": mask_sensitive_text(record.subject),
            "body": mask_sensitive_text(record.body),
            "support_reply": (
                mask_sensitive_text(record.support_reply)
                if record.support_reply is not None
                else None
            ),
            "metadata": new_metadata,
        },
    )

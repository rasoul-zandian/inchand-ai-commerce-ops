"""Live feed adapter contract validation (integration spec enforcement)."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import AppSettings, get_settings
from app.privacy_review.redaction import (
    _CARD_PATTERN,
    _EMAIL_PATTERN,
    _FORBIDDEN_OUTPUT_SUBSTRINGS,
    _IBAN_GENERIC_PATTERN,
    _IBAN_IR_PATTERN,
    _PHONE_GENERIC_PATTERN,
    _PHONE_IR_MOBILE_PATTERN,
)
from app.tickets.conversation_models import parse_conversation_ticket_snapshot

DEFAULT_VALIDATION_SUMMARY_PATH = Path("reports/live_feed_contract_validation_summary.json")
DEFAULT_VALIDATION_REPORT_PATH = Path("reports/live_feed_contract_validation_report.md")

CONTRACT_VERSION = "live_feed_adapter_v1"

_ALLOWED_SENDER_TYPES = frozenset(
    {"seller", "support_agent", "finance_agent", "system", "unknown"},
)
_INBOUND_SENDER_TYPES = _ALLOWED_SENDER_TYPES | {
    "vendor",
    "admin",
    "support",
    "operator",
    "finance",
    "accounting",
    "internal",
}
_SENDER_NORMALIZATION: dict[str, str] = {
    "vendor": "seller",
    "admin": "support_agent",
    "support": "support_agent",
    "operator": "support_agent",
    "finance": "finance_agent",
    "accounting": "finance_agent",
    "internal": "system",
}
_ACCEPTED_PLACEHOLDERS = (
    "[PHONE_NUMBER]",
    "[IBAN]",
    "[EMAIL]",
    "[CARD_NUMBER]",
    "[ADDRESS]",
)
_FORBIDDEN_ROW_KEYS = frozenset(
    {
        "api_key",
        "openai_api_key",
        "auth_token",
        "authorization",
        "password",
        "secret",
        "jwt",
        "bearer_token",
        "session_cookie",
        "cookie",
        "user_input",
        "raw_prompt",
        "draft_reply",
        "messages_raw",
        "conversation_transcript",
        "transcript",
        "retrieved_context",
        "gold_reference_reply",
        "attachment_body",
        "file_bytes",
    },
)
_REQUIRED_TICKET_FIELDS = ("room_id", "status", "created_at", "updated_at", "messages")
_REQUIRED_MESSAGE_FIELDS = ("message_id", "sender_type", "text", "created_at")
_MESSAGE_TIME_ALIASES = ("created_at", "timestamp")
_FORBIDDEN_REPORT_TOKENS = (
    "conversation transcript",
    '"messages"',
    "raw_prompt",
    "user_input",
    "draft_reply",
    "sk-",
    "begin private key",
    "postgresql://",
)
_JWT_PATTERN = re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}")
_BEARER_PATTERN = re.compile(r"Bearer\s+[a-zA-Z0-9._\-]{20,}", re.IGNORECASE)
_SESSION_COOKIE_PATTERN = re.compile(
    r"(sessionid|set-cookie|session=)[^\s]{8,}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LiveFeedRowValidationResult:
    """Validation outcome for one feed row."""

    line_number: int | None
    room_id: str | None
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    info: tuple[str, ...] = ()
    normalized: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "line_number": self.line_number,
            "room_id": self.room_id,
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "info": list(self.info),
            "normalized": self.normalized,
        }


@dataclass
class LiveFeedContractValidationSummary:
    """Aggregate validation summary for a live feed JSONL file."""

    contract_version: str
    generated_at_utc: str
    source_path: str
    total_lines: int
    empty_lines: int
    valid_rows: int
    invalid_rows: int
    warning_rows: int
    info_rows: int
    allow_raw_pii_internal_pilot: bool
    raw_identifier_info_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    first_sender_counts: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)
    sample_invalid_room_ids: tuple[str, ...] = ()
    passed: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "generated_at_utc": self.generated_at_utc,
            "source_path": self.source_path,
            "total_lines": self.total_lines,
            "empty_lines": self.empty_lines,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "warning_rows": self.warning_rows,
            "info_rows": self.info_rows,
            "allow_raw_pii_internal_pilot": self.allow_raw_pii_internal_pilot,
            "raw_identifier_info_counts": dict(self.raw_identifier_info_counts),
            "status_counts": dict(self.status_counts),
            "first_sender_counts": dict(self.first_sender_counts),
            "error_counts": dict(self.error_counts),
            "warning_counts": dict(self.warning_counts),
            "sample_invalid_room_ids": list(self.sample_invalid_room_ids),
            "passed": self.passed,
        }


def resolve_allow_raw_pii_internal_pilot(
    *,
    allow_raw_pii_internal_pilot: bool | None = None,
    settings: AppSettings | None = None,
) -> bool:
    """Resolve internal-pilot raw identifier policy (default: allow)."""
    if allow_raw_pii_internal_pilot is not None:
        return allow_raw_pii_internal_pilot
    cfg = settings or get_settings()
    return cfg.allow_raw_pii_internal_pilot


def _detect_raw_identifier_types(text: str) -> tuple[str, ...]:
    """Return identifier categories present in text (informational only)."""
    found: list[str] = []
    if _EMAIL_PATTERN.search(text):
        found.append("email")
    if _PHONE_IR_MOBILE_PATTERN.search(text) or _PHONE_GENERIC_PATTERN.search(text):
        found.append("phone")
    if _IBAN_IR_PATTERN.search(text) or _IBAN_GENERIC_PATTERN.search(text):
        found.append("iban")
    if _CARD_PATTERN.search(text):
        found.append("card")
    return tuple(dict.fromkeys(found))


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _parse_iso_timestamp(value: Any, *, field_name: str) -> datetime:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{field_name} must be non-empty")
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"{field_name} is not valid ISO-8601") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def normalize_sender_type(value: str) -> str:
    """Normalize inbound sender_type to contract allowed values."""
    raw = value.strip().lower()
    if not raw:
        raise ValueError("sender_type must be non-empty")
    if raw in _SENDER_NORMALIZATION:
        return _SENDER_NORMALIZATION[raw]
    if raw in _ALLOWED_SENDER_TYPES:
        return raw
    raise ValueError(f"unsupported sender_type: {value}")


def _find_forbidden_keys(payload: Any, *, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_lower = str(key).strip().lower()
            path = f"{prefix}.{key}" if prefix else key_lower
            if key_lower in _FORBIDDEN_ROW_KEYS:
                found.append(path)
            found.extend(_find_forbidden_keys(value, prefix=path))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            found.extend(_find_forbidden_keys(item, prefix=f"{prefix}[{index}]"))
    return found


def _scan_secret_patterns(text: str) -> list[str]:
    issues: list[str] = []
    lowered = text.lower()
    for token in _FORBIDDEN_OUTPUT_SUBSTRINGS:
        if token.lower() in lowered:
            issues.append(f"forbidden_secret_pattern:{token}")
    if re.search(r"sk-[a-z0-9]{8,}", text, flags=re.IGNORECASE):
        issues.append("forbidden_secret_pattern:api_key_prefix")
    if _JWT_PATTERN.search(text):
        issues.append("forbidden_secret_pattern:jwt")
    if _BEARER_PATTERN.search(text):
        issues.append("forbidden_secret_pattern:bearer_token")
    if _SESSION_COOKIE_PATTERN.search(text):
        issues.append("forbidden_secret_pattern:session_cookie")
    return issues


def normalize_live_ticket_row(row: Mapping[str, Any] | str) -> dict[str, Any]:
    """Normalize a live feed row to conversation snapshot shape (no side effects)."""
    if isinstance(row, str):
        data: dict[str, Any] = json.loads(row)
    else:
        data = dict(row)

    normalized_messages: list[dict[str, Any]] = []
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise ValueError("messages must be a non-empty list")

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"messages[{index}] must be an object")
        msg = dict(message)
        sender_raw = msg.get("sender_type")
        if not isinstance(sender_raw, str):
            raise ValueError(f"messages[{index}].sender_type is required")
        msg["sender_type"] = normalize_sender_type(sender_raw)
        ts_value = None
        for alias in _MESSAGE_TIME_ALIASES:
            if msg.get(alias) is not None:
                ts_value = msg.get(alias)
                break
        if ts_value is None:
            raise ValueError(f"messages[{index}] requires created_at or timestamp")
        msg["timestamp"] = _parse_iso_timestamp(ts_value, field_name=f"messages[{index}].time")
        msg.pop("created_at", None)
        normalized_messages.append(msg)

    ticket_label = data.get("ticket_label")
    if ticket_label is None or not str(ticket_label).strip():
        ticket_label = "unknown"

    normalized: dict[str, Any] = {
        "room_id": str(data["room_id"]).strip(),
        "ticket_label": str(ticket_label).strip(),
        "status": str(data["status"]).strip().lower(),
        "created_at": _parse_iso_timestamp(data["created_at"], field_name="created_at"),
        "messages": normalized_messages,
        "metadata": dict(data.get("metadata") or {}),
    }
    if data.get("updated_at") is not None:
        normalized["metadata"]["updated_at"] = _parse_iso_timestamp(
            data["updated_at"],
            field_name="updated_at",
        ).isoformat()
    if data.get("route_label") is not None:
        normalized["metadata"]["route_label"] = str(data["route_label"]).strip()
    for optional in ("vendor_id_hash", "seller_id_hash", "source_system", "priority"):
        if data.get(optional) is not None:
            normalized["metadata"][optional] = data[optional]
    if data.get("closed_at") is not None:
        normalized["closed_at"] = _parse_iso_timestamp(data["closed_at"], field_name="closed_at")
    if isinstance(data.get("attachments"), list):
        normalized["metadata"]["attachments"] = data["attachments"]
    return normalized


def validate_live_ticket_row(
    row: Mapping[str, Any] | str,
    *,
    line_number: int | None = None,
    allow_raw_pii_internal_pilot: bool | None = None,
    settings: AppSettings | None = None,
) -> LiveFeedRowValidationResult:
    """Validate one live feed row against the adapter contract."""
    allow_raw_pii = resolve_allow_raw_pii_internal_pilot(
        allow_raw_pii_internal_pilot=allow_raw_pii_internal_pilot,
        settings=settings,
    )
    errors: list[str] = []
    warnings: list[str] = []
    info: list[str] = []
    room_id: str | None = None
    normalized_applied = False

    try:
        if isinstance(row, str):
            data = json.loads(row)
        elif isinstance(row, dict):
            data = row
        else:
            return LiveFeedRowValidationResult(
                line_number=line_number,
                room_id=None,
                valid=False,
                errors=("row_must_be_object",),
                warnings=(),
                info=(),
            )
    except json.JSONDecodeError:
        return LiveFeedRowValidationResult(
            line_number=line_number,
            room_id=None,
            valid=False,
            errors=("invalid_json",),
            warnings=(),
            info=(),
        )

    if not isinstance(data, dict):
        return LiveFeedRowValidationResult(
            line_number=line_number,
            room_id=None,
            valid=False,
            errors=("row_must_be_object",),
            warnings=(),
            info=(),
        )

    raw_room = data.get("room_id")
    if isinstance(raw_room, str) and raw_room.strip():
        room_id = raw_room.strip()

    for key in _find_forbidden_keys(data):
        errors.append(f"forbidden_key:{key}")

    for field_name in _REQUIRED_TICKET_FIELDS:
        if field_name not in data or data[field_name] is None:
            errors.append(f"missing_required:{field_name}")

    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        errors.append("messages_empty")

    if isinstance(messages, list):
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                errors.append(f"messages[{index}]_not_object")
                continue
            for field_name in _REQUIRED_MESSAGE_FIELDS:
                if field_name not in message and not (
                    field_name == "created_at" and message.get("timestamp") is not None
                ):
                    errors.append(f"missing_required:messages[{index}].{field_name}")
            sender = message.get("sender_type")
            if isinstance(sender, str):
                try:
                    normalize_sender_type(sender)
                except ValueError:
                    errors.append(f"invalid_sender_type:messages[{index}]")
            else:
                errors.append(f"invalid_sender_type:messages[{index}]")
            text = message.get("text")
            if not isinstance(text, str) or not text.strip():
                errors.append(f"empty_text:messages[{index}]")
            else:
                for issue in _scan_secret_patterns(text):
                    errors.append(issue)
                identifier_types = _detect_raw_identifier_types(text)
                if identifier_types:
                    joined = ",".join(identifier_types)
                    note = f"raw_identifiers_detected:{joined}:messages[{index}]"
                    if allow_raw_pii:
                        info.append(note)
                    else:
                        errors.append(note)
            ts_value = message.get("created_at", message.get("timestamp"))
            try:
                _parse_iso_timestamp(ts_value, field_name=f"messages[{index}].time")
            except ValueError:
                errors.append(f"invalid_timestamp:messages[{index}]")

    for field_name in ("created_at", "updated_at"):
        if field_name in data:
            try:
                _parse_iso_timestamp(data[field_name], field_name=field_name)
            except ValueError:
                errors.append(f"invalid_timestamp:{field_name}")

    if errors:
        return LiveFeedRowValidationResult(
            line_number=line_number,
            room_id=room_id,
            valid=False,
            errors=tuple(errors),
            warnings=tuple(warnings),
            info=tuple(info),
        )

    try:
        normalized = normalize_live_ticket_row(data)
        normalized_applied = True
        parse_conversation_ticket_snapshot(normalized)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        errors.append(f"normalize_or_parse_failed:{type(exc).__name__}")

    return LiveFeedRowValidationResult(
        line_number=line_number,
        room_id=room_id,
        valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        info=tuple(info),
        normalized=normalized_applied,
    )


def validate_live_feed_jsonl(
    path: Path | str,
    *,
    allow_raw_pii_internal_pilot: bool | None = None,
    settings: AppSettings | None = None,
) -> list[LiveFeedRowValidationResult]:
    """Validate all rows in a live feed JSONL file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"live feed file not found: {file_path}")

    results: list[LiveFeedRowValidationResult] = []
    for line_number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        results.append(
            validate_live_ticket_row(
                line,
                line_number=line_number,
                allow_raw_pii_internal_pilot=allow_raw_pii_internal_pilot,
                settings=settings,
            ),
        )
    return results


def summarize_live_feed_contract_validation(
    path: Path | str,
    *,
    allow_raw_pii_internal_pilot: bool | None = None,
    settings: AppSettings | None = None,
    results: list[LiveFeedRowValidationResult] | None = None,
) -> LiveFeedContractValidationSummary:
    """Validate file and return aggregate summary."""
    allow_raw_pii = resolve_allow_raw_pii_internal_pilot(
        allow_raw_pii_internal_pilot=allow_raw_pii_internal_pilot,
        settings=settings,
    )
    file_path = Path(path)
    row_results = results or validate_live_feed_jsonl(
        file_path,
        allow_raw_pii_internal_pilot=allow_raw_pii,
        settings=settings,
    )

    total_lines = 0
    empty_lines = 0
    if file_path.is_file():
        for line in file_path.read_text(encoding="utf-8").splitlines():
            total_lines += 1
            if not line.strip():
                empty_lines += 1

    valid_rows = sum(1 for item in row_results if item.valid)
    invalid_rows = sum(1 for item in row_results if not item.valid)
    warning_rows = sum(1 for item in row_results if item.warnings)
    info_rows = sum(1 for item in row_results if item.info)

    status_counts: Counter[str] = Counter()
    first_sender_counts: Counter[str] = Counter()
    error_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    raw_identifier_info_counts: Counter[str] = Counter()
    invalid_room_ids: list[str] = []
    all_lines = file_path.read_text(encoding="utf-8").splitlines()

    for item in row_results:
        for error in item.errors:
            error_counts[error.split(":")[0]] += 1
        for warning in item.warnings:
            warning_counts[warning.split(":")[0]] += 1
        for note in item.info:
            if note.startswith("raw_identifiers_detected:"):
                parts = note.split(":")
                if len(parts) >= 2:
                    for identifier_type in parts[1].split(","):
                        if identifier_type:
                            raw_identifier_info_counts[identifier_type] += 1
        if not item.valid:
            if item.room_id:
                invalid_room_ids.append(item.room_id)
            continue
        try:
            if item.line_number is None or item.line_number < 1:
                continue
            raw_line = all_lines[item.line_number - 1]
            if not raw_line.strip():
                continue
            normalized = normalize_live_ticket_row(json.loads(raw_line))
            status_counts[str(normalized.get("status") or "unknown")] += 1
            first_sender = normalized["messages"][0]["sender_type"]
            first_sender_counts[str(first_sender)] += 1
        except (ValueError, json.JSONDecodeError, IndexError, KeyError):
            continue

    return LiveFeedContractValidationSummary(
        contract_version=CONTRACT_VERSION,
        generated_at_utc=_utc_now_iso(),
        source_path=str(file_path),
        total_lines=total_lines,
        empty_lines=empty_lines,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        warning_rows=warning_rows,
        info_rows=info_rows,
        allow_raw_pii_internal_pilot=allow_raw_pii,
        raw_identifier_info_counts=dict(raw_identifier_info_counts),
        status_counts=dict(status_counts),
        first_sender_counts=dict(first_sender_counts),
        error_counts=dict(error_counts),
        warning_counts=dict(warning_counts),
        sample_invalid_room_ids=tuple(invalid_room_ids[:20]),
        passed=invalid_rows == 0,
    )


def assert_live_feed_validation_report_safe(content: str) -> None:
    """Fail closed if validation report may contain forbidden content."""
    lowered = content.lower()
    for token in _FORBIDDEN_REPORT_TOKENS:
        if token in lowered:
            raise ValueError(
                f"live feed validation report must not contain forbidden token: {token}",
            )


def render_live_feed_contract_validation_markdown(
    summary: LiveFeedContractValidationSummary,
) -> str:
    """Render safe markdown validation report (aggregates only)."""
    lines = [
        "# Live feed adapter contract validation",
        "",
        f"- **contract_version:** {summary.contract_version}",
        f"- **generated_at_utc:** {summary.generated_at_utc}",
        f"- **source_path:** `{summary.source_path}`",
        f"- **passed:** {summary.passed}",
        f"- **allow_raw_pii_internal_pilot:** {summary.allow_raw_pii_internal_pilot}",
        "",
        "## Row counts",
        "",
        f"- **total_lines:** {summary.total_lines}",
        f"- **empty_lines:** {summary.empty_lines}",
        f"- **valid_rows:** {summary.valid_rows}",
        f"- **invalid_rows:** {summary.invalid_rows}",
        f"- **warning_rows:** {summary.warning_rows}",
        f"- **info_rows:** {summary.info_rows}",
        "",
        "## Status distribution (valid rows)",
        "",
    ]
    if summary.status_counts:
        for status, count in sorted(summary.status_counts.items()):
            lines.append(f"- `{status}`: {count}")
    else:
        lines.append("- *(none)*")

    lines.extend(["", "## First sender distribution (valid rows)", ""])
    if summary.first_sender_counts:
        for sender, count in sorted(summary.first_sender_counts.items()):
            lines.append(f"- `{sender}`: {count}")
    else:
        lines.append("- *(none)*")

    lines.extend(["", "## Error counts", ""])
    if summary.error_counts:
        for code, count in sorted(summary.error_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("- *(none)*")

    lines.extend(["", "## Warning counts", ""])
    if summary.warning_counts:
        for code, count in sorted(summary.warning_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("- *(none)*")

    lines.extend(
        [
            "",
            "## Raw identifier notes (internal pilot — allowed)",
            "",
            "Raw identifiers detected (allowed in internal pilot mode). "
            "These are informational only and do not fail validation.",
            "",
        ],
    )
    if summary.raw_identifier_info_counts:
        for identifier_type, count in sorted(
            summary.raw_identifier_info_counts.items(),
            key=lambda x: (-x[1], x[0]),
        ):
            lines.append(f"- `{identifier_type}`: {count}")
    else:
        lines.append("- *(none)*")

    lines.extend(["", "## Sample invalid room_ids", ""])
    if summary.sample_invalid_room_ids:
        for room_id in summary.sample_invalid_room_ids:
            lines.append(f"- `{room_id}`")
    else:
        lines.append("- *(none)*")

    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Contract validation only — no production API, send, or execution.",
            "- Spec: `docs/integration/live_feed_adapter_contract.md`.",
            "- Internal pilot feeds may include raw identifiers for extraction evaluation.",
            "- Reports exclude message bodies, prompts, and secrets.",
            "",
        ],
    )
    return "\n".join(lines)


def write_live_feed_contract_validation_reports(
    summary: LiveFeedContractValidationSummary,
    *,
    summary_json: Path = DEFAULT_VALIDATION_SUMMARY_PATH,
    report_md: Path = DEFAULT_VALIDATION_REPORT_PATH,
) -> tuple[Path, Path]:
    """Write JSON summary and markdown report with safety checks."""
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_live_feed_contract_validation_markdown(summary)
    assert_live_feed_validation_report_safe(json_text)
    assert_live_feed_validation_report_safe(markdown)
    summary_json.write_text(json_text, encoding="utf-8")
    report_md.write_text(markdown, encoding="utf-8")
    return summary_json, report_md

"""Fetch live rooms from Inchand API, normalize JSONL, and optionally validate contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.live_shadow.live_feed_contract import (
    DEFAULT_VALIDATION_REPORT_PATH,
    DEFAULT_VALIDATION_SUMMARY_PATH,
    summarize_live_feed_contract_validation,
    write_live_feed_contract_validation_reports,
)
from app.live_shadow.live_rooms_adapter import (
    normalize_rooms_to_live_tickets,
    write_json_file,
    write_normalized_live_tickets_jsonl,
)
from app.live_shadow.live_rooms_api_client import fetch_live_rooms

MISSING_API_TOKEN_MESSAGE = "توکن API تنظیم نشده است."

_BEARER_TOKEN_PATTERN = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_SECRET_LIKE_PATTERN = re.compile(
    r"(?i)(authorization|token|api[_-]?key|secret)\s*[:=]\s*\S+",
)


def resolve_live_rooms_api_token(settings: AppSettings | None = None) -> str | None:
    """Return configured live rooms bearer token, or None when unset."""
    cfg = settings or get_settings()
    token = (cfg.live_rooms_api_token or "").strip()
    return token or None


def sanitize_fetch_error_message(message: str | None) -> str | None:
    """Strip bearer tokens and secret-like fragments from error text."""
    if not message:
        return message
    redacted = _BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", message)
    redacted = _SECRET_LIKE_PATTERN.sub(r"\1=[REDACTED]", redacted)
    return redacted


@dataclass(frozen=True)
class LiveRoomsFetchServiceResult:
    success: bool
    rooms_fetched: int = 0
    tickets_written: int = 0
    normalize_errors: tuple[str, ...] = ()
    validation_passed: bool | None = None
    valid_rows: int | None = None
    invalid_rows: int | None = None
    raw_output: Path | None = None
    normalized_output: Path | None = None
    summary_json: Path | None = None
    report_md: Path | None = None
    fetch_warnings: tuple[str, ...] = ()
    error_message: str | None = None

    def to_session_dict(self) -> dict[str, Any]:
        """Safe serializable snapshot for Streamlit session state."""
        return {
            "success": self.success,
            "rooms_fetched": self.rooms_fetched,
            "tickets_written": self.tickets_written,
            "normalize_errors": list(self.normalize_errors),
            "validation_passed": self.validation_passed,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "raw_output": str(self.raw_output) if self.raw_output else None,
            "normalized_output": str(self.normalized_output) if self.normalized_output else None,
            "summary_json": str(self.summary_json) if self.summary_json else None,
            "report_md": str(self.report_md) if self.report_md else None,
            "fetch_warnings": list(self.fetch_warnings),
            "error_message": self.error_message,
        }


def _failure(
    *,
    error_message: str,
    raw_output: Path | None = None,
    normalized_output: Path | None = None,
    fetch_warnings: tuple[str, ...] = (),
) -> LiveRoomsFetchServiceResult:
    return LiveRoomsFetchServiceResult(
        success=False,
        raw_output=raw_output,
        normalized_output=normalized_output,
        fetch_warnings=fetch_warnings,
        error_message=sanitize_fetch_error_message(error_message),
    )


def fetch_and_prepare_live_rooms_feed(
    *,
    limit: int | None = None,
    overwrite: bool = True,
    validate: bool = True,
    settings: AppSettings | None = None,
    raw_output: Path | None = None,
    normalized_output: Path | None = None,
    summary_json: Path | None = None,
    report_md: Path | None = None,
    allow_non_private_output: bool = False,
) -> LiveRoomsFetchServiceResult:
    """Fetch rooms, write raw + normalized outputs, optionally validate contract."""
    cfg = settings or get_settings()
    resolved_limit = limit if limit is not None else cfg.live_rooms_api_fetch_limit
    raw_path = Path(raw_output or cfg.live_rooms_raw_output_path)
    normalized_path = Path(normalized_output or cfg.live_rooms_normalized_output_path)
    summary_path = Path(summary_json or DEFAULT_VALIDATION_SUMMARY_PATH)
    report_path = Path(report_md or DEFAULT_VALIDATION_REPORT_PATH)

    if not resolve_live_rooms_api_token(cfg):
        return _failure(
            error_message=MISSING_API_TOKEN_MESSAGE,
            raw_output=raw_path,
            normalized_output=normalized_path,
        )

    if not overwrite and normalized_path.is_file():
        return _failure(
            error_message=f"Output exists: {normalized_path} (overwrite disabled)",
            raw_output=raw_path,
            normalized_output=normalized_path,
        )

    try:
        rooms, raw_payload, fetch_warnings = fetch_live_rooms(
            limit=resolved_limit,
            settings=cfg,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _failure(
            error_message=str(exc),
            raw_output=raw_path,
            normalized_output=normalized_path,
        )

    write_json_file(
        raw_payload,
        raw_path,
        overwrite=True,
        allow_non_private=allow_non_private_output,
    )

    tickets, normalize_errors = normalize_rooms_to_live_tickets(rooms)
    if not tickets:
        return LiveRoomsFetchServiceResult(
            success=False,
            rooms_fetched=len(rooms),
            tickets_written=0,
            normalize_errors=tuple(normalize_errors),
            raw_output=raw_path,
            normalized_output=normalized_path,
            fetch_warnings=tuple(fetch_warnings),
            error_message="No tickets normalized from live rooms API response",
        )

    write_normalized_live_tickets_jsonl(
        tickets,
        normalized_path,
        overwrite=True,
        allow_non_private=allow_non_private_output,
    )

    validation_passed: bool | None = None
    valid_rows: int | None = None
    invalid_rows: int | None = None
    written_summary: Path | None = None
    written_report: Path | None = None

    if validate:
        summary = summarize_live_feed_contract_validation(normalized_path)
        validation_passed = summary.invalid_rows == 0
        valid_rows = summary.valid_rows
        invalid_rows = summary.invalid_rows
        written_summary, written_report = write_live_feed_contract_validation_reports(
            summary,
            summary_json=summary_path,
            report_md=report_path,
        )

    success = validation_passed if validate else True

    return LiveRoomsFetchServiceResult(
        success=success,
        rooms_fetched=len(rooms),
        tickets_written=len(tickets),
        normalize_errors=tuple(normalize_errors),
        validation_passed=validation_passed,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        raw_output=raw_path,
        normalized_output=normalized_path,
        summary_json=written_summary,
        report_md=written_report,
        fetch_warnings=tuple(fetch_warnings),
        error_message=None if success else "Live feed contract validation failed",
    )

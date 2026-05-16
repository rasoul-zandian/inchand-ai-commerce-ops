#!/usr/bin/env python3
"""Offline validator for anonymized conversation-ticket JSONL exports (no import/index)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)
from pydantic import ValidationError

_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
)
_IBAN_IR_PATTERN = re.compile(r"\bIR\d{22,26}\b", re.IGNORECASE)
_MOBILE_IR_PATTERN = re.compile(r"\b09\d{9}\b")
_LONG_DIGITS_PATTERN = re.compile(r"\b\d{13,19}\b")


@dataclass
class LineError:
    line_number: int
    error_message: str


@dataclass
class ValidationReport:
    total_lines: int = 0
    empty_lines_ignored: int = 0
    valid_tickets: int = 0
    invalid_lines: int = 0
    label_counts: Counter[str] = field(default_factory=Counter)
    sender_type_counts: Counter[str] = field(default_factory=Counter)
    status_counts: Counter[str] = field(default_factory=Counter)
    message_counts: list[int] = field(default_factory=list)
    tickets_with_final_resolution: int = 0
    errors: list[LineError] = field(default_factory=list)
    suspicious_warning_counts: Counter[str] = field(default_factory=Counter)

    @property
    def passed(self) -> bool:
        return self.invalid_lines == 0

    @property
    def min_messages(self) -> int | None:
        return min(self.message_counts) if self.message_counts else None

    @property
    def max_messages(self) -> int | None:
        return max(self.message_counts) if self.message_counts else None

    @property
    def avg_messages(self) -> float | None:
        if not self.message_counts:
            return None
        return sum(self.message_counts) / len(self.message_counts)


def count_suspicious_tokens(text: str) -> Counter[str]:
    """Count suspicious patterns in text; never returns matched substrings."""
    counts: Counter[str] = Counter()
    if _EMAIL_PATTERN.search(text):
        counts["email_like"] += 1
    if _MOBILE_IR_PATTERN.search(text):
        counts["phone_like"] += 1
    if _IBAN_IR_PATTERN.search(text):
        counts["iban_like"] += 1
    if _LONG_DIGITS_PATTERN.search(text):
        counts["card_like_long_digits"] += 1
    return counts


def _scan_snapshot_for_suspicious_tokens(snapshot: ConversationTicketSnapshot) -> Counter[str]:
    combined = "\n".join(message.text for message in snapshot.messages)
    seller = snapshot.seller_id or ""
    return count_suspicious_tokens(f"{combined}\n{seller}")


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = str(err.get("msg", "validation error"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else "validation error"


def validate_jsonl_content(lines: list[str]) -> ValidationReport:
    """Validate JSONL lines in memory (for tests and CLI)."""
    report = ValidationReport()
    physical_line = 0

    for raw_line in lines:
        physical_line += 1
        if not raw_line.strip():
            report.empty_lines_ignored += 1
            continue

        report.total_lines += 1
        try:
            snapshot = parse_conversation_ticket_snapshot(raw_line)
        except json.JSONDecodeError as exc:
            report.invalid_lines += 1
            report.errors.append(
                LineError(
                    line_number=physical_line,
                    error_message=f"JSON decode error at column {exc.colno}: {exc.msg}",
                )
            )
            continue
        except ValidationError as exc:
            report.invalid_lines += 1
            report.errors.append(
                LineError(
                    line_number=physical_line,
                    error_message=_format_validation_error(exc),
                )
            )
            continue
        except ValueError as exc:
            report.invalid_lines += 1
            report.errors.append(LineError(line_number=physical_line, error_message=str(exc)))
            continue

        report.valid_tickets += 1
        report.label_counts[snapshot.ticket_label] += 1
        if snapshot.status:
            report.status_counts[snapshot.status] += 1
        if snapshot.final_resolution:
            report.tickets_with_final_resolution += 1
        report.message_counts.append(len(snapshot.messages))
        for message in snapshot.messages:
            report.sender_type_counts[message.sender_type] += 1
        report.suspicious_warning_counts.update(_scan_snapshot_for_suspicious_tokens(snapshot))

    return report


def validate_jsonl_file(path: Path) -> ValidationReport:
    """Read UTF-8 JSONL from path and validate each non-empty line."""
    text = path.read_text(encoding="utf-8")
    return validate_jsonl_content(text.splitlines())


def format_human_report(report: ValidationReport, *, path: str | None = None) -> str:
    lines: list[str] = []
    if path:
        lines.append(f"ticket export validation: {path}")
    status = "passed" if report.passed else "FAILED"
    lines.append(f"result: {status}")
    lines.append(f"  total_lines={report.total_lines}")
    lines.append(f"  empty_lines_ignored={report.empty_lines_ignored}")
    lines.append(f"  valid_tickets={report.valid_tickets}")
    lines.append(f"  invalid_lines={report.invalid_lines}")
    if report.message_counts:
        lines.append(
            f"  messages_per_ticket: min={report.min_messages} "
            f"max={report.max_messages} avg={report.avg_messages:.2f}"
        )
    lines.append(f"  tickets_with_final_resolution={report.tickets_with_final_resolution}")
    if report.label_counts:
        lines.append("  ticket_label_counts:")
        for label, count in sorted(report.label_counts.items()):
            lines.append(f"    {label}={count}")
    if report.sender_type_counts:
        lines.append("  sender_type_counts:")
        for sender, count in sorted(report.sender_type_counts.items()):
            lines.append(f"    {sender}={count}")
    if report.status_counts:
        lines.append("  status_counts:")
        for status, count in sorted(report.status_counts.items()):
            lines.append(f"    {status}={count}")
    if report.suspicious_warning_counts:
        lines.append("  suspicious_pattern_warnings (counts only, not failures):")
        for key, count in sorted(report.suspicious_warning_counts.items()):
            lines.append(f"    {key}={count}")
    if report.errors:
        lines.append("  errors:")
        for err in report.errors:
            lines.append(f"    line {err.line_number}: {err.error_message}")
    return "\n".join(lines)


def format_json_report(report: ValidationReport, *, path: str | None = None) -> str:
    payload: dict[str, Any] = {
        "passed": report.passed,
        "path": path,
        "total_lines": report.total_lines,
        "empty_lines_ignored": report.empty_lines_ignored,
        "valid_tickets": report.valid_tickets,
        "invalid_lines": report.invalid_lines,
        "tickets_with_final_resolution": report.tickets_with_final_resolution,
        "messages_per_ticket": {
            "min": report.min_messages,
            "max": report.max_messages,
            "avg": round(report.avg_messages, 4) if report.avg_messages is not None else None,
        },
        "ticket_label_counts": dict(report.label_counts),
        "sender_type_counts": dict(report.sender_type_counts),
        "status_counts": dict(report.status_counts),
        "suspicious_pattern_warnings": dict(report.suspicious_warning_counts),
        "errors": [
            {"line_number": err.line_number, "error_message": err.error_message}
            for err in report.errors
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate anonymized conversation-ticket JSONL export (offline only).",
    )
    parser.add_argument("export_path", type=Path, help="Path to UTF-8 JSONL export file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary",
    )
    args = parser.parse_args(argv)

    path = args.export_path
    if not path.is_file():
        print(f"ticket export validation: file not found: {path}", file=sys.stderr)
        return 1

    report = validate_jsonl_file(path)
    output = (
        format_json_report(report, path=str(path))
        if args.json
        else format_human_report(report, path=str(path))
    )
    print(output)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

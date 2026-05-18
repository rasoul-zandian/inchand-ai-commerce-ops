#!/usr/bin/env python3
"""Offline PII redaction for normalized conversation-ticket JSONL (no corpus/embeddings)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.privacy_review.redaction import assert_redacted_export_safe, redact_conversation_snapshot
from app.tickets.conversation_models import parse_conversation_ticket_snapshot
from pydantic import ValidationError


@dataclass
class RedactionLineError:
    line_number: int
    error_message: str


@dataclass
class RedactionReport:
    input_records: int = 0
    output_records: int = 0
    invalid_records: int = 0
    empty_lines_ignored: int = 0
    records_changed: int = 0
    redaction_counts: Counter[str] = field(default_factory=Counter)
    errors: list[RedactionLineError] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.invalid_records == 0


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = str(err.get("msg", "validation error"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else "validation error"


def redact_jsonl_content(lines: list[str]) -> tuple[list[str], RedactionReport]:
    """Redact each non-empty JSONL line; return output lines and aggregate report."""
    report = RedactionReport()
    output_lines: list[str] = []

    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            report.empty_lines_ignored += 1
            continue

        report.input_records += 1
        try:
            snapshot = parse_conversation_ticket_snapshot(raw_line)
        except json.JSONDecodeError as exc:
            report.invalid_records += 1
            report.errors.append(
                RedactionLineError(
                    line_number=line_number,
                    error_message=f"JSON decode error: {exc.msg}",
                )
            )
            continue
        except ValidationError as exc:
            report.invalid_records += 1
            report.errors.append(
                RedactionLineError(
                    line_number=line_number,
                    error_message=_format_validation_error(exc),
                )
            )
            continue
        except ValueError as exc:
            report.invalid_records += 1
            report.errors.append(
                RedactionLineError(line_number=line_number, error_message=str(exc)),
            )
            continue

        redacted_snapshot, line_counts = redact_conversation_snapshot(snapshot)
        if line_counts:
            report.records_changed += 1
        report.redaction_counts.update(line_counts)

        try:
            parse_conversation_ticket_snapshot(redacted_snapshot.model_dump(mode="json"))
        except (ValidationError, ValueError) as exc:
            report.invalid_records += 1
            message = (
                _format_validation_error(exc) if isinstance(exc, ValidationError) else str(exc)
            )
            report.errors.append(
                RedactionLineError(
                    line_number=line_number,
                    error_message=f"redacted record invalid: {message}",
                )
            )
            continue

        serialized = json.dumps(
            redacted_snapshot.model_dump(mode="json"),
            ensure_ascii=False,
        )
        try:
            assert_redacted_export_safe(serialized)
        except ValueError as exc:
            report.invalid_records += 1
            report.errors.append(
                RedactionLineError(line_number=line_number, error_message=str(exc)),
            )
            continue

        output_lines.append(serialized)
        report.output_records += 1

    return output_lines, report


def format_summary(report: RedactionReport, *, input_path: str, output_path: str) -> str:
    lines = [
        f"ticket export redaction: {input_path} -> {output_path}",
        f"result: {'passed' if report.passed else 'FAILED'}",
        f"  input_records={report.input_records}",
        f"  output_records={report.output_records}",
        f"  invalid_records={report.invalid_records}",
        f"  empty_lines_ignored={report.empty_lines_ignored}",
        f"  records_changed={report.records_changed}",
    ]
    if report.redaction_counts:
        lines.append("  redaction_counts:")
        for key, count in sorted(report.redaction_counts.items()):
            lines.append(f"    {key}={count}")
    else:
        lines.append("  redaction_counts: (none)")
    if report.errors:
        lines.append("  errors:")
        for err in report.errors:
            lines.append(f"    line {err.line_number}: {err.error_message}")
    return "\n".join(lines)


def redact_jsonl_file(
    input_path: Path,
    output_path: Path,
    *,
    overwrite: bool = False,
) -> RedactionReport:
    if not input_path.is_file():
        raise ValueError(f"input file not found: {input_path}")
    if output_path.exists() and not overwrite:
        raise ValueError(f"output file already exists: {output_path} (use --overwrite)")

    lines = input_path.read_text(encoding="utf-8").splitlines()
    output_lines, report = redact_jsonl_content(lines)

    if report.passed:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(output_lines)
        if output_lines:
            payload += "\n"
        output_path.write_text(payload, encoding="utf-8")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Redact PII from normalized conversation-ticket JSONL (offline only).",
    )
    parser.add_argument("input_path", type=Path, help="Normalized UTF-8 JSONL input")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Path for redacted JSONL output (local/private; do not commit raw exports)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing output file",
    )
    args = parser.parse_args(argv)

    try:
        report = redact_jsonl_file(
            args.input_path,
            args.output,
            overwrite=args.overwrite,
        )
    except ValueError as exc:
        print(f"ticket export redaction: {exc}", file=sys.stderr)
        return 1

    print(format_summary(report, input_path=str(args.input_path), output_path=str(args.output)))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

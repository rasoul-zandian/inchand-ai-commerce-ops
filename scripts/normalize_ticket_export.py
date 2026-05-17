#!/usr/bin/env python3
"""Offline normalizer: real JSON ticket array → ConversationTicketSnapshot JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.tickets.conversation_models import ALLOWED_SENDER_TYPES, parse_conversation_ticket_snapshot
from pydantic import ValidationError

_SELLER_TYPES = frozenset({"seller", "user", "customer", "vendor", "shop"})
_SUPPORT_TYPES = frozenset({"admin", "operator", "support", "agent"})
_FINANCE_TYPES = frozenset({"finance", "financial"})


class RecordNormalizationError(ValueError):
    """Normalization failure for one ticket; may carry skip counts (no message text)."""

    def __init__(self, message: str, *, skipped_empty: int = 0) -> None:
        super().__init__(message)
        self.skipped_empty = skipped_empty


@dataclass
class RecordError:
    record_index: int
    error_message: str


@dataclass
class NormalizationReport:
    input_records: int = 0
    normalized_records: int = 0
    invalid_records: int = 0
    skipped_empty_messages: int = 0
    category_counts: Counter[str] = field(default_factory=Counter)
    sender_type_counts: Counter[str] = field(default_factory=Counter)
    unknown_source_type_counts: Counter[str] = field(default_factory=Counter)
    message_counts: list[int] = field(default_factory=list)
    errors: list[RecordError] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.invalid_records == 0 and self.input_records == self.normalized_records

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


def _normalize_type_key(raw_type: str) -> str:
    return raw_type.strip().lower().replace(" ", "_").replace("-", "_")


def normalize_sender_type(raw_type: str) -> tuple[str, str]:
    """Map exporter message type to canonical sender_type; return (canonical, raw)."""
    original = raw_type.strip() if isinstance(raw_type, str) else str(raw_type)
    key = _normalize_type_key(original) if original else ""

    if key in ALLOWED_SENDER_TYPES:
        return key, original

    if key == "system":
        return "system", original
    if key in _FINANCE_TYPES:
        return "finance_agent", original
    if key in _SELLER_TYPES:
        return "seller", original
    if key in _SUPPORT_TYPES:
        return "support_agent", original

    return "unknown", original


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    stripped = value.strip()
    return stripped if stripped else None


def _require_non_empty_str(record: dict[str, Any], key: str, *, field_label: str) -> str:
    if key not in record:
        raise ValueError(f"missing required field: {field_label}")
    value = record[key]
    if not isinstance(value, str):
        value = str(value)
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_label} must be non-empty")
    return stripped


def normalize_record(
    record: dict[str, Any],
    *,
    skip_empty_messages: bool = False,
) -> tuple[dict[str, Any], int]:
    """Convert one real-export ticket object to ConversationTicketSnapshot dict."""
    if not isinstance(record, dict):
        raise ValueError("ticket record must be a JSON object")

    room_id = _require_non_empty_str(record, "id", field_label="id")
    ticket_label = _require_non_empty_str(record, "category", field_label="category")
    seller_id = _optional_str(record.get("shop_id"))

    raw_messages = record.get("messages")
    if not isinstance(raw_messages, list):
        raise ValueError("messages must be an array")
    if not raw_messages:
        raise ValueError("messages must contain at least one message")

    status = _optional_str(record.get("status"))

    messages: list[dict[str, Any]] = []
    skipped_empty = 0
    message_seq = 0
    for index, raw_message in enumerate(raw_messages):
        if not isinstance(raw_message, dict):
            raise ValueError(f"messages[{index}] must be an object")
        if "type" not in raw_message:
            raise ValueError(f"messages[{index}] missing required field: type")
        if "content" not in raw_message:
            raise ValueError(f"messages[{index}] missing required field: content")

        raw_type = raw_message["type"]
        if not isinstance(raw_type, str):
            raw_type = str(raw_type)
        sender_type, source_type = normalize_sender_type(raw_type)

        content = raw_message["content"]
        if not isinstance(content, str):
            content = str(content)
        text = content.strip()
        if not text:
            if skip_empty_messages:
                skipped_empty += 1
                continue
            raise ValueError(f"messages[{index}].content must be non-empty")

        metadata: dict[str, Any] = {}
        if source_type and source_type.lower() != sender_type:
            metadata["source_type"] = source_type
        elif source_type and sender_type == "unknown":
            metadata["source_type"] = source_type

        message: dict[str, Any] = {
            "message_id": f"{room_id}_MSG_{message_seq:03d}",
            "sender_type": sender_type,
            "timestamp": None,
            "text": text,
        }
        message_seq += 1
        if metadata:
            message["metadata"] = metadata
        messages.append(message)

    if not messages:
        raise RecordNormalizationError(
            "messages must contain at least one message",
            skipped_empty=skipped_empty,
        )

    snapshot: dict[str, Any] = {
        "room_id": room_id,
        "ticket_label": ticket_label,
        "ticket_subtype": None,
        "status": status,
        "seller_id": seller_id,
        "final_resolution": {},
        "messages": messages,
    }
    return snapshot, skipped_empty


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = str(err.get("msg", "validation error"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else "validation error"


def normalize_export_records(
    records: list[Any],
    *,
    skip_empty_messages: bool = False,
) -> tuple[list[dict[str, Any]], NormalizationReport]:
    """Normalize and validate each record; return valid snapshots and summary report."""
    report = NormalizationReport(input_records=len(records))
    normalized: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        record_number = index + 1
        try:
            payload, skipped = normalize_record(
                record,
                skip_empty_messages=skip_empty_messages,
            )
            report.skipped_empty_messages += skipped
            snapshot = parse_conversation_ticket_snapshot(payload)
        except json.JSONDecodeError as exc:
            report.invalid_records += 1
            report.errors.append(
                RecordError(
                    record_index=record_number,
                    error_message=f"JSON error: {exc.msg}",
                )
            )
            continue
        except ValidationError as exc:
            report.invalid_records += 1
            report.errors.append(
                RecordError(
                    record_index=record_number,
                    error_message=_format_validation_error(exc),
                )
            )
            continue
        except RecordNormalizationError as exc:
            report.skipped_empty_messages += exc.skipped_empty
            report.invalid_records += 1
            report.errors.append(RecordError(record_index=record_number, error_message=str(exc)))
            continue
        except (ValueError, TypeError) as exc:
            report.invalid_records += 1
            report.errors.append(RecordError(record_index=record_number, error_message=str(exc)))
            continue

        report.normalized_records += 1
        report.category_counts[snapshot.ticket_label] += 1
        report.message_counts.append(len(snapshot.messages))
        for message in snapshot.messages:
            report.sender_type_counts[message.sender_type] += 1
            source_type = message.metadata.get("source_type")
            if message.sender_type == "unknown" and isinstance(source_type, str) and source_type:
                report.unknown_source_type_counts[source_type] += 1

        normalized.append(snapshot.model_dump(mode="json"))

    return normalized, report


def load_export_array(text: str) -> list[Any]:
    """Parse UTF-8 JSON array export."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("export must be a JSON array of ticket records")
    return data


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def format_human_report(report: NormalizationReport, *, input_path: str | None = None) -> str:
    lines: list[str] = []
    if input_path:
        lines.append(f"ticket export normalization: {input_path}")
    status = "passed" if report.passed else "FAILED"
    lines.append(f"result: {status}")
    lines.append(f"  input_records={report.input_records}")
    lines.append(f"  normalized_records={report.normalized_records}")
    lines.append(f"  invalid_records={report.invalid_records}")
    lines.append(f"  skipped_empty_messages={report.skipped_empty_messages}")
    if report.message_counts:
        avg = report.avg_messages
        lines.append(
            f"  messages_per_ticket: min={report.min_messages} "
            f"max={report.max_messages} avg={avg:.2f}"
        )
    if report.category_counts:
        lines.append("  category_counts:")
        for label, count in sorted(report.category_counts.items()):
            lines.append(f"    {label}={count}")
    if report.sender_type_counts:
        lines.append("  sender_type_counts:")
        for sender, count in sorted(report.sender_type_counts.items()):
            lines.append(f"    {sender}={count}")
    if report.unknown_source_type_counts:
        lines.append("  unknown_source_type_counts (from message.metadata.source_type):")
        for source_type, count in sorted(report.unknown_source_type_counts.items()):
            lines.append(f"    {source_type}={count}")
    if report.errors:
        lines.append("  errors:")
        for err in report.errors:
            lines.append(f"    record {err.record_index}: {err.error_message}")
    return "\n".join(lines)


def normalize_export_file(
    input_path: Path,
    output_path: Path,
    *,
    skip_empty_messages: bool = False,
) -> NormalizationReport:
    """Read JSON array export, write normalized JSONL, return report."""
    text = input_path.read_text(encoding="utf-8")
    records = load_export_array(text)
    normalized, report = normalize_export_records(
        records,
        skip_empty_messages=skip_empty_messages,
    )
    write_jsonl(output_path, normalized)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize real JSON ticket export to ConversationTicketSnapshot JSONL.",
    )
    parser.add_argument("export_path", type=Path, help="Path to UTF-8 JSON array export")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Path to write normalized JSONL (local/private; do not commit)",
    )
    parser.add_argument(
        "--skip-empty-messages",
        action="store_true",
        help=(
            "Skip messages with empty content instead of failing "
            "(ticket still invalid if none remain)"
        ),
    )
    args = parser.parse_args(argv)

    if not args.export_path.is_file():
        print(f"ticket export normalization: file not found: {args.export_path}", file=sys.stderr)
        return 1

    try:
        report = normalize_export_file(
            args.export_path,
            args.output,
            skip_empty_messages=args.skip_empty_messages,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"ticket export normalization: {exc}", file=sys.stderr)
        return 1

    print(format_human_report(report, input_path=str(args.export_path)))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build offline privacy-warning review report from replay + optional export scan."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.privacy_review.models import PrivacyReviewSummary, PrivacyWarningRecord
from app.privacy_review.review_builders import (
    build_privacy_review_summary,
    build_privacy_warning_records_from_export_lines,
    summary_to_json_dict,
)
from scripts.build_replay_metrics_dashboard import load_replay_report_rows

_FORBIDDEN_CONTENT_KEYS = frozenset(
    {
        "draft_response",
        "final_response",
        "user_input",
        "retrieved_context",
        "tool_results",
        "conversation_transcript",
        "messages",
        "specialist_output",
        "rag_sources",
        "grounding_sources",
        "audit_log",
        "text",
        "content",
    }
)
_FORBIDDEN_SUBSTRINGS = (
    "sk-",
    "api_key",
    "BEGIN PRIVATE KEY",
    "postgresql://",
    "OPENAI_API_KEY",
)


def assert_privacy_output_safe(content: str) -> None:
    """Reject outputs that accidentally embed forbidden keys or secret-like tokens."""
    lowered = content.lower()
    for key in _FORBIDDEN_CONTENT_KEYS:
        if f'"{key}"' in content or f"'{key}'" in content:
            raise ValueError(f"privacy report output must not reference forbidden key: {key}")
    for token in _FORBIDDEN_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"privacy report output must not contain forbidden token: {token}")


def _load_validation_warning_counts(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("validation JSON must be an object")
    warnings = payload.get("suspicious_pattern_warnings")
    if warnings is None:
        return {}
    if not isinstance(warnings, dict):
        raise ValueError("suspicious_pattern_warnings must be an object")
    return {str(key): int(value) for key, value in warnings.items()}


def _merge_type_counts(
    scanned: Counter[str],
    validation: dict[str, int] | None,
) -> dict[str, int]:
    merged: Counter[str] = Counter(scanned)
    if validation:
        for key, count in validation.items():
            if count > 0:
                merged[key] = max(merged.get(key, 0), count)
    return dict(merged)


def format_markdown_privacy_report(
    summary: PrivacyReviewSummary,
    *,
    warning_records: list[PrivacyWarningRecord],
    replay_path: str,
    export_path: str | None,
    validation_path: str | None,
    generated_at: str,
) -> str:
    lines: list[str] = [
        "# Privacy Warning Review Report",
        "",
        "## Purpose",
        "",
        (
            "Offline governance report summarizing privacy-pattern warnings detected "
            "during export validation. Supports manual review before any pilot corpus "
            "or indexing work. Observation only — no automatic redaction or removal."
        ),
        "",
        "## Source Safety",
        "",
        f"- **Replay report:** `{replay_path}` (local/private)",
        f"- **Normalized export:** `{export_path or '(not scanned)'}` (local/private)",
        (
            f"- **Validation JSON:** `{validation_path or '(not provided)'}` "
            "(optional aggregate cross-check)"
        ),
        f"- **Generated at:** {generated_at} (UTC)",
        "- No raw ticket text, transcripts, drafts, or message bodies are included.",
        "- No card numbers, phone numbers, IBAN values, or extracted secrets in this report.",
        "",
        "## Warning Summary",
        "",
        f"- **total_tickets_reviewed:** {summary.total_tickets_reviewed}",
        f"- **tickets_with_warnings:** {summary.tickets_with_warnings}",
        f"- **manual_review_required_count:** {summary.manual_review_required_count}",
        f"- **corpus_eligible_count:** {summary.corpus_eligible_count}",
        f"- **corpus_blocked_count:** {summary.corpus_blocked_count}",
        "",
        "### warning_type_counts",
        "",
        "| Type | Count |",
        "|------|------:|",
    ]
    if summary.warning_type_counts:
        for key, count in sorted(summary.warning_type_counts.items()):
            lines.append(f"| {key} | {count} |")
    else:
        lines.append("| *(none)* | 0 |")

    lines.extend(
        [
            "",
            "## Tickets With Warnings",
            "",
            "| room_id | warning_types | warning_count | corpus_eligible |",
            "|---------|---------------|--------------:|-----------------|",
        ]
    )
    if warning_records:
        for record in sorted(warning_records, key=lambda item: item.room_id):
            types = ", ".join(warning_type.value for warning_type in record.warning_types)
            lines.append(
                f"| {record.room_id} | {types} | {record.warning_count} | "
                f"{str(record.corpus_eligible).lower()} |"
            )
    else:
        lines.append("| *(none)* | — | 0 | — |")

    lines.extend(
        [
            "",
            "## Review Guidance",
            "",
            (
                "- Warnings are **observation signals** from pattern matching, "
                "not validation failures."
            ),
            "- **Manual privacy review** is required before corpus creation or vector indexing.",
            "- This workflow does **not** automatically reject, redact, or remove tickets.",
            "- Use room IDs above to locate tickets in local private exports for human triage.",
            "",
            "## Corpus Eligibility Guidance",
            "",
            "| Category | Count | Meaning |",
            "|----------|------:|---------|",
            (
                f"| eligible_after_review | {summary.corpus_eligible_count} | "
                "No privacy warnings detected; still subject to standard anonymization policy."
            ),
            (
                f"| blocked_pending_review | {summary.corpus_blocked_count} | "
                "One or more privacy warnings; corpus_eligible=False until manual review clears."
            ),
            "",
            "## Governance Notes",
            "",
            "- No raw text stored in git-safe artifacts.",
            "- No indexing performed; no embeddings generated.",
            "- No pgvector integration; no pilot corpus created.",
            "- Offline/local observation only; not a production moderation system.",
            "",
            "## Recommended Actions",
            "",
            "1. Manual review by technical/data team using local private exports.",
            "2. Verify anonymization placeholders and export sanitization.",
            "3. Optionally tighten export normalization before any corpus builder step.",
            "4. Obtain operator/business sign-off before pilot corpus planning.",
            "",
        ]
    )
    return "\n".join(lines)


def build_privacy_review_report(
    replay_path: Path,
    *,
    export_path: Path | None = None,
    validation_json_path: Path | None = None,
) -> tuple[PrivacyReviewSummary, list[PrivacyWarningRecord]]:
    """Load replay scope, scan export for warnings, and build review aggregates."""
    rows, _parse_errors = load_replay_report_rows(replay_path)
    total = len(rows)

    warning_records: list[PrivacyWarningRecord] = []
    type_counts: Counter[str] = Counter()

    if export_path is not None:
        export_lines = export_path.read_text(encoding="utf-8").splitlines()
        warning_records, type_counts = build_privacy_warning_records_from_export_lines(
            export_lines,
        )

    validation_counts: dict[str, int] | None = None
    if validation_json_path is not None:
        validation_counts = _load_validation_warning_counts(validation_json_path)

    merged_counts = _merge_type_counts(type_counts, validation_counts)
    summary = build_privacy_review_summary(
        total_tickets_reviewed=total,
        warning_records=warning_records,
        warning_type_counts=merged_counts,
    )
    return summary, warning_records


def write_privacy_review_report(
    replay_path: Path,
    *,
    markdown_output: Path,
    json_output: Path | None = None,
    export_path: Path | None = None,
    validation_json_path: Path | None = None,
) -> PrivacyReviewSummary:
    summary, warning_records = build_privacy_review_report(
        replay_path,
        export_path=export_path,
        validation_json_path=validation_json_path,
    )

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    replay_str = str(replay_path)
    export_str = str(export_path) if export_path else None
    validation_str = str(validation_json_path) if validation_json_path else None

    markdown = format_markdown_privacy_report(
        summary,
        warning_records=warning_records,
        replay_path=replay_str,
        export_path=export_str,
        validation_path=validation_str,
        generated_at=generated_at,
    )
    assert_privacy_output_safe(markdown)

    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(markdown, encoding="utf-8")

    if json_output is not None:
        payload = summary_to_json_dict(
            summary,
            warning_records=warning_records,
            replay_path=replay_str,
            export_path=export_str,
            generated_at=generated_at,
        )
        json_text = json.dumps(payload, ensure_ascii=False, indent=2)
        assert_privacy_output_safe(json_text)
        json_output.write_text(json_text, encoding="utf-8")

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build offline privacy-warning review report (aggregate-safe).",
    )
    parser.add_argument("replay_path", type=Path, help="Path to replay report JSONL")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Path to write Markdown privacy review report",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to write JSON summary",
    )
    parser.add_argument(
        "--export-path",
        type=Path,
        default=None,
        help="Normalized JSONL export for per-ticket privacy warning scan",
    )
    parser.add_argument(
        "--validation-json",
        type=Path,
        default=None,
        help="Optional validate_ticket_export.py --json output for aggregate counts",
    )
    args = parser.parse_args(argv)

    if not args.replay_path.is_file():
        print(f"privacy review: replay file not found: {args.replay_path}", file=sys.stderr)
        return 1
    if args.export_path is not None and not args.export_path.is_file():
        print(f"privacy review: export file not found: {args.export_path}", file=sys.stderr)
        return 1
    if args.validation_json is not None and not args.validation_json.is_file():
        print(
            f"privacy review: validation JSON not found: {args.validation_json}",
            file=sys.stderr,
        )
        return 1

    try:
        summary = write_privacy_review_report(
            args.replay_path,
            markdown_output=args.output,
            json_output=args.json_output,
            export_path=args.export_path,
            validation_json_path=args.validation_json,
        )
    except ValueError as exc:
        print(f"privacy review: {exc}", file=sys.stderr)
        return 1

    print(f"privacy review: wrote {args.output}")
    if args.json_output:
        print(f"privacy review: wrote {args.json_output}")
    print(f"  total_tickets_reviewed={summary.total_tickets_reviewed}")
    print(f"  tickets_with_warnings={summary.tickets_with_warnings}")
    print(f"  corpus_blocked_count={summary.corpus_blocked_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

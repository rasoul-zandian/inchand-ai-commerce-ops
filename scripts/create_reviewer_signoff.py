#!/usr/bin/env python3
"""Create local reviewer sign-off JSON (governance metadata only; no corpus build)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.corpus_planning.reviewer_builders import build_signoff_record, corpus_ready_after_signoff
from app.corpus_planning.reviewer_models import (
    ReviewerChecklistItem,
    ReviewerChecklistResult,
    ReviewerDecision,
    ReviewerRole,
    ReviewerSignoffRecord,
)

_CHECK_CHOICES = {item.value for item in ReviewerChecklistItem}
_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "draft_response",
        "final_response",
        "conversation_transcript",
        "messages",
        "user_input",
    }
)


def _build_checklist_from_cli(
    checked: set[str],
    *,
    decision: ReviewerDecision,
) -> list[ReviewerChecklistResult]:
    results: list[ReviewerChecklistResult] = []
    for item in ReviewerChecklistItem:
        passed = item.value in checked
        if decision == ReviewerDecision.APPROVED and not passed:
            raise ValueError(
                f"approved decision requires --check {item.value}; missing checklist confirmations"
            )
        results.append(ReviewerChecklistResult(item=item, passed=passed, notes=None))
    return results


def _assert_signoff_json_safe(payload: str) -> None:
    lowered = payload.lower()
    for key in _FORBIDDEN_OUTPUT_KEYS:
        if f'"{key}"' in payload:
            raise ValueError(f"signoff output must not contain forbidden key: {key}")
    for token in ("sk-", "OPENAI_API_KEY", "postgresql://"):
        if token.lower() in lowered:
            raise ValueError(f"signoff output must not contain forbidden token: {token}")


def create_signoff_record(
    *,
    signoff_id: str,
    source_batch_id: str,
    reviewer_role: ReviewerRole,
    reviewer_id: str,
    decision: ReviewerDecision,
    checked_items: set[str],
    privacy_review_completed: bool,
    replay_review_completed: bool,
    approved_record_count: int,
    signed_at_utc: str | None,
) -> ReviewerSignoffRecord:
    checklist = _build_checklist_from_cli(checked_items, decision=decision)
    return build_signoff_record(
        signoff_id=signoff_id,
        source_batch_id=source_batch_id,
        reviewer_role=reviewer_role,
        reviewer_id=reviewer_id,
        decision=decision,
        checklist_results=checklist,
        privacy_review_completed=privacy_review_completed,
        replay_review_completed=replay_review_completed,
        approved_record_count=approved_record_count,
        signed_at_utc=signed_at_utc,
    )


def write_signoff_record(
    record: ReviewerSignoffRecord,
    output_path: Path,
    *,
    overwrite: bool = False,
) -> None:
    if output_path.exists() and not overwrite:
        raise ValueError(f"output file already exists: {output_path} (use --overwrite)")

    payload = record.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _assert_signoff_json_safe(text)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create local reviewer sign-off JSON (no raw ticket content).",
    )
    parser.add_argument(
        "--source-batch-id",
        required=True,
        help="Batch label (e.g. replay_166_redacted_v1)",
    )
    parser.add_argument(
        "--reviewer-role",
        required=True,
        choices=[role.value for role in ReviewerRole],
        help="Reviewer role enum value",
    )
    parser.add_argument("--reviewer-id", required=True, help="Short reviewer handle (no PII)")
    parser.add_argument(
        "--decision",
        required=True,
        choices=[decision.value for decision in ReviewerDecision],
        help="Reviewer decision",
    )
    parser.add_argument(
        "--signoff-id",
        default=None,
        help="Sign-off ID (default: signoff_<source_batch_id>)",
    )
    parser.add_argument(
        "--check",
        action="append",
        choices=sorted(_CHECK_CHOICES),
        default=[],
        help="Checklist item confirmed passed (required for approved decision)",
    )
    parser.add_argument("--output", "-o", type=Path, required=True, help="Local JSON output path")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing output file")
    parser.add_argument(
        "--privacy-review-completed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Privacy review gate satisfied (default: true)",
    )
    parser.add_argument(
        "--replay-review-completed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Replay review gate satisfied (default: true)",
    )
    parser.add_argument(
        "--approved-record-count",
        type=int,
        default=0,
        help="Count of tickets approved for corpus scope (aggregate only)",
    )
    parser.add_argument(
        "--signed-at",
        default=None,
        help="Optional ISO-8601 UTC timestamp (default: now)",
    )
    args = parser.parse_args(argv)

    signoff_id = (args.signoff_id or f"signoff_{args.source_batch_id}").strip()
    checked = set(args.check or [])
    signed_at = args.signed_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        record = create_signoff_record(
            signoff_id=signoff_id,
            source_batch_id=args.source_batch_id,
            reviewer_role=ReviewerRole(args.reviewer_role),
            reviewer_id=args.reviewer_id,
            decision=ReviewerDecision(args.decision),
            checked_items=checked,
            privacy_review_completed=args.privacy_review_completed,
            replay_review_completed=args.replay_review_completed,
            approved_record_count=args.approved_record_count,
            signed_at_utc=signed_at,
        )
        write_signoff_record(record, args.output, overwrite=args.overwrite)
    except ValueError as exc:
        print(f"create_reviewer_signoff: {exc}", file=sys.stderr)
        return 1

    print(f"create_reviewer_signoff: wrote {args.output}")
    print(f"  signoff_id={record.signoff_id}")
    print(f"  decision={record.decision.value}")
    print(f"  corpus_ready_after_signoff={corpus_ready_after_signoff(record)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

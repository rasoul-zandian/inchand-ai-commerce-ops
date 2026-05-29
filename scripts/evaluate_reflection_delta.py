#!/usr/bin/env python3
"""Compare raw vs reflected final drafts on a sample JSONL (evaluation helper)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agentic_sandbox.final_draft_reflection import (
    apply_final_draft_reflection_review,
)
from app.config import get_settings


def _load_rows(path: Path, limit: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("reports/offline_draft_suggestions_first_turn_v1.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/reflection_delta_summary.json"),
    )
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    if not args.input.is_file():
        raise SystemExit(f"input not found: {args.input}")

    settings = get_settings()
    rows = _load_rows(args.input, args.limit)
    reviewed = 0
    rewrite_count = 0
    issue_count = 0
    samples: list[dict[str, object]] = []

    for row in rows:
        raw = str(row.get("draft_reply") or "").strip()
        if not raw:
            continue
        seller = ""
        snap = row.get("snapshot_before_reply")
        if isinstance(snap, dict):
            seller = str(snap.get("original_vendor_issue_preview") or "").strip()
        reflected, result = apply_final_draft_reflection_review(
            raw,
            seller_text=seller,
            detected_intent=str(row.get("detected_intent") or "") or None,
            suggested_action=str(row.get("suggested_action") or "") or None,
            conceptual_intent_fa=str(row.get("conceptual_intent_fa") or "") or None,
            order_ids=tuple(
                part.strip()
                for part in str(row.get("draft_extracted_order_ids") or "")
                .replace(",", " ")
                .split()
                if part.strip()
            ),
            product_ids=tuple(
                part.strip()
                for part in str(row.get("draft_extracted_product_ids") or "")
                .replace(",", " ")
                .split()
                if part.strip()
            ),
            settings=settings,
        )
        reviewed += 1
        if result.rewrite_applied:
            rewrite_count += 1
        if result.findings:
            issue_count += 1
        if len(samples) < 5 and result.rewrite_applied:
            samples.append(
                {
                    "room_id": row.get("room_id"),
                    "raw_chars": len(raw),
                    "reflected_chars": len(reflected),
                    "issue_types": [item.issue_type.value for item in result.findings],
                },
            )

    summary = {
        "input_path": str(args.input),
        "rows_scanned": len(rows),
        "drafts_reviewed": reviewed,
        "reflection_rewrite_rate": (rewrite_count / reviewed) if reviewed else 0.0,
        "reflection_issue_rate": (issue_count / reviewed) if reviewed else 0.0,
        "rewrite_count": rewrite_count,
        "issue_detected_count": issue_count,
        "sample_rewrites": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(payload, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

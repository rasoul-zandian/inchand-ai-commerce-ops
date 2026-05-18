"""Select and validate approved room IDs for pilot corpus (aggregate-safe)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.corpus_planning.pilot_corpus_builder import load_approved_room_ids

_FORBIDDEN_CONTENT_KEYS = frozenset(
    {
        "draft_response",
        "final_response",
        "user_input",
        "conversation_transcript",
        "messages",
        "text",
        "content",
    }
)


@dataclass
class RoomSelectionCriteria:
    limit: int | None = None
    include_labels: frozenset[str] = field(default_factory=frozenset)
    exclude_labels: frozenset[str] = field(default_factory=frozenset)
    include_departments: frozenset[str] = field(default_factory=frozenset)
    exclude_departments: frozenset[str] = field(default_factory=frozenset)
    exclude_qa_attention: bool = False


@dataclass(frozen=True)
class RoomSelectionResult:
    selected_room_ids: list[str]
    total_rows_scanned: int
    excluded_failed: int
    excluded_qa_attention: int
    excluded_label: int
    excluded_department: int


def _row_failed(row: dict[str, Any]) -> bool:
    return bool(row.get("errors"))


def _row_qa_attention(row: dict[str, Any]) -> bool:
    issues = row.get("qa_issue_count") or 0
    warnings = row.get("qa_warning_count") or 0
    if issues or warnings:
        return True
    if row.get("qa_passed") is False:
        return True
    return False


def _normalize_label(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _normalize_department(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def load_replay_rows_in_order(path: Path) -> list[dict[str, Any]]:
    """Load replay JSONL rows preserving file order."""
    rows: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: replay row must be a JSON object")
        for forbidden in _FORBIDDEN_CONTENT_KEYS:
            if forbidden in payload:
                raise ValueError(f"line {line_number}: forbidden key {forbidden!r} in report")
        rows.append(payload)
    return rows


def select_approved_room_ids_from_rows(
    rows: list[dict[str, Any]],
    *,
    criteria: RoomSelectionCriteria,
) -> RoomSelectionResult:
    """Select candidate room_ids from replay report rows (deterministic report order)."""
    selected: list[str] = []
    seen: set[str] = set()
    excluded_failed = 0
    excluded_qa = 0
    excluded_label = 0
    excluded_department = 0

    for row in rows:
        room_id = row.get("room_id")
        if not isinstance(room_id, str) or not room_id.strip():
            continue
        room_id = room_id.strip()

        if _row_failed(row):
            excluded_failed += 1
            continue

        if criteria.exclude_qa_attention and _row_qa_attention(row):
            excluded_qa += 1
            continue

        label = _normalize_label(row.get("ticket_label"))
        if criteria.include_labels and label not in criteria.include_labels:
            excluded_label += 1
            continue
        if criteria.exclude_labels and label in criteria.exclude_labels:
            excluded_label += 1
            continue

        department = _normalize_department(row.get("assigned_department"))
        if criteria.include_departments and department not in criteria.include_departments:
            excluded_department += 1
            continue
        if criteria.exclude_departments and department in criteria.exclude_departments:
            excluded_department += 1
            continue

        if room_id in seen:
            continue
        seen.add(room_id)
        selected.append(room_id)

        if criteria.limit is not None and len(selected) >= criteria.limit:
            break

    return RoomSelectionResult(
        selected_room_ids=selected,
        total_rows_scanned=len(rows),
        excluded_failed=excluded_failed,
        excluded_qa_attention=excluded_qa,
        excluded_label=excluded_label,
        excluded_department=excluded_department,
    )


def format_approved_room_ids_file(
    room_ids: list[str],
    *,
    criteria: RoomSelectionCriteria,
    source_report: str,
) -> str:
    """Build approved room IDs file with header comments only (no raw text)."""
    lines = [
        "# Approved room IDs for pilot corpus (local/private; do not commit)",
        f"# source_report: {source_report}",
        f"# selected_count: {len(room_ids)}",
        "# ordering: replay_report_file_order",
    ]
    if criteria.limit is not None:
        lines.append(f"# limit: {criteria.limit}")
    if criteria.include_labels:
        lines.append(f"# include_label: {','.join(sorted(criteria.include_labels))}")
    if criteria.exclude_labels:
        lines.append(f"# exclude_label: {','.join(sorted(criteria.exclude_labels))}")
    if criteria.include_departments:
        lines.append(f"# include_department: {','.join(sorted(criteria.include_departments))}")
    if criteria.exclude_departments:
        lines.append(f"# exclude_department: {','.join(sorted(criteria.exclude_departments))}")
    if criteria.exclude_qa_attention:
        lines.append("# exclude_qa_attention: true")
    lines.append("# Human reviewer must confirm this list before build_pilot_corpus.py")
    lines.append("")
    lines.extend(room_ids)
    lines.append("")
    return "\n".join(lines)


@dataclass(frozen=True)
class ApprovedRoomIdsValidation:
    approved_count: int
    found_count: int
    missing_room_ids: list[str]
    duplicate_approved_ids: int

    @property
    def passed(self) -> bool:
        return not self.missing_room_ids and self.duplicate_approved_ids == 0


def validate_approved_room_ids_against_export(
    export_path: Path,
    approved_path: Path,
) -> ApprovedRoomIdsValidation:
    """Ensure approved IDs exist in redacted export; no raw text returned."""
    approved_ids = load_approved_room_ids(approved_path)
    duplicate_count = len(approved_ids) - len(set(approved_ids))

    export_ids: set[str] = set()
    for raw_line in export_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        if isinstance(payload, dict) and isinstance(payload.get("room_id"), str):
            export_ids.add(payload["room_id"].strip())

    missing = [room_id for room_id in approved_ids if room_id not in export_ids]
    found = len(approved_ids) - len(missing)

    return ApprovedRoomIdsValidation(
        approved_count=len(approved_ids),
        found_count=found,
        missing_room_ids=missing,
        duplicate_approved_ids=duplicate_count,
    )

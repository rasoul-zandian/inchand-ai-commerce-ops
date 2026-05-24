"""Historical ticket memory lane — aggregate inventory only (no gold text, not policy truth)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.knowledge.knowledge_models import KnowledgeDocumentType, KnowledgeSourceLane


@dataclass(frozen=True)
class HistoricalTicketMemoryInventory:
    """Benchmark-derived aggregates only; never embeds gold replies or ticket bodies."""

    source_lane: KnowledgeSourceLane
    source_summary_path: str | None
    total_cases: int
    cases_by_label: dict[str, int]
    cases_by_responder_role: dict[str, int]
    skipped_unsafe: int | None
    skipped_no_support_reply: int | None
    tickets_processed: int | None
    benchmark_generated_at_utc: str | None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "document_type": KnowledgeDocumentType.HISTORICAL_TICKET_MEMORY.value,
            "source_lane": self.source_lane.value,
            "source_summary_path": self.source_summary_path,
            "total_cases": self.total_cases,
            "cases_by_label": dict(sorted(self.cases_by_label.items())),
            "cases_by_responder_role": dict(sorted(self.cases_by_responder_role.items())),
            "skipped_unsafe": self.skipped_unsafe,
            "skipped_no_support_reply": self.skipped_no_support_reply,
            "tickets_processed": self.tickets_processed,
            "benchmark_generated_at_utc": self.benchmark_generated_at_utc,
        }


def load_historical_reply_benchmark_summary(path: Path) -> dict[str, Any] | None:
    """Load benchmark summary JSON; return None if file is missing or invalid."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def build_historical_ticket_memory_inventory(
    summary: dict[str, Any] | None,
    *,
    source_summary_path: str | None = None,
) -> HistoricalTicketMemoryInventory:
    """Build aggregate-only inventory from ``historical_reply_benchmark_summary.json``."""

    if summary is None:
        return HistoricalTicketMemoryInventory(
            source_lane=KnowledgeSourceLane.HISTORICAL_MEMORY,
            source_summary_path=source_summary_path,
            total_cases=0,
            cases_by_label={},
            cases_by_responder_role={},
            skipped_unsafe=None,
            skipped_no_support_reply=None,
            tickets_processed=None,
            benchmark_generated_at_utc=None,
        )

    def _int(key: str) -> int:
        v = summary.get(key)
        if isinstance(v, bool) or v is None:
            return 0
        if isinstance(v, int):
            return v
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def _label_map(key: str) -> dict[str, int]:
        raw = summary.get(key)
        if not isinstance(raw, dict):
            return {}
        out: dict[str, int] = {}
        for k, v in raw.items():
            if isinstance(v, int):
                out[str(k)] = v
            else:
                try:
                    out[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
        return out

    gen_at = summary.get("generated_at_utc")
    gen_str = gen_at if isinstance(gen_at, str) else None

    return HistoricalTicketMemoryInventory(
        source_lane=KnowledgeSourceLane.HISTORICAL_MEMORY,
        source_summary_path=source_summary_path,
        total_cases=_int("total_cases"),
        cases_by_label=_label_map("cases_by_label"),
        cases_by_responder_role=_label_map("cases_by_responder_role"),
        skipped_unsafe=(_int("skipped_unsafe") if "skipped_unsafe" in summary else None),
        skipped_no_support_reply=(
            _int("skipped_no_support_reply") if "skipped_no_support_reply" in summary else None
        ),
        tickets_processed=_int("tickets_processed") if "tickets_processed" in summary else None,
        benchmark_generated_at_utc=gen_str,
    )

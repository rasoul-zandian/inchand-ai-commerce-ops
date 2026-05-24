"""Local polling loop for live vendor ticket feed (checkpoint JSON only)."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import AppSettings, get_settings
from app.corpus_planning.shadow_replay_jsonl_export import ShadowReplayExportConfig
from app.live_feed.ticket_feed_adapter import (
    _DEFAULT_EXPORT_CONFIG,
    advance_checkpoint,
    build_operator_payloads_from_live_tickets,
    fetch_new_vendor_tickets_since,
    fetch_recent_vendor_tickets,
)
from app.live_feed.ticket_models import LiveFeedCheckpoint, LiveTicketBatch

_DEFAULT_CHECKPOINT_PATH = Path("reports/live_feed_checkpoint.json")


def load_checkpoint(path: Path | str) -> LiveFeedCheckpoint:
    """Load local checkpoint JSON or return an empty checkpoint."""
    file_path = Path(path)
    if not file_path.is_file():
        return LiveFeedCheckpoint()
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("live feed checkpoint must be a JSON object")
    return LiveFeedCheckpoint.from_dict(data)


def save_checkpoint(checkpoint: LiveFeedCheckpoint, path: Path | str) -> None:
    """Persist checkpoint to local JSON (no database)."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def poll_live_ticket_feed(
    *,
    source_path: Path | str | None = None,
    checkpoint_path: Path | str | None = None,
    settings: AppSettings | None = None,
    export_config: ShadowReplayExportConfig | None = None,
    incremental: bool = True,
) -> LiveTicketBatch:
    """Poll live feed source; process new tickets into operator-safe payloads."""
    settings = settings or get_settings()
    if not settings.live_feed_enabled:
        raise ValueError("live feed is disabled (set LIVE_FEED_ENABLED=true for local polling)")

    source = Path(source_path or settings.live_feed_source_path)
    checkpoint_file = Path(checkpoint_path or settings.live_feed_checkpoint_path)
    export_config = export_config or _DEFAULT_EXPORT_CONFIG
    max_batch = settings.live_feed_max_batch

    checkpoint = load_checkpoint(checkpoint_file)
    if incremental and checkpoint.seen_room_ids:
        tickets = fetch_new_vendor_tickets_since(
            source,
            checkpoint,
            max_batch=max_batch,
        )
    else:
        tickets = fetch_recent_vendor_tickets(source, limit=max_batch)

    if not tickets:
        save_checkpoint(
            LiveFeedCheckpoint(
                last_seen_updated_at=checkpoint.last_seen_updated_at,
                seen_room_ids=checkpoint.seen_room_ids,
                last_poll_at=advance_checkpoint(checkpoint, []).last_poll_at,
            ),
            checkpoint_file,
        )
        return LiveTicketBatch(
            tickets=[],
            operator_payloads=[],
            fetched_count=0,
            new_count=0,
        )

    payloads = build_operator_payloads_from_live_tickets(
        tickets,
        export_config=export_config,
        settings=settings,
    )
    updated = advance_checkpoint(checkpoint, tickets)
    save_checkpoint(updated, checkpoint_file)

    return LiveTicketBatch(
        tickets=tickets,
        operator_payloads=payloads,
        fetched_count=len(tickets),
        new_count=len(tickets),
    )


def load_recent_operator_payloads(
    *,
    source_path: Path | str | None = None,
    settings: AppSettings | None = None,
    export_config: ShadowReplayExportConfig | None = None,
    limit: int | None = None,
) -> LiveTicketBatch:
    """One-shot load of recent tickets (no checkpoint advance; for console refresh)."""
    settings = settings or get_settings()
    source = Path(source_path or settings.live_feed_source_path)
    max_batch = limit if limit is not None else settings.live_feed_max_batch
    tickets = fetch_recent_vendor_tickets(source, limit=max_batch)
    if not tickets:
        return LiveTicketBatch(
            tickets=[],
            operator_payloads=[],
            fetched_count=0,
            new_count=0,
        )
    payloads = build_operator_payloads_from_live_tickets(
        tickets,
        export_config=export_config or _DEFAULT_EXPORT_CONFIG,
        settings=settings,
    )
    return LiveTicketBatch(
        tickets=tickets,
        operator_payloads=payloads,
        fetched_count=len(tickets),
        new_count=len(tickets),
    )

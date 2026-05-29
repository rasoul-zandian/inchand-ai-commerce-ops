"""Operator console handler for one-shot live API feed fetch (read-only)."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.live_shadow.live_rooms_fetch_service import (
    LiveRoomsFetchServiceResult,
    fetch_and_prepare_live_rooms_feed,
)
from app.operator_console.live_feed_loader import (
    LIVE_API_FEED_LAST_FETCH_ERROR_SESSION_KEY,
    LIVE_API_FEED_LAST_FETCH_RESULT_SESSION_KEY,
    LIVE_API_FEED_LAST_FETCH_TIME_SESSION_KEY,
    LiveFeedTicketEntry,
)


def handle_live_api_feed_fetch(
    session_state: MutableMapping[str, Any],
    *,
    feed_path: Path,
    settings: AppSettings | None = None,
    limit: int | None = None,
    reload_fn: Callable[[Path], list[LiveFeedTicketEntry]] | None = None,
) -> LiveRoomsFetchServiceResult:
    """Fetch latest tickets, store session metadata, reload feed on success."""
    cfg = settings or get_settings()
    result = fetch_and_prepare_live_rooms_feed(limit=limit, settings=cfg)
    fetch_time = datetime.now(tz=UTC).replace(microsecond=0).isoformat()
    session_state[LIVE_API_FEED_LAST_FETCH_TIME_SESSION_KEY] = fetch_time

    if result.success:
        session_state[LIVE_API_FEED_LAST_FETCH_RESULT_SESSION_KEY] = result.to_session_dict()
        session_state[LIVE_API_FEED_LAST_FETCH_ERROR_SESSION_KEY] = None
        reload_target = feed_path
        if result.normalized_output and result.normalized_output.is_file():
            reload_target = result.normalized_output
        if reload_fn is not None and reload_target.is_file():
            reload_fn(reload_target)
    else:
        session_state[LIVE_API_FEED_LAST_FETCH_ERROR_SESSION_KEY] = result.error_message
        session_state[LIVE_API_FEED_LAST_FETCH_RESULT_SESSION_KEY] = result.to_session_dict()

    return result

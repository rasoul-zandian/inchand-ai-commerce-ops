"""Read-only HTTP client for Inchand internal live rooms API (local/private dev)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from app.config import AppSettings, get_settings

logger = logging.getLogger(__name__)

_ROOM_LIST_KEYS = ("data", "items", "results", "rooms")
_NEXT_PAGE_KEYS = (
    ("meta", "next_page"),
    ("pagination", "next_page"),
    ("links", "next"),
)
_MAX_PAGE_FETCHES = 50


def build_live_rooms_headers(settings: AppSettings | None = None) -> dict[str, str]:
    """Build Authorization/Accept headers for the live rooms API."""
    cfg = settings or get_settings()
    headers = {"Accept": "application/json"}
    token = (cfg.live_rooms_api_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_live_rooms_page(
    url: str,
    *,
    params: Mapping[str, str | int | float | None] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float | int | None = None,
) -> Any:
    """Fetch one page from the live rooms endpoint; returns parsed JSON."""
    query: dict[str, str] = {}
    if params:
        for key, value in params.items():
            if value is None:
                continue
            query[str(key)] = str(value)
    full_url = url
    if query:
        full_url = f"{url}?{urllib.parse.urlencode(query)}"

    request = urllib.request.Request(full_url, headers=dict(headers or {}), method="GET")
    timeout_seconds = float(timeout if timeout is not None else 20)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"live_rooms_api HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"live_rooms_api request failed: {exc}") from exc

    if not body.strip():
        return []
    return json.loads(body)


def extract_rooms_from_payload(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Extract room dicts from common API response shapes; return (rooms, next_page_hint)."""
    if isinstance(payload, list):
        rooms = [item for item in payload if isinstance(item, dict)]
        return rooms, None

    if not isinstance(payload, dict):
        return [], None

    for key in _ROOM_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            rooms = [item for item in value if isinstance(item, dict)]
            next_page = _extract_next_page(payload)
            return rooms, next_page

    if payload.get("id") is not None or payload.get("room_id") is not None:
        return [payload], None

    return [], None


def _extract_next_page(payload: Mapping[str, Any]) -> str | None:
    for path in _NEXT_PAGE_KEYS:
        cursor: Any = payload
        for part in path:
            if not isinstance(cursor, dict):
                cursor = None
                break
            cursor = cursor.get(part)
        if isinstance(cursor, (str, int)) and str(cursor).strip():
            return str(cursor).strip()
    return None


def _room_id(room: Mapping[str, Any]) -> str:
    return str(room.get("id") or room.get("room_id") or "").strip()


def _build_query_params(
    *,
    limit: int | None,
    updated_after: str | None,
    page: int | None,
    page_size: int,
) -> dict[str, str]:
    params: dict[str, str] = {"per_page": str(page_size)}
    if limit is not None:
        params["limit"] = str(limit)
    if updated_after:
        params["updated_after"] = updated_after
    if page is not None:
        params["page"] = str(page)
    return params


def _resolve_next_page(
    *,
    next_hint: str | None,
    current_page: int,
    batch_count: int,
    page_size: int,
) -> int | None:
    """Return next page number to request, or None when pagination should stop."""
    if next_hint:
        if next_hint.isdigit():
            return int(next_hint)
        warnings_page = current_page + 1
        return warnings_page
    if batch_count >= page_size:
        return current_page + 1
    return None


def fetch_live_rooms(
    settings: AppSettings | None = None,
    *,
    limit: int | None = None,
    updated_after: str | None = None,
    page: int | None = None,
    url: str | None = None,
    fetch_page_fn: Any | None = None,
) -> tuple[list[dict[str, Any]], Any, list[str]]:
    """Fetch rooms across pages until ``limit`` reached or pagination ends.

    Returns (rooms, raw_payload_archive, warnings).
    """
    cfg = settings or get_settings()
    base_url = (url or cfg.live_rooms_api_url).strip()
    headers = build_live_rooms_headers(cfg)
    timeout = cfg.live_rooms_api_timeout_seconds
    page_size = max(1, int(cfg.live_rooms_api_page_size))
    if limit is not None:
        page_size = min(page_size, limit)

    warnings: list[str] = []
    _fetch = fetch_page_fn or fetch_live_rooms_page

    all_rooms: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    raw_pages: list[dict[str, Any]] = []
    current_page = page if page is not None else 1
    pages_fetched = 0

    while pages_fetched < _MAX_PAGE_FETCHES:
        if limit is not None and len(all_rooms) >= limit:
            break

        params = _build_query_params(
            limit=limit,
            updated_after=updated_after,
            page=current_page,
            page_size=page_size,
        )
        raw = _fetch(
            base_url,
            params=params,
            headers=headers,
            timeout=timeout,
        )
        raw_pages.append({"page": current_page, "params": params, "response": raw})
        batch, next_hint = extract_rooms_from_payload(raw)
        pages_fetched += 1

        added = 0
        for item in batch:
            rid = _room_id(item)
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            all_rooms.append(item)
            added += 1
            if limit is not None and len(all_rooms) >= limit:
                break

        if limit is not None and len(all_rooms) >= limit:
            break

        next_page = _resolve_next_page(
            next_hint=next_hint,
            current_page=current_page,
            batch_count=len(batch),
            page_size=page_size,
        )
        if next_page is None:
            break
        if next_page == current_page:
            warnings.append(f"pagination_stuck_on_page:{current_page}")
            break
        current_page = next_page
    else:
        warnings.append("pagination_max_pages_reached")

    if limit is not None and len(all_rooms) < limit:
        warnings.append(f"pagination_stopped_before_limit:{len(all_rooms)}_of_{limit}")

    if not raw_pages:
        raw_archive: Any = []
    elif len(raw_pages) == 1:
        raw_archive = raw_pages[0]["response"]
    else:
        raw_archive = {"pages": raw_pages, "rooms_fetched": len(all_rooms)}

    if limit is not None:
        all_rooms = all_rooms[:limit]

    if pages_fetched == 0:
        warnings.append("no_pages_fetched")
    elif pages_fetched > 1:
        warnings.append(f"pagination_pages_fetched:{pages_fetched}")

    return all_rooms, raw_archive, warnings

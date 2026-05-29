"""Tests for live rooms fetch service, CLI wiring, and operator console handler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.config import AppSettings
from app.live_shadow.live_rooms_fetch_service import (
    MISSING_API_TOKEN_MESSAGE,
    LiveRoomsFetchServiceResult,
    fetch_and_prepare_live_rooms_feed,
    resolve_live_rooms_api_token,
    sanitize_fetch_error_message,
)
from app.operator_console.live_feed_fetch_handler import handle_live_api_feed_fetch
from app.operator_console.live_feed_loader import (
    LIVE_API_FEED_ENTRIES_SESSION_KEY,
    LIVE_API_FEED_LAST_FETCH_ERROR_SESSION_KEY,
    LIVE_API_FEED_LAST_FETCH_RESULT_SESSION_KEY,
    LIVE_API_FEED_LAST_FETCH_TIME_SESSION_KEY,
)
from scripts import fetch_live_rooms_api as fetch_cli


def _sample_room(room_id: int = 47915) -> dict[str, object]:
    return {
        "id": room_id,
        "shop_id": 4136,
        "category": "complaint",
        "messages": [{"type": "seller", "content": "سلام، مشکل تسویه دارم"}],
    }


def _settings(
    *,
    token: str | None = "rooms-secret-token",
    fetch_limit: int = 400,
    tmp_path: Path | None = None,
) -> AppSettings:
    raw = (
        tmp_path / "data/private/live_rooms_raw.json"
        if tmp_path
        else Path(
            "data/private/live_rooms_raw.json",
        )
    )
    normalized = (
        tmp_path / "data/private/live_vendor_tickets.jsonl"
        if tmp_path
        else Path("data/private/live_vendor_tickets.jsonl")
    )
    return AppSettings(
        live_rooms_api_token=token,
        live_rooms_api_fetch_limit=fetch_limit,
        live_rooms_raw_output_path=str(raw),
        live_rooms_normalized_output_path=str(normalized),
    )


def _mock_fetch(monkeypatch: pytest.MonkeyPatch, rooms: list[dict[str, object]]) -> None:
    def _fake_fetch(*, limit: int, settings=None, fetch_page_fn=None):
        _ = limit, settings, fetch_page_fn
        return rooms, {"data": rooms}, ()

    monkeypatch.setattr(
        "app.live_shadow.live_rooms_fetch_service.fetch_live_rooms",
        _fake_fetch,
    )


def test_fetch_service_writes_raw_and_normalized(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path=tmp_path)
    _mock_fetch(monkeypatch, [_sample_room(), _sample_room(47916)])

    result = fetch_and_prepare_live_rooms_feed(
        settings=settings,
        allow_non_private_output=True,
    )

    assert result.success is True
    assert result.rooms_fetched == 2
    assert result.tickets_written == 2
    assert result.raw_output is not None
    assert result.normalized_output is not None
    assert result.raw_output.is_file()
    assert result.normalized_output.is_file()
    raw_payload = json.loads(result.raw_output.read_text(encoding="utf-8"))
    assert "data" in raw_payload
    lines = result.normalized_output.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_fetch_service_runs_validation_when_enabled(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path=tmp_path)
    _mock_fetch(monkeypatch, [_sample_room()])
    summary_path = tmp_path / "reports/live_feed_contract_validation_summary.json"
    report_path = tmp_path / "reports/live_feed_contract_validation_report.md"

    result = fetch_and_prepare_live_rooms_feed(
        settings=settings,
        validate=True,
        summary_json=summary_path,
        report_md=report_path,
        allow_non_private_output=True,
    )

    assert result.validation_passed is True
    assert result.valid_rows == 1
    assert result.invalid_rows == 0
    assert result.summary_json == summary_path
    assert result.report_md == report_path
    assert summary_path.is_file()
    assert report_path.is_file()


def test_missing_token_returns_safe_failure(tmp_path: Path) -> None:
    settings = _settings(token=None, tmp_path=tmp_path)

    result = fetch_and_prepare_live_rooms_feed(
        settings=settings,
        allow_non_private_output=True,
    )

    assert result.success is False
    assert result.error_message == MISSING_API_TOKEN_MESSAGE
    assert result.tickets_written == 0
    assert not Path(settings.live_rooms_normalized_output_path).is_file()


def test_cli_uses_fetch_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_service(**kwargs):
        captured.update(kwargs)
        return LiveRoomsFetchServiceResult(
            success=True,
            rooms_fetched=1,
            tickets_written=1,
            normalized_output=Path("data/private/live_vendor_tickets.jsonl"),
        )

    monkeypatch.setattr(fetch_cli, "fetch_and_prepare_live_rooms_feed", _fake_service)
    monkeypatch.setenv("LIVE_ROOMS_API_TOKEN", "cli-token")

    exit_code = fetch_cli.main(
        ["--limit", "25", "--overwrite", "--validate", "--allow-non-private-output"],
    )

    assert exit_code == 0
    assert captured["limit"] == 25
    assert captured["overwrite"] is True
    assert captured["validate"] is True
    assert captured["settings"].live_rooms_api_token == "cli-token"


def test_handler_stores_live_session_keys(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path=tmp_path)
    _mock_fetch(monkeypatch, [_sample_room()])
    session: dict[str, object] = {LIVE_API_FEED_ENTRIES_SESSION_KEY: []}
    feed_path = Path(settings.live_rooms_normalized_output_path)

    result = handle_live_api_feed_fetch(
        session,
        feed_path=feed_path,
        settings=settings,
        reload_fn=lambda path: session.setdefault(LIVE_API_FEED_ENTRIES_SESSION_KEY, ["reloaded"]),
    )

    assert result.success is True
    assert LIVE_API_FEED_LAST_FETCH_TIME_SESSION_KEY in session
    assert session[LIVE_API_FEED_LAST_FETCH_ERROR_SESSION_KEY] is None
    stored = session[LIVE_API_FEED_LAST_FETCH_RESULT_SESSION_KEY]
    assert isinstance(stored, dict)
    assert stored["success"] is True
    assert stored["tickets_written"] == 1


def test_successful_fetch_triggers_feed_reload(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path=tmp_path)
    _mock_fetch(monkeypatch, [_sample_room()])
    session: dict[str, object] = {}
    feed_path = Path(settings.live_rooms_normalized_output_path)
    reload_calls: list[Path] = []

    handle_live_api_feed_fetch(
        session,
        feed_path=feed_path,
        settings=settings,
        reload_fn=lambda path: reload_calls.append(path) or [],
    )

    assert reload_calls == [feed_path]


def test_failure_does_not_clear_existing_feed(tmp_path: Path) -> None:
    settings = _settings(token=None, tmp_path=tmp_path)
    existing_entries = [{"room_id": "keep-me"}]
    session: dict[str, object] = {LIVE_API_FEED_ENTRIES_SESSION_KEY: existing_entries}
    feed_path = Path(settings.live_rooms_normalized_output_path)

    handle_live_api_feed_fetch(
        session,
        feed_path=feed_path,
        settings=settings,
        reload_fn=lambda _path: pytest.fail("reload should not run on failure"),
    )

    assert session[LIVE_API_FEED_ENTRIES_SESSION_KEY] == existing_entries


def test_no_token_in_result_or_error_text(tmp_path: Path, monkeypatch) -> None:
    secret = "super-secret-bearer-token-xyz"
    settings = AppSettings(
        live_rooms_api_token=secret,
        live_rooms_raw_output_path=str(tmp_path / "data/private/live_rooms_raw.json"),
        live_rooms_normalized_output_path=str(
            tmp_path / "data/private/live_vendor_tickets.jsonl",
        ),
    )

    def _raise(*, limit, settings=None, fetch_page_fn=None):
        raise RuntimeError(f"HTTP 401 Unauthorized Bearer {secret}")

    monkeypatch.setattr(
        "app.live_shadow.live_rooms_fetch_service.fetch_live_rooms",
        _raise,
    )

    result = fetch_and_prepare_live_rooms_feed(
        settings=settings,
        allow_non_private_output=True,
    )

    serialized = json.dumps(result.to_session_dict())
    assert secret not in serialized
    assert result.error_message is not None
    assert secret not in result.error_message
    assert "REDACTED" in result.error_message or "401" in result.error_message


def test_default_limit_is_400(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(fetch_limit=400, tmp_path=tmp_path)
    seen: dict[str, int] = {}

    def _fake_fetch(*, limit: int, settings=None, fetch_page_fn=None):
        seen["limit"] = limit
        return [_sample_room()], {"data": [_sample_room()]}, ()

    monkeypatch.setattr(
        "app.live_shadow.live_rooms_fetch_service.fetch_live_rooms",
        _fake_fetch,
    )

    fetch_and_prepare_live_rooms_feed(
        settings=settings,
        allow_non_private_output=True,
    )

    assert seen["limit"] == 400
    assert settings.live_rooms_api_fetch_limit == 400


def test_raw_output_path_remains_under_data_private(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path=tmp_path)
    _mock_fetch(monkeypatch, [_sample_room()])

    result = fetch_and_prepare_live_rooms_feed(
        settings=settings,
        allow_non_private_output=True,
    )

    assert result.raw_output is not None
    assert "data/private" in result.raw_output.as_posix()


def test_resolve_live_rooms_api_token_strips_whitespace() -> None:
    settings = AppSettings(live_rooms_api_token="  tok  ")
    assert resolve_live_rooms_api_token(settings) == "tok"


def test_sanitize_fetch_error_message_redacts_bearer() -> None:
    text = sanitize_fetch_error_message("Auth failed: Bearer abc123xyz")
    assert text is not None
    assert "abc123xyz" not in text
    assert "REDACTED" in text

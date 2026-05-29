"""Tests for live rooms API client, adapter, and private output guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.live_shadow.live_rooms_adapter import (
    assert_private_output_path,
    extract_shop_identity_from_room,
    normalize_inbound_sender_type,
    normalize_room_to_live_ticket,
    normalize_rooms_to_live_tickets,
    write_normalized_live_tickets_jsonl,
)
from app.live_shadow.live_rooms_api_client import (
    build_live_rooms_headers,
    extract_rooms_from_payload,
)


def _sample_room(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 47915,
        "shop_id": 4136,
        "category": "complaint",
        "messages": [
            {"type": "seller", "content": "سلام، مشکل تسویه دارم"},
        ],
    }
    row.update(overrides)
    return row


def test_normalize_sample_room_matches_contract_fields() -> None:
    ticket = normalize_room_to_live_ticket(_sample_room())
    assert ticket["room_id"] == "47915"
    assert ticket["ticket_label"] == "complaint"
    assert ticket["shop_id"] == "4136"
    assert ticket["source_system"] == "inchand_internal_rooms_api"
    assert ticket["status"] == "open"
    assert ticket["status_fallback_used"] is True
    assert len(ticket["messages"]) == 1
    msg = ticket["messages"][0]
    assert msg["sender_type"] == "seller"
    assert msg["text"] == "سلام، مشکل تسویه دارم"
    assert msg["message_id"] == "47915-1"
    assert "created_at" in msg
    assert "created_at" in ticket
    assert "updated_at" in ticket


def test_sender_mapping_admin_and_seller() -> None:
    assert normalize_inbound_sender_type("admin") == "support_agent"
    assert normalize_inbound_sender_type("seller") == "seller"


def test_missing_timestamps_use_fallback_metadata() -> None:
    ticket = normalize_room_to_live_ticket(_sample_room())
    assert ticket["timestamp_fallback_used"] is True
    assert ticket["timestamp_fallback_reason"] == "missing_from_api"


def test_missing_status_defaults_open_with_flag() -> None:
    ticket = normalize_room_to_live_ticket(_sample_room(status=""))
    assert ticket["status"] == "open"
    assert ticket["status_fallback_used"] is True


def test_jsonl_writer_one_object_per_line(tmp_path: Path) -> None:
    private_dir = tmp_path / "data" / "private"
    private_dir.mkdir(parents=True)
    out = private_dir / "tickets.jsonl"
    rows = [
        normalize_room_to_live_ticket(_sample_room(id=1)),
        normalize_room_to_live_ticket(_sample_room(id=2, category="support")),
    ]
    write_normalized_live_tickets_jsonl(rows, out, overwrite=True)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "room_id" in parsed


def test_extract_rooms_list_response() -> None:
    payload = [{"id": 1, "category": "x", "messages": [{"type": "seller", "content": "a"}]}]
    rooms, _ = extract_rooms_from_payload(payload)
    assert len(rooms) == 1


def test_extract_rooms_data_wrapper() -> None:
    room = {"id": 2, "category": "y", "messages": [{"type": "seller", "content": "b"}]}
    rooms, _ = extract_rooms_from_payload({"data": [room]})
    assert rooms[0]["id"] == 2


def test_extract_rooms_rooms_key() -> None:
    room = {"id": 3, "category": "z", "messages": [{"type": "seller", "content": "c"}]}
    rooms, _ = extract_rooms_from_payload({"rooms": [room]})
    assert rooms[0]["id"] == 3


def test_no_redaction_phone_like_text_preserved() -> None:
    phone_text = "تماس: 09121234567"
    ticket = normalize_room_to_live_ticket(
        _sample_room(messages=[{"type": "seller", "content": phone_text}]),
    )
    assert ticket["messages"][0]["text"] == phone_text


def test_private_output_path_guard(tmp_path: Path) -> None:
    bad = tmp_path / "reports" / "leak.json"
    with pytest.raises(ValueError, match="data/private"):
        assert_private_output_path(bad)
    good = tmp_path / "data" / "private" / "ok.jsonl"
    assert assert_private_output_path(good) == good.resolve()


def test_private_output_guard_allows_override(tmp_path: Path) -> None:
    bad = tmp_path / "reports" / "leak.json"
    assert assert_private_output_path(bad, allow_non_private=True) == bad.resolve()


def test_build_live_rooms_headers_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import AppSettings, get_settings

    monkeypatch.setenv("LIVE_ROOMS_API_TOKEN", "test-token-value")
    get_settings.cache_clear()
    settings = AppSettings()
    headers = build_live_rooms_headers(settings)
    assert headers["Authorization"] == "Bearer test-token-value"
    assert headers["Accept"] == "application/json"
    get_settings.cache_clear()


def test_normalize_rooms_batch_collects_errors() -> None:
    tickets, errors = normalize_rooms_to_live_tickets(
        [
            _sample_room(),
            {"id": 99, "category": "x", "messages": []},
        ],
    )
    assert len(tickets) == 1
    assert errors


def test_extract_shop_id_from_top_level_field() -> None:
    identity = extract_shop_identity_from_room({"id": 1, "shop_id": 1234})
    assert identity["shop_id_present"] is True
    assert identity["shop_id_source"] == "shop_id"


def test_extract_shop_id_from_nested_shop_object() -> None:
    identity = extract_shop_identity_from_room({"id": 1, "shop": {"id": "abc-1"}})
    assert identity["shop_id_present"] is True
    assert identity["shop_id_source"] == "shop.id"


def test_extract_seller_id_from_nested_seller_object() -> None:
    identity = extract_shop_identity_from_room({"id": 1, "seller": {"id": "s-9"}})
    assert identity["seller_id_present"] is True
    assert identity["seller_id_source"] == "seller.id"


def test_normalized_ticket_preserves_shop_identity_metadata() -> None:
    ticket = normalize_room_to_live_ticket(
        _sample_room(
            shop_id=None,
            shop={"id": 99, "name": "My Shop"},
            seller={"id": "s-1"},
        ),
    )
    assert ticket["shop_id"] == "99"
    assert ticket["seller_id"] == "s-1"
    assert ticket["shop_name"] == "My Shop"
    assert ticket["shop_identity_available"] is True

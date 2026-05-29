"""Manual sandbox chat message models (shared; no assisted-input imports)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

AI_ASSISTED_DRAFT_SOURCE = "ai_assisted_draft"
IRAN_POST_TRACKING_SOURCE = "iran_post_tracking_verification"
SHIPMENT_DELIVERY_DECISION_SOURCE = "shipment_delivery_decision"


@dataclass(frozen=True)
class ManualChatMessage:
    """One manual sandbox chat message."""

    message_id: str
    sender_type: str
    text: str
    created_at: str
    source: str | None = None
    is_ai_generated: bool = False
    draft_provider: str | None = None
    tracking_verification_used: bool = False
    tracking_code: str | None = None
    tracking_verified: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message_id": self.message_id,
            "sender_type": self.sender_type,
            "text": self.text,
            "created_at": self.created_at,
        }
        if self.source is not None:
            payload["source"] = self.source
        if self.is_ai_generated:
            payload["is_ai_generated"] = True
        if self.draft_provider is not None:
            payload["draft_provider"] = self.draft_provider
        if self.tracking_verification_used:
            payload["tracking_verification_used"] = True
        if self.tracking_code is not None:
            payload["tracking_code"] = self.tracking_code
        if self.tracking_verified is not None:
            payload["tracking_verified"] = self.tracking_verified
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ManualChatMessage:
        sender = str(payload.get("sender_type") or "").strip().lower()
        if sender not in {"seller", "support_agent"}:
            raise ValueError("manual chat sender_type must be seller or support_agent")
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("manual chat text must be non-empty")
        is_ai = bool(payload.get("is_ai_generated"))
        source = payload.get("source")
        draft_provider = payload.get("draft_provider")
        tracking_used = bool(payload.get("tracking_verification_used"))
        tracking_code = payload.get("tracking_code")
        tracking_verified = payload.get("tracking_verified")
        return cls(
            message_id=str(payload.get("message_id") or "").strip() or "m1",
            sender_type=sender,
            text=text,
            created_at=str(payload.get("created_at") or utc_now_iso()),
            source=str(source).strip() if source is not None else None,
            is_ai_generated=is_ai,
            draft_provider=str(draft_provider).strip() if draft_provider is not None else None,
            tracking_verification_used=tracking_used,
            tracking_code=str(tracking_code).strip() if tracking_code is not None else None,
            tracking_verified=(bool(tracking_verified) if tracking_verified is not None else None),
        )


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()

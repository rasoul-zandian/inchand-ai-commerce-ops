"""Draft generation mode — first-turn isolation vs future live-thread context."""

from __future__ import annotations

from enum import StrEnum


class DraftGenerationMode(StrEnum):
    """How much ticket thread context may enter draft prompts."""

    FIRST_TURN_ONLY = "first_turn_only"
    LIVE_THREAD_CONTEXT = "live_thread_context"


DEFAULT_DRAFT_GENERATION_MODE = DraftGenerationMode.FIRST_TURN_ONLY


def parse_draft_generation_mode(value: str | None) -> DraftGenerationMode:
    """Parse config/env value; unknown values fall back to first-turn isolation."""
    if value is None:
        return DEFAULT_DRAFT_GENERATION_MODE
    normalized = str(value).strip().lower()
    if not normalized:
        return DEFAULT_DRAFT_GENERATION_MODE
    try:
        return DraftGenerationMode(normalized)
    except ValueError:
        return DEFAULT_DRAFT_GENERATION_MODE

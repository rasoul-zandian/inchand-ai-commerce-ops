"""Tests for operator-console Sheba/IBAN display policy (calibration vs masked)."""

from __future__ import annotations

import pytest
from app.operator_console.intent_display import (
    format_entity_extraction_lines,
    iban_display_value,
)
from app.workflows.operational_entity_extraction import (
    extract_operational_entities,
    mask_sensitive_entity,
)

_FULL_IBAN = "IR123456789012345678901234"


def test_iban_display_value_shows_full_when_config_true() -> None:
    masked = mask_sensitive_entity(_FULL_IBAN)
    assert (
        iban_display_value(
            full_iban=_FULL_IBAN,
            masked_iban=masked,
            show_full=True,
        )
        == _FULL_IBAN
    )


def test_iban_display_value_shows_masked_when_config_false() -> None:
    masked = mask_sensitive_entity(_FULL_IBAN)
    displayed = iban_display_value(
        full_iban=_FULL_IBAN,
        masked_iban=masked,
        show_full=False,
    )
    assert displayed == masked
    assert _FULL_IBAN not in displayed
    assert "*" in displayed


def test_iban_display_value_masks_from_full_when_no_masked_cached() -> None:
    displayed = iban_display_value(full_iban=_FULL_IBAN, show_full=False)
    assert _FULL_IBAN not in displayed
    assert displayed.endswith("1234")


def test_format_entity_extraction_lines_full_iban_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHOW_FULL_IBAN_IN_OPERATOR_CONSOLE", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    result = extract_operational_entities(f"شماره شبا {_FULL_IBAN[2:]}")
    lines = format_entity_extraction_lines(result, entity_source="test")
    joined = "\n".join(lines)
    assert _FULL_IBAN in joined or result.primary_iban in joined
    get_settings.cache_clear()


def test_format_entity_extraction_lines_masked_iban_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHOW_FULL_IBAN_IN_OPERATOR_CONSOLE", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    result = extract_operational_entities(f"شماره شبا {_FULL_IBAN[2:]}")
    lines = format_entity_extraction_lines(result, entity_source="test")
    joined = "\n".join(lines)
    assert _FULL_IBAN not in joined
    assert "*" in joined
    get_settings.cache_clear()

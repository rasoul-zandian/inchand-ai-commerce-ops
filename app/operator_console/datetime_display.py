"""Console datetime formatting (Gregorian EN, Jalali FA)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.operator_console.i18n import LANG_FA, normalize_console_lang

_GREGORIAN_FORMAT = "%Y-%m-%d %H:%M"


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_jalali_datetime(value: datetime | str | None) -> str:
    """Format as Persian Jalali YYYY/MM/DD HH:MM (minute precision, no timezone)."""
    import jdatetime

    parsed = _coerce_datetime(value)
    if parsed is None:
        return "—"
    utc_naive = parsed.astimezone(UTC).replace(tzinfo=None)
    jalali = jdatetime.datetime.fromgregorian(datetime=utc_naive)
    date_part = f"{jalali.year:04d}/{jalali.month:02d}/{jalali.day:02d}"
    time_part = f"{jalali.hour:02d}:{jalali.minute:02d}"
    return f"{date_part} {time_part}"


def format_gregorian_datetime(value: datetime | str | None) -> str:
    """Format as Gregorian YYYY-MM-DD HH:MM (minute precision, no timezone)."""
    parsed = _coerce_datetime(value)
    if parsed is None:
        return "—"
    utc_naive = parsed.astimezone(UTC).replace(tzinfo=None)
    return utc_naive.strftime(_GREGORIAN_FORMAT)


def format_datetime_for_console(value: datetime | str | None, language: str) -> str:
    """FA → Jalali; EN → Gregorian."""
    lang = normalize_console_lang(language)
    if lang == LANG_FA:
        return format_jalali_datetime(value)
    return format_gregorian_datetime(value)


def format_iso_for_console(iso_value: str | None, language: str) -> str:
    """Format ISO-8601 string for console display."""
    if iso_value is None or not str(iso_value).strip():
        return "—"
    return format_datetime_for_console(iso_value, language)

from __future__ import annotations

from datetime import UTC, datetime

from catering_system.ui import office_panel_views
from catering_system.ui.office_panel_views import (
    default_datetime_local_berlin,
    format_datetime_utc_iso,
    parse_datetime_local_berlin,
)


def test_default_datetime_local_berlin_preserves_seconds(monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is not None
            return datetime(2026, 8, 17, 17, 15, 54, tzinfo=tz)

    monkeypatch.setattr(office_panel_views, "datetime", FixedDateTime)

    assert default_datetime_local_berlin() == "2026-08-17T17:15:54"


def test_datetime_local_seconds_roundtrip_to_utc() -> None:
    parsed = parse_datetime_local_berlin("2026-08-17T17:15:54")

    assert parsed.isoformat() == "2026-08-17T17:15:54+02:00"
    assert format_datetime_utc_iso(parsed) == "2026-08-17T15:15:54+00:00"


def test_datetime_local_legacy_minute_input_still_parses() -> None:
    parsed = parse_datetime_local_berlin("2026-08-17T17:15")

    assert parsed.isoformat() == "2026-08-17T17:15:00+02:00"
    assert parsed.astimezone(UTC).isoformat() == "2026-08-17T15:15:00+00:00"

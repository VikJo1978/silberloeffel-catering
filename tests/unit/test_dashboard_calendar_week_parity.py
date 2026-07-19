"""Deterministic dashboard calendar-week parity (direct vs remote)."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from catering_system.ui import office_api_views as views
from catering_system.ui.remote_core_client import RemoteCoreClient
from tests.unit.test_office_panel_remote import (
    _API_TOKEN,
    _assert_same_modulo_remote_fields,
    _get,
    _seed,
    _start_api_server,
    _start_direct_panel,
    _start_remote_panel,
)

_BERLIN = ZoneInfo("Europe/Berlin")
_KW_RE = re.compile(r"Diese Woche \(KW (\d+)/(\d+)\)")


def _kw_from_html(html: str) -> tuple[int, int]:
    match = _KW_RE.search(html)
    assert match, "missing Diese Woche KW heading"
    return int(match.group(1)), int(match.group(2))


def _expected_kw(day: date) -> tuple[int, int]:
    iso = day.isocalendar()
    return iso.week, iso.year


def _patch_berlin_now(fixed: datetime):
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            if tz == _BERLIN:
                return fixed
            if tz is not None:
                return fixed.astimezone(tz)
            return fixed.replace(tzinfo=None)

    return patch.object(views, "datetime", _FixedDateTime)


@pytest.mark.parametrize(
    ("fixed", "expected_day"),
    [
        (datetime(2026, 7, 15, 12, 0, tzinfo=_BERLIN), date(2026, 7, 15)),
        (datetime(2026, 7, 20, 0, 30, tzinfo=_BERLIN), date(2026, 7, 20)),
        (datetime(2025, 12, 29, 9, 0, tzinfo=_BERLIN), date(2025, 12, 29)),
        (datetime(2026, 1, 1, 10, 0, tzinfo=_BERLIN), date(2026, 1, 1)),
    ],
    ids=["ordinary", "monday_boundary", "iso_year_boundary", "new_year_day"],
)
def test_berlin_today_and_expected_iso_week(
    fixed: datetime, expected_day: date
) -> None:
    with _patch_berlin_now(fixed):
        today = views.berlin_today()
    assert today == expected_day
    assert _expected_kw(today) == _expected_kw(expected_day)


def test_utc_and_berlin_differ_at_week_boundary() -> None:
    utc_sunday = datetime(2026, 7, 19, 22, 30, tzinfo=ZoneInfo("UTC"))
    berlin_time = utc_sunday.astimezone(_BERLIN)
    assert utc_sunday.date().isocalendar().week == 29
    assert berlin_time.date().isocalendar().week == 30


def _parity_at(fixed: datetime, tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    _seed(db)
    with _patch_berlin_now(fixed):
        direct_url, direct_server = _start_direct_panel(db)
        api_url, api_server = _start_api_server(db)
        remote = RemoteCoreClient(api_url, _API_TOKEN)
        remote_url, remote_server = _start_remote_panel(remote)
        try:
            d_status, d_html = _get(f"{direct_url}/")
            r_status, r_html = _get(f"{remote_url}/")
            assert d_status == r_status == 200
            assert _kw_from_html(d_html) == _kw_from_html(r_html)
            assert _kw_from_html(d_html) == _expected_kw(fixed.date())
            _assert_same_modulo_remote_fields(d_html, r_html)
        finally:
            for server in (direct_server, remote_server, api_server):
                server.shutdown()
                server.server_close()


def test_dashboard_direct_remote_parity_frozen_berlin_monday(tmp_path: Path) -> None:
    _parity_at(datetime(2026, 7, 20, 0, 30, tzinfo=_BERLIN), tmp_path)


def test_dashboard_direct_remote_parity_frozen_utc_berlin_divergence(
    tmp_path: Path,
) -> None:
    _parity_at(datetime(2026, 7, 20, 1, 0, tzinfo=_BERLIN), tmp_path)


def test_dashboard_kw_follows_frozen_clock_not_wall_clock(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    _seed(db)
    weeks: list[tuple[int, int]] = []
    for fixed in (
        datetime(2026, 7, 13, 12, 0, tzinfo=_BERLIN),
        datetime(2026, 7, 20, 12, 0, tzinfo=_BERLIN),
    ):
        with _patch_berlin_now(fixed):
            direct_url, direct_server = _start_direct_panel(db)
            try:
                _status, html = _get(f"{direct_url}/")
                weeks.append(_kw_from_html(html))
            finally:
                direct_server.shutdown()
                direct_server.server_close()
    assert weeks[0] != weeks[1]
    assert weeks[0] == _expected_kw(date(2026, 7, 13))
    assert weeks[1] == _expected_kw(date(2026, 7, 20))

from __future__ import annotations

import json
from datetime import date

from catering_system.domain.inquiry import PLANNING_MODES
from catering_system.domain.offer_charges import ReturnLogisticsDefinition
from catering_system.domain.wochenuebersicht import WochenuebersichtEntry
from catering_system.ui.kiosk_server import (
    next_return_working_day,
    render_order_feed_json,
)


def _entry(event_date: date) -> WochenuebersichtEntry:
    return WochenuebersichtEntry(
        order_id="order-1",
        effective_order_version_id="version-1",
        version_number=1,
        event_date=event_date,
        time_window_text="18:00-19:00",
        location_text="Hamburg",
        guest_count_estimate=40,
        planning_mode=PLANNING_MODES[0],
    )


def _render(
    event_date: date, definition: ReturnLogisticsDefinition | None
) -> dict[str, object]:
    document = json.loads(
        render_order_feed_json(
            event_date,
            (_entry(event_date),),
            {"order-1": definition},
        )
    )
    return document["orders"][0]


def test_next_return_working_day_skips_weekend() -> None:
    assert next_return_working_day(date(2026, 10, 1)) == date(2026, 10, 2)
    assert next_return_working_day(date(2026, 10, 2)) == date(2026, 10, 5)
    assert next_return_working_day(date(2026, 10, 3)) == date(2026, 10, 5)
    assert next_return_working_day(date(2026, 10, 4)) == date(2026, 10, 5)


def test_legacy_order_projects_null_return_logistics() -> None:
    order = _render(date(2026, 10, 1), None)
    assert order["return_logistics"] is None


def test_same_day_projects_event_date_and_requested_window_without_price() -> None:
    order = _render(
        date(2026, 10, 1),
        ReturnLogisticsDefinition(
            mode="SAME_DAY",
            pickup_window_text="22:00-23:00",
            same_day_fee_cents=2500,
        ),
    )
    assert order["return_logistics"] == {
        "mode": "SAME_DAY",
        "return_date": "2026-10-01",
        "pickup_window_text": "22:00-23:00",
    }
    assert "same_day_fee_cents" not in order["return_logistics"]


def test_next_working_day_projects_monday_after_friday() -> None:
    order = _render(
        date(2026, 10, 2),
        ReturnLogisticsDefinition(
            mode="NEXT_WORKING_DAY",
            pickup_window_text=None,
            same_day_fee_cents=2500,
        ),
    )
    assert order["return_logistics"] == {
        "mode": "NEXT_WORKING_DAY",
        "return_date": "2026-10-05",
        "pickup_window_text": None,
    }
    assert "same_day_fee_cents" not in order["return_logistics"]

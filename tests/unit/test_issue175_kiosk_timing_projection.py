from __future__ import annotations

import json
from datetime import date, datetime, time, timezone

from catering_system.domain.inquiry import PLANNING_MODES
from catering_system.domain.offer_charges import ReturnLogisticsDefinition
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.wochenuebersicht import (
    WochenuebersichtEntry,
    entry_from_effective,
)
from catering_system.ui.kiosk_server import render_order_feed_json


def _entry(*, canonical: bool) -> WochenuebersichtEntry:
    return WochenuebersichtEntry(
        order_id="order-1",
        effective_order_version_id="version-1",
        version_number=1,
        event_date=date(2026, 10, 1),
        time_window_text="18:00-19:00",
        location_text="Hamburg",
        guest_count_estimate=40,
        planning_mode=PLANNING_MODES[0],
        delivery_date_local=date(2026, 10, 1) if canonical else None,
        delivery_window_start_local=time(18, 0) if canonical else None,
        delivery_window_end_local=time(19, 0) if canonical else None,
    )


def _render(
    entry: WochenuebersichtEntry,
    return_logistics: ReturnLogisticsDefinition | None = None,
) -> dict[str, object]:
    document = json.loads(
        render_order_feed_json(
            entry.event_date,
            (entry,),
            {entry.order_id: return_logistics},
        )
    )
    return document["orders"][0]


def test_weekly_read_model_carries_canonical_delivery_timing_from_effective_version() -> (
    None
):
    now = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    order = Order(
        order_id="order-1",
        source_inquiry_id="inquiry-1",
        created_at=now,
        updated_at=now,
        effective_order_version_id="version-1",
    )
    effective = OrderVersion(
        order_version_id="version-1",
        order_id="order-1",
        version_number=1,
        created_at=now,
        event_date=date(2026, 10, 1),
        time_window_text="18:00-19:00",
        location_text="Hamburg",
        guest_count_estimate=40,
        planning_mode=PLANNING_MODES[0],
        delivery_date_local=date(2026, 10, 1),
        delivery_window_start_local=time(18, 0),
        delivery_window_end_local=time(19, 0),
    )

    entry = entry_from_effective(order, effective)

    assert entry.delivery_date_local == date(2026, 10, 1)
    assert entry.delivery_window_start_local == time(18, 0)
    assert entry.delivery_window_end_local == time(19, 0)


def test_delivery_window_projects_only_explicit_canonical_fields() -> None:
    order = _render(_entry(canonical=True))

    assert order["delivery_window"] == {
        "date": "2026-10-01",
        "start_local": "18:00",
        "end_local": "19:00",
    }


def test_legacy_delivery_text_is_not_parsed_into_canonical_window() -> None:
    order = _render(_entry(canonical=False))

    assert order["time_window_text"] == "18:00-19:00"
    assert "delivery_window" not in order


def test_same_day_return_projects_explicit_canonical_pickup_times() -> None:
    order = _render(
        _entry(canonical=True),
        ReturnLogisticsDefinition(
            mode="SAME_DAY",
            pickup_window_text="22:00-23:00",
            same_day_fee_cents=2500,
            pickup_window_start_local=time(22, 0),
            pickup_window_end_local=time(23, 0),
        ),
    )

    assert order["return_logistics"] == {
        "mode": "SAME_DAY",
        "return_date": "2026-10-01",
        "pickup_window_text": "22:00-23:00",
        "pickup_window_start_local": "22:00",
        "pickup_window_end_local": "23:00",
    }


def test_same_day_pickup_text_is_not_parsed_when_canonical_times_are_missing() -> None:
    order = _render(
        _entry(canonical=False),
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


def test_exact_delivery_and_event_start_project_without_synthetic_window() -> None:
    entry = WochenuebersichtEntry(
        order_id="order-exact",
        effective_order_version_id="version-exact",
        version_number=1,
        event_date=date(2026, 10, 1),
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=40,
        planning_mode=PLANNING_MODES[0],
        event_start_local=time(18, 0),
        delivery_time_local=time(16, 30),
    )

    order = _render(entry)

    assert order["event_start_local"] == "18:00"
    assert order["delivery_time_local"] == "16:30"
    assert "delivery_window" not in order

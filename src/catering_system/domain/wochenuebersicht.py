"""Wochenübersicht — kitchen-facing weekly overview, derived-only (WOCHENUEBERSICHT_EXECUTION_PACK_V1).

Derived on demand from Core truth (orders + effective versions); never persisted.
Only effective versions appear: the operational gate guarantees every listed
entry has a confirmed kitchen print.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from catering_system.domain.inquiry import PlanningMode
from catering_system.domain.order import Order, OrderVersion


@dataclass(frozen=True)
class WochenuebersichtEntry:
    """One kitchen-facing row; mirrors the effective OrderVersion only."""

    order_id: str
    effective_order_version_id: str
    version_number: int
    event_date: date
    time_window_text: str
    location_text: str
    guest_count_estimate: int | None
    planning_mode: PlanningMode
    delivery_date_local: date | None = None
    delivery_window_start_local: time | None = None
    delivery_window_end_local: time | None = None
    delivery_time_local: time | None = None
    event_start_local: time | None = None
    operational_pause_active: bool = False
    operational_pause_reason_code: str | None = None
    operational_pause_note: str | None = None


@dataclass(frozen=True)
class Wochenuebersicht:
    """Derived weekly overview for one ISO week; read-only, not a stored truth."""

    iso_year: int
    iso_week: int
    entries: tuple[WochenuebersichtEntry, ...]


def entry_from_effective(
    order: Order,
    effective: OrderVersion,
    *,
    operational_pause_active: bool = False,
    operational_pause_reason_code: str | None = None,
    operational_pause_note: str | None = None,
) -> WochenuebersichtEntry:
    return WochenuebersichtEntry(
        order_id=order.order_id,
        effective_order_version_id=effective.order_version_id,
        version_number=effective.version_number,
        event_date=effective.event_date,
        time_window_text=effective.time_window_text,
        location_text=effective.location_text,
        guest_count_estimate=effective.guest_count_estimate,
        planning_mode=effective.planning_mode,
        delivery_date_local=effective.delivery_date_local,
        delivery_window_start_local=effective.delivery_window_start_local,
        delivery_window_end_local=effective.delivery_window_end_local,
        delivery_time_local=effective.delivery_time_local,
        event_start_local=effective.event_start_local,
        operational_pause_active=operational_pause_active,
        operational_pause_reason_code=operational_pause_reason_code,
        operational_pause_note=operational_pause_note,
    )


def is_in_iso_week(day: date, iso_year: int, iso_week: int) -> bool:
    cal = day.isocalendar()
    return cal.year == iso_year and cal.week == iso_week

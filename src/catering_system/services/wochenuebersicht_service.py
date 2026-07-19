"""Wochenübersicht service — derived-only weekly read (WOCHENUEBERSICHT_EXECUTION_PACK_V1 §3).

Pure read: no writes, no events. Effective versions are the only source;
candidate and latest-historical versions never appear here.
"""

from __future__ import annotations

from datetime import date

from catering_system.domain.wochenuebersicht import (
    Wochenuebersicht,
    WochenuebersichtEntry,
    entry_from_effective,
    is_in_iso_week,
)
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.repositories.order_repository import OrderRepository


class WochenuebersichtService:
    def __init__(
        self,
        order_repository: OrderRepository,
        *,
        pause_repository: OrderOperationalPauseRepository | None = None,
    ) -> None:
        self._order_repository = order_repository
        self._pause_repository = pause_repository

    def _operational_pause(self, order_id: str) -> tuple[bool, str | None, str | None]:
        if self._pause_repository is None:
            return False, None, None
        active = self._pause_repository.get_active_pause(order_id)
        if active is None:
            return False, None, None
        return True, active.reason_code, active.note

    def get_week_overview(self, iso_year: int, iso_week: int) -> Wochenuebersicht:
        entries: list[WochenuebersichtEntry] = []
        for order in self._order_repository.list_orders():
            if order.cancelled_at is not None:
                continue  # STORNO pack §3: the kitchen must not deliver a cancelled order
            eid = order.effective_order_version_id
            if eid is None:
                continue
            effective = self._order_repository.get_order_version(eid)
            if effective is None or effective.order_id != order.order_id:
                continue
            if not is_in_iso_week(effective.event_date, iso_year, iso_week):
                continue
            pause_active, pause_reason_code, pause_note = self._operational_pause(
                order.order_id
            )
            entries.append(
                entry_from_effective(
                    order,
                    effective,
                    operational_pause_active=pause_active,
                    operational_pause_reason_code=pause_reason_code,
                    operational_pause_note=pause_note,
                )
            )
        entries.sort(key=lambda e: (e.event_date, e.time_window_text, e.order_id))
        return Wochenuebersicht(
            iso_year=iso_year, iso_week=iso_week, entries=tuple(entries)
        )

    def get_day_overview(self, event_date: date) -> tuple[WochenuebersichtEntry, ...]:
        """Per-date read for the courier order feed (KIOSK_ORDER_FEED_PACK_V1 §4).

        Delegates to get_week_overview so the selection gates (not cancelled,
        owned effective version only) cannot diverge from the kitchen view.
        """
        calendar = event_date.isocalendar()
        week = self.get_week_overview(calendar.year, calendar.week)
        return tuple(e for e in week.entries if e.event_date == event_date)

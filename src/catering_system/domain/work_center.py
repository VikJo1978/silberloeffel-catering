"""Arbeitszentrale read model — operational counters only, no lifecycle."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkCenterSnapshot:
    """Facts for the office work-center dashboard; source-agnostic counts only."""

    rueckrufe_open: int
    missed_calls_open: int
    offers_waiting: int
    offers_accepted: int
    upcoming_orders: int
    open_tasks: int
    today_calendar_entries: int
    pending_order_changes: int = 0

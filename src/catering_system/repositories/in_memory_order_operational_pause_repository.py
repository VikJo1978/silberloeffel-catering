"""In-memory pause-event store for tests and direct-mode defaults."""

from __future__ import annotations

from catering_system.domain.order_operational_pause import (
    OrderOperationalPauseEvent,
    derive_active_pause,
)


class InMemoryOrderOperationalPauseRepository:
    def __init__(self) -> None:
        self._events: list[OrderOperationalPauseEvent] = []

    def append_event(self, event: OrderOperationalPauseEvent) -> None:
        if any(row.command_id == event.command_id for row in self._events):
            raise ValueError(
                f"pause event already exists for command_id={event.command_id!r}"
            )
        if any(row.pause_event_id == event.pause_event_id for row in self._events):
            raise KeyError(event.pause_event_id)
        self._events.append(event)

    def list_events(self, order_id: str) -> tuple[OrderOperationalPauseEvent, ...]:
        rows = [row for row in self._events if row.order_id == order_id]
        return tuple(
            sorted(rows, key=lambda row: (row.occurred_at, row.pause_event_id))
        )

    def get_active_pause(self, order_id: str) -> OrderOperationalPauseEvent | None:
        return derive_active_pause(self.list_events(order_id))

"""Persistence protocol for order-level operational PAUSE events."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.order_operational_pause import OrderOperationalPauseEvent


class OrderOperationalPauseRepository(Protocol):
    def append_event(self, event: OrderOperationalPauseEvent) -> None: ...

    def list_events(self, order_id: str) -> tuple[OrderOperationalPauseEvent, ...]: ...

    def get_active_pause(self, order_id: str) -> OrderOperationalPauseEvent | None: ...

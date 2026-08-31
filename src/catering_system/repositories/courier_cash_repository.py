"""Persistence protocol for frozen Courier cash handoff events."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.courier_cash_handoff import CourierCashStoredEvent


class CourierCashRepository(Protocol):
    def append_event(self, event: CourierCashStoredEvent) -> None: ...

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> CourierCashStoredEvent | None: ...

    def get_latest_for_context(
        self, order_id: str, cash_execution_context_id: str
    ) -> CourierCashStoredEvent | None: ...

    def get_latest_for_order(self, order_id: str) -> CourierCashStoredEvent | None: ...

    def get_latest_correction_id(self, order_id: str) -> str | None: ...

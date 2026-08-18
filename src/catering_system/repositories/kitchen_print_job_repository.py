"""Persistence protocol for Phase 3 kitchen print attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from catering_system.domain.kitchen_print_job import KitchenPrintJob, KitchenPrintPolicy
from catering_system.domain.order import Order, OrderVersion


class KitchenPrintJobRepository(Protocol):
    def save(self, job: KitchenPrintJob) -> None: ...

    def get(self, print_job_id: str) -> KitchenPrintJob | None: ...

    def list_for_version(self, order_version_id: str) -> list[KitchenPrintJob]: ...

    def list_for_order(self, order_id: str) -> list[KitchenPrintJob]: ...

    def update(self, job: KitchenPrintJob) -> None: ...

    def save_reprint(
        self,
        previous: KitchenPrintJob,
        updated_previous: KitchenPrintJob | None,
        new_job: KitchenPrintJob,
    ) -> None: ...

    def acknowledge_and_confirm(
        self,
        job: KitchenPrintJob,
        confirmed_version: OrderVersion,
        *,
        expected_order: Order,
        activated_order: Order | None = None,
    ) -> bool: ...

    def claim_next_eligible(
        self, now: datetime, policy: KitchenPrintPolicy
    ) -> KitchenPrintJob | None: ...

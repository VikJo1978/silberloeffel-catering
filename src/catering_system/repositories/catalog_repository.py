"""Catalog repository protocol — read surface for 6D-1; seed insert is separate."""

from __future__ import annotations

from typing import Protocol

from datetime import datetime

from catering_system.domain.catalog import CatalogDish, CatalogPriceHistoryEntry


class CatalogRepository(Protocol):
    def list_dishes(
        self,
        *,
        active_only: bool = False,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CatalogDish]: ...

    def count_dishes(
        self,
        *,
        active_only: bool = False,
        q: str | None = None,
    ) -> int: ...

    def get_dish(self, dish_id: str) -> CatalogDish | None: ...

    def list_price_history(
        self, dish_id: str, *, limit: int = 20
    ) -> list[CatalogPriceHistoryEntry]: ...

    def insert_dish_if_absent(self, dish: CatalogDish) -> bool:
        """Seed-only: return False when dish_id already exists."""
        ...

    def update_dish(
        self,
        dish: CatalogDish,
        *,
        expected_updated_at: datetime,
        price_history_entry: CatalogPriceHistoryEntry | None = None,
    ) -> None:
        """Persist dish update; append history when entry is provided."""
        ...

    def close(self) -> None: ...

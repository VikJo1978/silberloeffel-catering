"""In-memory catalog repository for unit tests."""

from __future__ import annotations

from datetime import datetime

from catering_system.domain.catalog import (
    CatalogDish,
    CatalogDishNotFoundError,
    CatalogDishStaleError,
    CatalogPriceHistoryEntry,
)


class InMemoryCatalogRepository:
    def __init__(self) -> None:
        self._dishes: dict[str, CatalogDish] = {}
        self._history: dict[str, list[CatalogPriceHistoryEntry]] = {}

    def list_dishes(
        self,
        *,
        active: bool | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CatalogDish]:
        rows = self._filtered(active=active, q=q)
        return rows[offset : offset + limit]

    def count_dishes(
        self,
        *,
        active: bool | None = None,
        q: str | None = None,
    ) -> int:
        return len(self._filtered(active=active, q=q))

    def get_dish(self, dish_id: str) -> CatalogDish | None:
        return self._dishes.get(dish_id)

    def list_price_history(
        self, dish_id: str, *, limit: int = 20
    ) -> list[CatalogPriceHistoryEntry]:
        rows = self._history.get(dish_id, [])
        return rows[:limit]

    def insert_dish_if_absent(self, dish: CatalogDish) -> bool:
        if dish.dish_id in self._dishes:
            return False
        self._dishes[dish.dish_id] = dish
        return True

    def append_price_history(self, entry: CatalogPriceHistoryEntry) -> None:
        self._history.setdefault(entry.dish_id, []).append(entry)

    def update_dish(
        self,
        dish: CatalogDish,
        *,
        expected_updated_at: datetime,
        price_history_entry: CatalogPriceHistoryEntry | None = None,
    ) -> None:
        current = self._dishes.get(dish.dish_id)
        if current is None:
            raise CatalogDishNotFoundError(dish.dish_id)
        if current.updated_at != expected_updated_at:
            raise CatalogDishStaleError(dish.dish_id)
        self._dishes[dish.dish_id] = dish
        if price_history_entry is not None:
            self.append_price_history(price_history_entry)

    def close(self) -> None:
        return None

    def _filtered(self, *, active: bool | None, q: str | None) -> list[CatalogDish]:
        rows = list(self._dishes.values())
        # Mirrors the SQL WHERE: narrow before the caller's slice, never after.
        if active is not None:
            rows = [row for row in rows if row.active is active]
        if q:
            needle = q.casefold()
            rows = [row for row in rows if needle in row.name.casefold()]
        rows.sort(key=lambda row: (not row.active, row.name.casefold(), row.dish_id))
        return rows

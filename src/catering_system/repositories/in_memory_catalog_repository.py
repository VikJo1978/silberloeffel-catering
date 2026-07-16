"""In-memory catalog repository for unit tests."""

from __future__ import annotations

from catering_system.domain.catalog import CatalogDish, CatalogPriceHistoryEntry


class InMemoryCatalogRepository:
    def __init__(self) -> None:
        self._dishes: dict[str, CatalogDish] = {}
        self._history: dict[str, list[CatalogPriceHistoryEntry]] = {}

    def list_dishes(
        self,
        *,
        active_only: bool = False,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CatalogDish]:
        rows = self._filtered(active_only=active_only, q=q)
        return rows[offset : offset + limit]

    def count_dishes(
        self,
        *,
        active_only: bool = False,
        q: str | None = None,
    ) -> int:
        return len(self._filtered(active_only=active_only, q=q))

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

    def close(self) -> None:
        return None

    def _filtered(
        self, *, active_only: bool, q: str | None
    ) -> list[CatalogDish]:
        rows = list(self._dishes.values())
        if active_only:
            rows = [row for row in rows if row.active]
        if q:
            needle = q.casefold()
            rows = [row for row in rows if needle in row.name.casefold()]
        rows.sort(key=lambda row: (not row.active, row.name.casefold(), row.dish_id))
        return rows

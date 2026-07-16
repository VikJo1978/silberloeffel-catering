"""Read-only catalog dish service for office Verwaltung."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.catalog import (
    ALLERGEN_CODES,
    ALLERGEN_LABELS,
    AllergenCode,
    CatalogDish,
    CatalogPriceHistoryEntry,
)
from catering_system.repositories.catalog_repository import CatalogRepository

_MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class CatalogDishListResult:
    dishes: tuple[CatalogDish, ...]
    total_count: int
    truncated: bool


@dataclass(frozen=True)
class AllergenCodeDefinition:
    code: AllergenCode
    label: str


class CatalogDishService:
    def __init__(self, catalog_repository: CatalogRepository) -> None:
        self._catalog = catalog_repository

    def list_dishes(
        self,
        *,
        active_only: bool = False,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CatalogDishListResult:
        page_size = min(max(limit, 1), _MAX_PAGE_SIZE)
        offset = max(offset, 0)
        total = self._catalog.count_dishes(active_only=active_only, q=q)
        rows = self._catalog.list_dishes(
            active_only=active_only,
            q=q,
            limit=page_size,
            offset=offset,
        )
        return CatalogDishListResult(
            dishes=tuple(rows),
            total_count=total,
            truncated=offset + len(rows) < total,
        )

    def get_dish(self, dish_id: str) -> CatalogDish | None:
        return self._catalog.get_dish(dish_id)

    def list_price_history(
        self, dish_id: str, *, limit: int = 20
    ) -> tuple[CatalogPriceHistoryEntry, ...]:
        if self._catalog.get_dish(dish_id) is None:
            return ()
        return tuple(
            self._catalog.list_price_history(dish_id, limit=min(max(limit, 1), 100))
        )

    def list_allergen_codes(self) -> tuple[AllergenCodeDefinition, ...]:
        return tuple(
            AllergenCodeDefinition(code=code, label=ALLERGEN_LABELS[code])
            for code in ALLERGEN_CODES
        )

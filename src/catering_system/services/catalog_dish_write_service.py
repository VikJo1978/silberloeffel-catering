"""Büro write path for catalog Stammdaten (6D-2)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from catering_system.domain.catalog import (
    CatalogDish,
    CatalogDishNotFoundError,
    CatalogDishStaleError,
    CatalogDishUpdatePayload,
    CatalogDishUpdateResult,
    CatalogPriceHistoryEntry,
)
from catering_system.repositories.catalog_repository import CatalogRepository

_DEFAULT_CHANGED_BY = "office"


class CatalogDishWriteService:
    def __init__(self, catalog_repository: CatalogRepository) -> None:
        self._catalog = catalog_repository

    def update_dish(
        self,
        dish_id: str,
        *,
        update: CatalogDishUpdatePayload,
        expected_updated_at: datetime,
        changed_by: str = _DEFAULT_CHANGED_BY,
        now: datetime | None = None,
    ) -> CatalogDishUpdateResult:
        current = self._catalog.get_dish(dish_id)
        if current is None:
            raise CatalogDishNotFoundError(dish_id)
        if current.updated_at != expected_updated_at:
            raise CatalogDishStaleError(dish_id)
        commit_time = now or datetime.now(tz=UTC)
        updated = CatalogDish(
            dish_id=current.dish_id,
            name=update.name.strip(),
            description=update.description,
            composition=update.composition,
            notes=update.notes,
            current_unit_net_cents=update.current_unit_net_cents,
            allergens=update.allergens,
            active=update.active,
            created_at=current.created_at,
            updated_at=commit_time,
        )
        price_changed = (
            update.current_unit_net_cents != current.current_unit_net_cents
        )
        history_entry: CatalogPriceHistoryEntry | None = None
        if price_changed:
            history_entry = CatalogPriceHistoryEntry(
                entry_id=str(uuid.uuid4()),
                dish_id=dish_id,
                old_unit_net_cents=current.current_unit_net_cents,
                new_unit_net_cents=update.current_unit_net_cents,
                changed_at=commit_time,
                changed_by=changed_by,
                effective_from=update.effective_from,
            )
        self._catalog.update_dish(
            updated,
            expected_updated_at=expected_updated_at,
            price_history_entry=history_entry,
        )
        return CatalogDishUpdateResult(
            dish=updated,
            price_changed=price_changed,
            price_history_entry_id=(
                history_entry.entry_id if history_entry is not None else None
            ),
        )

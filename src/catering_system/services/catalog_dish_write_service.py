"""Büro write path for catalog Stammdaten (6D-2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from catering_system.domain.catalog import (
    CatalogDish,
    CatalogDishAlreadyExistsError,
    CatalogDishCreatePayload,
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

    def create_dish(
        self,
        create: CatalogDishCreatePayload,
        *,
        now: datetime | None = None,
    ) -> CatalogDish:
        """CATALOG_ADMIN_COMPLETION_V1A: a new dish is always created
        inactive (decision #8) — activation is a separate, explicit
        operation. dish_id is minted here, never client-supplied, matching
        every other Core-minted id in this codebase."""
        commit_time = now or datetime.now(tz=UTC)
        dish = CatalogDish(
            dish_id=str(uuid.uuid4()),
            name=create.name.strip(),
            description=create.description,
            composition=create.composition,
            notes=create.notes,
            current_unit_net_cents=create.current_unit_net_cents,
            allergens=create.allergens,
            active=False,
            created_at=commit_time,
            updated_at=commit_time,
            category=create.category,
            pricing_unit=create.pricing_unit,
            vat_rate_percent=create.vat_rate_percent,
        )
        if not self._catalog.insert_dish_if_absent(dish):
            raise CatalogDishAlreadyExistsError(dish.dish_id)
        return dish

    def _set_active(
        self,
        dish_id: str,
        *,
        active: bool,
        expected_updated_at: datetime,
        now: datetime | None = None,
    ) -> CatalogDish:
        """Shared activate/deactivate body: idempotent when the dish is
        already in the target state (repeated activate/deactivate is a
        no-op, not an error), but staleness is still checked first even for
        the no-op path — optimistic concurrency must reject an outdated
        client view regardless of whether anything would actually change."""
        current = self._catalog.get_dish(dish_id)
        if current is None:
            raise CatalogDishNotFoundError(dish_id)
        if current.updated_at != expected_updated_at:
            raise CatalogDishStaleError(dish_id)
        if current.active == active:
            return current
        commit_time = now or datetime.now(tz=UTC)
        updated = CatalogDish(
            dish_id=current.dish_id,
            name=current.name,
            description=current.description,
            composition=current.composition,
            notes=current.notes,
            current_unit_net_cents=current.current_unit_net_cents,
            allergens=current.allergens,
            active=active,
            created_at=current.created_at,
            updated_at=commit_time,
            category=current.category,
            pricing_unit=current.pricing_unit,
            vat_rate_percent=current.vat_rate_percent,
        )
        self._catalog.update_dish(updated, expected_updated_at=expected_updated_at)
        return updated

    def activate_dish(
        self,
        dish_id: str,
        *,
        expected_updated_at: datetime,
        now: datetime | None = None,
    ) -> CatalogDish:
        return self._set_active(
            dish_id, active=True, expected_updated_at=expected_updated_at, now=now
        )

    def deactivate_dish(
        self,
        dish_id: str,
        *,
        expected_updated_at: datetime,
        now: datetime | None = None,
    ) -> CatalogDish:
        return self._set_active(
            dish_id, active=False, expected_updated_at=expected_updated_at, now=now
        )

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
            # CATALOG_ADMIN_COMPLETION_V1A: this endpoint's payload has no
            # way to set these fields yet — carry the current values
            # forward so an unrelated text/price/active edit never wipes
            # them back to NULL.
            category=current.category,
            pricing_unit=current.pricing_unit,
            vat_rate_percent=current.vat_rate_percent,
        )
        price_changed = update.current_unit_net_cents != current.current_unit_net_cents
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

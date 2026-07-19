"""Catalog domain validation error paths."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from catering_system.domain.catalog import (
    CatalogDish,
    CatalogDishUpdatePayload,
    CatalogPriceHistoryEntry,
    validate_allergen_codes,
)


def test_validate_allergen_codes_rejects_unknown_code() -> None:
    with pytest.raises(ValueError, match="unknown allergen code"):
        validate_allergen_codes(["ZZ"])


def test_catalog_dish_rejects_invalid_uuid() -> None:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="dish_id must be a UUID"):
        CatalogDish(
            dish_id="not-a-uuid",
            name="Test",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=100,
            allergens=(),
            active=True,
            created_at=now,
            updated_at=now,
        )


def test_catalog_dish_rejects_negative_price() -> None:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="current_unit_net_cents must be non-negative"):
        CatalogDish(
            dish_id="11111111-1111-4111-8111-111111111111",
            name="Test",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=-1,
            allergens=(),
            active=True,
            created_at=now,
            updated_at=now,
        )


def test_catalog_update_payload_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name is required"):
        CatalogDishUpdatePayload(
            name="   ",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=100,
            allergens=(),
            active=True,
        )


def test_price_history_rejects_empty_changed_by() -> None:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="changed_by is required"):
        CatalogPriceHistoryEntry(
            entry_id="22222222-2222-4222-8222-222222222222",
            dish_id="11111111-1111-4111-8111-111111111111",
            old_unit_net_cents=100,
            new_unit_net_cents=120,
            changed_at=now,
            changed_by="   ",
            effective_from=date(2026, 7, 15),
        )


def test_catalog_dish_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CatalogDish(
            dish_id="11111111-1111-4111-8111-111111111111",
            name="Test",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=100,
            allergens=(),
            active=True,
            created_at=datetime(2026, 7, 14, 10, 0),
            updated_at=datetime(2026, 7, 14, 10, 0, tzinfo=UTC),
        )


def test_catalog_dish_rejects_long_description() -> None:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="description exceeds length limit"):
        CatalogDish(
            dish_id="11111111-1111-4111-8111-111111111111",
            name="Test",
            description="x" * 20001,
            composition=None,
            notes=None,
            current_unit_net_cents=100,
            allergens=(),
            active=True,
            created_at=now,
            updated_at=now,
        )


def test_catalog_update_payload_rejects_negative_price() -> None:
    with pytest.raises(ValueError, match="current_unit_net_cents must be non-negative"):
        CatalogDishUpdatePayload(
            name="Test",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=-5,
            allergens=(),
            active=True,
        )


def test_validate_allergen_codes_deduplicates_and_normalizes() -> None:
    assert validate_allergen_codes(["a", " A ", "g"]) == ("A", "G")


def test_allergen_labels_returns_german_labels() -> None:
    from catering_system.domain.catalog import allergen_labels

    assert allergen_labels(("A", "G")) == ("Gluten", "Milch")


def test_price_history_rejects_negative_old_and_new_prices() -> None:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="old_unit_net_cents must be non-negative"):
        CatalogPriceHistoryEntry(
            entry_id="22222222-2222-4222-8222-222222222222",
            dish_id="11111111-1111-4111-8111-111111111111",
            old_unit_net_cents=-1,
            new_unit_net_cents=120,
            changed_at=now,
            changed_by="chef",
            effective_from=None,
        )
    with pytest.raises(ValueError, match="new_unit_net_cents must be non-negative"):
        CatalogPriceHistoryEntry(
            entry_id="33333333-3333-4333-8333-333333333333",
            dish_id="11111111-1111-4111-8111-111111111111",
            old_unit_net_cents=100,
            new_unit_net_cents=-1,
            changed_at=now,
            changed_by="chef",
            effective_from=None,
        )


def test_catalog_update_payload_rejects_long_name() -> None:
    with pytest.raises(ValueError, match="name exceeds length limit"):
        CatalogDishUpdatePayload(
            name="x" * 501,
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=100,
            allergens=(),
            active=True,
        )

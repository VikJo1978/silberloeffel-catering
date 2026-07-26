"""Catalog domain validation error paths."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from catering_system.domain.catalog import (
    CatalogDish,
    CatalogDishCreatePayload,
    CatalogDishUpdatePayload,
    CatalogPriceHistoryEntry,
    validate_allergen_codes,
    validate_catalog_vat_rate_percent,
    validate_category,
    validate_pricing_unit,
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


# --- CATALOG_ADMIN_COMPLETION_V1A --------------------------------------------


def _create_payload(**overrides: object) -> CatalogDishCreatePayload:
    base: dict[str, object] = {
        "name": "Lachs-Canape",
        "category": "fingerfood",
        "pricing_unit": "stueck",
        "current_unit_net_cents": 250,
        "vat_rate_percent": 7,
    }
    base.update(overrides)
    return CatalogDishCreatePayload(**base)  # type: ignore[arg-type]


def test_catalog_dish_legacy_row_allows_null_admin_completion_fields() -> None:
    """A row read from storage before this slice existed must still
    construct — category/pricing_unit/vat_rate_percent stay optional on
    CatalogDish itself (decision #2/#3), unlike on the create payload."""
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    dish = CatalogDish(
        dish_id="11111111-1111-4111-8111-111111111111",
        name="Legacy",
        description=None,
        composition=None,
        notes=None,
        current_unit_net_cents=100,
        allergens=(),
        active=True,
        created_at=now,
        updated_at=now,
    )
    assert dish.category is None
    assert dish.pricing_unit is None
    assert dish.vat_rate_percent is None


def test_catalog_dish_rejects_invalid_pricing_unit_when_set() -> None:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="pricing_unit must be one of"):
        CatalogDish(
            dish_id="11111111-1111-4111-8111-111111111111",
            name="Test",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=100,
            allergens=(),
            active=True,
            created_at=now,
            updated_at=now,
            pricing_unit="kg",  # type: ignore[arg-type]
        )


def test_catalog_dish_rejects_invalid_vat_rate_when_set() -> None:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="vat_rate_percent must be one of"):
        CatalogDish(
            dish_id="11111111-1111-4111-8111-111111111111",
            name="Test",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=100,
            allergens=(),
            active=True,
            created_at=now,
            updated_at=now,
            vat_rate_percent=13,
        )


def test_validate_pricing_unit_accepts_all_three_values() -> None:
    for value in ("per_person", "stueck", "pauschal"):
        assert validate_pricing_unit(value) == value


def test_validate_pricing_unit_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="pricing_unit must be one of"):
        validate_pricing_unit("kg")


def test_validate_catalog_vat_rate_percent_accepts_7_and_19() -> None:
    assert validate_catalog_vat_rate_percent(7) == 7
    assert validate_catalog_vat_rate_percent(19) == 19


def test_validate_catalog_vat_rate_percent_rejects_other_values() -> None:
    with pytest.raises(ValueError, match="vat_rate_percent must be one of"):
        validate_catalog_vat_rate_percent(0)


def test_validate_category_requires_non_empty() -> None:
    with pytest.raises(ValueError, match="category is required"):
        validate_category("   ")
    with pytest.raises(ValueError, match="category is required"):
        validate_category("")


def test_validate_category_rejects_long_value() -> None:
    with pytest.raises(ValueError, match="category exceeds length limit"):
        validate_category("a" * 201)


def test_validate_category_trims_surrounding_whitespace_then_validates() -> None:
    """Trim at the edges is allowed, but the trimmed result still has to be
    a valid key — trimming never rescues an otherwise-invalid value."""
    assert validate_category("  fingerfood  ") == "fingerfood"
    with pytest.raises(ValueError, match="category must be a lowercase key"):
        validate_category("  Fingerfood  ")


@pytest.mark.parametrize(
    "value",
    [
        "fingerfood",
        "hauptgericht",
        "getraenke",
        "service-personal",
        "warme_speisen",
        "dessert2",
    ],
)
def test_validate_category_accepts_valid_ascii_keys(value: str) -> None:
    assert validate_category(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "Fingerfood",
        "finger food",
        "getränke",
        "-dessert",
        "dessert-",
        "food--hot",
        "food__hot",
    ],
)
def test_validate_category_rejects_invalid_ascii_keys(value: str) -> None:
    with pytest.raises(ValueError, match="category must be a lowercase key"):
        validate_category(value)


def test_catalog_dish_create_payload_full_dish() -> None:
    payload = _create_payload(
        description="Frisch",
        composition="Lachs, Brot",
        notes="Küchennotiz",
        allergens=("A", "D"),
    )
    assert payload.name == "Lachs-Canape"
    assert payload.category == "fingerfood"
    assert payload.pricing_unit == "stueck"
    assert payload.current_unit_net_cents == 250
    assert payload.vat_rate_percent == 7
    assert payload.allergens == ("A", "D")


def test_catalog_dish_create_payload_rejects_missing_category() -> None:
    with pytest.raises(ValueError, match="category is required"):
        _create_payload(category="   ")


def test_catalog_dish_create_payload_rejects_invalid_pricing_unit() -> None:
    with pytest.raises(ValueError, match="pricing_unit must be one of"):
        _create_payload(pricing_unit="kg")


def test_catalog_dish_create_payload_rejects_invalid_vat_rate() -> None:
    with pytest.raises(ValueError, match="vat_rate_percent must be one of"):
        _create_payload(vat_rate_percent=5)


def test_catalog_dish_create_payload_rejects_negative_price() -> None:
    with pytest.raises(ValueError, match="current_unit_net_cents must be non-negative"):
        _create_payload(current_unit_net_cents=-1)


def test_catalog_dish_create_payload_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name is required"):
        _create_payload(name="   ")

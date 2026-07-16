"""Domain tests for catalog Stammdaten."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from catering_system.domain.catalog import (
    ALLERGEN_LABELS,
    CatalogDish,
    allergen_labels,
    validate_allergen_codes,
)

_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
_DISH_ID = "11111111-1111-4111-8111-111111111111"


def _dish(**overrides: object) -> CatalogDish:
    base = {
        "dish_id": _DISH_ID,
        "name": "Kartoffelsalat",
        "description": "Hausgemacht",
        "composition": "Kartoffeln, Gurken",
        "notes": None,
        "current_unit_net_cents": 320,
        "allergens": ("G", "J"),
        "active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return CatalogDish(**base)  # type: ignore[arg-type]


def test_validate_allergen_codes_accepts_eu_codes() -> None:
    assert validate_allergen_codes(["A", "g", "C"]) == ("A", "G", "C")
    assert allergen_labels(("G", "J")) == ("Milch", "Senf")


def test_validate_allergen_codes_rejects_unknown_code() -> None:
    with pytest.raises(ValueError, match="unknown allergen"):
        validate_allergen_codes(["Z"])


def test_catalog_dish_rejects_negative_price_cents() -> None:
    with pytest.raises(ValueError, match="current_unit_net_cents"):
        _dish(current_unit_net_cents=-1)


def test_inactive_dish_is_valid() -> None:
    dish = _dish(active=False, allergens=())
    assert dish.active is False
    assert dish.allergens == ()


def test_allergen_dictionary_covers_a_through_n() -> None:
    assert len(ALLERGEN_LABELS) == 14

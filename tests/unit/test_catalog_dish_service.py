"""Catalog read service tests."""

from __future__ import annotations

from datetime import UTC, datetime

from catering_system.domain.catalog import CatalogDish
from catering_system.repositories.in_memory_catalog_repository import (
    InMemoryCatalogRepository,
)
from catering_system.services.catalog_dish_service import CatalogDishService

_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def _service(*dishes: CatalogDish) -> CatalogDishService:
    repo = InMemoryCatalogRepository()
    for dish in dishes:
        repo.insert_dish_if_absent(dish)
    return CatalogDishService(repo)


def test_list_dishes_search_and_active_filter() -> None:
    active = CatalogDish(
        dish_id="11111111-1111-4111-8111-111111111111",
        name="Schnitzel",
        description=None,
        composition=None,
        notes=None,
        current_unit_net_cents=850,
        allergens=("A",),
        active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    inactive = CatalogDish(
        dish_id="22222222-2222-4222-8222-222222222222",
        name="Kartoffelsalat",
        description=None,
        composition=None,
        notes=None,
        current_unit_net_cents=320,
        allergens=("J",),
        active=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
    service = _service(active, inactive)
    result = service.list_dishes(active=True, q="schn")
    assert result.total_count == 1
    assert result.dishes[0].name == "Schnitzel"


def test_list_dishes_inactive_filter_selects_only_inactive() -> None:
    """CATALOG_ADMIN_PANEL_V1: active=False is a real third state, not the
    absence of a filter — it must select the inactive rows."""
    active = CatalogDish(
        dish_id="11111111-1111-4111-8111-111111111111",
        name="Schnitzel",
        description=None,
        composition=None,
        notes=None,
        current_unit_net_cents=850,
        allergens=("A",),
        active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    inactive = CatalogDish(
        dish_id="22222222-2222-4222-8222-222222222222",
        name="Kartoffelsalat",
        description=None,
        composition=None,
        notes=None,
        current_unit_net_cents=320,
        allergens=("J",),
        active=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
    service = _service(active, inactive)
    result = service.list_dishes(active=False)
    assert result.total_count == 1
    assert result.dishes[0].name == "Kartoffelsalat"
    # None keeps both
    assert service.list_dishes(active=None).total_count == 2


def test_list_allergen_codes_returns_dictionary() -> None:
    service = _service()
    codes = service.list_allergen_codes()
    assert len(codes) == 14
    assert codes[0].code == "A"

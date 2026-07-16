"""Catalog write service tests (6D-2)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from catering_system.domain.catalog import (
    CatalogDish,
    CatalogDishNotFoundError,
    CatalogDishStaleError,
    CatalogDishUpdatePayload,
)
from catering_system.repositories.in_memory_catalog_repository import (
    InMemoryCatalogRepository,
)
from catering_system.services.catalog_dish_write_service import CatalogDishWriteService

_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
_LATER = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
_DISH_ID = "11111111-1111-4111-8111-111111111111"


def _dish(**overrides: object) -> CatalogDish:
    base = {
        "dish_id": _DISH_ID,
        "name": "Schnitzel",
        "description": "Alt",
        "composition": "mit Kartoffeln",
        "notes": None,
        "current_unit_net_cents": 850,
        "allergens": ("A", "G"),
        "active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return CatalogDish(**base)  # type: ignore[arg-type]


def _service(*dishes: CatalogDish) -> CatalogDishWriteService:
    repo = InMemoryCatalogRepository()
    for dish in dishes:
        repo.insert_dish_if_absent(dish)
    return CatalogDishWriteService(repo)


def test_update_text_fields_without_price_history() -> None:
    service = _service(_dish())
    result = service.update_dish(
        _DISH_ID,
        update=CatalogDishUpdatePayload(
            name="Schnitzel",
            description="Neu",
            composition="mit Rosmarinkartoffeln",
            notes="Intern",
            current_unit_net_cents=850,
            allergens=("A", "G"),
            active=True,
        ),
        expected_updated_at=_NOW,
        now=_LATER,
    )
    assert result.price_changed is False
    assert result.price_history_entry_id is None
    assert result.dish.composition == "mit Rosmarinkartoffeln"
    assert result.dish.updated_at == _LATER


def test_update_price_appends_history() -> None:
    service = _service(_dish())
    result = service.update_dish(
        _DISH_ID,
        update=CatalogDishUpdatePayload(
            name="Schnitzel",
            description="Alt",
            composition="mit Kartoffeln",
            notes=None,
            current_unit_net_cents=900,
            allergens=("A", "G"),
            active=True,
            effective_from=date(2026, 8, 1),
        ),
        expected_updated_at=_NOW,
        now=_LATER,
    )
    assert result.price_changed is True
    assert result.price_history_entry_id is not None
    history = service._catalog.list_price_history(_DISH_ID)
    assert len(history) == 1
    assert history[0].old_unit_net_cents == 850
    assert history[0].new_unit_net_cents == 900
    assert history[0].changed_by == "office"
    assert history[0].effective_from == date(2026, 8, 1)


def test_update_same_price_does_not_append_history() -> None:
    service = _service(_dish())
    result = service.update_dish(
        _DISH_ID,
        update=CatalogDishUpdatePayload(
            name="Schnitzel Wiener Art",
            description="Alt",
            composition="mit Kartoffeln",
            notes=None,
            current_unit_net_cents=850,
            allergens=("A",),
            active=True,
        ),
        expected_updated_at=_NOW,
        now=_LATER,
    )
    assert result.price_changed is False
    assert service._catalog.list_price_history(_DISH_ID) == []


def test_update_rejects_unknown_allergen_code() -> None:
    service = _service(_dish())
    with pytest.raises(ValueError, match="unknown allergen"):
        service.update_dish(
            _DISH_ID,
            update=CatalogDishUpdatePayload(
                name="Schnitzel",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=850,
                allergens=("Z",),
                active=True,
            ),
            expected_updated_at=_NOW,
        )


def test_update_rejects_stale_updated_at() -> None:
    service = _service(_dish())
    with pytest.raises(CatalogDishStaleError):
        service.update_dish(
            _DISH_ID,
            update=CatalogDishUpdatePayload(
                name="Schnitzel",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=900,
                allergens=(),
                active=True,
            ),
            expected_updated_at=_LATER,
        )


def test_update_missing_dish_raises_not_found() -> None:
    service = _service()
    with pytest.raises(CatalogDishNotFoundError):
        service.update_dish(
            _DISH_ID,
            update=CatalogDishUpdatePayload(
                name="Schnitzel",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=850,
                allergens=(),
                active=False,
            ),
            expected_updated_at=_NOW,
        )

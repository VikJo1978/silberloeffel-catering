"""Catalog write service tests (6D-2)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.catalog import (
    CatalogDish,
    CatalogDishAlreadyExistsError,
    CatalogDishCreatePayload,
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


def test_update_preserves_admin_completion_fields_not_in_payload() -> None:
    """Editing a dish through the pre-existing update endpoint must never
    silently wipe category/pricing_unit/vat_rate_percent back to NULL —
    that payload has no way to set them (CATALOG_ADMIN_COMPLETION_V1A)."""
    dish = _dish(category="fingerfood", pricing_unit="stueck", vat_rate_percent=7)
    service = _service(dish)
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
    assert result.dish.category == "fingerfood"
    assert result.dish.pricing_unit == "stueck"
    assert result.dish.vat_rate_percent == 7


# --- CATALOG_ADMIN_COMPLETION_V1A: create/activate/deactivate ---------------


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


def test_create_dish_full_dish_is_inactive() -> None:
    service = _service()
    dish = service.create_dish(
        _create_payload(
            description="Frisch",
            composition="Lachs, Brot",
            notes="Küchennotiz",
            allergens=("A", "D"),
        ),
        now=_NOW,
    )
    assert dish.active is False
    assert dish.name == "Lachs-Canape"
    assert dish.category == "fingerfood"
    assert dish.pricing_unit == "stueck"
    assert dish.current_unit_net_cents == 250
    assert dish.vat_rate_percent == 7
    assert dish.description == "Frisch"
    assert dish.composition == "Lachs, Brot"
    assert dish.notes == "Küchennotiz"
    assert dish.allergens == ("A", "D")
    assert dish.created_at == _NOW
    assert dish.updated_at == _NOW


def test_create_dish_mints_a_fresh_dish_id_each_call() -> None:
    service = _service()
    first = service.create_dish(_create_payload(), now=_NOW)
    second = service.create_dish(_create_payload(name="Andere"), now=_NOW)
    assert first.dish_id != second.dish_id


def test_create_dish_read_roundtrip_via_repository() -> None:
    repo = InMemoryCatalogRepository()
    service = CatalogDishWriteService(repo)
    created = service.create_dish(_create_payload(), now=_NOW)
    fetched = repo.get_dish(created.dish_id)
    assert fetched == created
    listed = repo.list_dishes()
    assert [row.dish_id for row in listed] == [created.dish_id]


def test_create_dish_duplicate_dish_id_rejected_at_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dish_id is server-minted (uuid4) so a real collision can't happen
    through normal use — but the repository guarantee create_dish relies on
    must hold. Force two calls to mint the same id to exercise the actual
    service code path end to end: the second is rejected, not silently
    overwritten, and CatalogDishAlreadyExistsError surfaces the failure."""
    import catering_system.services.catalog_dish_write_service as write_service_module

    fixed_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    monkeypatch.setattr(write_service_module.uuid, "uuid4", lambda: fixed_id)

    repo = InMemoryCatalogRepository()
    service = CatalogDishWriteService(repo)
    first = service.create_dish(_create_payload(), now=_NOW)
    assert first.dish_id == str(fixed_id)

    with pytest.raises(CatalogDishAlreadyExistsError):
        service.create_dish(_create_payload(name="Andere"), now=_LATER)

    unchanged = repo.get_dish(first.dish_id)
    assert unchanged == first


def test_activate_dish_flips_active_and_bumps_updated_at() -> None:
    service = _service(_dish(active=False))
    activated = service.activate_dish(_DISH_ID, expected_updated_at=_NOW, now=_LATER)
    assert activated.active is True
    assert activated.updated_at == _LATER


def test_deactivate_dish_flips_active_and_bumps_updated_at() -> None:
    service = _service(_dish(active=True))
    deactivated = service.deactivate_dish(
        _DISH_ID, expected_updated_at=_NOW, now=_LATER
    )
    assert deactivated.active is False
    assert deactivated.updated_at == _LATER


def test_repeated_activate_is_idempotent_no_op() -> None:
    service = _service(_dish(active=False))
    first = service.activate_dish(_DISH_ID, expected_updated_at=_NOW, now=_LATER)
    assert first.active is True
    second = service.activate_dish(
        _DISH_ID, expected_updated_at=first.updated_at, now=_LATER
    )
    assert second.active is True
    assert second.updated_at == first.updated_at


def test_repeated_deactivate_is_idempotent_no_op() -> None:
    service = _service(_dish(active=True))
    first = service.deactivate_dish(_DISH_ID, expected_updated_at=_NOW, now=_LATER)
    assert first.active is False
    second = service.deactivate_dish(
        _DISH_ID, expected_updated_at=first.updated_at, now=_LATER
    )
    assert second.active is False
    assert second.updated_at == first.updated_at


def test_activate_dish_rejects_stale_updated_at() -> None:
    service = _service(_dish(active=False))
    with pytest.raises(CatalogDishStaleError):
        service.activate_dish(_DISH_ID, expected_updated_at=_LATER)


def test_deactivate_dish_rejects_stale_updated_at() -> None:
    service = _service(_dish(active=True))
    with pytest.raises(CatalogDishStaleError):
        service.deactivate_dish(_DISH_ID, expected_updated_at=_LATER)


def test_activate_dish_missing_dish_raises_not_found() -> None:
    service = _service()
    with pytest.raises(CatalogDishNotFoundError):
        service.activate_dish(_DISH_ID, expected_updated_at=_NOW)


def test_deactivate_dish_missing_dish_raises_not_found() -> None:
    service = _service()
    with pytest.raises(CatalogDishNotFoundError):
        service.deactivate_dish(_DISH_ID, expected_updated_at=_NOW)


def test_activate_dish_preserves_admin_completion_fields() -> None:
    dish = _dish(
        active=False, category="fingerfood", pricing_unit="stueck", vat_rate_percent=7
    )
    service = _service(dish)
    activated = service.activate_dish(_DISH_ID, expected_updated_at=_NOW, now=_LATER)
    assert activated.category == "fingerfood"
    assert activated.pricing_unit == "stueck"
    assert activated.vat_rate_percent == 7

"""6D-3a — Offer Snapshot V2 catalog fields on OfferPosition."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from catering_system.domain.catalog import CatalogDish, CatalogDishUpdatePayload
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_catalog_repository import (
    SQLiteCatalogRepository,
)
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from catering_system.services.catalog_dish_write_service import CatalogDishWriteService
from catering_system.services.offer_service import OfferService
from catering_system.services.offer_snapshot_validation import validate_offer_snapshot
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _SNAPSHOT_ID,
    _VARIANT_ID,
    _sample_inquiry,
    _valid_snapshot,
    _world,
)

_OTHER_VARIANT_ID = "44444444-4444-4444-8444-444444444442"
_DISH_ID = "11111111-1111-4111-8111-111111111111"
_OTHER_INQUIRY_ID = "33333333-3333-4333-8333-333333333334"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"
_OTHER_POSITION_ID = "88888888-8888-4888-8888-888888888882"
_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def _catalog_position(
    *,
    unit_net_cents: int = 900,
    allergens: list[str] | None = None,
    dish_id: str = _DISH_ID,
    position_id: str = _POSITION_ID,
) -> dict[str, object]:
    return {
        "position_id": position_id,
        "kind": "catalog",
        "catalog_item_id": dish_id,
        "name": "Schnitzel",
        "description": "Knusprig",
        "composition": "Kalbfleisch",
        "quantity_mode": "total",
        "quantity": "10",
        "unit_label": "Portion",
        "unit_net_cents": unit_net_cents,
        "net_total_cents": unit_net_cents * 10,
        "vat_rate_percent": 7,
        "vat_amount_cents": (unit_net_cents * 10 * 7) // 100,
        "gross_total_cents": unit_net_cents * 10 + (unit_net_cents * 10 * 7) // 100,
        "notes": None,
        "related_position_id": None,
        "allergens": allergens if allergens is not None else ["A", "G"],
        "vegan": None,
        "vegetarian": None,
    }


def _v2_snapshot_body(
    *,
    inquiry_id: str = _INQUIRY_ID,
    variant_id: str = _VARIANT_ID,
    position_id: str = _POSITION_ID,
    unit_net_cents: int = 900,
    allergens: list[str] | None = None,
) -> dict[str, object]:
    position = _catalog_position(
        unit_net_cents=unit_net_cents,
        allergens=allergens,
        position_id=position_id,
    )
    net = position["net_total_cents"]
    vat = position["vat_amount_cents"]
    gross = position["gross_total_cents"]
    return {
        "schema_version": "offer_snapshot_v2",
        "source": "fingerfood-configurator-backend",
        "source_draft_id": "draft-v2",
        "inquiry_id": inquiry_id,
        "snapshot_id": _SNAPSHOT_ID,
        "snapshot_created_at": "2026-07-16T08:30:00+00:00",
        "valid_until": "2026-07-30",
        "currency": "EUR",
        "recipient": {
            "company_name": "Example company",
            "contact_name": "Example contact",
            "email": "customer@example.invalid",
            "postal_address": "Customer-visible recipient address",
        },
        "event": {
            "event_date": "2026-08-20",
            "time_window_text": "18:00–22:00",
            "location_text": "Hamburg",
            "guest_count": 80,
            "planning_mode": "caterer_suggestion",
        },
        "customer_text": {
            "title": "Sommerfest",
            "introduction": "Customer-visible introduction",
            "notes": "Customer-visible conditions and notes",
        },
        "payment_terms": {
            "method": "RECHNUNG",
            "customer_visible_text": "Zahlung per Rechnung",
        },
        "calculator": {
            "name": "fingerfood-backend",
            "calculator_revision": "v2",
            "catalog_revision": "core-catalog-v1",
            "tax_revision": "v1",
        },
        "variants": [
            {
                "variant_id": variant_id,
                "label": "Variante A",
                "description": "Catalog snapshot",
                "positions": [position],
                "totals": {
                    "net_cents": net,
                    "vat_7_base_cents": net,
                    "vat_7_amount_cents": vat,
                    "vat_19_base_cents": 0,
                    "vat_19_amount_cents": 0,
                    "gross_cents": gross,
                },
            }
        ],
    }


def _valid_v2_snapshot(**kwargs: object) -> dict[str, object]:
    payload = _v2_snapshot_body(**kwargs)
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def _sqlite_world(tmp_path: Path) -> tuple[OfferService, SQLiteOfferRepository, Path]:
    db = tmp_path / "core.db"
    inquiry_repo = InMemoryInquiryRepository()
    inquiry_repo.save(_sample_inquiry())
    offer_repo = SQLiteOfferRepository(db)
    service = OfferService(
        offer_repo,
        inquiry_repo,
        InMemoryOrderRepository(),
        now=lambda: _NOW,
        today=lambda: date(2026, 7, 15),
    )
    return service, offer_repo, db


def _other_inquiry() -> Inquiry:
    return _sample_inquiry(inquiry_id=_OTHER_INQUIRY_ID)


def test_v2_catalog_line_roundtrip_persists_snapshot_fields(tmp_path: Path) -> None:
    service, offer_repo, db = _sqlite_world(tmp_path)
    try:
        catalog_repo = SQLiteCatalogRepository(db)
        catalog_repo.insert_dish_if_absent(
            CatalogDish(
                dish_id=_DISH_ID,
                name="Schnitzel",
                description="Knusprig",
                composition="Kalbfleisch",
                notes=None,
                current_unit_net_cents=900,
                allergens=("A", "G"),
                active=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )

        offer = service.prepare_offer_version(_INQUIRY_ID, _valid_v2_snapshot())
        position = offer.versions[0].variants[0].positions[0]

        assert position.catalog_item_id == _DISH_ID
        assert position.unit_net_cents == 900
        assert position.allergens == ("A", "G")
        assert position.vegan is None
        assert position.vegetarian is None

        stored = offer_repo.get(offer.offer_id)
        assert stored is not None
        stored_position = stored.versions[0].variants[0].positions[0]
        assert stored_position.catalog_item_id == _DISH_ID
        assert stored_position.allergens == ("A", "G")
        assert stored_position.unit_net_cents == 900
    finally:
        offer_repo.close()


def test_catalog_change_isolation_between_offers(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    inquiry_repo = InMemoryInquiryRepository()
    inquiry_repo.save(_sample_inquiry())
    inquiry_repo.save(_other_inquiry())
    offer_repo = SQLiteOfferRepository(db)
    catalog_repo = SQLiteCatalogRepository(db)
    try:
        catalog_repo.insert_dish_if_absent(
            CatalogDish(
                dish_id=_DISH_ID,
                name="Schnitzel",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=900,
                allergens=("G",),
                active=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        service = OfferService(
            offer_repo,
            inquiry_repo,
            InMemoryOrderRepository(),
            now=lambda: _NOW,
            today=lambda: date(2026, 7, 15),
        )

        first = service.prepare_offer_version(
            _INQUIRY_ID, _valid_v2_snapshot(allergens=["G"])
        )
        first_position = first.versions[0].variants[0].positions[0]
        assert first_position.unit_net_cents == 900
        assert first_position.allergens == ("G",)

        write_service = CatalogDishWriteService(catalog_repo)
        write_service.update_dish(
            _DISH_ID,
            update=CatalogDishUpdatePayload(
                name="Schnitzel",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=1000,
                allergens=("G", "J"),
                active=True,
                effective_from=date(2026, 8, 1),
            ),
            expected_updated_at=_NOW,
            now=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
        )

        reloaded = offer_repo.get(first.offer_id)
        assert reloaded is not None
        reloaded_position = reloaded.versions[0].variants[0].positions[0]
        assert reloaded_position.unit_net_cents == 900
        assert reloaded_position.allergens == ("G",)

        second = service.prepare_offer_version(
            _OTHER_INQUIRY_ID,
            _valid_v2_snapshot(
                inquiry_id=_OTHER_INQUIRY_ID,
                variant_id=_OTHER_VARIANT_ID,
                position_id=_OTHER_POSITION_ID,
                unit_net_cents=1000,
                allergens=["G", "J"],
            ),
        )
        second_position = second.versions[0].variants[0].positions[0]
        assert second_position.unit_net_cents == 1000
        assert second_position.allergens == ("G", "J")
    finally:
        catalog_repo.close()
        offer_repo.close()


def test_v1_prepare_offer_leaves_allergens_null() -> None:
    _inquiries, _orders, _offers, service = _world(inquiry=_sample_inquiry())

    offer = service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    position = offer.versions[0].variants[0].positions[0]
    assert position.catalog_item_id == "catalog-1"
    assert position.allergens is None
    assert position.vegan is None
    assert position.vegetarian is None


def test_v2_catalog_position_requires_catalog_item_id() -> None:
    payload = _valid_v2_snapshot()
    positions = payload["variants"][0]["positions"]  # type: ignore[index]
    positions[0].pop("catalog_item_id")
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="catalog_item_id"):
        validate_offer_snapshot(payload)


def test_v2_catalog_position_requires_allergens() -> None:
    payload = _valid_v2_snapshot()
    positions = payload["variants"][0]["positions"]  # type: ignore[index]
    positions[0].pop("allergens")
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="allergens"):
        validate_offer_snapshot(payload)


def test_v2_rejects_invalid_allergen_code() -> None:
    payload = _valid_v2_snapshot(allergens=["Z"])
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="unknown allergen"):
        validate_offer_snapshot(payload)


def test_v1_rejects_v2_only_position_fields() -> None:
    payload = deepcopy(_valid_snapshot())
    positions = payload["variants"][0]["positions"]  # type: ignore[index]
    positions[0]["allergens"] = ["A"]
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="unknown"):
        validate_offer_snapshot(payload)

"""6C-0p — OfferPosition/OfferVariant print text persistence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
)
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _POSITION_ID,
    _VARIANT_ID,
    _accepted_offer_state,
    _sample_inquiry,
    _valid_snapshot,
    _world,
)

_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_VERSION_ID = "33333333-3333-4333-8333-333333333333"
_HASH = "sha256:" + ("a" * 64)
_NOW = datetime(2026, 7, 15, 8, 30, tzinfo=UTC)


def _accepted_variant(offer: Offer) -> OfferVariant:
    link = offer.conversion_link
    assert link is not None
    version = next(
        item
        for item in offer.versions
        if item.offer_version_id == link.offer_version_id
    )
    return next(item for item in version.variants if item.variant_id == link.variant_id)


def _legacy_position() -> OfferPosition:
    return OfferPosition(
        position_id=_POSITION_ID,
        kind="catalog",
        name="Legacy Fingerfood",
        unit_net_cents=290,
        net_total_cents=23200,
        vat_rate_percent=7,
        vat_amount_cents=1624,
        gross_total_cents=24824,
    )


def _legacy_offer() -> Offer:
    return Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        versions=(
            OfferVersion(
                offer_version_id=_VERSION_ID,
                offer_id=_OFFER_ID,
                version_number=1,
                created_at=_NOW,
                valid_until=date(2026, 7, 31),
                snapshot_id="77777777-7777-4777-8777-777777777771",
                snapshot_hash=_HASH,
                event_date=date(2026, 8, 20),
                time_window_text="18:00–22:00",
                location_text="Hamburg",
                guest_count=80,
                planning_mode="caterer_suggestion",
                payment_method="RECHNUNG",
                payment_customer_visible_text="Zahlung per Rechnung",
                variants=(
                    OfferVariant(
                        variant_id=_VARIANT_ID,
                        offer_version_id=_VERSION_ID,
                        label="Legacy Variante",
                        positions=(_legacy_position(),),
                    ),
                ),
            ),
        ),
    )


def test_prepare_offer_version_persists_print_text_fields() -> None:
    _inquiries, _orders, offers, service = _world(inquiry=_sample_inquiry())
    offer = service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    version = offer.versions[0]
    variant = version.variants[0]
    position = variant.positions[0]

    assert variant.description == "Customer-visible alternative"
    assert position.description == "Frozen description"
    assert position.composition == "Frozen composition"
    assert position.notes == "Frozen customization"
    assert position.quantity == Decimal("80")
    assert position.quantity_mode == "total"
    assert position.unit_label == "Stück"

    reloaded = offers.get(offer.offer_id)
    assert reloaded == offer


def test_convert_accepted_offer_keeps_print_text_fields_on_offer() -> None:
    offer, version_id, variant_id, acceptance_id, _offers, _orders, _inq, service = (
        _accepted_offer_state()
    )
    converted, _order, _order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        accepted_variant_id=variant_id,
        acceptance_id=acceptance_id,
    )
    position = _accepted_variant(converted).positions[0]

    assert position.name == "Fingerfood Paket"
    assert position.composition == "Frozen composition"
    assert position.description == "Frozen description"


def test_sqlite_roundtrip_preserves_print_text_fields(tmp_path: Path) -> None:
    _inquiries, _orders, offers, service = _world(inquiry=_sample_inquiry())
    offer = service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    in_memory = offers.get(offer.offer_id)
    assert in_memory is not None

    sqlite = SQLiteOfferRepository(tmp_path / "offer-print-fields.db")
    sqlite.save(in_memory)
    loaded = sqlite.get(offer.offer_id)
    sqlite.close()
    assert loaded == in_memory


def test_legacy_offer_without_print_text_fields_roundtrips(tmp_path: Path) -> None:
    offer = _legacy_offer()
    repo = SQLiteOfferRepository(tmp_path / "legacy-offer.db")
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    repo.close()
    assert loaded == offer
    assert loaded is not None
    position = loaded.versions[0].variants[0].positions[0]
    assert position.name == "Legacy Fingerfood"
    assert position.description is None
    assert position.composition is None
    assert position.notes is None
    assert position.quantity is None
    assert position.quantity_mode is None
    assert position.unit_label is None


def test_accepted_variant_positions_are_print_projection_ready() -> None:
    (
        offer,
        _version_id,
        _variant_id,
        _acceptance_id,
        _offers,
        _orders,
        _inq,
        _service,
    ) = _accepted_offer_state()
    position = offer.versions[0].variants[0].positions[0]
    print_row = {
        "name": position.name,
        "description": position.description,
        "composition": position.composition,
        "notes": position.notes,
        "quantity": position.quantity,
        "unit_label": position.unit_label,
    }
    assert print_row == {
        "name": "Fingerfood Paket",
        "description": "Frozen description",
        "composition": "Frozen composition",
        "notes": "Frozen customization",
        "quantity": Decimal("80"),
        "unit_label": "Stück",
    }

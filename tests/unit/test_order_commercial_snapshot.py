"""Unit tests — OrderCommercialSnapshot domain factory (PR A)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from catering_system.domain.offer import (
    AcceptanceEvidence,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    SentEvidence,
)
from catering_system.domain.order_commercial_snapshot import (
    OrderCommercialPosition,
    OrderCommercialSnapshot,
    build_order_commercial_snapshot,
    map_offer_position,
)

_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_ORDER_ID = "22222222-2222-4222-8222-222222222222"
_VERSION_ID = "33333333-3333-4333-8333-333333333331"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "55555555-5555-4555-8555-555555555551"
_ACCEPTANCE_ID = "66666666-6666-4666-8666-666666666661"
_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _position(**overrides: object) -> OfferPosition:
    payload: dict[str, object] = {
        "position_id": _POSITION_ID,
        "kind": "catalog",
        "name": "Fingerfood Paket",
        "unit_net_cents": 290,
        "net_total_cents": 23200,
        "vat_rate_percent": 7,
        "vat_amount_cents": 1624,
        "gross_total_cents": 24824,
        "description": "Frozen description",
        "composition": "Frozen composition",
        "notes": "Frozen notes",
        "quantity": Decimal("80"),
        "quantity_mode": "total",
        "unit_label": "Stück",
        "catalog_item_id": "catalog-1",
        "allergens": ("A", "C"),
    }
    payload.update(overrides)
    return OfferPosition(**payload)  # type: ignore[arg-type]


def _variant(*, positions: tuple[OfferPosition, ...] | None = None) -> OfferVariant:
    return OfferVariant(
        variant_id=_VARIANT_ID,
        offer_version_id=_VERSION_ID,
        label="Variante A",
        description="Customer-visible alternative",
        positions=positions or (_position(),),
    )


def _version(*, variant: OfferVariant | None = None) -> OfferVersion:
    chosen = variant or _variant()
    return OfferVersion(
        offer_version_id=_VERSION_ID,
        offer_id=_OFFER_ID,
        version_number=1,
        created_at=_NOW,
        valid_until=date(2026, 7, 29),
        snapshot_id="77777777-7777-4777-8777-777777777771",
        snapshot_hash="sha256:" + ("a" * 64),
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count=80,
        planning_mode="caterer_suggestion",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        variants=(chosen,),
    )


def _acceptance() -> AcceptanceEvidence:
    return AcceptanceEvidence(
        acceptance_id=_ACCEPTANCE_ID,
        offer_id=_OFFER_ID,
        accepted_offer_version_id=_VERSION_ID,
        accepted_variant_id=_VARIANT_ID,
        accepted_at=_NOW + timedelta(hours=1),
        recorded_at=_NOW + timedelta(hours=1, minutes=5),
        channel="email",
        evidence_reference="reply-1",
        recorded_by="office-panel",
    )


def _offer(*, version: OfferVersion | None = None) -> Offer:
    chosen = version or _version()
    sent = SentEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=chosen.offer_version_id,
        sent_at=_NOW,
        recorded_at=_NOW + timedelta(minutes=1),
        channel="email",
        recipient_reference="kunde@example.invalid",
        evidence_reference="mail-1",
        recorded_by="office-panel",
    )
    return Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id="88888888-8888-4888-8888-888888888881",
        created_at=_NOW,
        versions=(chosen,),
        sent_evidence=(sent,),
        acceptance_evidence=_acceptance(),
    )


def test_map_offer_position_copies_frozen_commercial_fields() -> None:
    mapped = map_offer_position(_position())
    assert mapped == OrderCommercialPosition(
        position_id=_POSITION_ID,
        kind="catalog",
        name="Fingerfood Paket",
        unit_net_cents=290,
        net_total_cents=23200,
        vat_rate_percent=7,
        vat_amount_cents=1624,
        gross_total_cents=24824,
        description="Frozen description",
        composition="Frozen composition",
        notes="Frozen notes",
        quantity=Decimal("80"),
        quantity_mode="total",
        unit_label="Stück",
        catalog_item_id="catalog-1",
        allergens=("A", "C"),
    )


def test_build_order_commercial_snapshot_from_accepted_variant() -> None:
    offer = _offer()
    version = offer.versions[0]
    variant = version.variants[0]
    acceptance = offer.acceptance_evidence
    assert acceptance is not None

    snapshot = build_order_commercial_snapshot(
        order_id=_ORDER_ID,
        offer=offer,
        offer_version=version,
        variant=variant,
        acceptance=acceptance,
        created_at=_NOW + timedelta(hours=2),
        snapshot_id="99999999-9999-4999-8999-999999999991",
    )

    assert snapshot.order_id == _ORDER_ID
    assert snapshot.source_offer_id == _OFFER_ID
    assert snapshot.source_offer_version_id == _VERSION_ID
    assert snapshot.source_variant_id == _VARIANT_ID
    assert snapshot.acceptance_id == _ACCEPTANCE_ID
    assert snapshot.accepted_at == acceptance.accepted_at
    assert snapshot.recorded_by == "office-panel"
    assert snapshot.variant_label == "Variante A"
    assert snapshot.variant_description == "Customer-visible alternative"
    assert snapshot.payment_method == "RECHNUNG"
    assert snapshot.payment_customer_visible_text == "Zahlung per Rechnung"
    assert len(snapshot.positions) == 1
    assert snapshot.positions[0].name == "Fingerfood Paket"
    assert snapshot.positions[0].unit_net_cents == 290


def test_build_rejects_acceptance_variant_mismatch() -> None:
    offer = _offer()
    version = offer.versions[0]
    variant = version.variants[0]
    acceptance = _acceptance()
    bad = AcceptanceEvidence(
        acceptance_id=_ACCEPTANCE_ID,
        offer_id=_OFFER_ID,
        accepted_offer_version_id=_VERSION_ID,
        accepted_variant_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        accepted_at=acceptance.accepted_at,
        recorded_at=acceptance.recorded_at,
        channel="email",
        evidence_reference="reply-1",
        recorded_by="office-panel",
    )
    with pytest.raises(ValueError, match="acceptance variant mismatch"):
        build_order_commercial_snapshot(
            order_id=_ORDER_ID,
            offer=offer,
            offer_version=version,
            variant=variant,
            acceptance=bad,
            created_at=_NOW,
        )


def test_snapshot_requires_at_least_one_position() -> None:
    with pytest.raises(ValueError, match="at least one position"):
        OrderCommercialSnapshot(
            snapshot_id="99999999-9999-4999-8999-999999999991",
            order_id=_ORDER_ID,
            source_offer_id=_OFFER_ID,
            source_offer_version_id=_VERSION_ID,
            source_variant_id=_VARIANT_ID,
            acceptance_id=_ACCEPTANCE_ID,
            accepted_at=_NOW,
            recorded_by="office-panel",
            variant_label="Variante A",
            payment_method="RECHNUNG",
            payment_customer_visible_text="Zahlung per Rechnung",
            created_at=_NOW,
            positions=(),
        )

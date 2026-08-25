from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from catering_system.domain.offer_charges import (
    BuffetChargeDefinition,
    DeliveryChargeDefinition,
    DishwareChargeDefinition,
    OfferChargesDefinition,
    ReturnLogisticsDefinition,
)
from catering_system.domain.order_commercial_snapshot import (
    build_order_commercial_snapshot,
)
from tests.unit.test_order_commercial_snapshot import (
    _NOW,
    _ORDER_ID,
    _offer,
    _version,
)


def test_accepted_offer_carries_structured_return_into_order_snapshot() -> None:
    return_logistics = ReturnLogisticsDefinition(
        mode="SAME_DAY",
        pickup_window_text="22:00-23:00",
        same_day_fee_cents=4500,
    )
    charges = OfferChargesDefinition(
        delivery=DeliveryChargeDefinition(amount_cents=3500),
        dishware=DishwareChargeDefinition(
            base_mode="NONE", pauschale_per_person_cents=200
        ),
        buffet=BuffetChargeDefinition(base_mode="NONE", pauschale_per_person_cents=50),
        return_logistics=return_logistics,
    )
    version = replace(_version(), charges_definition=charges)
    offer = _offer(version=version)
    acceptance = offer.acceptance_evidence
    assert acceptance is not None
    snapshot = build_order_commercial_snapshot(
        order_id=_ORDER_ID,
        offer=offer,
        offer_version=version,
        variant=version.variants[0],
        acceptance=acceptance,
        created_at=_NOW + timedelta(hours=2),
    )
    assert snapshot.return_logistics == return_logistics


def test_legacy_offer_without_structured_charges_keeps_return_fact_absent() -> None:
    version = _version()
    offer = _offer(version=version)
    acceptance = offer.acceptance_evidence
    assert acceptance is not None
    snapshot = build_order_commercial_snapshot(
        order_id=_ORDER_ID,
        offer=offer,
        offer_version=version,
        variant=version.variants[0],
        acceptance=acceptance,
        created_at=_NOW + timedelta(hours=2),
    )
    assert snapshot.return_logistics is None

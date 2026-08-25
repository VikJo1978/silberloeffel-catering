from __future__ import annotations

import json

from catering_system.domain.offer_charges import (
    BuffetChargeDefinition,
    DeliveryChargeDefinition,
    DishwareChargeDefinition,
    OfferChargesDefinition,
    ReturnLogisticsDefinition,
)
from catering_system.repositories.sqlite_offer_repository import (
    _charges_definition_storage,
    _stored_charges_definition,
)


def _charges(return_logistics: ReturnLogisticsDefinition) -> OfferChargesDefinition:
    return OfferChargesDefinition(
        delivery=DeliveryChargeDefinition(amount_cents=3500),
        dishware=DishwareChargeDefinition(
            base_mode="NONE", pauschale_per_person_cents=200
        ),
        buffet=BuffetChargeDefinition(base_mode="NONE", pauschale_per_person_cents=50),
        return_logistics=return_logistics,
    )


def test_offer_charges_json_roundtrips_same_day_return() -> None:
    expected = _charges(
        ReturnLogisticsDefinition(
            mode="SAME_DAY",
            pickup_window_text="22:00-23:00",
            same_day_fee_cents=4500,
        )
    )
    stored = _charges_definition_storage(expected)
    assert stored is not None
    assert _stored_charges_definition(stored) == expected


def test_old_offer_charges_json_loads_with_next_working_day_default() -> None:
    stored = json.dumps(
        {
            "delivery": {"amount_cents": 3500},
            "dishware": {
                "base_mode": "NONE",
                "pauschale_per_person_cents": 200,
                "additional_lines": [],
            },
            "buffet": {
                "base_mode": "NONE",
                "pauschale_per_person_cents": 50,
            },
        }
    )
    loaded = _stored_charges_definition(stored)
    assert loaded is not None
    assert loaded.return_logistics == ReturnLogisticsDefinition()

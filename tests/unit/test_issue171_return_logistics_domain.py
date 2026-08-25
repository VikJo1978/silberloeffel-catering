from __future__ import annotations

import pytest

from catering_system.domain.offer_charges import (
    BuffetChargeDefinition,
    DeliveryChargeDefinition,
    DishwareChargeDefinition,
    OfferChargesDefinition,
    ReturnLogisticsDefinition,
    validate_return_mode,
)


def test_return_mode_validator_accepts_frozen_modes() -> None:
    assert validate_return_mode("NEXT_WORKING_DAY") == "NEXT_WORKING_DAY"
    assert validate_return_mode("SAME_DAY") == "SAME_DAY"


def test_return_mode_validator_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="invalid return mode"):
        validate_return_mode("TOMORROW")


def test_return_logistics_defaults_to_next_working_day() -> None:
    definition = ReturnLogisticsDefinition()
    assert definition.mode == "NEXT_WORKING_DAY"
    assert definition.pickup_window_text is None
    assert definition.same_day_fee_cents == 0


def test_same_day_requires_pickup_window() -> None:
    with pytest.raises(ValueError, match="requires pickup_window_text"):
        ReturnLogisticsDefinition(mode="SAME_DAY", same_day_fee_cents=4500)


def test_same_day_accepts_trimmed_pickup_window_and_fee() -> None:
    definition = ReturnLogisticsDefinition(
        mode="SAME_DAY",
        pickup_window_text="22:00-23:00",
        same_day_fee_cents=4500,
    )
    assert definition.pickup_window_text == "22:00-23:00"
    assert definition.same_day_fee_cents == 4500


def test_next_working_day_rejects_pickup_window() -> None:
    with pytest.raises(ValueError, match="must not specify pickup_window_text"):
        ReturnLogisticsDefinition(
            mode="NEXT_WORKING_DAY",
            pickup_window_text="10:00-12:00",
        )


def test_return_pickup_window_must_be_trimmed() -> None:
    with pytest.raises(ValueError, match="must be trimmed"):
        ReturnLogisticsDefinition(
            mode="SAME_DAY",
            pickup_window_text=" 22:00-23:00 ",
            same_day_fee_cents=4500,
        )


def test_return_fee_rejects_bool_and_negative_amount() -> None:
    with pytest.raises(ValueError, match="integer euro cents"):
        ReturnLogisticsDefinition(same_day_fee_cents=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be non-negative"):
        ReturnLogisticsDefinition(same_day_fee_cents=-1)


def test_existing_offer_charges_constructor_remains_backward_compatible() -> None:
    charges = OfferChargesDefinition(
        delivery=DeliveryChargeDefinition(amount_cents=3500),
        dishware=DishwareChargeDefinition(
            base_mode="NONE",
            pauschale_per_person_cents=200,
        ),
        buffet=BuffetChargeDefinition(
            base_mode="NONE",
            pauschale_per_person_cents=50,
        ),
    )
    assert charges.return_logistics == ReturnLogisticsDefinition()

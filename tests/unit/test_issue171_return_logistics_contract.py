from __future__ import annotations

from typing import cast

import pytest

from catering_system.services.offer_snapshot_validation import validate_offer_snapshot
from tests.unit.test_offer_charges_validation import (
    _charge_position,
    _charges_definition,
    _default_positions,
    _dishware_line_def,
    _snapshot,
)

_RETURN_FEE = 4500


def _return_fee_position() -> dict[str, object]:
    return _charge_position(
        position_id="88888888-8888-4888-8888-888888888895",
        kind="fee",
        name="Rückholung am Veranstaltungstag",
        quantity_mode="total",
        quantity="1",
        unit_net_cents=_RETURN_FEE,
        net_total_cents=_RETURN_FEE,
    )


def _with_return(
    charges: dict[str, object],
    *,
    mode: str,
    pickup_window_text: str | None,
    same_day_fee_cents: int = _RETURN_FEE,
) -> dict[str, object]:
    charges["return_logistics"] = {
        "mode": mode,
        "pickup_window_text": pickup_window_text,
        "same_day_fee_cents": same_day_fee_cents,
    }
    return charges


def test_pre_171_structured_charges_default_to_next_working_day() -> None:
    snapshot = validate_offer_snapshot(_snapshot())
    assert snapshot.charges_definition is not None
    assert snapshot.charges_definition.return_logistics.mode == "NEXT_WORKING_DAY"
    assert snapshot.charges_definition.return_logistics.pickup_window_text is None


def test_same_day_requires_pickup_window_on_wire() -> None:
    charges = _with_return(
        _charges_definition(dishware_lines=[_dishware_line_def()]),
        mode="SAME_DAY",
        pickup_window_text=None,
    )
    with pytest.raises(ValueError, match="requires pickup_window_text"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_same_day_requires_exactly_one_customer_visible_fee_position() -> None:
    charges = _with_return(
        _charges_definition(dishware_lines=[_dishware_line_def()]),
        mode="SAME_DAY",
        pickup_window_text="22:00-23:00",
    )
    with pytest.raises(ValueError, match="exactly one return pickup fee"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_same_day_matching_fee_position_is_accepted() -> None:
    charges = _with_return(
        _charges_definition(dishware_lines=[_dishware_line_def()]),
        mode="SAME_DAY",
        pickup_window_text="22:00-23:00",
    )
    positions = _default_positions() + [_return_fee_position()]
    snapshot = validate_offer_snapshot(
        _snapshot(positions=positions, charges_definition=charges)
    )
    assert snapshot.charges_definition is not None
    assert snapshot.charges_definition.return_logistics.mode == "SAME_DAY"
    assert (
        snapshot.charges_definition.return_logistics.pickup_window_text == "22:00-23:00"
    )


def test_next_working_day_rejects_same_day_fee_position() -> None:
    charges = _with_return(
        _charges_definition(dishware_lines=[_dishware_line_def()]),
        mode="NEXT_WORKING_DAY",
        pickup_window_text=None,
    )
    with pytest.raises(ValueError, match="only valid for SAME_DAY"):
        validate_offer_snapshot(
            _snapshot(
                positions=_default_positions() + [_return_fee_position()],
                charges_definition=charges,
            )
        )


def test_return_logistics_rejects_unknown_key() -> None:
    charges = _with_return(
        _charges_definition(dishware_lines=[_dishware_line_def()]),
        mode="NEXT_WORKING_DAY",
        pickup_window_text=None,
    )
    cast(dict[str, object], charges["return_logistics"])["driver_id"] = "nope"
    with pytest.raises(
        ValueError, match="unknown charges_definition.return_logistics field"
    ):
        validate_offer_snapshot(_snapshot(charges_definition=charges))

"""Unit tests — CONFIGURABLE_OFFER_CHARGES_V1 envelope validation.

Covers: schema parsing (required/optional shape, unknown-key rejection,
bool-as-int rejection, quantity/description rules) and the new
charges-vs-positions consistency cross-check. Basic per-position/per-variant
net/VAT/gross arithmetic is exercised generically by
``test_offer_snapshot_validation.py`` already and is not re-tested here.
"""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.services.offer_snapshot_validation import validate_offer_snapshot

_INQUIRY_ID = "22222222-2222-4222-8222-222222222222"
_SNAPSHOT_ID = "77777777-7777-4777-8777-777777777771"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_GUEST_COUNT = 80

_DELIVERY_AMOUNT_CENTS = 3500
_DISHWARE_PAUSCHALE_PER_PERSON_CENTS = 200
_BUFFET_PAUSCHALE_PER_PERSON_CENTS = 50
_DISHWARE_LINE_QUANTITY = 20
_DISHWARE_LINE_UNIT_NET_CENTS = 80


def _catalog_position() -> dict[str, object]:
    return {
        "position_id": "88888888-8888-4888-8888-888888888881",
        "kind": "catalog",
        "catalog_item_id": "catalog-1",
        "name": "Fingerfood Paket",
        "description": None,
        "composition": None,
        "quantity_mode": "total",
        "quantity": "80",
        "unit_label": "Stück",
        "unit_net_cents": 290,
        "net_total_cents": 23200,
        "vat_rate_percent": 7,
        "vat_amount_cents": 1624,
        "gross_total_cents": 24824,
        "notes": None,
        "related_position_id": None,
    }


def _charge_position(
    *,
    position_id: str,
    kind: str,
    name: str,
    quantity_mode: str,
    quantity: str,
    unit_net_cents: int,
    net_total_cents: int,
    vat_rate_percent: int = 19,
) -> dict[str, object]:
    vat_amount_cents = round(net_total_cents * vat_rate_percent / 100)
    return {
        "position_id": position_id,
        "kind": kind,
        "catalog_item_id": None,
        "name": name,
        "description": None,
        "composition": None,
        "quantity_mode": quantity_mode,
        "quantity": quantity,
        "unit_label": "Pauschale",
        "unit_net_cents": unit_net_cents,
        "net_total_cents": net_total_cents,
        "vat_rate_percent": vat_rate_percent,
        "vat_amount_cents": vat_amount_cents,
        "gross_total_cents": net_total_cents + vat_amount_cents,
        "notes": None,
        "related_position_id": None,
    }


def _delivery_position(
    position_id: str = "88888888-8888-4888-8888-888888888891",
    amount_cents: int = _DELIVERY_AMOUNT_CENTS,
) -> dict[str, object]:
    return _charge_position(
        position_id=position_id,
        kind="delivery",
        name="Anlieferung",
        quantity_mode="total",
        quantity="1",
        unit_net_cents=amount_cents,
        net_total_cents=amount_cents,
    )


def _dishware_pauschale_position(
    position_id: str = "88888888-8888-4888-8888-888888888892",
    per_person_cents: int = _DISHWARE_PAUSCHALE_PER_PERSON_CENTS,
    guest_count: int = _GUEST_COUNT,
) -> dict[str, object]:
    return _charge_position(
        position_id=position_id,
        kind="dishware",
        name="Geschirrpauschale",
        quantity_mode="per_person",
        quantity="1",
        unit_net_cents=per_person_cents,
        net_total_cents=per_person_cents * guest_count,
    )


def _dishware_line_position(
    position_id: str = "88888888-8888-4888-8888-888888888893",
    description: str = "Weinglas",
    quantity: int = _DISHWARE_LINE_QUANTITY,
    unit_net_cents: int = _DISHWARE_LINE_UNIT_NET_CENTS,
) -> dict[str, object]:
    return _charge_position(
        position_id=position_id,
        kind="dishware",
        name=description,
        quantity_mode="total",
        quantity=str(quantity),
        unit_net_cents=unit_net_cents,
        net_total_cents=quantity * unit_net_cents,
    )


def _buffet_position(
    position_id: str = "88888888-8888-4888-8888-888888888894",
    per_person_cents: int = _BUFFET_PAUSCHALE_PER_PERSON_CENTS,
    guest_count: int = _GUEST_COUNT,
) -> dict[str, object]:
    return _charge_position(
        position_id=position_id,
        kind="buffet_fee",
        name="Büffetpauschale",
        quantity_mode="per_person",
        quantity="1",
        unit_net_cents=per_person_cents,
        net_total_cents=per_person_cents * guest_count,
    )


def _dishware_line_def(
    description: str = "Weinglas",
    quantity: int = _DISHWARE_LINE_QUANTITY,
    unit_net_cents: int = _DISHWARE_LINE_UNIT_NET_CENTS,
) -> dict[str, object]:
    return {
        "description": description,
        "quantity": quantity,
        "unit_net_cents": unit_net_cents,
    }


def _charges_definition(
    *,
    delivery_amount_cents: int = _DELIVERY_AMOUNT_CENTS,
    dishware_base_mode: str = "PAUSCHALE",
    dishware_per_person_cents: int = _DISHWARE_PAUSCHALE_PER_PERSON_CENTS,
    dishware_lines: list[dict[str, object]] | None = None,
    buffet_base_mode: str = "PAUSCHALE",
    buffet_per_person_cents: int = _BUFFET_PAUSCHALE_PER_PERSON_CENTS,
) -> dict[str, object]:
    return {
        "delivery": {"amount_cents": delivery_amount_cents},
        "dishware": {
            "base_mode": dishware_base_mode,
            "pauschale_per_person_cents": dishware_per_person_cents,
            "additional_lines": dishware_lines if dishware_lines is not None else [],
        },
        "buffet": {
            "base_mode": buffet_base_mode,
            "pauschale_per_person_cents": buffet_per_person_cents,
        },
    }


def _variant(positions: list[dict[str, object]]) -> dict[str, object]:
    net_cents = sum(cast(int, item["net_total_cents"]) for item in positions)
    vat_7_base_cents = sum(
        cast(int, item["net_total_cents"])
        for item in positions
        if item["vat_rate_percent"] == 7
    )
    vat_7_amount_cents = sum(
        cast(int, item["vat_amount_cents"])
        for item in positions
        if item["vat_rate_percent"] == 7
    )
    vat_19_base_cents = sum(
        cast(int, item["net_total_cents"])
        for item in positions
        if item["vat_rate_percent"] == 19
    )
    vat_19_amount_cents = sum(
        cast(int, item["vat_amount_cents"])
        for item in positions
        if item["vat_rate_percent"] == 19
    )
    gross_cents = sum(cast(int, item["gross_total_cents"]) for item in positions)
    return {
        "variant_id": _VARIANT_ID,
        "label": "Variante A",
        "description": "Customer-visible alternative",
        "positions": positions,
        "totals": {
            "net_cents": net_cents,
            "vat_7_base_cents": vat_7_base_cents,
            "vat_7_amount_cents": vat_7_amount_cents,
            "vat_19_base_cents": vat_19_base_cents,
            "vat_19_amount_cents": vat_19_amount_cents,
            "gross_cents": gross_cents,
        },
    }


def _default_positions() -> list[dict[str, object]]:
    return [
        _catalog_position(),
        _delivery_position(),
        _dishware_pauschale_position(),
        _dishware_line_position(),
        _buffet_position(),
    ]


def _snapshot(
    *,
    guest_count: int | None = _GUEST_COUNT,
    positions: list[dict[str, object]] | None = None,
    charges_definition: dict[str, object] | None | object = "__default__",
) -> dict[str, object]:
    variant = _variant(positions if positions is not None else _default_positions())
    body: dict[str, object] = {
        "schema_version": "offer_snapshot_v1",
        "source": "fingerfood-configurator-backend",
        "source_draft_id": "draft-1",
        "inquiry_id": _INQUIRY_ID,
        "snapshot_id": _SNAPSHOT_ID,
        "snapshot_created_at": "2026-07-15T08:30:00+00:00",
        "valid_until": "2026-07-29",
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
            "guest_count": guest_count,
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
            "calculator_revision": "future-revision",
            "catalog_revision": "future-revision",
            "tax_revision": "future-revision",
        },
        "variants": [variant],
    }
    if charges_definition == "__default__":
        body["charges_definition"] = _charges_definition(
            dishware_lines=[_dishware_line_def()]
        )
    elif charges_definition is not None:
        body["charges_definition"] = charges_definition
    payload = deepcopy(body)
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


# --- happy paths -------------------------------------------------------------------


def test_full_schema_with_all_charge_kinds_is_accepted() -> None:
    snapshot = validate_offer_snapshot(_snapshot())
    assert snapshot.charges_definition is not None
    assert snapshot.charges_definition.delivery.amount_cents == _DELIVERY_AMOUNT_CENTS
    assert snapshot.charges_definition.dishware.base_mode == "PAUSCHALE"
    assert len(snapshot.charges_definition.dishware.additional_lines) == 1
    assert snapshot.charges_definition.buffet.base_mode == "PAUSCHALE"


def test_legacy_snapshot_without_charges_definition_is_unaffected() -> None:
    positions = [_catalog_position()]
    snapshot = validate_offer_snapshot(
        _snapshot(positions=positions, charges_definition=None)
    )
    assert snapshot.charges_definition is None


def test_dishware_none_mode_no_lines_no_materialized_position() -> None:
    positions = [_catalog_position(), _delivery_position(), _buffet_position()]
    charges = _charges_definition(dishware_base_mode="NONE", dishware_lines=[])
    snapshot = validate_offer_snapshot(
        _snapshot(positions=positions, charges_definition=charges)
    )
    assert snapshot.charges_definition is not None
    assert snapshot.charges_definition.dishware.base_mode == "NONE"


def test_dishware_none_mode_with_lines_only() -> None:
    positions = [
        _catalog_position(),
        _delivery_position(),
        _dishware_line_position(),
        _buffet_position(),
    ]
    charges = _charges_definition(
        dishware_base_mode="NONE", dishware_lines=[_dishware_line_def()]
    )
    snapshot = validate_offer_snapshot(
        _snapshot(positions=positions, charges_definition=charges)
    )
    assert snapshot.charges_definition is not None
    assert snapshot.charges_definition.dishware.base_mode == "NONE"


def test_dishware_pauschale_mode_no_lines() -> None:
    positions = [
        _catalog_position(),
        _delivery_position(),
        _dishware_pauschale_position(),
        _buffet_position(),
    ]
    charges = _charges_definition(dishware_base_mode="PAUSCHALE", dishware_lines=[])
    snapshot = validate_offer_snapshot(
        _snapshot(positions=positions, charges_definition=charges)
    )
    assert snapshot.charges_definition is not None


def test_buffet_none_mode_no_materialized_position() -> None:
    positions = [_catalog_position(), _delivery_position()]
    charges = _charges_definition(
        dishware_base_mode="NONE", dishware_lines=[], buffet_base_mode="NONE"
    )
    snapshot = validate_offer_snapshot(
        _snapshot(positions=positions, charges_definition=charges)
    )
    assert snapshot.charges_definition is not None


# --- envelope / schema shape ---------------------------------------------------------


def test_charges_definition_rejects_unknown_top_level_key() -> None:
    charges = _charges_definition(dishware_lines=[])
    charges["extra"] = 1
    with pytest.raises(ValueError, match="unknown charges_definition field"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_charges_definition_requires_delivery() -> None:
    charges = _charges_definition(dishware_lines=[])
    del charges["delivery"]
    with pytest.raises(ValueError, match="delivery must be an object"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_charges_definition_requires_dishware() -> None:
    charges = _charges_definition(dishware_lines=[])
    del charges["dishware"]
    with pytest.raises(ValueError, match="dishware must be an object"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_charges_definition_requires_buffet() -> None:
    charges = _charges_definition(dishware_lines=[])
    del charges["buffet"]
    with pytest.raises(ValueError, match="buffet must be an object"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_delivery_rejects_unknown_key() -> None:
    charges = _charges_definition(dishware_lines=[])
    cast(dict[str, object], charges["delivery"])["extra"] = 1
    with pytest.raises(ValueError, match="unknown charges_definition.delivery field"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_delivery_rejects_bool_amount() -> None:
    charges = _charges_definition(dishware_lines=[])
    cast(dict[str, object], charges["delivery"])["amount_cents"] = True
    with pytest.raises(ValueError, match="integer euro cents"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_dishware_rejects_unknown_key() -> None:
    charges = _charges_definition(dishware_lines=[])
    cast(dict[str, object], charges["dishware"])["extra"] = 1
    with pytest.raises(ValueError, match="unknown charges_definition.dishware field"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_dishware_rejects_invalid_base_mode() -> None:
    charges = _charges_definition(dishware_lines=[])
    cast(dict[str, object], charges["dishware"])["base_mode"] = "MAYBE"
    with pytest.raises(ValueError, match="invalid charge base_mode"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_dishware_line_rejects_unknown_key() -> None:
    line = _dishware_line_def()
    line["extra"] = 1
    charges = _charges_definition(dishware_lines=[line])
    with pytest.raises(
        ValueError,
        match="unknown charges_definition.dishware.additional_lines\\[0\\] field",
    ):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_dishware_line_rejects_empty_description() -> None:
    line = _dishware_line_def(description="")
    charges = _charges_definition(dishware_lines=[line])
    with pytest.raises(ValueError, match="description is required"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_dishware_line_rejects_untrimmed_description() -> None:
    line = _dishware_line_def(description=" Weinglas ")
    charges = _charges_definition(dishware_lines=[line])
    with pytest.raises(ValueError, match="must be trimmed"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_dishware_line_rejects_zero_quantity() -> None:
    line = _dishware_line_def(quantity=0)
    charges = _charges_definition(dishware_lines=[line])
    with pytest.raises(ValueError, match="positive integer"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_dishware_line_rejects_fractional_quantity() -> None:
    """Floats are rejected even earlier, by canonical-hash serialization
    (see domain/offer_snapshot.py `_serialize_json_value`) — a stronger,
    pre-existing, envelope-wide protection that fires before this field's
    own whole-number check ever runs (that check is exercised directly
    against the domain object in test_offer_charges_domain.py instead)."""
    line = _dishware_line_def()
    line["quantity"] = 1.5
    charges = _charges_definition(dishware_lines=[line])
    with pytest.raises(ValueError, match="floating-point values are forbidden"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_dishware_line_rejects_bool_quantity() -> None:
    line = _dishware_line_def()
    line["quantity"] = True
    charges = _charges_definition(dishware_lines=[line])
    with pytest.raises(ValueError, match="whole number"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_buffet_rejects_unknown_key() -> None:
    charges = _charges_definition(dishware_lines=[])
    cast(dict[str, object], charges["buffet"])["extra"] = 1
    with pytest.raises(ValueError, match="unknown charges_definition.buffet field"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


def test_buffet_rejects_negative_rate() -> None:
    charges = _charges_definition(dishware_lines=[])
    cast(dict[str, object], charges["buffet"])["pauschale_per_person_cents"] = -1
    with pytest.raises(ValueError, match="non-negative"):
        validate_offer_snapshot(_snapshot(charges_definition=charges))


# --- consistency: delivery -----------------------------------------------------------


def test_consistency_rejects_missing_delivery_position() -> None:
    positions = [
        _catalog_position(),
        _dishware_pauschale_position(),
        _dishware_line_position(),
        _buffet_position(),
    ]
    with pytest.raises(ValueError, match="requires exactly one"):
        validate_offer_snapshot(_snapshot(positions=positions))


def test_consistency_rejects_delivery_amount_mismatch() -> None:
    positions = [
        _catalog_position(),
        _delivery_position(amount_cents=4000),
        _dishware_pauschale_position(),
        _dishware_line_position(),
        _buffet_position(),
    ]
    with pytest.raises(ValueError, match="delivery position does not match"):
        validate_offer_snapshot(_snapshot(positions=positions))


def test_consistency_rejects_duplicate_delivery_position() -> None:
    positions = [
        _catalog_position(),
        _delivery_position(),
        _delivery_position(position_id="88888888-8888-4888-8888-888888888895"),
        _dishware_pauschale_position(),
        _dishware_line_position(),
        _buffet_position(),
    ]
    with pytest.raises(ValueError, match="requires exactly one"):
        validate_offer_snapshot(_snapshot(positions=positions))


# --- consistency: dishware -----------------------------------------------------------


def test_consistency_rejects_unexplained_dishware_position_when_none() -> None:
    positions = [
        _catalog_position(),
        _delivery_position(),
        _dishware_pauschale_position(),
        _buffet_position(),
    ]
    charges = _charges_definition(dishware_base_mode="NONE", dishware_lines=[])
    with pytest.raises(
        ValueError, match="unexplained dishware position present for base_mode=NONE"
    ):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_rejects_missing_pauschale_position_when_enabled() -> None:
    positions = [_catalog_position(), _delivery_position(), _buffet_position()]
    charges = _charges_definition(dishware_base_mode="PAUSCHALE", dishware_lines=[])
    with pytest.raises(ValueError, match="dishware Pauschale position not found"):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_rejects_unmatched_additional_line() -> None:
    positions = [
        _catalog_position(),
        _delivery_position(),
        _dishware_line_position(description="Teller"),
        _buffet_position(),
    ]
    charges = _charges_definition(
        dishware_base_mode="NONE",
        dishware_lines=[_dishware_line_def(description="Weinglas")],
    )
    with pytest.raises(ValueError, match="has no matching dishware position"):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_dishware_pauschale_requires_guest_count() -> None:
    positions = [_catalog_position(), _delivery_position()]
    charges = _charges_definition(
        dishware_base_mode="PAUSCHALE", dishware_lines=[], buffet_base_mode="NONE"
    )
    with pytest.raises(
        ValueError, match="dishware base_mode=PAUSCHALE requires event.guest_count"
    ):
        validate_offer_snapshot(
            _snapshot(guest_count=None, positions=positions, charges_definition=charges)
        )


# --- consistency: dishware — stricter deterministic matching -------------------------


def test_consistency_rejects_line_position_with_same_total_but_different_quantity() -> (
    None
):
    """A position with the same net total but a different quantity/unit
    price must not be accepted as a match — the composite key requires
    quantity and unit_net_cents to match too, not just the derived total."""
    decoy = _charge_position(
        position_id="88888888-8888-4888-8888-888888888895",
        kind="dishware",
        name="Weinglas",
        quantity_mode="total",
        quantity="40",
        unit_net_cents=40,
        net_total_cents=1600,  # same total as the real line (20 * 80), different shape
    )
    positions = [_catalog_position(), _delivery_position(), decoy, _buffet_position()]
    charges = _charges_definition(
        dishware_base_mode="NONE", dishware_lines=[_dishware_line_def()]
    )
    with pytest.raises(ValueError, match="has no matching dishware position"):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_rejects_duplicate_matching_positions_for_one_line() -> None:
    line_pos_1 = _dishware_line_position(
        position_id="88888888-8888-4888-8888-888888888893"
    )
    line_pos_2 = _dishware_line_position(
        position_id="88888888-8888-4888-8888-888888888895"
    )
    positions = [
        _catalog_position(),
        _delivery_position(),
        line_pos_1,
        line_pos_2,
        _buffet_position(),
    ]
    charges = _charges_definition(
        dishware_base_mode="NONE", dishware_lines=[_dishware_line_def()]
    )
    with pytest.raises(ValueError, match="matches multiple dishware positions"):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_does_not_treat_total_mode_position_as_pauschale() -> None:
    """The Pauschale is identified by quantity_mode="per_person", never by
    elimination — a quantity_mode="total" position whose amount happens to
    equal guest_count * pauschale_per_person_cents is not the Pauschale."""
    decoy = _charge_position(
        position_id="88888888-8888-4888-8888-888888888895",
        kind="dishware",
        name="Zufällig gleicher Betrag",
        quantity_mode="total",
        quantity="1",
        unit_net_cents=16000,
        net_total_cents=16000,  # == 80 guests * 200 cents/person, by coincidence
    )
    positions = [_catalog_position(), _delivery_position(), decoy, _buffet_position()]
    charges = _charges_definition(dishware_base_mode="PAUSCHALE", dishware_lines=[])
    with pytest.raises(
        ValueError, match="unexplained dishware position present for additional_lines"
    ):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_rejects_multiple_pauschale_candidates() -> None:
    pauschale_1 = _dishware_pauschale_position(
        position_id="88888888-8888-4888-8888-888888888892"
    )
    pauschale_2 = _dishware_pauschale_position(
        position_id="88888888-8888-4888-8888-888888888895"
    )
    positions = [
        _catalog_position(),
        _delivery_position(),
        pauschale_1,
        pauschale_2,
        _buffet_position(),
    ]
    charges = _charges_definition(dishware_base_mode="PAUSCHALE", dishware_lines=[])
    with pytest.raises(
        ValueError, match="multiple dishware Pauschale positions present"
    ):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_rejects_pauschale_position_with_wrong_quantity() -> None:
    bad_pauschale = _charge_position(
        position_id="88888888-8888-4888-8888-888888888892",
        kind="dishware",
        name="Geschirrpauschale",
        quantity_mode="per_person",
        quantity="2",
        unit_net_cents=200,
        net_total_cents=200 * 2 * _GUEST_COUNT,
    )
    positions = [
        _catalog_position(),
        _delivery_position(),
        bad_pauschale,
        _buffet_position(),
    ]
    charges = _charges_definition(dishware_base_mode="PAUSCHALE", dishware_lines=[])
    with pytest.raises(
        ValueError, match="dishware Pauschale position quantity must be 1"
    ):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_rejects_pauschale_position_unit_net_cents_mismatch() -> None:
    bad_pauschale = _charge_position(
        position_id="88888888-8888-4888-8888-888888888892",
        kind="dishware",
        name="Geschirrpauschale",
        quantity_mode="per_person",
        quantity="1",
        unit_net_cents=250,
        net_total_cents=250 * _GUEST_COUNT,
    )
    positions = [
        _catalog_position(),
        _delivery_position(),
        bad_pauschale,
        _buffet_position(),
    ]
    charges = _charges_definition(dishware_base_mode="PAUSCHALE", dishware_lines=[])
    with pytest.raises(
        ValueError, match="dishware Pauschale position unit_net_cents mismatch"
    ):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


# --- consistency: buffet --------------------------------------------------------------


def test_consistency_rejects_unexplained_buffet_position_when_none() -> None:
    positions = [
        _catalog_position(),
        _delivery_position(),
        _dishware_pauschale_position(),
        _buffet_position(),
    ]
    charges = _charges_definition(buffet_base_mode="NONE", dishware_lines=[])
    with pytest.raises(
        ValueError, match="unexplained buffet_fee position present for base_mode=NONE"
    ):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_rejects_missing_buffet_position_when_enabled() -> None:
    positions = [
        _catalog_position(),
        _delivery_position(),
        _dishware_pauschale_position(),
    ]
    charges = _charges_definition(buffet_base_mode="PAUSCHALE", dishware_lines=[])
    with pytest.raises(ValueError, match="buffet_fee position not found"):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_consistency_rejects_buffet_amount_mismatch() -> None:
    positions = [
        _catalog_position(),
        _delivery_position(),
        _dishware_pauschale_position(),
        _buffet_position(per_person_cents=99),
    ]
    charges = _charges_definition(buffet_base_mode="PAUSCHALE", dishware_lines=[])
    with pytest.raises(ValueError, match="buffet_fee position amount mismatch"):
        validate_offer_snapshot(
            _snapshot(positions=positions, charges_definition=charges)
        )


def test_buffet_default_none_never_auto_materializes_a_fee_position() -> None:
    """Operator confirmation: Büffetpauschale must be explicitly selected by
    the office user. A charges_definition with buffet.base_mode="NONE"
    (the default for new Offers) requires — and permits — zero buffet_fee
    positions; nothing is added automatically."""
    positions = [
        _catalog_position(),
        _delivery_position(),
        _dishware_pauschale_position(),
    ]
    charges = _charges_definition(buffet_base_mode="NONE", dishware_lines=[])
    snapshot = validate_offer_snapshot(
        _snapshot(positions=positions, charges_definition=charges)
    )
    assert snapshot.charges_definition is not None
    assert snapshot.charges_definition.buffet.base_mode == "NONE"
    kinds = {
        position.kind for variant in snapshot.variants for position in variant.positions
    }
    assert "buffet_fee" not in kinds


def test_legacy_snapshot_without_charges_definition_never_synthesizes_buffet_fee() -> (
    None
):
    """Absence of charges_definition is the legacy path — Core trusts
    whatever positions arrived and never invents a Büffetpauschale on its
    own, regardless of whether the operator's snapshot includes one."""
    snapshot = validate_offer_snapshot(
        _snapshot(positions=[_catalog_position()], charges_definition=None)
    )
    kinds = {
        position.kind for variant in snapshot.variants for position in variant.positions
    }
    assert "buffet_fee" not in kinds
    assert snapshot.charges_definition is None

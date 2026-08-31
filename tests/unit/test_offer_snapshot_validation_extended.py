"""Extended OfferSnapshot validation error-path coverage."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from catering_system.domain.offer_snapshot import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_V2,
    compute_snapshot_hash,
)
from catering_system.domain.offer_snapshot import OfferSnapshotV1
from catering_system.services.offer_snapshot_validation import (
    validate_offer_snapshot,
    validate_offer_snapshot_bytes,
)

_DISH_ID = "11111111-1111-4111-8111-111111111111"

from tests.unit.test_offer_snapshot_validation import (
    _BASE_POSITION_ID,
    _SURCHARGE_ID,
    _position,
    _valid_snapshot,
    _variant,
)


def test_non_object_json_envelope_is_rejected() -> None:
    with pytest.raises(ValueError, match="snapshot envelope must be a JSON object"):
        validate_offer_snapshot_bytes(b"[]")


def test_invalid_schema_version_is_rejected() -> None:
    payload = _valid_snapshot()
    payload["schema_version"] = "offer_snapshot_v9"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="invalid schema_version"):
        validate_offer_snapshot(payload)


def test_invalid_source_is_rejected() -> None:
    payload = _valid_snapshot()
    payload["source"] = "other-backend"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="invalid source"):
        validate_offer_snapshot(payload)


def test_invalid_currency_is_rejected() -> None:
    payload = _valid_snapshot()
    payload["currency"] = "USD"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="invalid currency"):
        validate_offer_snapshot(payload)


def test_v1_snapshot_returns_offer_snapshot_v1_type() -> None:
    payload = _valid_snapshot()
    snapshot = validate_offer_snapshot(payload)
    assert isinstance(snapshot, OfferSnapshotV1)
    assert snapshot.schema_version == SCHEMA_VERSION


def test_recipient_requires_company_or_contact_name() -> None:
    payload = _valid_snapshot()
    recipient = cast(dict[str, object], payload["recipient"])
    recipient["company_name"] = "   "
    recipient["contact_name"] = "   "
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(
        ValueError, match="recipient requires company_name or contact_name"
    ):
        validate_offer_snapshot(payload)


def test_recipient_unknown_field_is_rejected() -> None:
    payload = _valid_snapshot()
    recipient = cast(dict[str, object], payload["recipient"])
    recipient["extra"] = "x"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="unknown recipient field"):
        validate_offer_snapshot(payload)


def test_guest_count_must_be_positive_integer_or_null() -> None:
    payload = _valid_snapshot()
    event = cast(dict[str, object], payload["event"])
    event["guest_count"] = 0
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="guest_count must be a positive integer"):
        validate_offer_snapshot(payload)


def test_guest_count_rejects_non_integer() -> None:
    payload = _valid_snapshot()
    event = cast(dict[str, object], payload["event"])
    event["guest_count"] = "80"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="guest_count must be a positive integer"):
        validate_offer_snapshot(payload)


def test_duplicate_variant_id_is_rejected() -> None:
    variant_a = _variant()
    variant_b = deepcopy(variant_a)
    payload = _valid_snapshot(variants=[variant_a, variant_b])
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="variant_id must be unique"):
        validate_offer_snapshot(payload)


def test_duplicate_position_id_is_rejected() -> None:
    pos = _position()
    payload = _valid_snapshot(variants=[_variant(positions=[pos, deepcopy(pos)])])
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="position_id must be unique"):
        validate_offer_snapshot(payload)


def test_variant_gross_arithmetic_mismatch_is_rejected() -> None:
    catalog = _position(
        quantity="100",
        unit_net_cents=100,
        net_total_cents=10000,
        vat_rate_percent=7,
        vat_amount_cents=700,
        gross_total_cents=10700,
    )
    fee = _position(
        position_id=_BASE_POSITION_ID,
        kind="fee",
        quantity="1",
        unit_net_cents=5000,
        net_total_cents=5000,
        vat_rate_percent=19,
        vat_amount_cents=950,
        gross_total_cents=5950,
    )
    payload = _valid_snapshot(variants=[_variant(positions=[catalog, fee])])
    variants = cast(list[dict[str, object]], payload["variants"])
    totals = cast(dict[str, object], variants[0]["totals"])
    totals["gross_cents"] = cast(int, totals["gross_cents"]) + 1
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="offer snapshot gross total mismatch"):
        validate_offer_snapshot(payload)


def test_surcharge_vat_rate_must_match_base() -> None:
    base = _position(position_id=_BASE_POSITION_ID, kind="catalog", vat_rate_percent=7)
    surcharge = _position(
        position_id=_SURCHARGE_ID,
        kind="surcharge",
        related_position_id=_BASE_POSITION_ID,
        vat_rate_percent=19,
        vat_amount_cents=4408,
        gross_total_cents=27568,
    )
    payload = _valid_snapshot(variants=[_variant(positions=[base, surcharge])])
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="same VAT rate"):
        validate_offer_snapshot(payload)


def test_invalid_position_kind_is_rejected() -> None:
    payload = _valid_snapshot(
        variants=[_variant(positions=[_position(kind="unknown")])]
    )
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="invalid position kind"):
        validate_offer_snapshot(payload)


def test_invalid_quantity_mode_is_rejected() -> None:
    pos = _position()
    pos["quantity_mode"] = "per_table"
    payload = _valid_snapshot(variants=[_variant(positions=[pos])])
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="invalid quantity_mode"):
        validate_offer_snapshot(payload)


def test_zero_quantity_is_rejected() -> None:
    payload = _valid_snapshot(variants=[_variant(positions=[_position(quantity="0")])])
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="positive decimal string"):
        validate_offer_snapshot(payload)


def test_negative_cents_are_rejected() -> None:
    payload = _valid_snapshot(
        variants=[_variant(positions=[_position(unit_net_cents=-1)])]
    )
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="non-negative"):
        validate_offer_snapshot(payload)


def test_invalid_snapshot_hash_format_is_rejected() -> None:
    payload = _valid_snapshot()
    payload["snapshot_hash"] = "not-a-hash"
    with pytest.raises(
        ValueError, match="snapshot_hash must be a lowercase sha256 digest"
    ):
        validate_offer_snapshot(payload)


def test_non_uuid4_inquiry_id_is_rejected() -> None:
    payload = _valid_snapshot()
    payload["inquiry_id"] = "11111111-1111-1111-1111-111111111111"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="inquiry_id must be a UUID4 string"):
        validate_offer_snapshot(payload)


def test_non_utc_snapshot_created_at_is_rejected() -> None:
    payload = _valid_snapshot()
    payload["snapshot_created_at"] = "2026-07-15T08:30:00+02:00"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="timezone-aware UTC timestamp"):
        validate_offer_snapshot(payload)


def test_v2_catalog_position_requires_allergens() -> None:
    pos = _position()
    pos["catalog_item_id"] = _DISH_ID
    pos.pop("allergens", None)
    body = _valid_snapshot(variants=[_variant(positions=[pos])])
    body["schema_version"] = SCHEMA_VERSION_V2
    body["snapshot_hash"] = compute_snapshot_hash(body)
    with pytest.raises(ValueError, match="catalog position requires allergens"):
        validate_offer_snapshot(body)


def test_v2_optional_bool_fields_must_be_boolean() -> None:
    pos = _position()
    pos["catalog_item_id"] = _DISH_ID
    pos["allergens"] = []
    pos["vegan"] = "yes"
    body = _valid_snapshot(variants=[_variant(positions=[pos])])
    body["schema_version"] = SCHEMA_VERSION_V2
    body["snapshot_hash"] = compute_snapshot_hash(body)
    with pytest.raises(ValueError, match="vegan must be a boolean"):
        validate_offer_snapshot(body)


def test_variant_must_be_object() -> None:
    payload = _valid_snapshot()
    payload["variants"] = ["not-an-object"]
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="variant must be an object"):
        validate_offer_snapshot(payload)


def test_position_must_be_object() -> None:
    variant = _variant()
    variant["positions"] = ["not-an-object"]
    payload = _valid_snapshot(variants=[variant])
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="position must be an object"):
        validate_offer_snapshot(payload)


def test_optional_source_draft_id_empty_becomes_none() -> None:
    payload = _valid_snapshot()
    payload["source_draft_id"] = "   "
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    snapshot = validate_offer_snapshot(payload)
    assert snapshot.source_draft_id is None


def test_invalid_utf8_bytes_are_rejected() -> None:
    with pytest.raises(ValueError, match="invalid snapshot JSON"):
        validate_offer_snapshot_bytes(b"\xff\xfe")


def test_recipient_name_length_limit_is_enforced() -> None:
    payload = _valid_snapshot()
    recipient = cast(dict[str, object], payload["recipient"])
    recipient["company_name"] = "x" * 501
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="recipient name exceeds length limit"):
        validate_offer_snapshot(payload)


def test_event_unknown_field_is_rejected() -> None:
    payload = _valid_snapshot()
    event = cast(dict[str, object], payload["event"])
    event["unexpected"] = True
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="unknown event field"):
        validate_offer_snapshot(payload)


def test_calculator_unknown_field_is_rejected() -> None:
    payload = _valid_snapshot()
    calculator = cast(dict[str, object], payload["calculator"])
    calculator["unexpected"] = True
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="unknown calculator field"):
        validate_offer_snapshot(payload)


def test_v2_fee_position_may_carry_optional_allergens() -> None:
    fee = _position(kind="fee")
    fee["allergens"] = ["A"]
    fee["vegan"] = True
    body = _valid_snapshot(variants=[_variant(positions=[fee])])
    body["schema_version"] = SCHEMA_VERSION_V2
    body["snapshot_hash"] = compute_snapshot_hash(body)
    snapshot = validate_offer_snapshot(body)
    assert snapshot.variants[0].positions[0].allergens == ("A",)
    assert snapshot.variants[0].positions[0].vegan is True


def test_allergens_must_be_array() -> None:
    pos = _position()
    pos["catalog_item_id"] = _DISH_ID
    pos["allergens"] = "A"
    body = _valid_snapshot(variants=[_variant(positions=[pos])])
    body["schema_version"] = SCHEMA_VERSION_V2
    body["snapshot_hash"] = compute_snapshot_hash(body)
    with pytest.raises(ValueError, match="allergens must be an array"):
        validate_offer_snapshot(body)


def test_recipient_must_be_object() -> None:
    payload = _valid_snapshot()
    payload["recipient"] = "not-an-object"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="recipient must be an object"):
        validate_offer_snapshot(payload)


def test_variants_must_be_array() -> None:
    payload = _valid_snapshot()
    payload["variants"] = "not-an-array"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="variants must be an array"):
        validate_offer_snapshot(payload)


def test_empty_required_short_text_is_rejected() -> None:
    payload = _valid_snapshot()
    event = cast(dict[str, object], payload["event"])
    event["location_text"] = "   "
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="location_text is required"):
        validate_offer_snapshot(payload)


def test_postal_address_length_limit_is_enforced() -> None:
    payload = _valid_snapshot()
    recipient = cast(dict[str, object], payload["recipient"])
    recipient["postal_address"] = "x" * 501
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="postal_address exceeds length limit"):
        validate_offer_snapshot(payload)


def test_invalid_event_date_is_rejected() -> None:
    payload = _valid_snapshot()
    event = cast(dict[str, object], payload["event"])
    event["event_date"] = "not-a-date"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="event_date must be an ISO date"):
        validate_offer_snapshot(payload)


def test_bool_cents_value_is_rejected() -> None:
    payload = _valid_snapshot()
    variants = cast(list[dict[str, object]], payload["variants"])
    positions = cast(list[dict[str, object]], variants[0]["positions"])
    positions[0]["unit_net_cents"] = True
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="integer euro cents"):
        validate_offer_snapshot(payload)


def test_optional_long_text_length_limit_is_enforced() -> None:
    payload = _valid_snapshot()
    variants = cast(list[dict[str, object]], payload["variants"])
    positions = cast(list[dict[str, object]], variants[0]["positions"])
    positions[0]["notes"] = "x" * 20001
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="notes exceeds length limit"):
        validate_offer_snapshot(payload)


def test_exact_event_times_are_accepted_without_delivery_window() -> None:
    payload = _valid_snapshot()
    event = cast(dict[str, object], payload["event"])
    event["time_window_text"] = "18:00"
    event["delivery_time_local"] = "16:30"
    event["event_start_local"] = "18:00"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)

    snapshot = validate_offer_snapshot(payload)

    assert snapshot.event.delivery_time_local is not None
    assert snapshot.event.delivery_time_local.strftime("%H:%M") == "16:30"
    assert snapshot.event.event_start_local is not None
    assert snapshot.event.event_start_local.strftime("%H:%M") == "18:00"
    assert snapshot.event.delivery_date_local is None
    assert snapshot.event.delivery_window_start_local is None
    assert snapshot.event.delivery_window_end_local is None


def test_exact_delivery_time_rejects_legacy_delivery_window_combination() -> None:
    payload = _valid_snapshot()
    event = cast(dict[str, object], payload["event"])
    event["delivery_date_local"] = "2026-07-25"
    event["delivery_window_start_local"] = "16:00"
    event["delivery_window_end_local"] = "17:00"
    event["delivery_time_local"] = "16:30"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)

    with pytest.raises(ValueError, match="mutually exclusive"):
        validate_offer_snapshot(payload)

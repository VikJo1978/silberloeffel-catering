from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import cast

import pytest

from catering_system.domain.offer_snapshot import (
    MAX_PAYLOAD_BYTES,
    MAX_POSITIONS_PER_VARIANT,
    MAX_VARIANTS,
    compute_snapshot_hash,
    canonical_snapshot_json,
)
from catering_system.services.offer_snapshot_validation import (
    validate_offer_snapshot,
    validate_offer_snapshot_bytes,
)

_INQUIRY_ID = "22222222-2222-4222-8222-222222222222"
_SNAPSHOT_ID = "77777777-7777-4777-8777-777777777771"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"
_BASE_POSITION_ID = "88888888-8888-4888-8888-888888888882"
_SURCHARGE_ID = "88888888-8888-4888-8888-888888888883"


def _position(
    *,
    position_id: str = _POSITION_ID,
    kind: str = "catalog",
    quantity_mode: str = "total",
    quantity: str = "80",
    unit_net_cents: int = 290,
    net_total_cents: int = 23200,
    vat_rate_percent: int = 7,
    vat_amount_cents: int = 1624,
    gross_total_cents: int = 24824,
    related_position_id: str | None = None,
) -> dict[str, object]:
    return {
        "position_id": position_id,
        "kind": kind,
        "catalog_item_id": "catalog-1",
        "name": "Fingerfood Paket",
        "description": "Frozen description",
        "composition": "Frozen composition",
        "quantity_mode": quantity_mode,
        "quantity": quantity,
        "unit_label": "Stück",
        "unit_net_cents": unit_net_cents,
        "net_total_cents": net_total_cents,
        "vat_rate_percent": vat_rate_percent,
        "vat_amount_cents": vat_amount_cents,
        "gross_total_cents": gross_total_cents,
        "notes": "Frozen customization",
        "related_position_id": related_position_id,
    }


def _variant(*, positions: list[dict[str, object]] | None = None) -> dict[str, object]:
    items = positions if positions is not None else [_position()]
    net_cents = sum(cast(int, item["net_total_cents"]) for item in items)
    vat_7_base_cents = sum(
        cast(int, item["net_total_cents"])
        for item in items
        if item["vat_rate_percent"] == 7
    )
    vat_7_amount_cents = sum(
        cast(int, item["vat_amount_cents"])
        for item in items
        if item["vat_rate_percent"] == 7
    )
    vat_19_base_cents = sum(
        cast(int, item["net_total_cents"])
        for item in items
        if item["vat_rate_percent"] == 19
    )
    vat_19_amount_cents = sum(
        cast(int, item["vat_amount_cents"])
        for item in items
        if item["vat_rate_percent"] == 19
    )
    gross_cents = sum(cast(int, item["gross_total_cents"]) for item in items)
    return {
        "variant_id": _VARIANT_ID,
        "label": "Variante A",
        "description": "Customer-visible alternative",
        "positions": items,
        "totals": {
            "net_cents": net_cents,
            "vat_7_base_cents": vat_7_base_cents,
            "vat_7_amount_cents": vat_7_amount_cents,
            "vat_19_base_cents": vat_19_base_cents,
            "vat_19_amount_cents": vat_19_amount_cents,
            "gross_cents": gross_cents,
        },
    }


def _budget_definition(
    *,
    amount_cents: int = 3500,
    type: str = "PER_PERSON",
    tax_basis: str = "GROSS",
    cost_scope: str = "FULL_OFFER",
) -> dict[str, object]:
    return {
        "amount_cents": amount_cents,
        "type": type,
        "tax_basis": tax_basis,
        "cost_scope": cost_scope,
    }


def _snapshot_body(
    *,
    guest_count: int | None = 80,
    variants: list[dict[str, object]] | None = None,
    budget_definition: dict[str, object] | None = None,
) -> dict[str, object]:
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
        "variants": variants or [_variant()],
    }
    if budget_definition is not None:
        body["budget_definition"] = budget_definition
    return body


def _valid_snapshot(
    *,
    guest_count: int | None = 80,
    variants: list[dict[str, object]] | None = None,
    budget_definition: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = _snapshot_body(
        guest_count=guest_count, variants=variants, budget_definition=budget_definition
    )
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def test_valid_snapshot_passes_validation() -> None:
    payload = _valid_snapshot()
    snapshot = validate_offer_snapshot(payload)

    assert snapshot.inquiry_id == _INQUIRY_ID
    assert snapshot.snapshot_id == _SNAPSHOT_ID
    assert len(snapshot.variants) == 1
    assert snapshot.variants[0].positions[0].unit_net_cents == 290


def test_valid_snapshot_bytes_roundtrip() -> None:
    payload = _valid_snapshot()
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    snapshot = validate_offer_snapshot_bytes(raw)
    assert snapshot.snapshot_hash == payload["snapshot_hash"]


def test_position_net_total_mismatch_is_rejected() -> None:
    payload = _valid_snapshot()
    variants = cast(list[dict[str, object]], payload["variants"])
    positions = cast(list[dict[str, object]], variants[0]["positions"])
    positions[0]["net_total_cents"] = 23201
    payload["snapshot_hash"] = compute_snapshot_hash(payload)

    with pytest.raises(ValueError, match="offer snapshot position net total mismatch"):
        validate_offer_snapshot(payload)


def test_position_vat_mismatch_is_rejected() -> None:
    payload = _valid_snapshot()
    variants = cast(list[dict[str, object]], payload["variants"])
    positions = cast(list[dict[str, object]], variants[0]["positions"])
    positions[0]["vat_amount_cents"] = 100
    payload["snapshot_hash"] = compute_snapshot_hash(payload)

    with pytest.raises(ValueError, match="offer snapshot position VAT mismatch"):
        validate_offer_snapshot(payload)


def test_position_gross_total_mismatch_is_rejected() -> None:
    payload = _valid_snapshot()
    variants = cast(list[dict[str, object]], payload["variants"])
    positions = cast(list[dict[str, object]], variants[0]["positions"])
    positions[0]["gross_total_cents"] = 24825
    payload["snapshot_hash"] = compute_snapshot_hash(payload)

    with pytest.raises(
        ValueError, match="offer snapshot position gross total mismatch"
    ):
        validate_offer_snapshot(payload)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("net_cents", "offer snapshot net total mismatch"),
        ("vat_7_base_cents", "offer snapshot 7% VAT base mismatch"),
        ("vat_7_amount_cents", "offer snapshot 7% VAT amount mismatch"),
        ("vat_19_base_cents", "offer snapshot 19% VAT base mismatch"),
        ("vat_19_amount_cents", "offer snapshot 19% VAT amount mismatch"),
        ("gross_cents", "offer snapshot gross total mismatch"),
    ],
)
def test_variant_total_mismatch_is_rejected(field: str, message: str) -> None:
    payload = _valid_snapshot()
    variants = cast(list[dict[str, object]], payload["variants"])
    totals = cast(dict[str, object], variants[0]["totals"])
    totals[field] = cast(int, totals[field]) + 1
    payload["snapshot_hash"] = compute_snapshot_hash(payload)

    with pytest.raises(ValueError, match=message):
        validate_offer_snapshot(payload)


def test_mixed_vat_snapshot_passes_arithmetic_validation() -> None:
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

    snapshot = validate_offer_snapshot(payload)

    assert snapshot.variants[0].totals.net_cents == 15000
    assert snapshot.variants[0].totals.vat_7_base_cents == 10000
    assert snapshot.variants[0].totals.vat_19_base_cents == 5000
    assert snapshot.variants[0].totals.gross_cents == 16650


def test_fractional_quantity_uses_round_half_up() -> None:
    position = _position(
        quantity="2.5",
        unit_net_cents=1,
        net_total_cents=3,
        vat_amount_cents=0,
        gross_total_cents=3,
    )
    payload = _valid_snapshot(variants=[_variant(positions=[position])])

    snapshot = validate_offer_snapshot(payload)

    assert snapshot.variants[0].positions[0].net_total_cents == 3


def test_position_vat_uses_round_half_up() -> None:
    position = _position(
        quantity="1",
        unit_net_cents=50,
        net_total_cents=50,
        vat_amount_cents=4,
        gross_total_cents=54,
    )
    payload = _valid_snapshot(variants=[_variant(positions=[position])])

    snapshot = validate_offer_snapshot(payload)

    assert snapshot.variants[0].positions[0].vat_amount_cents == 4


def test_per_person_quantity_uses_event_guest_count() -> None:
    position = _position(quantity_mode="per_person", quantity="1")
    payload = _valid_snapshot(guest_count=80, variants=[_variant(positions=[position])])

    snapshot = validate_offer_snapshot(payload)

    assert snapshot.variants[0].positions[0].net_total_cents == 23200


def test_invalid_vat_rate_is_rejected() -> None:
    variant = _variant(
        positions=[_position(vat_rate_percent=8)],
    )
    payload = _valid_snapshot(variants=[variant])
    with pytest.raises(ValueError, match="vat_rate_percent"):
        validate_offer_snapshot(payload)


def test_variant_count_limit_is_rejected() -> None:
    variants = [_variant() for _ in range(MAX_VARIANTS + 1)]
    for index, variant in enumerate(variants):
        variant["variant_id"] = str(uuid.uuid4())
    payload = _valid_snapshot(variants=variants)
    with pytest.raises(ValueError, match="variant count"):
        validate_offer_snapshot(payload)


def test_position_count_limit_is_rejected() -> None:
    positions = [
        _position(position_id=str(uuid.uuid4()))
        for _ in range(MAX_POSITIONS_PER_VARIANT + 1)
    ]
    payload = _valid_snapshot(variants=[_variant(positions=positions)])
    with pytest.raises(ValueError, match="position count"):
        validate_offer_snapshot(payload)


def test_payload_size_limit_is_rejected() -> None:
    payload = _valid_snapshot()
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    oversized = raw + b"x" * (MAX_PAYLOAD_BYTES - len(raw) + 1)
    with pytest.raises(ValueError, match="size limit"):
        validate_offer_snapshot_bytes(oversized)


def test_snapshot_hash_mismatch_is_rejected() -> None:
    payload = _valid_snapshot()
    payload["snapshot_hash"] = "sha256:" + ("a" * 64)
    with pytest.raises(ValueError, match="snapshot_hash mismatch"):
        validate_offer_snapshot(payload)


def test_snapshot_hash_is_deterministic_for_reordered_keys() -> None:
    payload_a = _snapshot_body()
    payload_b = {
        "variants": payload_a["variants"],
        "calculator": payload_a["calculator"],
        "payment_terms": payload_a["payment_terms"],
        "customer_text": payload_a["customer_text"],
        "event": payload_a["event"],
        "recipient": payload_a["recipient"],
        "currency": payload_a["currency"],
        "valid_until": payload_a["valid_until"],
        "snapshot_created_at": payload_a["snapshot_created_at"],
        "snapshot_id": payload_a["snapshot_id"],
        "inquiry_id": payload_a["inquiry_id"],
        "source_draft_id": payload_a["source_draft_id"],
        "source": payload_a["source"],
        "schema_version": payload_a["schema_version"],
    }
    assert compute_snapshot_hash(payload_a) == compute_snapshot_hash(payload_b)
    assert canonical_snapshot_json(payload_a) == canonical_snapshot_json(payload_b)


def test_unknown_envelope_field_is_rejected() -> None:
    payload = _valid_snapshot()
    payload["unexpected"] = "hostile"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="unknown envelope field"):
        validate_offer_snapshot(payload)


def test_duplicate_json_key_is_rejected() -> None:
    raw = b'{"schema_version":"offer_snapshot_v1","schema_version":"offer_snapshot_v1"}'
    with pytest.raises(ValueError, match="invalid snapshot JSON"):
        validate_offer_snapshot_bytes(raw)


def test_per_person_quantity_requires_guest_count() -> None:
    variant = _variant(positions=[_position(quantity_mode="per_person")])
    payload = _valid_snapshot(guest_count=None, variants=[variant])
    with pytest.raises(ValueError, match="guest_count"):
        validate_offer_snapshot(payload)


def test_surcharge_must_be_separate_position_with_base_reference() -> None:
    base = _position(position_id=_BASE_POSITION_ID, kind="catalog")
    surcharge = _position(
        position_id=_SURCHARGE_ID,
        kind="surcharge",
        related_position_id=_BASE_POSITION_ID,
    )
    payload = _valid_snapshot(variants=[_variant(positions=[base, surcharge])])
    snapshot = validate_offer_snapshot(payload)
    assert snapshot.variants[0].positions[1].kind == "surcharge"

    bad = deepcopy(payload)
    bad_variants = cast(list[dict[str, object]], bad["variants"])
    bad_positions = cast(list[dict[str, object]], bad_variants[0]["positions"])
    bad_positions[1]["related_position_id"] = None
    bad["snapshot_hash"] = compute_snapshot_hash(bad)
    with pytest.raises(ValueError, match="surcharge requires related_position_id"):
        validate_offer_snapshot(bad)


def test_surcharge_must_reference_catalog_position() -> None:
    fee = _position(position_id=_BASE_POSITION_ID, kind="fee")
    surcharge = _position(
        position_id=_SURCHARGE_ID,
        kind="surcharge",
        related_position_id=_BASE_POSITION_ID,
    )
    payload = _valid_snapshot(variants=[_variant(positions=[fee, surcharge])])

    with pytest.raises(ValueError, match="surcharge must reference a catalog position"):
        validate_offer_snapshot(payload)


def test_non_surcharge_cannot_carry_related_position_id() -> None:
    variant = _variant(
        positions=[_position(related_position_id=_POSITION_ID)],
    )
    payload = _valid_snapshot(variants=[variant])
    with pytest.raises(
        ValueError, match="related_position_id is only valid for surcharges"
    ):
        validate_offer_snapshot(payload)


def test_float_money_values_are_rejected() -> None:
    variant = _variant()
    positions = cast(list[dict[str, object]], variant["positions"])
    positions[0]["unit_net_cents"] = 290.5
    body = _snapshot_body(variants=[variant])
    body["snapshot_hash"] = "sha256:" + ("a" * 64)
    with pytest.raises(ValueError, match="integer euro cents"):
        validate_offer_snapshot(body)


def test_v2_empty_allergens_list_is_valid() -> None:
    from catering_system.domain.offer_snapshot import (
        SCHEMA_VERSION_V2,
        compute_snapshot_hash,
    )
    from catering_system.services.offer_snapshot_validation import (
        validate_offer_snapshot,
    )

    dish_id = "11111111-1111-4111-8111-111111111111"
    position = _position()
    position["catalog_item_id"] = dish_id
    position["allergens"] = []
    variant = _variant(positions=[position])
    body = _snapshot_body(variants=[variant])
    body["schema_version"] = SCHEMA_VERSION_V2
    body["snapshot_hash"] = compute_snapshot_hash(body)
    snapshot = validate_offer_snapshot(body)
    assert snapshot.schema_version == SCHEMA_VERSION_V2
    assert snapshot.variants[0].positions[0].allergens == ()
    assert snapshot.variants[0].positions[0].catalog_item_id == dish_id


def test_budget_definition_absent_is_valid() -> None:
    """OFFER_BUDGET_DEFINITION_V1 backward compatibility: older/plain
    snapshots without budget tracking must validate exactly as before."""
    snapshot = validate_offer_snapshot(_valid_snapshot())
    assert snapshot.budget_definition is None


def test_budget_definition_valid_roundtrips() -> None:
    payload = _valid_snapshot(budget_definition=_budget_definition())
    snapshot = validate_offer_snapshot(payload)
    assert snapshot.budget_definition is not None
    assert snapshot.budget_definition.amount_cents == 3500
    assert snapshot.budget_definition.type == "PER_PERSON"
    assert snapshot.budget_definition.tax_basis == "GROSS"
    assert snapshot.budget_definition.cost_scope == "FULL_OFFER"


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "TOTAL", "tax_basis": "NET", "cost_scope": "POSITIONS_ONLY"},
        {"type": "TOTAL", "tax_basis": "GROSS", "cost_scope": "FULL_OFFER"},
        {"type": "PER_PERSON", "tax_basis": "NET", "cost_scope": "FULL_OFFER"},
        {"type": "PER_PERSON", "tax_basis": "GROSS", "cost_scope": "POSITIONS_ONLY"},
    ],
)
def test_budget_definition_every_combination_is_valid(
    overrides: dict[str, object],
) -> None:
    payload = _valid_snapshot(budget_definition=_budget_definition(**overrides))
    snapshot = validate_offer_snapshot(payload)
    assert snapshot.budget_definition is not None
    assert snapshot.budget_definition.type == overrides["type"]
    assert snapshot.budget_definition.tax_basis == overrides["tax_basis"]
    assert snapshot.budget_definition.cost_scope == overrides["cost_scope"]


def test_budget_definition_rejects_unknown_field() -> None:
    definition = _budget_definition()
    definition["extra"] = "nope"
    with pytest.raises(ValueError, match="unknown budget_definition field"):
        validate_offer_snapshot(_valid_snapshot(budget_definition=definition))


@pytest.mark.parametrize("field", ["amount_cents", "type", "tax_basis", "cost_scope"])
def test_budget_definition_rejects_missing_field(field: str) -> None:
    definition = _budget_definition()
    del definition[field]
    with pytest.raises(ValueError):
        validate_offer_snapshot(_valid_snapshot(budget_definition=definition))


def test_budget_definition_rejects_invalid_type_enum() -> None:
    definition = _budget_definition(type="TOTAL_BUDGET")
    with pytest.raises(ValueError, match="invalid budget_definition.type"):
        validate_offer_snapshot(_valid_snapshot(budget_definition=definition))


def test_budget_definition_rejects_invalid_tax_basis_enum() -> None:
    definition = _budget_definition(tax_basis="brutto")
    with pytest.raises(ValueError, match="invalid budget_definition.tax_basis"):
        validate_offer_snapshot(_valid_snapshot(budget_definition=definition))


def test_budget_definition_rejects_invalid_cost_scope_enum() -> None:
    definition = _budget_definition(cost_scope="EVERYTHING")
    with pytest.raises(ValueError, match="invalid budget_definition.cost_scope"):
        validate_offer_snapshot(_valid_snapshot(budget_definition=definition))


def test_budget_definition_rejects_negative_amount() -> None:
    definition = _budget_definition(amount_cents=-100)
    with pytest.raises(ValueError):
        validate_offer_snapshot(_valid_snapshot(budget_definition=definition))


def test_budget_definition_rejects_float_amount() -> None:
    # budget_definition is parsed before the snapshot_hash is even checked
    # (see validate_offer_snapshot), so the float is caught first — a stale
    # hash from the float mutation never gets evaluated.
    payload = _valid_snapshot(budget_definition=_budget_definition())
    payload["budget_definition"]["amount_cents"] = 35.0
    with pytest.raises(ValueError, match="amount_cents must be integer euro cents"):
        validate_offer_snapshot(payload)


def test_budget_definition_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="budget_definition must be an object"):
        validate_offer_snapshot(_valid_snapshot(budget_definition="not-an-object"))  # type: ignore[arg-type]


def test_domain_module_has_no_repository_or_api_imports() -> None:
    from pathlib import Path

    for relative in (
        "domain/offer_snapshot.py",
        "services/offer_snapshot_validation.py",
    ):
        source = (
            Path(__file__).resolve().parents[2] / "src" / "catering_system" / relative
        )
        text = source.read_text(encoding="utf-8")
        assert "sqlite" not in text.lower()
        assert "repositories" not in text
        assert "office_api" not in text

"""OFFER_DOCUMENT_SNAPSHOT_V1 — domain, hash, serialization, tamper detection.

Covers the frozen ANGEBOT / AUFTRAGSBESTÄTIGUNG snapshot in isolation, with
no service/repository involved: structural invariants, deterministic
reference, canonical hash contract, and the mandatory runtime hash
verification on every read.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.offer_document_snapshot import (
    SCHEMA_VERSION,
    OfferDocumentHashMismatchError,
    OfferDocumentPosition,
    OfferDocumentSnapshot,
    OfferDocumentVatBucket,
    document_reference,
)
from catering_system.services.offer_document_snapshot_hash import compute_document_hash
from catering_system.services.offer_document_snapshot_serialization import (
    snapshot_from_canonical_json,
    snapshot_from_verified_row,
    snapshot_to_canonical_json,
)

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
_INVOICE = CustomerAddress(
    street="Bürostraße 1", postal_code="20095", city="Hamburg", country="DE"
)
_DELIVERY = CustomerAddress(
    street="Eventplatz 9", postal_code="20457", city="Hamburg", country="DE"
)


def _valid_snapshot(**overrides: object) -> OfferDocumentSnapshot:
    base = dict(
        offer_document_snapshot_id=str(uuid.uuid4()),
        offer_id="7b5a5a7d-1111-4111-8111-111111111111",
        offer_version_id=str(uuid.uuid4()),
        offer_variant_id=str(uuid.uuid4()),
        document_reference="ANG-7B5A5A7D-V1",
        created_at=_NOW,
        created_by="office-panel",
        recipient_name="Anna",
        recipient_company="ACME GmbH",
        recipient_email="anna@example.invalid",
        recipient_phone=None,
        invoice_address=_INVOICE,
        fulfillment_mode="DELIVERY",
        delivery_address=_INVOICE,
        delivery_address_differs=False,
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        positions=(
            OfferDocumentPosition(
                position_id="pos-1",
                kind="catalog",
                name="Fingerfood Paket",
                unit_net_cents=290,
                net_total_cents=23200,
                vat_rate_percent=7,
                vat_cents=1624,
                gross_cents=24824,
                quantity="80",
                unit_label="Stück",
            ),
        ),
        vat_buckets=(
            OfferDocumentVatBucket(
                rate_percent=7, base_net_cents=23200, vat_cents=1624
            ),
        ),
        net_total_cents=23200,
        vat_total_cents=1624,
        gross_total_cents=24824,
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        document_hash="sha256:" + "0" * 64,
        schema_version=SCHEMA_VERSION,
    )
    base.update(overrides)
    snapshot = OfferDocumentSnapshot(**base)  # type: ignore[arg-type]
    if overrides.get("document_hash") is None and "document_hash" not in overrides:
        snapshot = replace(snapshot, document_hash=compute_document_hash(snapshot))
    return snapshot


# --- document_reference -------------------------------------------------------


def test_document_reference_is_deterministic_and_filename_safe() -> None:
    ref = document_reference("7b5a5a7d-1111-4111-8111-111111111111", 1)
    assert ref == "ANG-7B5A5A7D-V1"
    assert ref == document_reference("7b5a5a7d-1111-4111-8111-111111111111", 1)
    assert " " not in ref
    assert "/" not in ref


def test_document_reference_rejects_blank_offer_id_or_bad_version() -> None:
    with pytest.raises(ValueError):
        document_reference("", 1)
    with pytest.raises(ValueError):
        document_reference("offer-1", 0)


# --- structural invariants -----------------------------------------------------


def test_schema_version_must_be_exactly_one() -> None:
    with pytest.raises(ValueError, match="unsupported offer document schema version"):
        _valid_snapshot(schema_version=2)


def test_document_hash_format_enforced() -> None:
    with pytest.raises(ValueError, match="document_hash"):
        _valid_snapshot(document_hash="not-a-hash")


def test_fulfillment_mode_must_be_delivery_or_pickup() -> None:
    with pytest.raises(ValueError, match="DELIVERY or PICKUP"):
        _valid_snapshot(fulfillment_mode="UNKNOWN")


def test_invoice_address_must_be_structurally_complete() -> None:
    incomplete = CustomerAddress(street="Only street")
    with pytest.raises(ValueError, match="invoice_address"):
        _valid_snapshot(invoice_address=incomplete)


def test_delivery_requires_effective_delivery_address() -> None:
    with pytest.raises(ValueError, match="DELIVERY requires"):
        _valid_snapshot(
            fulfillment_mode="DELIVERY",
            delivery_address=None,
            delivery_address_differs=False,
        )


def test_pickup_forbids_delivery_address() -> None:
    with pytest.raises(ValueError, match="PICKUP must not store a delivery address"):
        _valid_snapshot(
            fulfillment_mode="PICKUP",
            delivery_address=_DELIVERY,
            delivery_address_differs=False,
        )


def test_pickup_forbids_differs_true() -> None:
    with pytest.raises(ValueError, match="delivery_address_differs"):
        _valid_snapshot(
            fulfillment_mode="PICKUP",
            delivery_address=None,
            delivery_address_differs=True,
        )


def test_delivery_address_differs_must_match_computed_equality() -> None:
    with pytest.raises(ValueError, match="delivery_address_differs does not match"):
        _valid_snapshot(
            fulfillment_mode="DELIVERY",
            delivery_address=_DELIVERY,
            delivery_address_differs=False,
        )


def test_negative_cents_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _valid_snapshot(net_total_cents=-1)


def test_snapshot_and_positions_are_frozen() -> None:
    snap = _valid_snapshot()
    with pytest.raises(Exception):
        snap.document_reference = "ANG-OTHER-V1"  # type: ignore[misc]
    with pytest.raises(Exception):
        snap.positions[0].name = "changed"  # type: ignore[misc]


# --- hash contract --------------------------------------------------------------


def test_every_contractual_fact_changes_the_hash() -> None:
    base = _valid_snapshot()
    mutations = [
        {"document_reference": "ANG-OTHER0-V1"},
        {"recipient_name": "Someone Else"},
        {"event_date": date(2026, 9, 1)},
        {"customer_title": "Different title"},
        {"positions": (replace(base.positions[0], net_total_cents=1),)},
        {"payment_method": "VORKASSE"},
        {"document_warnings": ("SOME_WARNING",)},
    ]
    for mutation in mutations:
        changed = replace(base, **mutation)  # type: ignore[arg-type]
        changed = replace(changed, document_hash=compute_document_hash(changed))
        assert changed.document_hash != base.document_hash, mutation


def test_created_at_and_created_by_do_not_affect_hash() -> None:
    base = _valid_snapshot()
    same_content = replace(
        base, created_at=datetime(2030, 1, 1, tzinfo=UTC), created_by="someone-else"
    )
    assert compute_document_hash(same_content) == compute_document_hash(base)


def test_hash_differs_between_delivery_and_pickup() -> None:
    delivery = _valid_snapshot(
        fulfillment_mode="DELIVERY",
        delivery_address=_INVOICE,
        delivery_address_differs=False,
    )
    pickup = _valid_snapshot(
        fulfillment_mode="PICKUP",
        delivery_address=None,
        delivery_address_differs=False,
    )
    assert compute_document_hash(delivery) != compute_document_hash(pickup)


def test_canonical_json_key_ordering_is_stable() -> None:
    snap = _valid_snapshot()
    a = snapshot_to_canonical_json(snap)
    b = snapshot_to_canonical_json(snap)
    assert a == b
    payload = json.loads(a)
    assert list(payload.keys()) == sorted(payload.keys())


def test_canonical_round_trip_preserves_every_field() -> None:
    snap = _valid_snapshot(
        customer_title="Sommerfest",
        customer_introduction="Intro",
        customer_notes="Notes",
    )
    loaded = snapshot_from_canonical_json(snapshot_to_canonical_json(snap))
    assert loaded == snap


# --- runtime hash verification (mandatory on every read) ----------------------


def test_valid_row_reads_successfully() -> None:
    snap = _valid_snapshot()
    canonical = snapshot_to_canonical_json(snap)
    loaded = snapshot_from_verified_row(canonical, snap.document_hash)
    assert loaded == snap


def test_modified_canonical_json_is_detected() -> None:
    snap = _valid_snapshot()
    canonical = snapshot_to_canonical_json(snap)
    tampered = canonical.replace('"net_total_cents":23200', '"net_total_cents":1')
    with pytest.raises(OfferDocumentHashMismatchError):
        snapshot_from_verified_row(tampered, snap.document_hash)


def test_modified_row_hash_column_is_detected() -> None:
    snap = _valid_snapshot()
    canonical = snapshot_to_canonical_json(snap)
    with pytest.raises(OfferDocumentHashMismatchError):
        snapshot_from_verified_row(canonical, "sha256:" + "b" * 64)


def test_modified_embedded_document_hash_is_detected() -> None:
    snap = _valid_snapshot()
    canonical = snapshot_to_canonical_json(snap)
    tampered = canonical.replace(snap.document_hash, "sha256:" + "c" * 64)
    with pytest.raises(OfferDocumentHashMismatchError):
        snapshot_from_verified_row(tampered, snap.document_hash)


def test_malformed_canonical_json_fails_closed() -> None:
    with pytest.raises(json.JSONDecodeError):
        snapshot_from_verified_row("{not valid json", "sha256:" + "0" * 64)


def test_unsupported_schema_version_in_payload_rejected() -> None:
    snap = _valid_snapshot()
    payload = json.loads(snapshot_to_canonical_json(snap))
    payload["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported offer document schema version"):
        snapshot_from_canonical_json(json.dumps(payload))

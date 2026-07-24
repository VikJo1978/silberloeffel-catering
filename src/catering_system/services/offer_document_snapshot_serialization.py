"""Canonical JSON for OfferDocumentSnapshot persistence + runtime verification.

Unlike the older OrderConfirmationDocumentSnapshot reader, every persisted
read here re-derives the hash and compares it against both stored copies
(the one embedded in the canonical JSON and the one in the table column).
A mismatch raises instead of returning a partially trusted document.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import (
    customer_address_from_mapping,
    customer_address_to_mapping,
)
from catering_system.domain.offer_document_snapshot import (
    SCHEMA_VERSION,
    OFFER_DOCUMENT_FULFILLMENT_MODES,
    OfferDocumentFulfillmentMode,
    OfferDocumentHashMismatchError,
    OfferDocumentPosition,
    OfferDocumentSnapshot,
    OfferDocumentVatBucket,
)
from catering_system.domain.order_payment_reminder import validate_payment_method
from catering_system.services.offer_document_snapshot_hash import compute_document_hash


def snapshot_to_canonical_json(snapshot: OfferDocumentSnapshot) -> str:
    return json.dumps(
        _snapshot_payload(snapshot),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def snapshot_from_canonical_json(raw: str) -> OfferDocumentSnapshot:
    """Parse without trusting the hash — callers that read persisted rows
    must use ``snapshot_from_verified_row`` instead."""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("offer document snapshot JSON must be an object")
    schema_version = int(payload.get("schema_version", SCHEMA_VERSION))
    if schema_version != SCHEMA_VERSION:
        raise ValueError("unsupported offer document schema version")
    positions_raw = payload.get("positions")
    buckets_raw = payload.get("vat_buckets")
    if not isinstance(positions_raw, list) or not isinstance(buckets_raw, list):
        raise ValueError("offer document snapshot JSON is incomplete")
    invoice_address = customer_address_from_mapping(payload["invoice_address"])
    if invoice_address is None:
        raise ValueError("offer document snapshot requires an invoice address")
    return OfferDocumentSnapshot(
        offer_document_snapshot_id=str(payload["offer_document_snapshot_id"]),
        offer_id=str(payload["offer_id"]),
        offer_version_id=str(payload["offer_version_id"]),
        offer_variant_id=str(payload["offer_variant_id"]),
        document_reference=str(payload["document_reference"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        created_by=str(payload["created_by"]),
        recipient_name=_optional_str(payload.get("recipient_name")),
        recipient_company=_optional_str(payload.get("recipient_company")),
        recipient_email=_optional_str(payload.get("recipient_email")),
        recipient_phone=_optional_str(payload.get("recipient_phone")),
        invoice_address=invoice_address,
        fulfillment_mode=_fulfillment_mode(payload.get("fulfillment_mode")),
        delivery_address=_delivery_address(payload.get("delivery_address")),
        delivery_address_differs=_bool(payload["delivery_address_differs"]),
        event_date=date.fromisoformat(str(payload["event_date"])),
        time_window_text=str(payload["time_window_text"]),
        location_text=str(payload["location_text"]),
        guest_count_estimate=_optional_int(payload.get("guest_count_estimate")),
        customer_title=_optional_str(payload.get("customer_title")),
        customer_introduction=_optional_str(payload.get("customer_introduction")),
        customer_notes=_optional_str(payload.get("customer_notes")),
        positions=tuple(_position(item) for item in positions_raw),
        vat_buckets=tuple(_bucket(item) for item in buckets_raw),
        net_total_cents=_int(payload["net_total_cents"]),
        vat_total_cents=_int(payload["vat_total_cents"]),
        gross_total_cents=_int(payload["gross_total_cents"]),
        payment_method=validate_payment_method(str(payload["payment_method"])),
        payment_customer_visible_text=str(payload["payment_customer_visible_text"]),
        document_hash=str(payload["document_hash"]),
        schema_version=schema_version,
        document_warnings=_document_warnings(payload.get("document_warnings")),
    )


def snapshot_from_verified_row(
    canonical_json: str, row_document_hash: str
) -> OfferDocumentSnapshot:
    """Mandatory read path for persisted rows.

    Recomputes the business hash and requires it to match BOTH stored copies.
    Checking both distinguishes a mutated JSON body (neither matches), a
    mutated row column (only the embedded one matches) and a mutated embedded
    value (only the row column matches).
    """
    snapshot = snapshot_from_canonical_json(canonical_json)
    recomputed = compute_document_hash(snapshot)
    if recomputed != snapshot.document_hash or recomputed != row_document_hash:
        raise OfferDocumentHashMismatchError(
            offer_document_snapshot_id=snapshot.offer_document_snapshot_id,
            recomputed=recomputed,
            embedded=snapshot.document_hash,
            row=row_document_hash,
        )
    return snapshot


def _snapshot_payload(snapshot: OfferDocumentSnapshot) -> dict[str, object]:
    return {
        "offer_document_snapshot_id": snapshot.offer_document_snapshot_id,
        "offer_id": snapshot.offer_id,
        "offer_version_id": snapshot.offer_version_id,
        "offer_variant_id": snapshot.offer_variant_id,
        "document_reference": snapshot.document_reference,
        "created_at": snapshot.created_at.isoformat(),
        "created_by": snapshot.created_by,
        "recipient_name": snapshot.recipient_name,
        "recipient_company": snapshot.recipient_company,
        "recipient_email": snapshot.recipient_email,
        "recipient_phone": snapshot.recipient_phone,
        "invoice_address": customer_address_to_mapping(snapshot.invoice_address),
        "fulfillment_mode": snapshot.fulfillment_mode,
        "delivery_address": customer_address_to_mapping(snapshot.delivery_address),
        "delivery_address_differs": snapshot.delivery_address_differs,
        "event_date": snapshot.event_date.isoformat(),
        "time_window_text": snapshot.time_window_text,
        "location_text": snapshot.location_text,
        "guest_count_estimate": snapshot.guest_count_estimate,
        "customer_title": snapshot.customer_title,
        "customer_introduction": snapshot.customer_introduction,
        "customer_notes": snapshot.customer_notes,
        "positions": [
            {
                "position_id": position.position_id,
                "kind": position.kind,
                "name": position.name,
                "description": position.description,
                "composition": position.composition,
                "quantity": position.quantity,
                "unit_label": position.unit_label,
                "unit_net_cents": position.unit_net_cents,
                "net_total_cents": position.net_total_cents,
                "vat_rate_percent": position.vat_rate_percent,
                "vat_cents": position.vat_cents,
                "gross_cents": position.gross_cents,
                "related_position_id": position.related_position_id,
            }
            for position in snapshot.positions
        ],
        "vat_buckets": [
            {
                "rate_percent": bucket.rate_percent,
                "base_net_cents": bucket.base_net_cents,
                "vat_cents": bucket.vat_cents,
            }
            for bucket in snapshot.vat_buckets
        ],
        "net_total_cents": snapshot.net_total_cents,
        "vat_total_cents": snapshot.vat_total_cents,
        "gross_total_cents": snapshot.gross_total_cents,
        "payment_method": snapshot.payment_method,
        "payment_customer_visible_text": snapshot.payment_customer_visible_text,
        "document_hash": snapshot.document_hash,
        "schema_version": snapshot.schema_version,
        "document_warnings": list(snapshot.document_warnings),
    }


def _fulfillment_mode(value: object) -> OfferDocumentFulfillmentMode:
    if not isinstance(value, str) or value not in OFFER_DOCUMENT_FULFILLMENT_MODES:
        raise ValueError("fulfillment_mode must be DELIVERY or PICKUP")
    return value


def _delivery_address(value: object) -> CustomerAddress | None:
    if value is None:
        return None
    return customer_address_from_mapping(value)


def _position(raw: object) -> OfferDocumentPosition:
    if not isinstance(raw, dict):
        raise ValueError("position must be an object")
    return OfferDocumentPosition(
        position_id=str(raw["position_id"]),
        kind=str(raw["kind"]),
        name=str(raw["name"]),
        unit_net_cents=_int(raw["unit_net_cents"]),
        net_total_cents=_int(raw["net_total_cents"]),
        vat_rate_percent=_int(raw["vat_rate_percent"]),
        vat_cents=_int(raw["vat_cents"]),
        gross_cents=_int(raw["gross_cents"]),
        related_position_id=_optional_str(raw.get("related_position_id")),
        description=_optional_str(raw.get("description")),
        composition=_optional_str(raw.get("composition")),
        quantity=_optional_str(raw.get("quantity")),
        unit_label=_optional_str(raw.get("unit_label")),
    )


def _bucket(raw: object) -> OfferDocumentVatBucket:
    if not isinstance(raw, dict):
        raise ValueError("vat bucket must be an object")
    return OfferDocumentVatBucket(
        rate_percent=_int(raw["rate_percent"]),
        base_net_cents=_int(raw["base_net_cents"]),
        vat_cents=_int(raw["vat_cents"]),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("invalid integer")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int(value)


def _bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected a boolean")
    return value


def _document_warnings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("document_warnings must be a list")
    return tuple(str(item) for item in value)

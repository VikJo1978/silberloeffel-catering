"""Canonical hash for OrderConfirmationDocumentSnapshot."""

from __future__ import annotations

from catering_system.domain.inquiry_customer_snapshot import customer_address_to_mapping
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentSnapshot,
    SCHEMA_VERSION_V2,
    SCHEMA_VERSION_V3,
)


def snapshot_hash_payload(
    snapshot: OrderConfirmationDocumentSnapshot,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": snapshot.schema_version,
        "order_id": snapshot.order_id,
        "order_version_id": snapshot.order_version_id,
        "offer_id": snapshot.offer_id,
        "offer_version_id": snapshot.offer_version_id,
        "document_reference": snapshot.document_reference,
        "recipient_name": snapshot.recipient_name,
        "recipient_email": snapshot.recipient_email,
        "recipient_company": snapshot.recipient_company,
        "recipient_phone": snapshot.recipient_phone,
        "recipient_status": snapshot.recipient_status,
        "event_date": snapshot.event_date.isoformat(),
        "time_window_text": snapshot.time_window_text,
        "location_text": snapshot.location_text,
        "guest_count_estimate": snapshot.guest_count_estimate,
        "planning_mode": snapshot.planning_mode,
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
        "document_warnings": list(snapshot.document_warnings),
    }
    # Schema 1 hash payload must stay byte-identical to pre-address-work hash.
    if snapshot.schema_version >= SCHEMA_VERSION_V2:
        payload["invoice_address"] = customer_address_to_mapping(
            snapshot.invoice_address
        )
        payload["delivery_address"] = customer_address_to_mapping(
            snapshot.delivery_address
        )
        payload["delivery_address_differs"] = snapshot.delivery_address_differs
    # Schema 2 hash payload must stay byte-identical to pre-fulfillment hash.
    if snapshot.schema_version >= SCHEMA_VERSION_V3:
        payload["fulfillment_mode"] = snapshot.fulfillment_mode
    return payload


def compute_document_hash(snapshot: OrderConfirmationDocumentSnapshot) -> str:
    return compute_snapshot_hash(snapshot_hash_payload(snapshot))

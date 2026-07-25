"""Canonical hash for OfferDocumentSnapshot — OFFER_DOCUMENT_SNAPSHOT_V1.

The hash covers every contractual, customer-visible fact of the document.
It deliberately excludes creation metadata (created_at/created_by) and all
future transport/acceptance evidence, so re-sending or later accepting the
same document never changes what the customer agreed to.

Three distinct hashes exist in the wider flow and must not be confused:
``document_hash`` (this one, the business content), ``original_pdf_hash``
(bytes actually sent) and ``signed_file_hash`` (bytes returned signed).
The latter two are not equal to each other and are out of this slice.
"""

from __future__ import annotations

from catering_system.domain.inquiry_customer_snapshot import customer_address_to_mapping
from catering_system.domain.offer_document_snapshot import OfferDocumentSnapshot
from catering_system.domain.offer_snapshot import compute_snapshot_hash


def snapshot_hash_payload(snapshot: OfferDocumentSnapshot) -> dict[str, object]:
    """Deterministic hash payload; key order is normalized by the serializer."""
    return {
        "schema_version": snapshot.schema_version,
        "document_reference": snapshot.document_reference,
        "offer_id": snapshot.offer_id,
        "offer_version_id": snapshot.offer_version_id,
        "offer_variant_id": snapshot.offer_variant_id,
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
        "document_warnings": list(snapshot.document_warnings),
    }


def compute_document_hash(snapshot: OfferDocumentSnapshot) -> str:
    """sha256 over the canonical business payload (RFC 8785-style ordering)."""
    return compute_snapshot_hash(snapshot_hash_payload(snapshot))

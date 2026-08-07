"""Frozen operational delivery facts at offer conversion — Slice 6."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import FulfillmentMode, Inquiry
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.order import OrderVersion

_CREATED_FROM = "accepted_order_conversion"
_MAX_TEXT = 20_000


class MissingDeliverySnapshotError(LookupError):
    """Order/version has no OrderDeliverySnapshot."""

    def __init__(self, order_id: str, order_version_id: str) -> None:
        self.order_id = order_id
        self.order_version_id = order_version_id
        super().__init__(
            "order delivery snapshot missing "
            f"(order_id={order_id!r}, order_version_id={order_version_id!r})"
        )


def format_delivery_address(address: CustomerAddress | None) -> str | None:
    if address is None:
        return None
    lines = [
        value
        for value in (
            (address.street or "").strip(),
            " ".join(
                part
                for part in (
                    (address.postal_code or "").strip(),
                    (address.city or "").strip(),
                )
                if part
            ),
            (address.country or "").strip(),
        )
        if value
    ]
    if not lines:
        return None
    text = "\n".join(lines)
    if len(text) > _MAX_TEXT:
        raise ValueError("delivery_address exceeds length limit")
    return text


def _resolved_delivery_address(
    snapshot: InquiryCustomerSnapshot,
) -> CustomerAddress | None:
    if snapshot.delivery_address_mode == "SEPARATE":
        return snapshot.delivery_address
    if snapshot.delivery_address_mode == "SAME_AS_INVOICE":
        return snapshot.invoice_address
    return None


def _delivery_contact(snapshot: InquiryCustomerSnapshot) -> str | None:
    contact = snapshot.email or snapshot.phone or snapshot.contact_name
    if contact is None:
        return None
    contact = contact.strip()
    if not contact:
        return None
    if len(contact) > _MAX_TEXT:
        raise ValueError("delivery_contact exceeds length limit")
    return contact


@dataclass(frozen=True)
class OrderDeliverySnapshot:
    snapshot_id: str
    order_id: str
    order_version_id: str
    fulfillment_mode: FulfillmentMode
    delivery_address: str | None
    delivery_contact: str | None
    time_window_text: str
    location_text: str
    created_from: str = _CREATED_FROM

    def __post_init__(self) -> None:
        if self.created_from != _CREATED_FROM:
            raise ValueError("unsupported delivery snapshot source")
        if not self.time_window_text.strip():
            raise ValueError("time_window_text is required")
        if not self.location_text.strip():
            raise ValueError("location_text is required")
        if self.fulfillment_mode == "PICKUP":
            if self.delivery_address is not None:
                raise ValueError("PICKUP must not store delivery_address")


def build_order_delivery_snapshot(
    *,
    order_id: str,
    order_version: OrderVersion,
    inquiry: Inquiry,
) -> OrderDeliverySnapshot:
    customer = inquiry.customer_snapshot
    fulfillment_mode = inquiry.fulfillment_mode
    delivery_address: str | None = None
    if fulfillment_mode == "DELIVERY":
        delivery_address = format_delivery_address(_resolved_delivery_address(customer))
    return OrderDeliverySnapshot(
        snapshot_id=str(uuid.uuid4()),
        order_id=order_id,
        order_version_id=order_version.order_version_id,
        fulfillment_mode=fulfillment_mode,
        delivery_address=delivery_address,
        delivery_contact=_delivery_contact(customer),
        time_window_text=order_version.time_window_text,
        location_text=order_version.location_text,
    )

"""Frozen customer-facing Auftragsbestätigung snapshot — EMAIL_MVP_1 slice B1.

CONFIRMATION_ADDRESS_SNAPSHOT_V1: schema 2 persists invoice/delivery address
facts once at create time. Schema 1 is legacy without address facts
(delivery_address_differs is None / NOT_STORED — never false-by-default).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from catering_system.domain.customer_document_projection import (
    CustomerAddress,
    customer_addresses_equal,
)
from catering_system.domain.inquiry import PlanningMode

SCHEMA_VERSION_V1 = 1
SCHEMA_VERSION_V2 = 2
SCHEMA_VERSION = SCHEMA_VERSION_V2
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION_V1, SCHEMA_VERSION_V2})
RecipientStatus = Literal["ready", "missing"]
_DOCUMENT_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class OrderConfirmationDocumentPosition:
    position_id: str
    kind: str
    name: str
    unit_net_cents: int
    net_total_cents: int
    vat_rate_percent: int
    vat_cents: int
    gross_cents: int
    related_position_id: str | None = None
    description: str | None = None
    composition: str | None = None
    quantity: str | None = None
    unit_label: str | None = None


@dataclass(frozen=True)
class OrderConfirmationVatBucket:
    rate_percent: int
    base_net_cents: int
    vat_cents: int


@dataclass(frozen=True)
class OrderConfirmationDocumentSnapshot:
    document_snapshot_id: str
    order_id: str
    order_version_id: str
    offer_id: str
    offer_version_id: str
    document_reference: str
    created_at: datetime
    created_by: str
    recipient_name: str | None
    recipient_email: str | None
    recipient_company: str | None
    recipient_phone: str | None
    recipient_status: RecipientStatus
    event_date: date
    time_window_text: str
    location_text: str
    guest_count_estimate: int | None
    planning_mode: PlanningMode
    positions: tuple[OrderConfirmationDocumentPosition, ...]
    vat_buckets: tuple[OrderConfirmationVatBucket, ...]
    net_total_cents: int
    vat_total_cents: int
    gross_total_cents: int
    payment_method: str
    payment_customer_visible_text: str
    document_hash: str
    schema_version: int = SCHEMA_VERSION
    document_warnings: tuple[str, ...] = ()
    invoice_address: CustomerAddress | None = None
    delivery_address: CustomerAddress | None = None
    # None = NOT_STORED (schema 1 legacy). Schema 2 requires bool.
    delivery_address_differs: bool | None = None

    def __post_init__(self) -> None:
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("unsupported order confirmation document schema version")
        if not _DOCUMENT_HASH.fullmatch(self.document_hash):
            raise ValueError("document_hash must be sha256:<hex>")
        if self.schema_version == SCHEMA_VERSION_V1:
            if (
                self.invoice_address is not None
                or self.delivery_address is not None
                or self.delivery_address_differs is not None
            ):
                raise ValueError(
                    "schema 1 confirmation snapshot must not store address facts"
                )
            return
        if self.delivery_address_differs is None:
            raise ValueError("schema 2 requires delivery_address_differs as bool")
        expected_differs = (
            self.invoice_address is not None
            and self.delivery_address is not None
            and not customer_addresses_equal(
                self.invoice_address, self.delivery_address
            )
        )
        if self.delivery_address_differs != expected_differs:
            raise ValueError("delivery_address_differs does not match addresses")

    @property
    def address_facts_stored(self) -> bool:
        """True when invoice/delivery facts were persisted (schema 2)."""
        return self.schema_version == SCHEMA_VERSION_V2


def mask_recipient_email(email: str | None) -> str | None:
    if email is None:
        return None
    local, separator, domain = email.partition("@")
    if not separator or not local or not domain:
        return "***"
    if len(local) <= 1:
        masked_local = "*"
    else:
        masked_local = f"{local[0]}***"
    return f"{masked_local}@{domain}"


def short_document_hash(document_hash: str) -> str:
    prefix, _, suffix = document_hash.partition(":")
    if not suffix or len(suffix) < 12:
        return document_hash
    return f"{prefix}:{suffix[:8]}…{suffix[-4:]}"

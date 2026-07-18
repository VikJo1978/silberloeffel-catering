"""Frozen customer-facing Auftragsbestätigung snapshot — EMAIL_MVP_1 slice B1."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from catering_system.domain.inquiry import PlanningMode

SCHEMA_VERSION = 1
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

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported order confirmation document schema version")
        if not _DOCUMENT_HASH.fullmatch(self.document_hash):
            raise ValueError("document_hash must be sha256:<hex>")


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

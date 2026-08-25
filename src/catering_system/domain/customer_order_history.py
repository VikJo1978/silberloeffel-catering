"""Read-only factual customer order history projection.

This module does not persist CRM history or inferred preferences. It projects
facts that already exist in Inquiry, Order/OrderVersion and accepted Offer
snapshots so later recommendation logic can consume history without rewriting
it into customer preference state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from catering_system.domain.inquiry import FulfillmentMode


@dataclass(frozen=True)
class CustomerOrderHistoryDish:
    """One accepted menu position from the customer-selected Offer variant."""

    position_id: str
    name: str
    kind: str
    catalog_item_id: str | None
    gross_total_cents: int


@dataclass(frozen=True)
class CustomerOrderHistoryEntry:
    """Factual projection for one Order explicitly linked to a CustomerIdentity.

    Accepted commercial fields are optional so legacy Orders without a complete
    Offer conversion trail remain visible instead of being silently discarded.
    """

    order_id: str
    source_inquiry_id: str
    order_version_id: str
    event_date: date
    guest_count: int | None
    fulfillment_mode: FulfillmentMode
    accepted_offer_id: str | None
    accepted_offer_version_id: str | None
    accepted_variant_id: str | None
    accepted_variant_label: str | None
    dishes: tuple[CustomerOrderHistoryDish, ...]
    gross_total_cents: int | None
    order_created_at: datetime
    cancelled_at: datetime | None

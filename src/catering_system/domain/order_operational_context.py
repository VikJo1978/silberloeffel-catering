"""Frozen operational customer/delivery context bound to one OrderVersion."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import FulfillmentMode, validate_fulfillment_mode

OrderOperationalContextSource = Literal[
    "initial_inquiry_snapshot",
    "inherited_parent",
    "explicit_change",
    "confirmation_snapshot_backfill",
]

ORDER_OPERATIONAL_CONTEXT_SOURCES: tuple[OrderOperationalContextSource, ...] = (
    "initial_inquiry_snapshot",
    "inherited_parent",
    "explicit_change",
    "confirmation_snapshot_backfill",
)


@dataclass(frozen=True)
class OrderOperationalContextData:
    recipient_company: str | None
    recipient_name: str | None
    recipient_phone: str | None
    delivery_address: CustomerAddress | None
    invoice_address: CustomerAddress | None = None
    fulfillment_mode: FulfillmentMode = "UNKNOWN"

    def __post_init__(self) -> None:
        validate_fulfillment_mode(self.fulfillment_mode)


@dataclass(frozen=True)
class OrderVersionOperationalContextSnapshot:
    order_version_id: str
    order_id: str
    recipient_company: str | None
    recipient_name: str | None
    recipient_phone: str | None
    delivery_address: CustomerAddress | None
    created_at: datetime
    source: OrderOperationalContextSource
    invoice_address: CustomerAddress | None = None
    fulfillment_mode: FulfillmentMode = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.source not in ORDER_OPERATIONAL_CONTEXT_SOURCES:
            raise ValueError("invalid operational context source")
        validate_fulfillment_mode(self.fulfillment_mode)


def copy_operational_context_for_version(
    snapshot: OrderVersionOperationalContextSnapshot,
    *,
    order_version_id: str,
    order_id: str,
    created_at: datetime,
    source: OrderOperationalContextSource = "inherited_parent",
) -> OrderVersionOperationalContextSnapshot:
    return replace(
        snapshot,
        order_version_id=order_version_id,
        order_id=order_id,
        created_at=created_at,
        source=source,
    )

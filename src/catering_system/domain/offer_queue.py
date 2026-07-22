"""Offer operational queue read model — derived groups only, never persisted."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from catering_system.domain.offer import OfferState

OfferQueueGroup = Literal["action_required", "overdue", "history"]
OfferQueueSubkind = Literal[
    "prepared",
    "sent",
    "accepted",
    "accepted_contact_blocked",
    "expired",
    "converted",
    "rejected",
    "withdrawn",
    "superseded",
    "inquiry_closed",
]
OfferQueueNextAction = Literal[
    "mark_sent",
    "await_customer",
    "convert_accepted",
    "complete_contact",
    "prepare_next_version",
    "none",
]
ValidityHint = Literal["expires_today"]


@dataclass(frozen=True)
class OfferQueueItem:
    """One offer row in the operational queue; all fields are derived."""

    offer_id: str
    inquiry_id: str
    offer_version_id: str
    version_number: int
    state: OfferState
    queue_group: OfferQueueGroup
    queue_subkind: OfferQueueSubkind
    next_action: OfferQueueNextAction
    next_action_label: str
    customer_display: str
    intake_subject: str | None
    event_date: date
    guest_count: int | None
    valid_until: date
    days_until_valid_until: int
    days_overdue: int | None
    prepared_at: datetime
    sent_at: datetime | None
    validity_hint: ValidityHint | None
    sort_key: tuple[object, ...]


@dataclass(frozen=True)
class OfferQueueSection:
    group: OfferQueueGroup
    label: str
    count: int
    items: tuple[OfferQueueItem, ...]


@dataclass(frozen=True)
class OfferQueueSnapshot:
    today: date
    sections: tuple[OfferQueueSection, ...]
    total_count: int
    limit: int
    offset: int

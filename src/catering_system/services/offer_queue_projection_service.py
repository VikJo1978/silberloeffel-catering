"""Offer operational queue projection — derived office triage from existing facts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

from catering_system.domain.inquiry import Inquiry, derive_inquiry_offer_projection
from catering_system.domain.inquiry_contact_completeness import inquiry_contact_complete
from catering_system.domain.offer import Offer, OfferState
from catering_system.domain.offer_queue import (
    OfferQueueGroup,
    OfferQueueItem,
    OfferQueueNextAction,
    OfferQueueSection,
    OfferQueueSnapshot,
    OfferQueueSubkind,
    ValidityHint,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository

_SECTION_LABELS: dict[OfferQueueGroup, str] = {
    "action_required": "Aktion erforderlich",
    "overdue": "Frist überschritten",
    "history": "Abgeschlossen / Verlauf",
}

_SUBKIND_ORDER: dict[OfferQueueSubkind, int] = {
    "prepared": 0,
    "sent": 1,
    "accepted": 2,
    "accepted_contact_blocked": 3,
    "expired": 4,
    "converted": 10,
    "rejected": 11,
    "withdrawn": 12,
    "superseded": 13,
    "inquiry_closed": 14,
}


class OfferQueueProjectionService:
    def __init__(
        self,
        offer_repository: OfferRepository,
        inquiry_repository: InquiryRepository,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._offers = offer_repository
        self._inquiries = inquiry_repository
        self._today = today or (lambda: date.today())

    def snapshot(
        self,
        *,
        group: OfferQueueGroup | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> OfferQueueSnapshot:
        operating_today = self._today()
        inquiries_by_id = {
            inquiry.inquiry_id: inquiry for inquiry in self._inquiries.list_all()
        }
        buckets: dict[OfferQueueGroup, list[OfferQueueItem]] = {
            "action_required": [],
            "overdue": [],
            "history": [],
        }
        for offer in self._offers.list_all():
            inquiry = inquiries_by_id.get(offer.source_inquiry_id)
            if inquiry is None:
                continue
            item = _build_queue_item(offer, inquiry, today=operating_today)
            if item is None:
                continue
            buckets[item.queue_group].append(item)

        for items in buckets.values():
            items.sort(key=lambda item: item.sort_key)

        groups: tuple[OfferQueueGroup, ...]
        if group is not None:
            groups = (group,)
        else:
            groups = ("action_required", "overdue", "history")

        flat = [item for key in groups for item in buckets[key]]
        total_count = len(flat)
        _ = flat[offset : offset + limit]  # reserved for future pagination

        sections = tuple(
            OfferQueueSection(
                group=group_key,
                label=_SECTION_LABELS[group_key],
                count=len(buckets[group_key]),
                items=tuple(buckets[group_key]),
            )
            for group_key in groups
        )

        return OfferQueueSnapshot(
            today=operating_today,
            sections=sections,
            total_count=total_count,
            limit=limit,
            offset=offset,
        )


def _build_queue_item(
    offer: Offer, inquiry: Inquiry, *, today: date
) -> OfferQueueItem | None:
    projection = derive_inquiry_offer_projection(offer, today=today)
    state = projection.commercial_state
    version = next(
        item
        for item in offer.versions
        if item.offer_version_id == projection.offer_version_id
    )
    inquiry_closed = inquiry.crm_stage == "Abgelehnt / verloren"
    contact_complete = inquiry_contact_complete(inquiry)

    queue_group, subkind = _classify(
        state,
        inquiry_closed=inquiry_closed,
        contact_complete=contact_complete,
    )
    next_action, next_action_label = _next_action(
        subkind,
        state=state,
        valid_until=version.valid_until,
        today=today,
    )
    validity_hint: ValidityHint | None = None
    if state == "Sent" and version.valid_until == today:
        validity_hint = "expires_today"

    sent_at = _sent_at(offer, version.offer_version_id)
    days_until = (version.valid_until - today).days
    days_overdue = (today - version.valid_until).days if state == "Expired" else None

    return OfferQueueItem(
        offer_id=offer.offer_id,
        inquiry_id=inquiry.inquiry_id,
        offer_version_id=version.offer_version_id,
        version_number=version.version_number,
        state=state,
        queue_group=queue_group,
        queue_subkind=subkind,
        next_action=next_action,
        next_action_label=next_action_label,
        customer_display=_customer_display(inquiry),
        intake_subject=inquiry.intake_subject,
        event_date=version.event_date,
        guest_count=version.guest_count,
        valid_until=version.valid_until,
        days_until_valid_until=days_until,
        days_overdue=days_overdue,
        prepared_at=version.created_at,
        sent_at=sent_at,
        validity_hint=validity_hint,
        sort_key=_sort_key(
            queue_group=queue_group,
            subkind=subkind,
            version=version,
            sent_at=sent_at,
            offer=offer,
            today=today,
        ),
    )


def _classify(
    state: OfferState,
    *,
    inquiry_closed: bool,
    contact_complete: bool,
) -> tuple[OfferQueueGroup, OfferQueueSubkind]:
    if state in ("Converted", "Rejected", "Withdrawn", "Superseded"):
        return "history", _history_subkind(state)

    if inquiry_closed:
        return "history", "inquiry_closed"

    if state == "Expired":
        return "overdue", "expired"

    if state == "Prepared":
        return "action_required", "prepared"

    if state == "Sent":
        return "action_required", "sent"

    if state == "Accepted":
        if not contact_complete:
            return "action_required", "accepted_contact_blocked"
        return "action_required", "accepted"

    return "history", _history_subkind(state)


def _history_subkind(state: OfferState) -> OfferQueueSubkind:
    if state == "Converted":
        return "converted"
    if state == "Rejected":
        return "rejected"
    if state == "Withdrawn":
        return "withdrawn"
    if state == "Superseded":
        return "superseded"
    return "inquiry_closed"


def _next_action(
    subkind: OfferQueueSubkind,
    *,
    state: OfferState,
    valid_until: date,
    today: date,
) -> tuple[OfferQueueNextAction, str]:
    if subkind == "prepared":
        return "mark_sent", "Als gesendet markieren"
    if subkind == "sent":
        if state == "Sent" and valid_until == today:
            return "await_customer", "Läuft heute ab"
        return "await_customer", "Kundenantwort ausstehend"
    if subkind == "accepted":
        return "convert_accepted", "In Auftrag umwandeln"
    if subkind == "accepted_contact_blocked":
        return "complete_contact", "Kontaktdaten vervollständigen"
    if subkind == "expired":
        return "none", "Frist abgelaufen"
    return "none", "—"


def _customer_display(inquiry: Inquiry) -> str:
    snapshot = inquiry.customer_snapshot
    if snapshot is not None:
        if snapshot.company_name:
            return snapshot.company_name
        if snapshot.contact_name:
            return snapshot.contact_name
    if inquiry.intake_subject:
        return inquiry.intake_subject
    if inquiry.location_text:
        return inquiry.location_text
    return "–"


def _sent_at(offer: Offer, offer_version_id: str) -> datetime | None:
    for evidence in offer.sent_evidence:
        if evidence.offer_version_id == offer_version_id:
            return evidence.sent_at
    return None


def _sort_key(
    *,
    queue_group: OfferQueueGroup,
    subkind: OfferQueueSubkind,
    version,
    sent_at: datetime | None,
    offer: Offer,
    today: date,
) -> tuple[object, ...]:
    if queue_group == "action_required":
        if subkind == "prepared":
            return (_SUBKIND_ORDER[subkind], version.created_at, offer.offer_id)
        if subkind == "sent":
            sent_boundary = sent_at or version.created_at
            return (
                _SUBKIND_ORDER[subkind],
                version.valid_until,
                sent_boundary,
                offer.offer_id,
            )
        if subkind in ("accepted", "accepted_contact_blocked"):
            accepted_at = (
                offer.acceptance_evidence.accepted_at
                if offer.acceptance_evidence is not None
                else version.created_at
            )
            return (_SUBKIND_ORDER[subkind], accepted_at, offer.offer_id)
    if queue_group == "overdue":
        days_overdue = today - version.valid_until
        return (days_overdue.days * -1, version.valid_until, offer.offer_id)
    last_event = _last_event_at(offer, version.offer_version_id)
    return (last_event, offer.offer_id)


def _last_event_at(offer: Offer, offer_version_id: str) -> datetime:
    if offer.conversion_link is not None:
        if offer.conversion_link.offer_version_id == offer_version_id:
            return offer.conversion_link.created_at
    if offer.acceptance_evidence is not None:
        if offer.acceptance_evidence.accepted_offer_version_id == offer_version_id:
            return offer.acceptance_evidence.accepted_at
    for rejection in offer.rejection_evidence:
        if rejection.offer_version_id == offer_version_id:
            return rejection.rejected_at
    for withdrawal in offer.withdrawal_evidence:
        if withdrawal.offer_version_id == offer_version_id:
            return withdrawal.withdrawn_at
    for sent in offer.sent_evidence:
        if sent.offer_version_id == offer_version_id:
            return sent.sent_at
    for version in offer.versions:
        if version.offer_version_id == offer_version_id:
            return version.created_at
    return offer.created_at

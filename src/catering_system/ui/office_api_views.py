"""Read-model serialization for the Core Office API
(PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §4.1–§4.2).

Pure functions: domain objects in, JSON-ready dicts out. Field sets, list
caps, orderings, next-action resolution and search semantics are the frozen
contract and must reproduce the current office panel exactly (§3.10 —
identical behavior is a contract requirement, verified by the dashboard
parity tests).
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from catering_system.domain.contact_projection import ContactProjection
from catering_system.domain.inquiry_contact_completeness import (
    derive_inquiry_contact_completeness,
    missing_contact_fields,
)
from catering_system.domain.inquiry_customer_snapshot import (
    customer_snapshot_to_mapping,
)
from catering_system.domain.email_intake_projection import EmailIntakeProjection
from catering_system.domain.inquiry import (
    Inquiry,
    InquiryOfferProjection,
    InquiryOfficeState,
    derive_inquiry_offer_projection,
    derive_inquiry_office_state,
)
from catering_system.domain.calendar_entry_projection import (
    CALENDAR_ENTRY_KIND_LABELS,
    CalendarEntryProjection,
)
from catering_system.domain.task_projection import TaskProjection
from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferState,
    derive_offer_state,
)
from catering_system.services.order_print_projection_service import (
    OrderPrintProjection,
    PrintPositionLine,
)
from catering_system.services.buffet_cards_service import BuffetCard, BuffetCardsView
from catering_system.domain.catalog import allergen_labels
from catering_system.services.catalog_dish_service import (
    AllergenCodeDefinition,
    CatalogDishListResult,
)
from catering_system.domain.catalog import CatalogDish, CatalogPriceHistoryEntry
from catering_system.domain.order import (
    Order,
    OrderVersion,
    is_order_version_superseded,
)
from catering_system.domain.order_operational_pause import (
    OrderOperationalPauseEvent,
    derive_operational_pause_projection,
)
from catering_system.domain.order_payment_reminder import PaymentReminderView
from catering_system.domain.ready_to_send import ReadyToSendEvaluation
from catering_system.domain.wochenuebersicht import Wochenuebersicht
from catering_system.domain.work_center import WorkCenterSnapshot
from catering_system.services.order_confirmation_document_preview import (
    OrderConfirmationDocumentPreview,
    preview_to_json,
)
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentEligibility,
    OrderConfirmationDocumentSummary,
)
from catering_system.ui.office_panel_offer_prefill import offer_prefill_payload


BERLIN = ZoneInfo("Europe/Berlin")

LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 100  # round-3: makes the 512 KiB bound constructive
DETAIL_ORDERS_CAP = 50
DETAIL_VERSIONS_CAP = 200
WEEK_ENTRIES_CAP = 100
TOP_ROWS_CAP = 5  # the dashboard's own cap


def berlin_today() -> date:
    return datetime.now(BERLIN).date()


OFFER_STATE_LABELS: dict[OfferState, str] = {
    "Prepared": "Vorbereitet",
    "Sent": "Gesendet",
    "Accepted": "Angenommen",
    "Converted": "Auftrag erstellt",
    "Expired": "Abgelaufen",
    "Withdrawn": "Zurückgezogen",
    "Rejected": "Abgelehnt",
    "Superseded": "Ersetzt",
}


def offer_state_label(state: OfferState) -> str:
    return OFFER_STATE_LABELS[state]


def _offer_version(offer: Offer, offer_version_id: str):
    for version in offer.versions:
        if version.offer_version_id == offer_version_id:
            return version
    raise ValueError(f"unknown offer_version_id={offer_version_id!r}")


def offer_list_row(
    offer: Offer, inquiry: Inquiry, *, today: date | None = None
) -> dict[str, object]:
    projection = derive_inquiry_offer_projection(offer, today=today or berlin_today())
    version = _offer_version(offer, projection.offer_version_id)
    return {
        "offer_id": offer.offer_id,
        "inquiry_id": offer.source_inquiry_id,
        "state": projection.commercial_state,
        "event_date": version.event_date.isoformat(),
        "valid_until": version.valid_until.isoformat(),
    }


def offer_list_view(
    offers: list[Offer],
    inquiries_by_id: dict[str, Inquiry],
    *,
    today: date | None = None,
) -> list[dict[str, object]]:
    operating_today = today or berlin_today()
    rows: list[dict[str, object]] = []
    for offer in offers:
        inquiry = inquiries_by_id.get(offer.source_inquiry_id)
        if inquiry is None:
            continue
        rows.append(offer_list_row(offer, inquiry, today=operating_today))
    rows.sort(key=lambda row: (str(row["event_date"]), str(row["offer_id"])))
    return rows


def _surface_sent_evidence(
    offer: Offer, offer_version_id: str
) -> dict[str, object] | None:
    for item in offer.sent_evidence:
        if item.offer_version_id == offer_version_id:
            return {
                "sent_at": item.sent_at.isoformat(),
                "channel": item.channel,
            }
    return None


def _acceptance_shape(acceptance: object | None) -> dict[str, object] | None:
    if acceptance is None:
        return None
    from catering_system.domain.offer import AcceptanceEvidence

    if not isinstance(acceptance, AcceptanceEvidence):
        return None
    return {
        "accepted_at": acceptance.accepted_at.isoformat(),
        "channel": acceptance.channel,
        "accepted_variant_id": acceptance.accepted_variant_id,
    }


def _offer_history(offer: Offer) -> list[dict[str, object]]:
    entries: list[tuple[datetime, str]] = []
    for version in sorted(offer.versions, key=lambda item: item.version_number):
        label = (
            "Angebot erstellt" if version.version_number == 1 else "Angebot vorbereitet"
        )
        entries.append((version.created_at, label))
    for sent in offer.sent_evidence:
        entries.append((sent.sent_at, "Angebot gesendet"))
    for rejection in offer.rejection_evidence:
        entries.append((rejection.rejected_at, "Angebot abgelehnt"))
    for withdrawal in offer.withdrawal_evidence:
        entries.append((withdrawal.withdrawn_at, "Angebot zurückgezogen"))
    if offer.acceptance_evidence is not None:
        entries.append((offer.acceptance_evidence.accepted_at, "Angebot angenommen"))
    if offer.conversion_link is not None:
        entries.append((offer.conversion_link.created_at, "In Auftrag umgewandelt"))
    entries.sort(key=lambda item: item[0])
    return [{"at": at.isoformat(), "label": label} for at, label in entries]


def _position_detail(position: OfferPosition) -> dict[str, object]:
    row: dict[str, object] = {
        "position_id": position.position_id,
        "kind": position.kind,
        "name": position.name,
        "unit_net_cents": position.unit_net_cents,
        "net_total_cents": position.net_total_cents,
        "catalog_item_id": position.catalog_item_id,
        "description": position.description,
        "composition": position.composition,
    }
    if position.allergens is None:
        row["allergens"] = None
        row["allergen_labels"] = None
        row["allergens_unknown"] = True
    else:
        row["allergens"] = list(position.allergens)
        row["allergen_labels"] = list(allergen_labels(position.allergens))
        row["allergens_unknown"] = False
    return row


def offer_detail(offer: Offer, *, today: date | None = None) -> dict[str, object]:
    operating_today = today or berlin_today()
    projection = derive_inquiry_offer_projection(offer, today=operating_today)
    versions = sorted(offer.versions, key=lambda item: item.version_number)
    detail: dict[str, object] = {
        "offer_id": offer.offer_id,
        "inquiry_id": offer.source_inquiry_id,
        "offer_version_id": projection.offer_version_id,
        "commercial_state": projection.commercial_state,
        "acceptance_id": projection.acceptance_id,
        "versions": [
            {
                "version": version.version_number,
                "state": derive_offer_state(
                    offer, version.offer_version_id, today=operating_today
                ),
                "event_date": version.event_date.isoformat(),
                "valid_until": version.valid_until.isoformat(),
                "time_window_text": version.time_window_text,
                "location_text": version.location_text,
                "guest_count": version.guest_count,
                "planning_mode": version.planning_mode,
                "variants": [
                    {
                        "variant_id": variant.variant_id,
                        "name": variant.label,
                        "positions": [
                            _position_detail(position) for position in variant.positions
                        ],
                    }
                    for variant in version.variants
                ],
            }
            for version in versions
        ],
        "sent_evidence": _surface_sent_evidence(offer, projection.offer_version_id),
        "acceptance": _acceptance_shape(offer.acceptance_evidence),
        "history": _offer_history(offer),
    }
    if offer.conversion_link is not None:
        detail["order_id"] = offer.conversion_link.order_id
    return detail


# --- shared shapes -----------------------------------------------------------


def inquiry_summary(inquiry: Inquiry) -> dict[str, object]:
    return {
        "inquiry_id": inquiry.inquiry_id,
        "event_date": inquiry.event_date.isoformat(),
        "created_at": inquiry.created_at.isoformat(),
        "updated_at": inquiry.updated_at.isoformat(),
        "inquiry_source": inquiry.inquiry_source,
        "crm_stage": inquiry.crm_stage,
        "time_window_text": inquiry.time_window_text,
        "location_text": inquiry.location_text,
        "guest_count_estimate": inquiry.guest_count_estimate,
        "planning_mode": inquiry.planning_mode,
        "call_verification_required": inquiry.call_verification_required,
        "call_verification_status": inquiry.call_verification_status,
    }


def inquiry_list_row(inquiry: Inquiry, orders: list[Order]) -> dict[str, object]:
    """§4.1 round-3: the list page needs only the single active order's id."""
    active = [o for o in orders if o.cancelled_at is None]
    row = inquiry_summary(inquiry)
    row["intake_subject"] = inquiry.intake_subject
    row["linked_order_id"] = active[0].order_id if active else None
    row["orders_total_count"] = len(orders)
    # INQUIRY_CONTACT_COMPLETENESS_V1 §9/§10: the remote panel's list badge
    # must derive from the same structured snapshot as direct mode.
    row["customer_snapshot"] = customer_snapshot_to_mapping(inquiry.customer_snapshot)
    return row


def inquiry_offer_projection_shape(
    projection: InquiryOfferProjection,
) -> dict[str, object]:
    row: dict[str, object] = {
        "offer_id": projection.offer_id,
        "offer_version_id": projection.offer_version_id,
        "commercial_state": projection.commercial_state,
    }
    if projection.accepted_variant_id is not None:
        row["accepted_variant_id"] = projection.accepted_variant_id
    if projection.acceptance_id is not None:
        row["acceptance_id"] = projection.acceptance_id
    return row


def inquiry_office_state(
    inquiry: Inquiry,
    orders: list[Order],
    *,
    offer: Offer | None = None,
    today: date | None = None,
) -> InquiryOfficeState:
    return derive_inquiry_office_state(
        inquiry,
        has_order=bool(orders),
        has_active_order=any(order.cancelled_at is None for order in orders),
        offer=offer,
        today=today or berlin_today(),
    )


def inquiry_detail(
    inquiry: Inquiry,
    orders: list[Order],
    *,
    offer: Offer | None = None,
    today: date | None = None,
) -> dict[str, object]:
    detail = inquiry_list_row(inquiry, orders)
    detail["customer_linkage"] = dict(inquiry.customer_linkage)
    detail["customer_id"] = inquiry.customer_id
    detail["customer_snapshot"] = customer_snapshot_to_mapping(
        inquiry.customer_snapshot
    )
    completeness = derive_inquiry_contact_completeness(inquiry)
    detail["contact_completeness"] = completeness
    detail["missing_contact_fields"] = list(missing_contact_fields(completeness))
    detail["contact_completion_allowed"] = completeness != "complete"
    detail["intake_message"] = inquiry.intake_message
    detail["intake_summary"] = inquiry.intake_summary
    detail["intake_external_ref"] = inquiry.intake_external_ref
    state = inquiry_office_state(inquiry, orders, offer=offer, today=today)
    detail["allows_conversion"] = False
    detail["next_action"] = state.next_action
    if state.offer is not None:
        detail["offer"] = inquiry_offer_projection_shape(state.offer)
    detail["orders"] = [
        {
            "order_id": o.order_id,
            "cancelled_at": (
                o.cancelled_at.isoformat() if o.cancelled_at is not None else None
            ),
        }
        for o in orders[:DETAIL_ORDERS_CAP]
    ]
    detail["orders_truncated"] = len(orders) > DETAIL_ORDERS_CAP
    detail["offer_prefill"] = offer_prefill_payload(inquiry)
    return detail


def operational_pause_projection(
    events: tuple[OrderOperationalPauseEvent, ...],
) -> dict[str, object]:
    return derive_operational_pause_projection(events)


def operational_pause_projection_from_active(
    active: OrderOperationalPauseEvent | None,
    *,
    latest_pause_event_id: str | None = None,
) -> dict[str, object]:
    """Legacy helper when only the active pause event is available."""
    if active is None:
        return {
            "active": False,
            "latest_pause_event_id": latest_pause_event_id,
        }
    return {
        "active": True,
        "current_pause_event_id": active.pause_event_id,
        "latest_pause_event_id": latest_pause_event_id or active.pause_event_id,
        "reason_code": active.reason_code,
        "note": active.note,
        "paused_at": active.occurred_at.isoformat(),
        "actor_reference": active.actor_reference,
    }


def order_summary(order: Order) -> dict[str, object]:
    return {
        "order_id": order.order_id,
        "source_inquiry_id": order.source_inquiry_id,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "candidate_order_version_id": order.candidate_order_version_id,
        "effective_order_version_id": order.effective_order_version_id,
        "cancelled_at": (
            order.cancelled_at.isoformat() if order.cancelled_at is not None else None
        ),
    }


def resolve_next_action(
    order: Order, versions: list[OrderVersion]
) -> dict[str, str] | None:
    """Exactly the panel's `_next_step_action` rule (§1.2): target version =
    candidate if it names a real owned version, else the highest
    version_number; print-confirm before effective; null when cancelled,
    versionless, or nothing to do."""
    if order.cancelled_at is not None or not versions:
        return None
    target = next(
        (v for v in versions if v.order_version_id == order.candidate_order_version_id),
        None,
    )
    if target is None:
        target = max(versions, key=lambda v: v.version_number)
    if target.kitchen_print_confirmed_at is None:
        return {"action": "print-confirm", "order_version_id": target.order_version_id}
    if target.order_version_id != order.effective_order_version_id:
        return {"action": "effective", "order_version_id": target.order_version_id}
    return None


def order_list_row(
    order: Order,
    versions: list[OrderVersion],
    evaluation: ReadyToSendEvaluation,
    *,
    active_pause: OrderOperationalPauseEvent | None = None,
) -> dict[str, object]:
    row = order_summary(order)
    row["ready"] = evaluation.ready
    row["blocker_reason"] = evaluation.reasons[0] if evaluation.reasons else None
    row["next_action"] = resolve_next_action(order, versions)
    row["operational_pause_active"] = active_pause is not None
    return row


def order_version_shape(
    version: OrderVersion, *, superseded: bool = False
) -> dict[str, object]:
    return {
        "order_version_id": version.order_version_id,
        "order_id": version.order_id,
        "version_number": version.version_number,
        "created_at": version.created_at.isoformat(),
        "event_date": version.event_date.isoformat(),
        "time_window_text": version.time_window_text,
        "location_text": version.location_text,
        "guest_count_estimate": version.guest_count_estimate,
        "planning_mode": version.planning_mode,
        "kitchen_print_confirmed_at": (
            version.kitchen_print_confirmed_at.isoformat()
            if version.kitchen_print_confirmed_at is not None
            else None
        ),
        "parent_order_version_id": version.parent_order_version_id,
        "created_by": version.created_by,
        "change_reason": version.change_reason,
        "changed_fields": list(version.changed_fields),
        "superseded": superseded,
    }


def order_detail(
    order: Order,
    versions: list[OrderVersion],
    evaluation: ReadyToSendEvaluation,
    payment_reminder: PaymentReminderView | None = None,
    confirmation_document: OrderConfirmationDocumentEligibility | None = None,
    *,
    pause_projection: dict[str, object] | None = None,
    active_pause: OrderOperationalPauseEvent | None = None,
) -> dict[str, object]:
    detail = order_summary(order)
    detail["ready_to_send"] = {
        "ready": evaluation.ready,
        "reasons": list(evaluation.reasons),
    }
    candidate = next(
        (
            version
            for version in versions
            if version.order_version_id == order.candidate_order_version_id
        ),
        None,
    )
    detail["version_change"] = {
        "pending": candidate is not None,
        "reason": candidate.change_reason if candidate is not None else None,
        "changed_fields": (
            list(candidate.changed_fields) if candidate is not None else []
        ),
        "kitchen_reprint_required": (
            candidate is not None
            and candidate.kitchen_print_confirmed_at is None
            and candidate.order_version_id != order.effective_order_version_id
        ),
    }
    if pause_projection is not None:
        detail["operational_pause"] = pause_projection
    else:
        detail["operational_pause"] = operational_pause_projection_from_active(
            active_pause
        )
    ordered = sorted(versions, key=lambda v: v.version_number)
    detail["versions"] = [
        order_version_shape(
            version,
            superseded=is_order_version_superseded(order, version, versions),
        )
        for version in ordered[:DETAIL_VERSIONS_CAP]
    ]
    detail["versions_total_count"] = len(versions)
    detail["versions_truncated"] = len(versions) > DETAIL_VERSIONS_CAP
    if payment_reminder is not None:
        detail["payment_reminder"] = payment_reminder_shape(payment_reminder)
    if confirmation_document is not None:
        detail["confirmation_document"] = confirmation_document_shape(
            confirmation_document
        )
    return detail


def confirmation_document_shape(
    eligibility: OrderConfirmationDocumentEligibility,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "state": eligibility.state,
        "available": eligibility.available,
        "can_prepare": eligibility.can_prepare,
        "blocker_code": eligibility.blocker_code,
        "snapshot": (
            confirmation_document_summary_shape(eligibility.snapshot)
            if eligibility.snapshot is not None
            else None
        ),
    }
    return payload


def confirmation_document_summary_shape(
    summary: OrderConfirmationDocumentSummary,
) -> dict[str, object]:
    return {
        "document_snapshot_id": summary.document_snapshot_id,
        "order_id": summary.order_id,
        "order_version_id": summary.order_version_id,
        "document_reference": summary.document_reference,
        "created_at": summary.created_at.isoformat(),
        "created_by": summary.created_by,
        "recipient_status": summary.recipient_status,
        "recipient_email_masked": summary.recipient_email_masked,
        "document_hash_short": summary.document_hash_short,
        "net_total_cents": summary.net_total_cents,
        "vat_total_cents": summary.vat_total_cents,
        "gross_total_cents": summary.gross_total_cents,
        "effective_version_number": summary.effective_version_number,
    }


def confirmation_document_preview_shape(
    preview: OrderConfirmationDocumentPreview,
) -> dict[str, object]:
    return preview_to_json(preview)


def payment_reminder_shape(view: PaymentReminderView) -> dict[str, object]:
    return {
        "order_id": view.order_id,
        "payment_method": view.payment_method,
        "payment_method_label": view.payment_method_label,
        "invoice_created": view.invoice_created,
        "invoice_number": view.invoice_number,
        "sent_on": view.sent_on.isoformat() if view.sent_on else None,
        "due_on": view.due_on.isoformat() if view.due_on else None,
        "paid_on": view.paid_on.isoformat() if view.paid_on else None,
        "cash_received": view.cash_received,
        "invoice_state_label": view.invoice_state_label,
        "payment_state_label": view.payment_state_label,
        "next_step": view.next_step,
        "updated_at": view.updated_at.isoformat() if view.updated_at else None,
    }


# --- search (fixed semantics, matching the panel's `_matches`) ---------------


def inquiry_matches(inquiry: Inquiry, needle: str) -> bool:
    if not needle:
        return True
    needle = needle.lower()
    fields = (
        inquiry.inquiry_id,
        inquiry.location_text,
        inquiry.event_date.isoformat(),
        inquiry.crm_stage,
        inquiry.inquiry_source,
        inquiry.intake_subject or "",
    )
    return any(needle in field.lower() for field in fields)


def order_matches(order: Order, needle: str) -> bool:
    if not needle:
        return True
    needle = needle.lower()
    return needle in order.order_id.lower() or needle in order.source_inquiry_id.lower()


# --- queue view (dashboard parity, §1.2/§4.1) --------------------------------


def week_view(week: Wochenuebersicht) -> dict[str, object]:
    entries = [
        {
            "order_id": e.order_id,
            "event_date": e.event_date.isoformat(),
            "time_window_text": e.time_window_text,
            "location_text": e.location_text,
            "guest_count_estimate": e.guest_count_estimate,
        }
        for e in week.entries[:WEEK_ENTRIES_CAP]
    ]
    return {
        "iso_year": week.iso_year,
        "iso_week": week.iso_week,
        "entries": entries,
        "total_count": len(week.entries),
        "truncated": len(week.entries) > WEEK_ENTRIES_CAP,
    }


def inquiry_top_row(inquiry: Inquiry, state: InquiryOfficeState) -> dict[str, object]:
    row = inquiry_summary(inquiry)
    if state.next_action is None:
        raise ValueError("open inquiry top row requires a next action")
    row["next_action"] = state.next_action
    if state.offer is not None:
        row["offer"] = inquiry_offer_projection_shape(state.offer)
    return row


def order_top_row(
    order: Order,
    versions: list[OrderVersion],
    evaluation: ReadyToSendEvaluation,
    *,
    active_pause: OrderOperationalPauseEvent | None = None,
) -> dict[str, object]:
    row = order_summary(order)
    row["blocker_reason"] = evaluation.reasons[0] if evaluation.reasons else None
    row["next_action"] = resolve_next_action(order, versions)
    row["operational_pause_active"] = active_pause is not None
    if active_pause is not None:
        row["operational_pause_reason_code"] = active_pause.reason_code
    return row


def work_center_snapshot(snapshot: WorkCenterSnapshot) -> dict[str, object]:
    return {
        "rueckrufe_open": snapshot.rueckrufe_open,
        "missed_calls_open": snapshot.missed_calls_open,
        "offers_waiting": snapshot.offers_waiting,
        "offers_accepted": snapshot.offers_accepted,
        "upcoming_orders": snapshot.upcoming_orders,
        "open_tasks": snapshot.open_tasks,
        "today_calendar_entries": snapshot.today_calendar_entries,
        "pending_order_changes": snapshot.pending_order_changes,
    }


def contact_list_row(projection: ContactProjection) -> dict[str, object]:
    return {
        "contact_key": projection.contact_key,
        "identity_source": projection.identity_source,
        "display_name": projection.display_name,
        "email": projection.email,
        "phone": projection.phone,
        "inquiry_count": projection.inquiry_count,
        "open_inquiries": projection.open_inquiries,
        "active_orders": projection.active_orders,
        "linked_order_count": projection.linked_order_count,
        "contact_status": projection.contact_status,
        "last_activity": projection.last_activity.isoformat(),
    }


def contact_list_view(projections: list[ContactProjection]) -> list[dict[str, object]]:
    return [contact_list_row(projection) for projection in projections]


def contact_detail_view(
    projection: ContactProjection,
    inquiries: list[Inquiry],
    offers: list[Offer],
    orders: list[Order],
    *,
    today: date | None = None,
) -> dict[str, object]:
    operating_today = today or berlin_today()
    orders_by_inquiry: dict[str, list[Order]] = {}
    for order in orders:
        orders_by_inquiry.setdefault(order.source_inquiry_id, []).append(order)
    offers_by_inquiry = {offer.source_inquiry_id: offer for offer in offers}
    inquiry_rows: list[dict[str, object]] = []
    for inquiry in inquiries:
        linked = orders_by_inquiry.get(inquiry.inquiry_id, [])
        offer = offers_by_inquiry.get(inquiry.inquiry_id)
        state = inquiry_office_state(
            inquiry,
            linked,
            offer=offer,
            today=operating_today,
        )
        inquiry_rows.append(
            {
                "inquiry_id": inquiry.inquiry_id,
                "intake_subject": inquiry.intake_subject,
                "event_date": inquiry.event_date.isoformat(),
                "crm_stage": inquiry.crm_stage,
                "is_open": state.is_open,
            }
        )
    offer_rows = [
        {
            "offer_id": offer.offer_id,
            "inquiry_id": offer.source_inquiry_id,
            "state": derive_inquiry_offer_projection(
                offer, today=operating_today
            ).commercial_state,
        }
        for offer in offers
    ]
    order_rows = [
        {
            "order_id": order.order_id,
            "inquiry_id": order.source_inquiry_id,
            "cancelled_at": (
                order.cancelled_at.isoformat()
                if order.cancelled_at is not None
                else None
            ),
        }
        for order in orders
    ]
    detail = contact_list_row(projection)
    detail["inquiry_ids"] = list(projection.inquiry_ids)
    detail["inquiries"] = inquiry_rows
    detail["offers"] = offer_rows
    detail["orders"] = order_rows
    return detail


def email_list_row(projection: EmailIntakeProjection) -> dict[str, object]:
    return {
        "email_id": projection.email_id,
        "inquiry_id": projection.inquiry_id,
        "contact_key": projection.contact_key,
        "sender_name": projection.sender_name,
        "sender_email": projection.sender_email,
        "subject": projection.subject,
        "preview": projection.preview,
        "crm_stage": projection.crm_stage,
        "received_at": projection.received_at.isoformat(),
        "external_ref": projection.external_ref,
        "linked_offer_id": projection.linked_offer_id,
        "linked_order_ids": list(projection.linked_order_ids),
    }


def email_list_view(
    projections: list[EmailIntakeProjection],
) -> list[dict[str, object]]:
    return [email_list_row(projection) for projection in projections]


def email_detail_view(projection: EmailIntakeProjection) -> dict[str, object]:
    return email_list_row(projection)


def task_list_row(projection: TaskProjection) -> dict[str, object]:
    return {
        "task_id": projection.task_id,
        "category": projection.category,
        "title": projection.title,
        "subtitle": projection.subtitle,
        "entity_type": projection.entity_type,
        "entity_id": projection.entity_id,
        "action_label": projection.action_label,
        "action_href": projection.action_href,
        "due_at": (
            projection.due_at.isoformat() if projection.due_at is not None else None
        ),
        "urgency": projection.urgency,
        "opened_at": projection.opened_at.isoformat(),
    }


def task_list_view(projections: list[TaskProjection]) -> list[dict[str, object]]:
    return [task_list_row(projection) for projection in projections]


def calendar_list_row(projection: CalendarEntryProjection) -> dict[str, object]:
    return {
        "entry_id": projection.entry_id,
        "entry_kind": projection.entry_kind,
        "status_label": CALENDAR_ENTRY_KIND_LABELS[projection.entry_kind],
        "title": projection.title,
        "event_date": projection.event_date.isoformat(),
        "time_window_text": projection.time_window_text,
        "location_text": projection.location_text,
        "guest_count_estimate": projection.guest_count_estimate,
        "entity_type": projection.entity_type,
        "entity_id": projection.entity_id,
        "action_label": projection.action_label,
        "action_href": projection.action_href,
        "source_inquiry_id": projection.source_inquiry_id,
    }


def calendar_list_view(
    projections: list[CalendarEntryProjection],
) -> list[dict[str, object]]:
    return [calendar_list_row(projection) for projection in projections]


def _print_position_line_shape(line: PrintPositionLine) -> dict[str, object]:
    return {
        "position_id": line.position_id,
        "kind": line.kind,
        "name": line.name,
        "description": line.description,
        "composition": line.composition,
        "notes": line.notes,
        "quantity_display": line.quantity_display,
        "unit_label": line.unit_label,
    }


def order_print_projection_shape(projection: OrderPrintProjection) -> dict[str, object]:
    event = projection.event
    commercial = projection.commercial
    flags = projection.flags
    return {
        "event": {
            "order_id": event.order_id,
            "order_version_id": event.order_version_id,
            "version_number": event.version_number,
            "event_date": event.event_date.isoformat(),
            "time_window_text": event.time_window_text,
            "location_text": event.location_text,
            "guest_count_estimate": event.guest_count_estimate,
            "planning_mode": event.planning_mode,
            "kitchen_print_confirmed_at": (
                event.kitchen_print_confirmed_at.isoformat()
                if event.kitchen_print_confirmed_at is not None
                else None
            ),
            "order_cancelled_at": (
                event.order_cancelled_at.isoformat()
                if event.order_cancelled_at is not None
                else None
            ),
            "is_candidate": event.is_candidate,
            "is_effective": event.is_effective,
            "change_reason": event.change_reason,
            "changed_fields": list(event.changed_fields),
        },
        "commercial": {
            "source": commercial.source,
            "offer_id": commercial.offer_id,
            "offer_version_id": commercial.offer_version_id,
            "accepted_variant_id": commercial.accepted_variant_id,
            "variant_label": commercial.variant_label,
            "positions": [
                _print_position_line_shape(line) for line in commercial.positions
            ],
        },
        "flags": {
            "intent": flags.intent,
            "is_preview": flags.is_preview,
            "is_final_allowed": flags.is_final_allowed,
            "is_stale": flags.is_stale,
            "watermark": flags.watermark,
        },
    }


def buffet_card_shape(card: BuffetCard) -> dict[str, object]:
    return {
        "position_id": card.position_id,
        "name": card.name,
        "description": card.description,
        "composition": card.composition,
        "notes": card.notes,
    }


def buffet_cards_data_shape(view: BuffetCardsView) -> dict[str, object]:
    return {
        "projection": order_print_projection_shape(view.projection),
        "cards": [buffet_card_shape(card) for card in view.cards],
        "effective_version_number": view.effective_version_number,
    }


def format_catalog_price_eur(cents: int) -> str:
    whole, fraction = divmod(cents, 100)
    return f"{whole},{fraction:02d} €"


def catalog_price_input_value(cents: int) -> str:
    whole, fraction = divmod(cents, 100)
    return f"{whole},{fraction:02d}"


def parse_catalog_price_cents(raw: str) -> int:
    text = raw.strip().replace(",", ".")
    if text.endswith("€"):
        text = text[:-1].strip()
    if not text:
        raise ValueError("price is required")
    if "." in text:
        from decimal import Decimal, InvalidOperation

        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError("invalid price") from exc
        return int((value * 100).quantize(Decimal("1")))
    return int(text)


def catalog_dish_list_row(dish: CatalogDish) -> dict[str, object]:
    return {
        "dish_id": dish.dish_id,
        "name": dish.name,
        "current_unit_net_cents": dish.current_unit_net_cents,
        "price_display": format_catalog_price_eur(dish.current_unit_net_cents),
        "allergens": list(dish.allergens),
        "allergen_labels": list(allergen_labels(dish.allergens)),
        "active": dish.active,
    }


def catalog_dish_list_view(result: CatalogDishListResult) -> dict[str, object]:
    return {
        "dishes": [catalog_dish_list_row(dish) for dish in result.dishes],
        "total_count": result.total_count,
        "truncated": result.truncated,
    }


def _price_history_shape(entry: CatalogPriceHistoryEntry) -> dict[str, object]:
    old_cents = entry.old_unit_net_cents
    return {
        "entry_id": entry.entry_id,
        "dish_id": entry.dish_id,
        "old_unit_net_cents": old_cents,
        "new_unit_net_cents": entry.new_unit_net_cents,
        "old_price_display": (
            format_catalog_price_eur(old_cents) if old_cents is not None else None
        ),
        "new_price_display": format_catalog_price_eur(entry.new_unit_net_cents),
        "changed_at": entry.changed_at.isoformat(),
        "changed_by": entry.changed_by,
        "effective_from": (
            entry.effective_from.isoformat()
            if entry.effective_from is not None
            else None
        ),
    }


def catalog_dish_detail_view(
    dish: CatalogDish,
    history: tuple[CatalogPriceHistoryEntry, ...],
) -> dict[str, object]:
    detail = catalog_dish_list_row(dish)
    detail.update(
        {
            "description": dish.description,
            "composition": dish.composition,
            "notes": dish.notes,
            "created_at": dish.created_at.isoformat(),
            "updated_at": dish.updated_at.isoformat(),
            "price_history": [_price_history_shape(entry) for entry in history],
        }
    )
    return detail


def allergen_codes_view(
    definitions: tuple[AllergenCodeDefinition, ...],
) -> dict[str, object]:
    return {
        "allergen_codes": [
            {"code": item.code, "label": item.label} for item in definitions
        ]
    }

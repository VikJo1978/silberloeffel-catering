"""Inquiry service — create_inquiry and update_inquiry only."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timezone
from typing import Any

from catering_system.domain.inquiry import (
    apply_inquiry_customer_reference,
    set_inquiry_fulfillment_mode,
    CallVerificationStatus,
    CrmStage,
    CustomerLinkage,
    FulfillmentMode,
    Inquiry,
    InquirySource,
    PlanningMode,
    validate_call_verification_status,
    validate_crm_stage,
    validate_customer_linkage,
    validate_fulfillment_mode,
    validate_planning_mode,
)
from catering_system.domain.slice_a_events import (
    CustomerCallVerified,
    InquiryCreated,
    InquiryUpdated,
)
from catering_system.domain.inquiry_contact_completeness import (
    complete_inquiry_contact_information,
    derive_contact_completeness,
)
from catering_system.domain.inquiry_customer_snapshot import (
    DeliveryAddressMode,
    InquiryCustomerSnapshot,
    set_inquiry_customer_addresses,
    snapshot_from_structured_contact,
)
from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.logistics_timing import validate_optional_local_time
from catering_system.repositories.inquiry_repository import InquiryRepository

_ALLOWED_SOURCES: frozenset[str] = frozenset(
    {
        "wix_form",
        "phone",
        "manual",
        "phone_by_office",
        "missed_call",
        "ai_telefonist",
        "website_form",
        "configurator",
        "email",
    }
)

_UNSET = object()

# Public customer-facing channels must arrive contact-complete
# (INQUIRY_CONTACT_COMPLETENESS_V1 §5). Enforced here in the canonical
# service layer so no entry point can bypass the rule with the same
# inquiry_source.
_CONTACT_COMPLETE_REQUIRED_SOURCES: frozenset[str] = frozenset(
    {"website_form", "configurator"}
)

_log = logging.getLogger(__name__)


def validate_inquiry_source(value: str) -> InquirySource:
    if value not in _ALLOWED_SOURCES:
        raise ValueError(
            f"inquiry_source must be one of {sorted(_ALLOWED_SOURCES)}, got {value!r}"
        )
    return value  # type: ignore[return-value]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_intake(value: str | None) -> str | None:
    """Trim; empty/whitespace-only becomes None (INQUIRY_INTAKE_CONTEXT_FIELDS
    _IMPLEMENTATION_PACK_V1 §3 — one consistent rule for all four intake fields)."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _normalize_intake_update(
    value: str | None | object, current: str | None
) -> str | None:
    if value is _UNSET:
        return current
    if value is not None and not isinstance(value, str):
        raise TypeError("intake context fields must be str, None, or omitted")
    return _normalize_intake(value)


class InquiryService:
    def __init__(
        self,
        repository: InquiryRepository,
        *,
        event_sink: Callable[[object], None] | None = None,
    ) -> None:
        self._repository = repository
        self._event_sink = event_sink

    def _emit(self, event: object) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def create_inquiry(
        self,
        *,
        event_date: date,
        inquiry_source: str,
        crm_stage: str,
        customer_linkage: dict[str, Any],
        time_window_text: str,
        location_text: str,
        guest_count_estimate: int | None,
        planning_mode: str,
        call_verification_required: bool,
        call_verification_status: str,
        intake_subject: str | None = None,
        intake_message: str | None = None,
        intake_summary: str | None = None,
        intake_external_ref: str | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
        contact_name: str | None = None,
        company_name: str | None = None,
        fulfillment_mode: str = "UNKNOWN",
        event_start_local: time | None = None,
        delivery_time_local: time | None = None,
    ) -> Inquiry:
        _log.info("create_inquiry called inquiry_source=%s", inquiry_source)
        intake_subject_norm = _normalize_intake(intake_subject)
        intake_message_norm = _normalize_intake(intake_message)
        try:
            src = validate_inquiry_source(inquiry_source)
            crm = validate_crm_stage(crm_stage)
            linkage = validate_customer_linkage(customer_linkage)
            pm = validate_planning_mode(planning_mode)
            cvs = validate_call_verification_status(call_verification_status)
            # FULFILLMENT_SOURCE_V1: structured, optional, never inferred —
            # every channel that omits it gets UNKNOWN (the default above).
            fm = validate_fulfillment_mode(fulfillment_mode)
            validate_optional_local_time(event_start_local, label="event_start_local")
            validate_optional_local_time(
                delivery_time_local, label="delivery_time_local"
            )
            customer_snapshot = snapshot_from_structured_contact(
                contact_email=contact_email,
                contact_phone=contact_phone,
                contact_name=contact_name,
                company_name=company_name,
                intake_message=intake_message_norm,
                intake_subject=intake_subject_norm,
            )
            if src in _CONTACT_COMPLETE_REQUIRED_SOURCES:
                completeness = derive_contact_completeness(customer_snapshot)
                if completeness != "complete":
                    raise ValueError(
                        f"{src} intake requires email and phone "
                        f"(contact_completeness={completeness})"
                    )
        except (ValueError, TypeError):
            _log.warning("create_inquiry validation failed")
            raise
        now = _utc_now()
        inquiry = Inquiry(
            inquiry_id=str(uuid.uuid4()),
            event_date=event_date,
            created_at=now,
            updated_at=now,
            inquiry_source=src,
            crm_stage=crm,
            customer_linkage=linkage,
            time_window_text=time_window_text,
            location_text=location_text,
            guest_count_estimate=guest_count_estimate,
            planning_mode=pm,
            call_verification_required=call_verification_required,
            call_verification_status=cvs,
            intake_subject=intake_subject_norm,
            intake_message=intake_message_norm,
            intake_summary=_normalize_intake(intake_summary),
            intake_external_ref=_normalize_intake(intake_external_ref),
            customer_id=None,
            customer_snapshot=customer_snapshot,
            fulfillment_mode=fm,
            event_start_local=event_start_local,
            delivery_time_local=delivery_time_local,
        )
        self._repository.save(inquiry)
        _log.info("inquiry created inquiry_id=%s", inquiry.inquiry_id)
        self._emit(InquiryCreated(inquiry_id=inquiry.inquiry_id))
        return inquiry

    def update_inquiry(
        self,
        inquiry_id: str,
        *,
        event_date: date | object = _UNSET,
        inquiry_source: str | object = _UNSET,
        crm_stage: str | object = _UNSET,
        customer_linkage: dict[str, Any] | object = _UNSET,
        time_window_text: str | object = _UNSET,
        location_text: str | object = _UNSET,
        guest_count_estimate: int | None | object = _UNSET,
        planning_mode: str | object = _UNSET,
        call_verification_required: bool | object = _UNSET,
        call_verification_status: str | object = _UNSET,
        intake_subject: str | None | object = _UNSET,
        intake_message: str | None | object = _UNSET,
        intake_summary: str | None | object = _UNSET,
        intake_external_ref: str | None | object = _UNSET,
        event_start_local: time | None | object = _UNSET,
        delivery_time_local: time | None | object = _UNSET,
    ) -> Inquiry:
        _log.info("update_inquiry called inquiry_id=%s", inquiry_id)
        current = self._repository.get_by_id(inquiry_id)
        if current is None:
            _log.warning(
                "update_inquiry failed: inquiry not found inquiry_id=%s", inquiry_id
            )
            raise ValueError(f"no inquiry with id {inquiry_id!r}")

        try:
            next_source: InquirySource = current.inquiry_source
            if inquiry_source is not _UNSET:
                next_source = validate_inquiry_source(inquiry_source)  # type: ignore[arg-type]

            next_crm: CrmStage = current.crm_stage
            if crm_stage is not _UNSET:
                next_crm = validate_crm_stage(crm_stage)  # type: ignore[arg-type]

            next_linkage: CustomerLinkage = current.customer_linkage
            if customer_linkage is not _UNSET:
                next_linkage = validate_customer_linkage(customer_linkage)  # type: ignore[arg-type]

            next_pm: PlanningMode = current.planning_mode
            if planning_mode is not _UNSET:
                next_pm = validate_planning_mode(planning_mode)  # type: ignore[arg-type]

            next_cvs: CallVerificationStatus = current.call_verification_status
            if call_verification_status is not _UNSET:
                next_cvs = validate_call_verification_status(
                    call_verification_status  # type: ignore[arg-type]
                )

            next_event_start = current.event_start_local
            if event_start_local is not _UNSET:
                next_event_start = event_start_local  # type: ignore[assignment]
                validate_optional_local_time(
                    next_event_start, label="event_start_local"
                )

            next_delivery_time = current.delivery_time_local
            if delivery_time_local is not _UNSET:
                next_delivery_time = delivery_time_local  # type: ignore[assignment]
                validate_optional_local_time(
                    next_delivery_time, label="delivery_time_local"
                )
        except (ValueError, TypeError):
            _log.warning("update_inquiry validation failed inquiry_id=%s", inquiry_id)
            raise

        updated = replace(
            current,
            event_date=event_date if event_date is not _UNSET else current.event_date,  # type: ignore[arg-type]
            updated_at=_utc_now(),
            inquiry_source=next_source,
            crm_stage=next_crm,
            customer_linkage=next_linkage,
            time_window_text=time_window_text
            if time_window_text is not _UNSET
            else current.time_window_text,  # type: ignore[arg-type]
            location_text=location_text
            if location_text is not _UNSET
            else current.location_text,  # type: ignore[arg-type]
            guest_count_estimate=guest_count_estimate
            if guest_count_estimate is not _UNSET
            else current.guest_count_estimate,  # type: ignore[arg-type]
            planning_mode=next_pm,
            call_verification_required=call_verification_required
            if call_verification_required is not _UNSET
            else current.call_verification_required,  # type: ignore[arg-type]
            call_verification_status=next_cvs,
            intake_subject=_normalize_intake_update(
                intake_subject, current.intake_subject
            ),
            intake_message=_normalize_intake_update(
                intake_message, current.intake_message
            ),
            intake_summary=_normalize_intake_update(
                intake_summary, current.intake_summary
            ),
            intake_external_ref=_normalize_intake_update(
                intake_external_ref, current.intake_external_ref
            ),
            customer_id=current.customer_id,
            customer_snapshot=current.customer_snapshot,
            event_start_local=next_event_start,
            delivery_time_local=next_delivery_time,
        )
        self._repository.update(updated)
        _log.info("inquiry updated inquiry_id=%s", inquiry_id)
        self._emit(InquiryUpdated(inquiry_id=inquiry_id))
        if (
            call_verification_status is not _UNSET
            and next_cvs == "verified"
            and current.call_verification_status != "verified"
        ):
            self._emit(CustomerCallVerified(inquiry_id=inquiry_id))
        return updated

    def verify_customer_by_call(self, inquiry_id: str) -> Inquiry:
        """Pack §6.1 — inquiry-level progression only; no order side effects."""
        return self.update_inquiry(
            inquiry_id,
            call_verification_status="verified",
        )

    def complete_inquiry_contact_information(
        self,
        inquiry_id: str,
        *,
        email: str | None = None,
        phone: str | None = None,
    ) -> Inquiry:
        """Append-only contact completion (INQUIRY_CONTACT_COMPLETENESS_V1 §4).

        Fills only missing snapshot email/phone; stored values never change.
        Identical resubmission is idempotent and does not touch updated_at.
        """
        _log.info(
            "complete_inquiry_contact_information called inquiry_id=%s", inquiry_id
        )
        current = self._repository.get_by_id(inquiry_id)
        if current is None:
            raise KeyError(inquiry_id)
        updated = complete_inquiry_contact_information(
            current, email=email, phone=phone
        )
        if updated.customer_snapshot == current.customer_snapshot:
            return current
        updated = replace(updated, updated_at=_utc_now())
        self._repository.update(updated)
        _log.info("inquiry contact information completed inquiry_id=%s", inquiry_id)
        self._emit(InquiryUpdated(inquiry_id=inquiry_id))
        return updated

    def set_inquiry_customer_addresses(
        self,
        inquiry_id: str,
        *,
        invoice_address: CustomerAddress | None,
        delivery_address: CustomerAddress | None,
        delivery_address_mode: DeliveryAddressMode | str,
    ) -> Inquiry:
        """Replace Rechnungs-/Lieferadresse on the inquiry snapshot (V1-B)."""
        _log.info("set_inquiry_customer_addresses called inquiry_id=%s", inquiry_id)
        current = self._repository.get_by_id(inquiry_id)
        if current is None:
            raise KeyError(inquiry_id)
        updated = set_inquiry_customer_addresses(
            current,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
            delivery_address_mode=delivery_address_mode,
        )
        if updated.customer_snapshot == current.customer_snapshot:
            return current
        updated = replace(updated, updated_at=_utc_now())
        self._repository.update(updated)
        _log.info("inquiry customer addresses updated inquiry_id=%s", inquiry_id)
        self._emit(InquiryUpdated(inquiry_id=inquiry_id))
        return updated

    def set_inquiry_fulfillment_mode(
        self, inquiry_id: str, *, fulfillment_mode: FulfillmentMode | str
    ) -> Inquiry:
        """Explicit Office write of Lieferung/Abholung (FULFILLMENT_SOURCE_V1).

        UNKNOWN/DELIVERY/PICKUP only; never inferred from address/text/
        payment. Same optimistic-locking contract as set_inquiry_customer_
        addresses (caller compares updated_at before calling).
        """
        _log.info("set_inquiry_fulfillment_mode called inquiry_id=%s", inquiry_id)
        current = self._repository.get_by_id(inquiry_id)
        if current is None:
            raise KeyError(inquiry_id)
        updated = set_inquiry_fulfillment_mode(current, fulfillment_mode)
        if updated.fulfillment_mode == current.fulfillment_mode:
            return current
        updated = replace(updated, updated_at=_utc_now())
        self._repository.update(updated)
        _log.info("inquiry fulfillment mode updated inquiry_id=%s", inquiry_id)
        self._emit(InquiryUpdated(inquiry_id=inquiry_id))
        return updated

    def assign_customer_reference(
        self, inquiry_id: str, *, customer_id: str, snapshot: InquiryCustomerSnapshot
    ) -> Inquiry:
        _log.info("assign_customer_reference called inquiry_id=%s", inquiry_id)
        current = self._repository.get_by_id(inquiry_id)
        if current is None:
            raise ValueError(f"no inquiry with id {inquiry_id!r}")
        updated = apply_inquiry_customer_reference(
            current, customer_id=customer_id, snapshot=snapshot
        )
        if (
            updated.customer_id == current.customer_id
            and updated.customer_snapshot == current.customer_snapshot
        ):
            return current
        updated = replace(updated, updated_at=_utc_now())
        self._repository.update(updated)
        self._emit(InquiryUpdated(inquiry_id=inquiry_id))
        return updated

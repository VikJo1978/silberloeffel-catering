"""Inquiry service — create_inquiry and update_inquiry only."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any

from catering_system.domain.inquiry import (
    CallVerificationStatus,
    CrmStage,
    CustomerLinkage,
    Inquiry,
    InquirySource,
    PlanningMode,
    validate_call_verification_status,
    validate_crm_stage,
    validate_customer_linkage,
    validate_planning_mode,
)
from catering_system.domain.slice_a_events import (
    CustomerCallVerified,
    InquiryCreated,
    InquiryUpdated,
)
from catering_system.repositories.inquiry_repository import InquiryRepository

_ALLOWED_SOURCES: frozenset[str] = frozenset({"wix_form", "email", "phone", "manual"})

_UNSET = object()

_log = logging.getLogger(__name__)


def validate_inquiry_source(value: str) -> InquirySource:
    if value not in _ALLOWED_SOURCES:
        raise ValueError(
            f"inquiry_source must be one of {sorted(_ALLOWED_SOURCES)}, got {value!r}"
        )
    return value  # type: ignore[return-value]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    ) -> Inquiry:
        _log.info("create_inquiry called inquiry_source=%s", inquiry_source)
        try:
            src = validate_inquiry_source(inquiry_source)
            crm = validate_crm_stage(crm_stage)
            linkage = validate_customer_linkage(customer_linkage)
            pm = validate_planning_mode(planning_mode)
            cvs = validate_call_verification_status(call_verification_status)
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
        except (ValueError, TypeError):
            _log.warning(
                "update_inquiry validation failed inquiry_id=%s", inquiry_id
            )
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
            location_text=location_text if location_text is not _UNSET else current.location_text,  # type: ignore[arg-type]
            guest_count_estimate=guest_count_estimate
            if guest_count_estimate is not _UNSET
            else current.guest_count_estimate,  # type: ignore[arg-type]
            planning_mode=next_pm,
            call_verification_required=call_verification_required
            if call_verification_required is not _UNSET
            else current.call_verification_required,  # type: ignore[arg-type]
            call_verification_status=next_cvs,
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

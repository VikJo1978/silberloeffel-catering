"""Phone channel → InquiryService.create_inquiry."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Mapping

from catering_system.domain.inquiry import CRM_PIPELINE, Inquiry, PLANNING_MODES
from catering_system.services.inquiry_service import InquiryService

_log = logging.getLogger(__name__)


def intake_from_phone(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    _log.info("phone adapter called")
    try:
        return _intake_from_phone_body(service, raw)
    except (ValueError, TypeError):
        _log.warning("phone adapter validation failed")
        raise


def _intake_from_phone_body(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    event_date = raw.get("event_date")
    if not isinstance(event_date, date):
        raise ValueError("phone intake: event_date (date) is required")

    if raw.get("time_window_text") is None:
        notes = raw.get("call_notes")
        time_window_text = "" if notes is None else str(notes)[:500]
    elif isinstance(raw.get("time_window_text"), str):
        time_window_text = raw["time_window_text"]
    else:
        raise TypeError("phone intake: time_window_text must be str or absent")

    if raw.get("location_text") is None:
        location_text = ""
    elif isinstance(raw.get("location_text"), str):
        location_text = raw["location_text"]
    else:
        raise TypeError("phone intake: location_text must be str or absent")

    guest_raw = raw.get("guest_count_estimate")
    if guest_raw is None:
        guest_count_estimate = None
    elif isinstance(guest_raw, int):
        guest_count_estimate = guest_raw
    else:
        raise TypeError("phone intake: guest_count_estimate must be int or absent")

    if raw.get("planning_mode") is None:
        planning_mode = PLANNING_MODES[0]
    elif isinstance(raw.get("planning_mode"), str):
        planning_mode = raw["planning_mode"]
    else:
        raise TypeError("phone intake: planning_mode must be str or absent")

    if raw.get("customer_linkage") is None:
        customer_linkage: dict[str, Any] = {}
    elif isinstance(raw.get("customer_linkage"), dict):
        customer_linkage = dict(raw["customer_linkage"])
    else:
        raise TypeError("phone intake: customer_linkage must be dict or absent")

    if raw.get("crm_stage") is None:
        crm_stage = CRM_PIPELINE[0]
    elif isinstance(raw.get("crm_stage"), str):
        crm_stage = raw["crm_stage"]
    else:
        raise TypeError("phone intake: crm_stage must be str or absent")

    if raw.get("call_verification_required") is None:
        call_verification_required = True
        call_verification_status = "pending"
    elif isinstance(raw.get("call_verification_required"), bool):
        call_verification_required = raw["call_verification_required"]
        if raw.get("call_verification_status") is None:
            call_verification_status = (
                "pending" if call_verification_required else "not_required"
            )
        elif isinstance(raw.get("call_verification_status"), str):
            call_verification_status = raw["call_verification_status"]
        else:
            raise TypeError(
                "phone intake: call_verification_status must be str or absent"
            )
    else:
        raise TypeError(
            "phone intake: call_verification_required must be bool or absent"
        )

    return service.create_inquiry(
        event_date=event_date,
        inquiry_source="phone",
        crm_stage=crm_stage,
        customer_linkage=customer_linkage,
        time_window_text=time_window_text,
        location_text=location_text,
        guest_count_estimate=guest_count_estimate,
        planning_mode=planning_mode,
        call_verification_required=call_verification_required,
        call_verification_status=call_verification_status,
    )

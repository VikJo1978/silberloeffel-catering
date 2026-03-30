"""Wix form channel → InquiryService.create_inquiry."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Mapping

from catering_system.domain.inquiry import CRM_PIPELINE, Inquiry, PLANNING_MODES
from catering_system.intake.external_secure_intake_layer import (
    normalize_public_wix_inquiry_payload,
)
from catering_system.services.inquiry_service import InquiryService

_log = logging.getLogger(__name__)


def intake_from_wix_form(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    _log.info("wix_form adapter called")
    try:
        return _intake_from_wix_form_body(service, raw)
    except (ValueError, TypeError):
        _log.warning("wix_form adapter validation failed")
        raise


def _intake_from_wix_form_body(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    raw = normalize_public_wix_inquiry_payload(raw)
    event_date = raw.get("event_date")
    if not isinstance(event_date, date):
        raise ValueError("wix_form intake: event_date (date) is required")

    time_window_text = raw.get("time_window_text", "")
    if not isinstance(time_window_text, str):
        raise TypeError("wix_form intake: time_window_text must be str")

    location_text = raw.get("location_text", "")
    if not isinstance(location_text, str):
        raise TypeError("wix_form intake: location_text must be str")

    guest_raw = raw.get("guest_count_estimate")
    if guest_raw is None:
        guest_count_estimate = None
    elif isinstance(guest_raw, int):
        guest_count_estimate = guest_raw
    else:
        raise TypeError("wix_form intake: guest_count_estimate must be int or absent")

    if raw.get("planning_mode") is None:
        planning_mode = PLANNING_MODES[0]
    elif isinstance(raw.get("planning_mode"), str):
        planning_mode = raw["planning_mode"]
    else:
        raise TypeError("wix_form intake: planning_mode must be str or absent")

    if raw.get("customer_linkage") is None:
        customer_linkage: dict[str, Any] = {}
    elif isinstance(raw.get("customer_linkage"), dict):
        customer_linkage = dict(raw["customer_linkage"])
    else:
        raise TypeError("wix_form intake: customer_linkage must be dict or absent")

    if raw.get("crm_stage") is None:
        crm_stage = CRM_PIPELINE[0]
    elif isinstance(raw.get("crm_stage"), str):
        crm_stage = raw["crm_stage"]
    else:
        raise TypeError("wix_form intake: crm_stage must be str or absent")

    if raw.get("call_verification_required") is None:
        call_verification_required = False
        call_verification_status = "not_required"
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
                "wix_form intake: call_verification_status must be str or absent"
            )
    else:
        raise TypeError(
            "wix_form intake: call_verification_required must be bool or absent"
        )

    return service.create_inquiry(
        event_date=event_date,
        inquiry_source="wix_form",
        crm_stage=crm_stage,
        customer_linkage=customer_linkage,
        time_window_text=time_window_text,
        location_text=location_text,
        guest_count_estimate=guest_count_estimate,
        planning_mode=planning_mode,
        call_verification_required=call_verification_required,
        call_verification_status=call_verification_status,
    )

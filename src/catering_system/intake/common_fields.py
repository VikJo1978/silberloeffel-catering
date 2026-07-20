"""Shared validation for trusted/legacy Inquiry intake adapters."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, TypedDict

from catering_system.domain.inquiry import CRM_PIPELINE, PLANNING_MODES


class CommonInquiryFields(TypedDict):
    event_date: date
    crm_stage: str
    customer_linkage: dict[str, Any]
    guest_count_estimate: int | None
    planning_mode: str
    call_verification_required: bool
    call_verification_status: str
    contact_email: str | None
    contact_phone: str | None
    contact_name: str | None
    company_name: str | None


def _optional_contact_str(raw: Mapping[str, Any], key: str, channel: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{channel} intake: {key} must be str or absent")
    return value


def parse_common_inquiry_fields(
    raw: Mapping[str, Any],
    *,
    channel: str,
    verification_required_by_default: bool,
) -> CommonInquiryFields:
    event_date = raw.get("event_date")
    if not isinstance(event_date, date):
        raise ValueError(f"{channel} intake: event_date (date) is required")

    guest_raw = raw.get("guest_count_estimate")
    if guest_raw is None:
        guest_count_estimate = None
    elif isinstance(guest_raw, bool) or not isinstance(guest_raw, int):
        raise TypeError(f"{channel} intake: guest_count_estimate must be int or absent")
    else:
        guest_count_estimate = guest_raw

    planning_raw = raw.get("planning_mode")
    if planning_raw is None:
        planning_mode: str = PLANNING_MODES[0]
    elif isinstance(planning_raw, str):
        planning_mode = planning_raw
    else:
        raise TypeError(f"{channel} intake: planning_mode must be str or absent")

    linkage_raw = raw.get("customer_linkage")
    if linkage_raw is None:
        customer_linkage: dict[str, Any] = {}
    elif isinstance(linkage_raw, dict):
        customer_linkage = dict(linkage_raw)
    else:
        raise TypeError(f"{channel} intake: customer_linkage must be dict or absent")

    crm_raw = raw.get("crm_stage")
    if crm_raw is None:
        crm_stage: str = CRM_PIPELINE[0]
    elif isinstance(crm_raw, str):
        crm_stage = crm_raw
    else:
        raise TypeError(f"{channel} intake: crm_stage must be str or absent")

    required_raw = raw.get("call_verification_required")
    if required_raw is None:
        required = verification_required_by_default
        status = "pending" if required else "not_required"
    elif isinstance(required_raw, bool):
        required = required_raw
        status_raw = raw.get("call_verification_status")
        if status_raw is None:
            status = "pending" if required else "not_required"
        elif isinstance(status_raw, str):
            status = status_raw
        else:
            raise TypeError(
                f"{channel} intake: call_verification_status must be str or absent"
            )
    else:
        raise TypeError(
            f"{channel} intake: call_verification_required must be bool or absent"
        )

    return {
        "event_date": event_date,
        "crm_stage": crm_stage,
        "customer_linkage": customer_linkage,
        "guest_count_estimate": guest_count_estimate,
        "planning_mode": planning_mode,
        "call_verification_required": required,
        "call_verification_status": status,
        # Structured contact contract (INQUIRY_CONTACT_COMPLETENESS_V1 §6):
        # optional on office/legacy channels — a preliminary incomplete
        # Inquiry is allowed there and surfaces as an office blocker.
        "contact_email": _optional_contact_str(raw, "contact_email", channel),
        "contact_phone": _optional_contact_str(raw, "contact_phone", channel),
        "contact_name": _optional_contact_str(raw, "contact_name", channel),
        "company_name": _optional_contact_str(raw, "company_name", channel),
    }

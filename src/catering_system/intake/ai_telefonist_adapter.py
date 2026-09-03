"""STRATO AI telephone assistant channel -> InquiryService.create_inquiry."""

from __future__ import annotations

import logging
import re
from datetime import date, time
from typing import Any, Mapping

from catering_system.domain.inquiry import CRM_PIPELINE, Inquiry, PLANNING_MODES
from catering_system.services.inquiry_service import InquiryService

_log = logging.getLogger(__name__)

_MAX_TEXT_LEN = 500
_MAX_MESSAGE_LEN = 5000
_MAX_EXTERNAL_REF_LEN = 200
_MIN_GUEST_COUNT = 1
_MAX_GUEST_COUNT = 2000


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise TypeError(f"ai_telefonist intake: {key} must be str")
    value = value.strip()
    if not value:
        raise ValueError(f"ai_telefonist intake: {key} is required")
    return value[:_MAX_TEXT_LEN]


def _optional_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"ai_telefonist intake: {key} must be str or absent")
    return value.strip()[:_MAX_TEXT_LEN]


def _normalize_phone(value: str) -> str:
    """Compact phone numbers when STRATO spells digits with separators."""
    compact = re.sub(r"[\s,;./()\-]+", "", value)
    if re.fullmatch(r"\+?\d+", compact):
        return compact
    return value


def intake_from_ai_telefonist(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    _log.info("ai_telefonist adapter called")
    try:
        return _intake_from_ai_telefonist_body(service, raw)
    except (ValueError, TypeError):
        _log.warning("ai_telefonist adapter validation failed")
        raise


def _intake_from_ai_telefonist_body(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    event_date = raw.get("event_date")
    if not isinstance(event_date, date):
        raise ValueError("ai_telefonist intake: event_date (date) is required")

    guest_count = raw.get("guest_count")
    if isinstance(guest_count, bool) or not isinstance(guest_count, int):
        raise TypeError("ai_telefonist intake: guest_count must be int")
    if not (_MIN_GUEST_COUNT <= guest_count <= _MAX_GUEST_COUNT):
        raise ValueError(
            "ai_telefonist intake: guest_count must be between "
            f"{_MIN_GUEST_COUNT} and {_MAX_GUEST_COUNT}"
        )

    contact_name = _required_text(raw, "contact_name")
    phone = _normalize_phone(_required_text(raw, "phone"))
    submission_id = _required_text(raw, "submission_id")[:_MAX_EXTERNAL_REF_LEN]

    company_name = _optional_text(raw, "company_name")
    email = _optional_text(raw, "email")
    event_type = _optional_text(raw, "event_type")
    location = _optional_text(raw, "location")
    customer_request = _optional_text(raw, "customer_request")

    event_start = raw.get("event_start")
    if event_start is not None and not isinstance(event_start, time):
        raise TypeError("ai_telefonist intake: event_start must be time or absent")

    fulfillment_raw = raw.get("fulfillment_mode")
    if fulfillment_raw is None:
        fulfillment_mode = "UNKNOWN"
    elif isinstance(fulfillment_raw, str):
        fulfillment_mode = fulfillment_raw.strip().upper() or "UNKNOWN"
    else:
        raise TypeError("ai_telefonist intake: fulfillment_mode must be str or absent")

    subject_base = company_name or contact_name
    subject = f"{subject_base} — {event_type}" if event_type else subject_base

    message_lines = [
        f"Name: {contact_name}",
        f"Telefon: {phone}",
    ]
    if company_name:
        message_lines.insert(0, f"Firma: {company_name}")
    if email:
        message_lines.append(f"E-Mail: {email}")
    if event_type:
        message_lines.append(f"Veranstaltungsart: {event_type}")
    if customer_request:
        message_lines.append(f"Wunsch: {customer_request}")
    intake_message = "\n".join(message_lines)[:_MAX_MESSAGE_LEN]

    time_window_text = (
        f"ab {event_start.strftime('%H:%M')} Uhr" if event_start is not None else ""
    )

    return service.create_inquiry(
        event_date=event_date,
        inquiry_source="ai_telefonist",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text=time_window_text,
        location_text=location,
        guest_count_estimate=guest_count,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=True,
        call_verification_status="pending",
        intake_subject=subject,
        intake_message=intake_message,
        intake_summary=(
            f"Telefon-Anfrage — {guest_count} Personen, {event_date.isoformat()}"
        ),
        intake_external_ref=submission_id,
        contact_email=email or None,
        contact_phone=phone,
        contact_name=contact_name,
        company_name=company_name or None,
        fulfillment_mode=fulfillment_mode,
        event_start_local=event_start,
    )

"""Website form channel → InquiryService.create_inquiry.

Custom Website-Anfrageformular intake (WEBSITE_FORM_INTAKE_TO_INQUIRY_PACK_V1).
Pure in-process adapter, same shape as the other intake/*.py adapters — no
HTTP code here, no public endpoint. Assumes its input already passed the
frozen External Secure Intake Layer boundary (SLICE_A_EXECUTION_PACK_V1 §8,
Cloudflare Worker); Worker→Core wiring is a separate, not-yet-built future
step (pack §5/§11).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Mapping

from catering_system.domain.inquiry import CRM_PIPELINE, Inquiry, PLANNING_MODES
from catering_system.intake.external_secure_intake_layer import (
    normalize_public_website_inquiry_payload,
)
from catering_system.services.inquiry_service import InquiryService

_log = logging.getLogger(__name__)

# NEW rules for this specifically public-facing channel (pack §6) — none of
# the other intake/*.py adapters need these, since office-typed input is
# already trusted.
_MAX_SUBJECT_LEN = 200
_MAX_MESSAGE_LEN = 5000
_MAX_TEXT_LEN = 500  # location_text / time_window_text
_MAX_EXTERNAL_REF_LEN = 200
_MIN_GUEST_COUNT = 1
_MAX_GUEST_COUNT = 2000
_TRUNCATION_MARKER = "… (gekürzt)"


def _truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[:max_len] + _TRUNCATION_MARKER


def intake_from_website_form(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    _log.info("website_form adapter called")
    try:
        return _intake_from_website_form_body(service, raw)
    except (ValueError, TypeError):
        _log.warning("website_form adapter validation failed")
        raise


def _intake_from_website_form_body(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    raw = normalize_public_website_inquiry_payload(raw)

    event_date = raw.get("event_date")
    if not isinstance(event_date, date):
        raise ValueError("website_form intake: event_date (date) is required")

    guest_raw = raw.get("guest_count_estimate")
    if guest_raw is None:
        guest_count_estimate = None
    elif isinstance(guest_raw, bool):
        raise TypeError(
            "website_form intake: guest_count_estimate must be int or absent"
        )
    elif isinstance(guest_raw, int):
        if not (_MIN_GUEST_COUNT <= guest_raw <= _MAX_GUEST_COUNT):
            raise ValueError(
                "website_form intake: guest_count_estimate must be between "
                f"{_MIN_GUEST_COUNT} and {_MAX_GUEST_COUNT}, got {guest_raw!r}"
            )
        guest_count_estimate = guest_raw
    else:
        raise TypeError(
            "website_form intake: guest_count_estimate must be int or absent"
        )

    location_raw = raw.get("location_text")
    if location_raw is None:
        location_text = ""
    elif isinstance(location_raw, str):
        location_text = _truncate(location_raw, _MAX_TEXT_LEN)
    else:
        raise TypeError("website_form intake: location_text must be str or absent")

    time_window_raw = raw.get("time_window_text")
    if time_window_raw is None:
        time_window_text = ""
    elif isinstance(time_window_raw, str):
        time_window_text = _truncate(time_window_raw, _MAX_TEXT_LEN)
    else:
        raise TypeError("website_form intake: time_window_text must be str or absent")

    # intake_subject: company/name + event_type (pack §4) — a short
    # identifying line only, never a fake structured customer/company field.
    subject_parts: list[str] = []
    for key in ("company", "name"):
        v = raw.get(key)
        if v is not None:
            if not isinstance(v, str):
                raise TypeError(f"website_form intake: {key} must be str or absent")
            if v:
                subject_parts.append(v)
                break  # company preferred over name if both given
    event_type = raw.get("event_type")
    if event_type is not None:
        if not isinstance(event_type, str):
            raise TypeError("website_form intake: event_type must be str or absent")
        if event_type:
            subject_parts.append(event_type)
    intake_subject = (
        _truncate(" — ".join(subject_parts), _MAX_SUBJECT_LEN) if subject_parts else ""
    )

    # intake_message: complete labelled public-form context. Keeping both
    # company and name here avoids losing the contact name when the shorter
    # intake_subject prefers the company. These remain intake context, never
    # customer_linkage or invented structured Core customer fields.
    message_lines: list[str] = []
    for key, label in (
        ("company", "Firma"),
        ("name", "Name"),
        ("event_type", "Veranstaltungsart"),
        ("phone", "Telefon"),
        ("email", "E-Mail"),
        ("message", "Wunsch"),
    ):
        v = raw.get(key)
        if v is not None:
            if not isinstance(v, str):
                raise TypeError(f"website_form intake: {key} must be str or absent")
            if v:
                message_lines.append(f"{label}: {v}")
    intake_message = (
        _truncate("\n".join(message_lines), _MAX_MESSAGE_LEN) if message_lines else ""
    )

    # intake_summary: adapter-generated one-liner, never raw user text —
    # same role as the configurator's computed item summary (5d5e007).
    if guest_count_estimate is not None:
        intake_summary = f"Website-Anfrage — {guest_count_estimate} Personen, {event_date.isoformat()}"
    else:
        intake_summary = f"Website-Anfrage — {event_date.isoformat()}"

    submission_raw = raw.get("submission_id")
    if submission_raw is None:
        intake_external_ref = ""
    elif isinstance(submission_raw, str):
        intake_external_ref = _truncate(submission_raw, _MAX_EXTERNAL_REF_LEN)
    else:
        raise TypeError("website_form intake: submission_id must be str or absent")

    if raw.get("crm_stage") is None:
        crm_stage = CRM_PIPELINE[0]
    elif isinstance(raw.get("crm_stage"), str):
        crm_stage = raw["crm_stage"]
    else:
        raise TypeError("website_form intake: crm_stage must be str or absent")

    # Public, unverified channel — same "requires verification by default"
    # precedent as email_adapter.py/phone_adapter.py (indirect/hands-off
    # channels), not wix_form/manual's office-mediated default.
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
                "website_form intake: call_verification_status must be str or absent"
            )
    else:
        raise TypeError(
            "website_form intake: call_verification_required must be bool or absent"
        )

    return service.create_inquiry(
        event_date=event_date,
        inquiry_source="website_form",
        crm_stage=crm_stage,
        customer_linkage={},  # never phone/email/name here — pack §4/§6
        time_window_text=time_window_text,
        location_text=location_text,
        guest_count_estimate=guest_count_estimate,
        planning_mode=PLANNING_MODES[0],  # never derived from event_type — pack §4
        call_verification_required=call_verification_required,
        call_verification_status=call_verification_status,
        intake_subject=intake_subject,
        intake_message=intake_message,
        intake_summary=intake_summary,
        intake_external_ref=intake_external_ref,
    )

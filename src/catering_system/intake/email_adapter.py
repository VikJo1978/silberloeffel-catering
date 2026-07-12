"""Email channel → InquiryService.create_inquiry."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from catering_system.domain.inquiry import Inquiry
from catering_system.intake.common_fields import parse_common_inquiry_fields
from catering_system.services.inquiry_service import InquiryService

_log = logging.getLogger(__name__)


def intake_from_email(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    _log.info("email adapter called")
    try:
        return _intake_from_email_body(service, raw)
    except (ValueError, TypeError):
        _log.warning("email adapter validation failed")
        raise


def _intake_from_email_body(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    common = parse_common_inquiry_fields(
        raw, channel="email", verification_required_by_default=True
    )
    if raw.get("time_window_text") is None:
        body = raw.get("body_text")
        time_window_text = "" if body is None else str(body)[:500]
    elif isinstance(raw.get("time_window_text"), str):
        time_window_text = raw["time_window_text"]
    else:
        raise TypeError("email intake: time_window_text must be str or absent")
    if raw.get("location_text") is None:
        subject = raw.get("subject")
        location_text = "" if subject is None else str(subject)[:500]
    elif isinstance(raw.get("location_text"), str):
        location_text = raw["location_text"]
    else:
        raise TypeError("email intake: location_text must be str or absent")
    return service.create_inquiry(
        inquiry_source="email",
        time_window_text=time_window_text,
        location_text=location_text,
        **common,
    )

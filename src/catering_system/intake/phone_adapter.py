"""Phone channel → InquiryService.create_inquiry."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from catering_system.domain.inquiry import Inquiry
from catering_system.intake.common_fields import parse_common_inquiry_fields
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
    common = parse_common_inquiry_fields(
        raw, channel="phone", verification_required_by_default=True
    )
    if raw.get("time_window_text") is None:
        notes = raw.get("call_notes")
        time_window_text = "" if notes is None else str(notes)[:500]
    elif isinstance(raw.get("time_window_text"), str):
        time_window_text = raw["time_window_text"]
    else:
        raise TypeError("phone intake: time_window_text must be str or absent")
    location_raw = raw.get("location_text")
    if location_raw is None:
        location_text = ""
    elif isinstance(location_raw, str):
        location_text = location_raw
    else:
        raise TypeError("phone intake: location_text must be str or absent")
    return service.create_inquiry(
        inquiry_source="phone",
        time_window_text=time_window_text,
        location_text=location_text,
        **common,
    )

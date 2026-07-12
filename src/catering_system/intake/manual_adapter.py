"""Manual entry channel → InquiryService.create_inquiry."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from catering_system.domain.inquiry import Inquiry
from catering_system.intake.common_fields import parse_common_inquiry_fields
from catering_system.services.inquiry_service import InquiryService

_log = logging.getLogger(__name__)


def intake_from_manual(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    _log.info("manual adapter called")
    try:
        return _intake_from_manual_body(service, raw)
    except (ValueError, TypeError):
        _log.warning("manual adapter validation failed")
        raise


def _intake_from_manual_body(
    service: InquiryService,
    raw: Mapping[str, Any],
) -> Inquiry:
    common = parse_common_inquiry_fields(
        raw, channel="manual", verification_required_by_default=False
    )
    time_window_text = raw.get("time_window_text", "")
    if not isinstance(time_window_text, str):
        raise TypeError("manual intake: time_window_text must be str")
    location_text = raw.get("location_text", "")
    if not isinstance(location_text, str):
        raise TypeError("manual intake: location_text must be str")
    return service.create_inquiry(
        inquiry_source="manual",
        time_window_text=time_window_text,
        location_text=location_text,
        **common,
    )

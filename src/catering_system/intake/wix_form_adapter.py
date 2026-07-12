"""Wix form channel → InquiryService.create_inquiry."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from catering_system.domain.inquiry import Inquiry
from catering_system.intake.common_fields import parse_common_inquiry_fields
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
    common = parse_common_inquiry_fields(
        raw, channel="wix_form", verification_required_by_default=False
    )
    time_window_text = raw.get("time_window_text", "")
    if not isinstance(time_window_text, str):
        raise TypeError("wix_form intake: time_window_text must be str")
    location_text = raw.get("location_text", "")
    if not isinstance(location_text, str):
        raise TypeError("wix_form intake: location_text must be str")
    return service.create_inquiry(
        inquiry_source="wix_form",
        time_window_text=time_window_text,
        location_text=location_text,
        **common,
    )

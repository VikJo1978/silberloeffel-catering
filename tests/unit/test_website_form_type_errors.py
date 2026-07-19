"""Website form adapter type-guard coverage."""

from __future__ import annotations

from datetime import date

import pytest

from catering_system.intake.website_form_adapter import intake_from_website_form
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService

_D = date(2026, 10, 1)


def _service() -> InquiryService:
    return InquiryService(InMemoryInquiryRepository())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("location_text", 123),
        ("time_window_text", 123),
        ("company", 123),
        ("event_type", 123),
        ("phone", 123),
        ("submission_id", 123),
        ("crm_stage", 123),
    ],
)
def test_non_string_optional_fields_are_rejected(field: str, value: object) -> None:
    payload = {"event_date": _D, field: value}
    with pytest.raises(TypeError):
        intake_from_website_form(_service(), payload)


def test_non_bool_call_verification_required_is_rejected() -> None:
    payload = {"event_date": _D, "call_verification_required": "yes"}
    with pytest.raises(TypeError, match="call_verification_required must be bool"):
        intake_from_website_form(_service(), payload)


def test_non_string_call_verification_status_is_rejected_when_required() -> None:
    payload = {
        "event_date": _D,
        "call_verification_required": True,
        "call_verification_status": 123,
    }
    with pytest.raises(TypeError, match="call_verification_status must be str"):
        intake_from_website_form(_service(), payload)

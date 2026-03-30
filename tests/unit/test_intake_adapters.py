"""Unit tests for A2 intake adapters."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from catering_system.domain.inquiry import CRM_PIPELINE, Inquiry, PLANNING_MODES
from catering_system.intake.email_adapter import intake_from_email
from catering_system.intake.manual_adapter import intake_from_manual
from catering_system.intake.phone_adapter import intake_from_phone
from catering_system.intake.wix_form_adapter import intake_from_wix_form
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService

_D = date(2026, 7, 15)


def test_wix_form_happy_path_uses_create_inquiry_and_source() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with patch.object(svc, "create_inquiry", wraps=svc.create_inquiry) as spy:
        q = intake_from_wix_form(
            svc,
            {
                "event_date": _D,
                "time_window_text": "18–22",
                "location_text": "München",
                "guest_count_estimate": 30,
                "planning_mode": PLANNING_MODES[1],
            },
        )
        spy.assert_called_once()
    assert q.inquiry_source == "wix_form"
    assert q.event_date == _D
    assert q.crm_stage == CRM_PIPELINE[0]
    assert q.planning_mode == PLANNING_MODES[1]


def test_email_happy_path_uses_create_inquiry_and_source() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with patch.object(svc, "create_inquiry", wraps=svc.create_inquiry) as spy:
        q = intake_from_email(
            svc,
            {
                "event_date": _D,
                "body_text": "abends",
                "subject": "Firma X",
            },
        )
        spy.assert_called_once()
    assert q.inquiry_source == "email"
    assert "abends" in q.time_window_text
    assert q.call_verification_required is True
    assert q.call_verification_status == "pending"


def test_phone_happy_path_uses_create_inquiry_and_source() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with patch.object(svc, "create_inquiry", wraps=svc.create_inquiry) as spy:
        q = intake_from_phone(
            svc,
            {
                "event_date": _D,
                "call_notes": "mittags, 50 Personen",
                "location_text": "vor Ort",
            },
        )
        spy.assert_called_once()
    assert q.inquiry_source == "phone"
    assert "mittags" in q.time_window_text
    assert q.location_text == "vor Ort"


def test_manual_happy_path_uses_create_inquiry_and_source() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with patch.object(svc, "create_inquiry", wraps=svc.create_inquiry) as spy:
        q = intake_from_manual(
            svc,
            {
                "event_date": _D,
                "time_window_text": "ganztags",
                "location_text": "Berlin",
                "guest_count_estimate": 12,
            },
        )
        spy.assert_called_once()
    assert q.inquiry_source == "manual"
    assert q.guest_count_estimate == 12


def test_defaults_wix_form_crm_planning_call_verification() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_wix_form(svc, {"event_date": _D})
    assert q.crm_stage == CRM_PIPELINE[0]
    assert q.planning_mode == PLANNING_MODES[0]
    assert q.call_verification_required is False
    assert q.call_verification_status == "not_required"


def test_defaults_email_crm_planning_call_verification() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_email(svc, {"event_date": _D, "body_text": "x"})
    assert q.crm_stage == CRM_PIPELINE[0]
    assert q.planning_mode == PLANNING_MODES[0]
    assert q.call_verification_required is True
    assert q.call_verification_status == "pending"


def test_defaults_phone_crm_planning_call_verification() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_phone(svc, {"event_date": _D})
    assert q.crm_stage == CRM_PIPELINE[0]
    assert q.planning_mode == PLANNING_MODES[0]
    assert q.call_verification_required is True
    assert q.call_verification_status == "pending"


def test_defaults_manual_crm_planning_call_verification() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_manual(svc, {"event_date": _D})
    assert q.crm_stage == CRM_PIPELINE[0]
    assert q.planning_mode == PLANNING_MODES[0]
    assert q.call_verification_required is False
    assert q.call_verification_status == "not_required"


def test_integration_each_channel_persists_inquiry_with_source() -> None:
    for fn, src in (
        (intake_from_wix_form, "wix_form"),
        (intake_from_email, "email"),
        (intake_from_phone, "phone"),
        (intake_from_manual, "manual"),
    ):
        repo = InMemoryInquiryRepository()
        svc = InquiryService(repo)
        raw = {"event_date": _D, "time_window_text": "t", "location_text": "l"}
        if fn is intake_from_email:
            raw = {"event_date": _D, "body_text": "b"}
        q = fn(svc, raw)
        loaded = repo.get_by_id(q.inquiry_id)
        assert loaded is not None
        assert loaded.inquiry_source == src


def test_missing_event_date_rejected_each_channel() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="event_date"):
        intake_from_wix_form(svc, {})
    with pytest.raises(ValueError, match="event_date"):
        intake_from_email(svc, {})
    with pytest.raises(ValueError, match="event_date"):
        intake_from_phone(svc, {})
    with pytest.raises(ValueError, match="event_date"):
        intake_from_manual(svc, {})


def test_invalid_event_date_type_rejected_each_channel() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    for fn in (
        intake_from_wix_form,
        intake_from_email,
        intake_from_phone,
        intake_from_manual,
    ):
        with pytest.raises(ValueError, match="event_date"):
            fn(svc, {"event_date": "2026-08-01"})


def test_invalid_guest_count_rejected_where_applicable() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    for fn in (
        intake_from_wix_form,
        intake_from_email,
        intake_from_phone,
        intake_from_manual,
    ):
        with pytest.raises(TypeError, match="guest_count_estimate"):
            fn(svc, {"event_date": _D, "guest_count_estimate": "12"})


def test_invalid_customer_linkage_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="customer_linkage"):
        intake_from_wix_form(
            svc,
            {"event_date": _D, "customer_linkage": {"unknown_key": "x"}},
        )


def test_invalid_crm_stage_through_service_path() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="crm_stage"):
        intake_from_manual(
            svc,
            {"event_date": _D, "crm_stage": "bogus"},
        )


def test_invalid_planning_mode_through_service_path() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="planning_mode"):
        intake_from_email(
            svc,
            {"event_date": _D, "body_text": "b", "planning_mode": "x"},
        )


def test_invalid_call_verification_status_through_service_path() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="call_verification_status"):
        intake_from_phone(
            svc,
            {
                "event_date": _D,
                "call_verification_required": True,
                "call_verification_status": "nope",
            },
        )


def test_invalid_planning_mode_passes_to_service_and_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="planning_mode"):
        intake_from_wix_form(
            svc,
            {"event_date": _D, "planning_mode": "invalid_mode"},
        )


def test_adapters_only_call_create_inquiry_not_update() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    payload = {"event_date": _D, "time_window_text": "a", "location_text": "b"}
    for fn in (
        intake_from_wix_form,
        intake_from_email,
        intake_from_phone,
        intake_from_manual,
    ):
        with patch.object(svc, "update_inquiry") as u:
            if fn is intake_from_email:
                fn(svc, {"event_date": _D, "body_text": "b"})
            else:
                fn(svc, payload)
            u.assert_not_called()


def test_no_second_status_axis_on_inquiry() -> None:
    assert "InquiryStatus" not in Inquiry.__annotations__


def test_adapters_have_no_order_side_surface() -> None:
    for m in (
        intake_from_wix_form,
        intake_from_email,
        intake_from_phone,
        intake_from_manual,
    ):
        assert not hasattr(m, "create_order")


def test_wix_adapter_logs_called(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    intake_from_wix_form(
        svc,
        {"event_date": _D, "time_window_text": "t", "location_text": "l"},
    )
    assert "wix_form adapter called" in caplog.text

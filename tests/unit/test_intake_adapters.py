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
from catering_system.intake.website_form_adapter import intake_from_website_form
from catering_system.intake.wix_form_adapter import intake_from_wix_form
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService

_D = date(2026, 7, 15)
# website_form/configurator require email+phone (INQUIRY_CONTACT_COMPLETENESS_V1)
_WF_CONTACT = {"email": "kunde@example.com", "phone": "030 123456"}


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
    assert q.location_text == "Firma X"
    assert q.intake_subject == "Firma X"
    assert q.intake_message == "abends"
    assert q.call_verification_required is True
    assert q.call_verification_status == "pending"


def test_email_maps_subject_to_intake_subject() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_email(
        svc,
        {"event_date": _D, "subject": "Catering Anfrage Sommerfest"},
    )
    assert q.intake_subject == "Catering Anfrage Sommerfest"
    assert q.location_text == "Catering Anfrage Sommerfest"


def test_email_maps_body_text_to_intake_message() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_email(
        svc,
        {"event_date": _D, "body_text": "Wir planen ein Event für 80 Personen."},
    )
    assert q.intake_message == "Wir planen ein Event für 80 Personen."
    assert q.time_window_text == "Wir planen ein Event für 80 Personen."


def test_email_maps_from_to_labelled_sender() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_email(
        svc,
        {"event_date": _D, "from": "sender@example.invalid"},
    )
    assert q.intake_message == "E-Mail: sender@example.invalid"


def test_email_intake_context_combined() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_email(
        svc,
        {
            "event_date": _D,
            "subject": "Anfrage Firmenfeier",
            "body_text": "Bitte um Rückruf wegen Menüauswahl.",
            "from": "office@example.invalid",
        },
    )
    assert q.intake_subject == "Anfrage Firmenfeier"
    assert q.intake_message == (
        "E-Mail: office@example.invalid\nBitte um Rückruf wegen Menüauswahl."
    )
    assert q.location_text == "Anfrage Firmenfeier"
    assert q.time_window_text == "Bitte um Rückruf wegen Menüauswahl."


def test_email_explicit_location_and_time_window_fallbacks_preserved() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_email(
        svc,
        {
            "event_date": _D,
            "subject": "Betreff",
            "body_text": "Nachricht",
            "location_text": "Expliziter Ort",
            "time_window_text": "Explizites Fenster",
        },
    )
    assert q.location_text == "Expliziter Ort"
    assert q.time_window_text == "Explizites Fenster"
    assert q.intake_subject == "Betreff"
    assert q.intake_message == "Nachricht"


def test_email_non_string_from_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(TypeError, match="from"):
        intake_from_email(svc, {"event_date": _D, "from": ["not", "a", "string"]})


def test_email_absent_subject_body_sender_safe() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_email(svc, {"event_date": _D})
    assert q.inquiry_source == "email"
    assert q.intake_subject is None
    assert q.intake_message is None
    assert q.location_text == ""
    assert q.time_window_text == ""


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


def test_boolean_guest_count_rejected_each_channel() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    for fn in (
        intake_from_wix_form,
        intake_from_email,
        intake_from_phone,
        intake_from_manual,
    ):
        with pytest.raises(TypeError, match="guest_count_estimate"):
            fn(svc, {"event_date": _D, "guest_count_estimate": True})


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


# -- website_form adapter (WEBSITE_FORM_INTAKE_TO_INQUIRY_PACK_V1) ----------
# Custom Website-Anfrageformular intake. Not folded into the shared loop
# tests above — a new, dedicated section, so the existing four channels'
# tests stay exactly as they are.


def test_website_form_happy_path_uses_create_inquiry_and_source() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with patch.object(svc, "create_inquiry", wraps=svc.create_inquiry) as spy:
        q = intake_from_website_form(
            svc,
            {
                "event_date": _D,
                "guest_count_estimate": 25,
                "location_text": "Musterstraße 1, München",
                "time_window_text": "abends",
                "company": "Musterfirma GmbH",
                "name": "Herr Beispiel",
                "event_type": "Firmenfeier",
                "phone": "0151 2345678",
                "email": "info@musterfirma.de",
                "message": "Bitte Rückruf vor Lieferung.",
                "submission_id": "web-42",
            },
        )
        spy.assert_called_once()
    assert q.inquiry_source == "website_form"
    assert q.event_date == _D
    assert q.guest_count_estimate == 25
    assert q.location_text == "Musterstraße 1, München"
    assert q.time_window_text == "abends"
    assert q.intake_subject == "Musterfirma GmbH — Firmenfeier"
    assert q.intake_message == (
        "Firma: Musterfirma GmbH\n"
        "Name: Herr Beispiel\n"
        "Veranstaltungsart: Firmenfeier\n"
        "Telefon: 0151 2345678\n"
        "E-Mail: info@musterfirma.de\n"
        "Wunsch: Bitte Rückruf vor Lieferung."
    )
    assert q.intake_summary == f"Website-Anfrage — 25 Personen, {_D.isoformat()}"
    assert q.intake_external_ref == "web-42"
    assert q.customer_linkage == {}
    assert q.planning_mode == PLANNING_MODES[0]
    assert q.call_verification_required is True
    assert q.call_verification_status == "pending"


def test_website_form_uses_name_when_company_absent() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_website_form(
        svc, {**_WF_CONTACT, "event_date": _D, "name": "Frau Muster"}
    )
    assert q.intake_subject == "Frau Muster"
    assert q.intake_message == (
        "Name: Frau Muster\nTelefon: 030 123456\nE-Mail: kunde@example.com"
    )


def test_website_form_without_contact_info_rejected() -> None:
    """INQUIRY_CONTACT_COMPLETENESS_V1 §5: public channel requires email+phone."""
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="requires email and phone"):
        intake_from_website_form(svc, {"event_date": _D})
    assert repo.list_all() == []


def test_website_form_missing_event_date_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="event_date"):
        intake_from_website_form(svc, {})


def test_website_form_invalid_event_date_type_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="event_date"):
        intake_from_website_form(svc, {"event_date": "2026-08-01"})


def test_website_form_guest_count_below_minimum_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="guest_count_estimate"):
        intake_from_website_form(svc, {"event_date": _D, "guest_count_estimate": 0})


def test_website_form_guest_count_above_maximum_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="guest_count_estimate"):
        intake_from_website_form(svc, {"event_date": _D, "guest_count_estimate": 2001})


def test_website_form_guest_count_boundaries_accepted() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q_min = intake_from_website_form(
        svc, {**_WF_CONTACT, "event_date": _D, "guest_count_estimate": 1}
    )
    q_max = intake_from_website_form(
        svc, {**_WF_CONTACT, "event_date": _D, "guest_count_estimate": 2000}
    )
    assert q_min.guest_count_estimate == 1
    assert q_max.guest_count_estimate == 2000


def test_website_form_bool_guest_count_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(TypeError, match="guest_count_estimate"):
        intake_from_website_form(svc, {"event_date": _D, "guest_count_estimate": True})


def test_website_form_non_int_guest_count_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(TypeError, match="guest_count_estimate"):
        intake_from_website_form(svc, {"event_date": _D, "guest_count_estimate": "25"})


def test_website_form_long_message_truncated_with_marker() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    long_message = "Sehr ausführlicher Wunschtext. " * 300  # well over 5000 chars
    q = intake_from_website_form(
        svc, {**_WF_CONTACT, "event_date": _D, "message": long_message}
    )
    assert q.intake_message is not None
    assert q.intake_message.endswith("… (gekürzt)")
    assert len(q.intake_message) <= 5000 + len("… (gekürzt)")


def test_website_form_long_subject_truncated_with_marker() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_website_form(
        svc,
        {**_WF_CONTACT, "event_date": _D, "company": "X" * 300, "event_type": "Feier"},
    )
    assert q.intake_subject is not None
    assert q.intake_subject.endswith("… (gekürzt)")


def test_website_form_long_location_and_time_window_truncated() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_website_form(
        svc,
        {
            **_WF_CONTACT,
            "event_date": _D,
            "location_text": "Y" * 600,
            "time_window_text": "Z" * 600,
        },
    )
    assert q.location_text.endswith("… (gekürzt)")
    assert q.time_window_text.endswith("… (gekürzt)")


def test_website_form_planning_mode_stays_default_even_with_buffet_event_type() -> None:
    """event_type must never leak into planning_mode (pack §4)."""
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_website_form(
        svc, {**_WF_CONTACT, "event_date": _D, "event_type": "Büfett Firmenfeier"}
    )
    assert q.planning_mode == PLANNING_MODES[0]


def test_website_form_customer_linkage_never_gets_contact_details() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_website_form(
        svc,
        {"event_date": _D, "phone": "0151", "email": "a@b.de", "name": "X"},
    )
    assert q.customer_linkage == {}


def test_website_form_explicit_call_verification_overrides_default() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_website_form(
        svc,
        {
            **_WF_CONTACT,
            "event_date": _D,
            "call_verification_required": False,
            "call_verification_status": "not_required",
        },
    )
    assert q.call_verification_required is False
    assert q.call_verification_status == "not_required"


def test_website_form_non_string_contact_field_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(TypeError, match="phone"):
        intake_from_website_form(
            svc, {"event_date": _D, "phone": ["not", "a", "string"]}
        )


def test_website_form_adapter_only_calls_create_inquiry_not_update() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with patch.object(svc, "update_inquiry") as u:
        intake_from_website_form(svc, {**_WF_CONTACT, "event_date": _D})
        u.assert_not_called()


def test_website_form_adapter_has_no_order_side_surface() -> None:
    assert not hasattr(intake_from_website_form, "create_order")


def test_website_form_adapter_logs_called(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    intake_from_website_form(svc, {**_WF_CONTACT, "event_date": _D})
    assert "website_form adapter called" in caplog.text


def test_website_form_stored_via_repository() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_website_form(svc, {**_WF_CONTACT, "event_date": _D, "company": "X"})
    loaded = repo.get_by_id(q.inquiry_id)
    assert loaded is not None
    assert loaded.inquiry_source == "website_form"
    assert loaded.intake_subject == "X"

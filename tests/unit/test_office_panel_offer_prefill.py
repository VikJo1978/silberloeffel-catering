from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from catering_system.domain.inquiry import (
    Inquiry,
    InquiryOfficeState,
    InquiryOfferProjection,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.ui.office_panel import OfficePanel
from catering_system.ui.office_panel_inquiry_detail import (
    InquiryDetailFormFields,
    render_inquiry_detail,
)
from catering_system.ui.office_panel_offer_prefill import (
    build_offer_prefill_url,
    normalize_configurator_url,
    offer_prefill_payload,
)
from tests.helpers.office_panel_context import legacy_office_context


def _inquiry(*, guest_count: int | None = 42) -> Inquiry:
    now = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=date(2026, 10, 3),
        created_at=now,
        updated_at=now,
        inquiry_source="website_form",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:30–23:00",
        location_text="Große Bleichen 1, Hamburg",
        guest_count_estimate=guest_count,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_subject="Möbel & Mehr GmbH — Jubiläum",
        intake_message=(
            "Firma: Möbel & Mehr GmbH\n"
            "Name: Jörg Weiß\n"
            "Veranstaltungsart: Jubiläum\n"
            "Telefon: 040 12345\n"
            "E-Mail: joerg@example.test\n"
            "Wunsch: Vegetarisch & glutenfrei"
        ),
        intake_summary="Website-Anfrage — 42 Personen, 2026-10-03",
        intake_external_ref="web-test-42",
        customer_snapshot=InquiryCustomerSnapshot(
            email="joerg@example.test",
            phone="040 12345",
        ),
    )


def test_payload_maps_labelled_context_without_creating_core_records() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    inquiry = _inquiry()
    inquiry_repo.save(inquiry)

    panel = OfficePanel(
        inquiry_repo,
        order_repo,
        configurator_url="http://127.0.0.1:5173",
    )
    page = panel.render_inquiry(inquiry.inquiry_id, context=legacy_office_context())

    assert page is not None
    assert "Angebot mit Anfragedaten vorbereiten" in page
    assert 'href="http://127.0.0.1:5173/#core-inquiry=' in page
    assert "Authorization" not in page
    assert "CORE_OFFICE_API_TOKEN" not in page
    assert "offer_snapshot_v" not in page
    assert "snapshot_hash" not in page
    assert order_repo.list_orders() == []

    payload = offer_prefill_payload(inquiry)
    transfer = payload["transfer"]
    assert isinstance(transfer, dict)
    planning = transfer["planning"]
    context = transfer["orderContextPrefill"]
    assert planning["persons"] == 42
    assert planning["eventType"] == "Jubiläum"
    assert context["companyName"] == "Möbel & Mehr GmbH"
    assert context["contactPerson"] == "Jörg Weiß"
    assert context["email"] == "joerg@example.test"
    assert context["phone"] == "040 12345"
    assert context["eventDate"] == "2026-10-03"


def test_fragment_maps_structured_customer_snapshot_and_all_event_fields() -> None:
    inquiry = replace(
        _inquiry(),
        intake_message=(
            "Veranstaltungsart: Jubiläum\n"
            "Wunsch: Vegetarisch & glutenfrei\n"
            "Zusätzlicher Anfragekontext"
        ),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="Strukturierte Firma GmbH",
            contact_name="Strukturierter Kontakt",
            email="structured@example.test",
            phone="+49 40 98765",
        ),
    )

    url = build_offer_prefill_url("https://angebote.example.test", inquiry)
    request_url, fragment = url.split("#", 1)
    encoded = fragment.split("=", 1)[1]
    padded = encoded + "=" * (-len(encoded) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))

    assert request_url == "https://angebote.example.test/"
    assert decoded["transfer"]["orderContextPrefill"] == {
        "companyName": "Strukturierte Firma GmbH",
        "contactPerson": "Strukturierter Kontakt",
        "email": "structured@example.test",
        "phone": "+49 40 98765",
        "eventDate": "2026-10-03",
        "eventTime": "18:30–23:00",
        "location": "Große Bleichen 1, Hamburg",
        "billingAddress": "",
        "remarks": (
            "Betreff: Möbel & Mehr GmbH — Jubiläum\n\n"
            "Wunsch: Vegetarisch & glutenfrei\n\n"
            "Zusätzlicher Anfragekontext\n\n"
            "Zusammenfassung: Website-Anfrage — 42 Personen, 2026-10-03"
        ),
    }


def test_structured_customer_snapshot_precedes_legacy_labelled_contact() -> None:
    inquiry = replace(
        _inquiry(),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="Structured Company",
            contact_name="Structured Contact",
            email="structured@example.test",
            phone="+49 40 98765",
        ),
    )

    context = offer_prefill_payload(inquiry)["transfer"]["orderContextPrefill"]

    assert context["companyName"] == "Structured Company"
    assert context["contactPerson"] == "Structured Contact"
    assert context["email"] == "structured@example.test"
    assert context["phone"] == "+49 40 98765"


def test_fragment_round_trip_preserves_unicode_and_stays_out_of_request_url() -> None:
    url = build_offer_prefill_url("https://angebote.example.test/app/", _inquiry())
    request_url, fragment = url.split("#", 1)
    assert request_url == "https://angebote.example.test/app"
    assert "Jörg" not in request_url
    assert fragment.startswith("core-inquiry=")

    encoded = fragment.split("=", 1)[1]
    padded = encoded + "=" * (-len(encoded) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    assert decoded["schema_version"] == "core_inquiry_offer_prefill_v1"
    assert decoded["transfer"]["orderContextPrefill"]["contactPerson"] == "Jörg Weiß"


def test_unknown_guest_count_remains_null() -> None:
    payload = offer_prefill_payload(_inquiry(guest_count=None))
    assert payload["transfer"]["planning"]["persons"] is None


@pytest.mark.parametrize(
    "value",
    [
        "ftp://configurator.example.test",
        "http://user:secret@configurator.example.test",
        "http://configurator.example.test?token=secret",
        "http://configurator.example.test#existing",
        "relative/path",
    ],
)
def test_invalid_configurator_url_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_configurator_url(value)


def test_empty_configurator_url_keeps_handoff_dormant() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    inquiry_repo.save(_inquiry())
    page = OfficePanel(inquiry_repo, order_repo).render_inquiry(
        "11111111-1111-1111-1111-111111111111",
        context=legacy_office_context(),
    )
    assert page is not None
    assert "Angebot mit Anfragedaten vorbereiten" not in page
    assert "Der Angebotskonfigurator ist derzeit nicht verfügbar" in page


@pytest.mark.parametrize(
    ("configurator_url", "expected"),
    [
        ("https://angebote.example.test", "Angebot vorbereiten</a>"),
        ("", "Der Angebotskonfigurator ist derzeit nicht verfügbar"),
    ],
)
def test_v2_inquiry_detail_has_action_or_safe_unavailable_state(
    configurator_url: str,
    expected: str,
) -> None:
    inquiry_repo = InMemoryInquiryRepository()
    inquiry = _inquiry()
    inquiry_repo.save(inquiry)
    page = OfficePanel(
        inquiry_repo,
        InMemoryOrderRepository(),
        configurator_url=configurator_url,
        ui_version="v2",
    ).render_inquiry(inquiry.inquiry_id, context=legacy_office_context())

    assert page is not None
    assert expected in page


def test_blocked_inquiry_never_renders_configurator_link() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    inquiry = replace(
        _inquiry(),
        call_verification_required=True,
        call_verification_status="pending",
    )
    inquiry_repo.save(inquiry)
    page = OfficePanel(
        inquiry_repo,
        order_repo,
        configurator_url="https://angebote.example.test",
    ).render_inquiry(inquiry.inquiry_id, context=legacy_office_context())

    assert page is not None
    assert "https://angebote.example.test" not in page


def test_existing_offer_links_to_core_detail_instead_of_configurator() -> None:
    inquiry = _inquiry()
    offer_id = "22222222-2222-4222-8222-222222222222"
    state = InquiryOfficeState(
        is_open=True,
        next_action="offer-pending",
        offer=InquiryOfferProjection(
            offer_id=offer_id,
            offer_version_id="33333333-3333-4333-8333-333333333333",
            commercial_state="Prepared",
        ),
        offer_preparation_blockers=("offer_already_exists",),
    )
    detail = render_inquiry_detail(
        inquiry,
        [],
        state,
        state.offer_preparation_blockers,
        forms=InquiryDetailFormFields(
            csrf_input="",
            primary_command_fields="",
            update_command_fields="",
        ),
        offer_url="https://angebote.example.test#must-not-render",
    )

    assert f'href="/offer/{offer_id}"' in detail.body
    assert "Angebot öffnen" in detail.body
    assert "angebote.example.test" not in detail.body

"""Unit tests — callback contact resolution against Core contacts (V1)."""

from __future__ import annotations

from datetime import date

from catering_system.intake.intake_contact import normalize_phone
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui import office_api_views as api_views
from catering_system.ui.callback_contact_resolution import (
    enrich_missed_board_with_core_contacts,
    resolve_core_contact_fields,
)
from catering_system.ui.office_panel import OfficePanel, _format_rueckruf_contact_cell
from catering_system.services.contact_projection_service import ContactProjectionService

_PHONE_E164 = "+4917642795029"
_JKART_MESSAGE = f"Firma: JK-art\nTelefon: {_PHONE_E164}\n"


def _contact_rows(inquiries: InMemoryInquiryRepository) -> list[dict[str, object]]:
    service = ContactProjectionService(
        inquiries,
        InMemoryOfferRepository(),
        InMemoryOrderRepository(),
        today=lambda: date(2026, 7, 15),
    )
    return api_views.contact_list_view(service.list_contacts())


def _save_inquiry(
    repo: InMemoryInquiryRepository,
    *,
    intake_message: str,
    customer_linkage: dict[str, str] | None = None,
) -> None:
    InquiryService(repo).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage=customer_linkage or {},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_message=intake_message,
    )


def _missed_item(**overrides: object) -> dict:
    item = {
        "call_id": "21.07.26|09:00:00|+4917642795029",
        "date": "21.07.26",
        "time": "09:00:00",
        "phone": "017642795029",
        "normalized_phone": _PHONE_E164,
        "contact_found": True,
        "contact_name": "Auerswald Stub Name",
        "contact_url": "https://example.invalid/hubspot",
        "reason": "Nicht angenommen",
    }
    item.update(overrides)
    return item


def test_normalize_phone_matches_german_local_to_e164() -> None:
    assert normalize_phone("017642795029") == _PHONE_E164
    assert normalize_phone(_PHONE_E164) == _PHONE_E164


def test_exact_e164_match_resolves_unique_contact() -> None:
    inquiries = InMemoryInquiryRepository()
    _save_inquiry(inquiries, intake_message=_JKART_MESSAGE)
    contacts = _contact_rows(inquiries)

    resolved = resolve_core_contact_fields(
        _missed_item(phone=_PHONE_E164),
        {normalize_phone(_PHONE_E164): contacts},
    )

    assert resolved["core_contact_label"] == "JK-art"
    assert resolved["core_contact_href"] == "/kontakt/intake%3Aphone%3A%2B4917642795029"


def test_german_local_callback_matches_normalized_core_phone() -> None:
    inquiries = InMemoryInquiryRepository()
    _save_inquiry(inquiries, intake_message=_JKART_MESSAGE)
    contacts = _contact_rows(inquiries)

    enriched = enrich_missed_board_with_core_contacts(
        [_missed_item(normalized_phone="", phone="017642795029")],
        contacts,
    )

    assert enriched[0]["core_contact_label"] == "JK-art"
    assert "/kontakt/intake%3Aphone%3A%2B4917642795029" in str(
        enriched[0]["core_contact_href"]
    )


def test_no_match_remains_unbekannt() -> None:
    resolved = resolve_core_contact_fields(_missed_item(), {})
    assert resolved["core_contact_label"] == "Unbekannt"
    assert resolved["core_contact_href"] is None


def test_duplicate_phone_is_mehrdeutig() -> None:
    inquiries = InMemoryInquiryRepository()
    _save_inquiry(inquiries, intake_message=_JKART_MESSAGE)
    _save_inquiry(
        inquiries,
        intake_message=_JKART_MESSAGE,
        customer_linkage={"customer_id": "cust-other"},
    )
    contacts = _contact_rows(inquiries)

    enriched = enrich_missed_board_with_core_contacts([_missed_item()], contacts)

    assert enriched[0]["core_contact_label"] == "Mehrdeutig – Kundenprüfung"
    assert enriched[0]["core_contact_href"] is None


def test_unique_match_renders_contact_detail_link() -> None:
    inquiries = InMemoryInquiryRepository()
    _save_inquiry(inquiries, intake_message=_JKART_MESSAGE)
    panel = OfficePanel(inquiries, InMemoryOrderRepository(), ui_version="v2")
    enriched = panel.enrich_rueckruf_items([_missed_item()])

    html = _format_rueckruf_contact_cell(enriched[0])
    assert 'href="/kontakt/intake%3Aphone%3A%2B4917642795029"' in html
    assert ">JK-art</a>" in html


def test_auerswald_contact_name_does_not_override_core_truth() -> None:
    inquiries = InMemoryInquiryRepository()
    _save_inquiry(inquiries, intake_message=_JKART_MESSAGE)
    panel = OfficePanel(inquiries, InMemoryOrderRepository())
    enriched = panel.enrich_rueckruf_items([_missed_item()])

    html = _format_rueckruf_contact_cell(enriched[0])
    assert "Auerswald Stub Name" not in html
    assert "JK-art" in html

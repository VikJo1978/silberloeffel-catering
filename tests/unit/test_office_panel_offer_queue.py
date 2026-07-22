"""Panel tests — grouped /angebote operational queue page."""

from __future__ import annotations

from datetime import date

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
from catering_system.ui.office_panel import OfficePanel
from tests.unit.test_offer_list import _offer

_TODAY = date(2026, 7, 15)


def test_angebote_queue_renders_sections_and_counters(monkeypatch) -> None:
    monkeypatch.setattr(
        "catering_system.ui.office_api_views.berlin_today", lambda: _TODAY
    )
    inquiries = InMemoryInquiryRepository()
    inquiry = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_subject="Hochzeit Müller",
        contact_email="kunde@example.com",
        contact_phone="030 1234567",
    )
    offers = InMemoryOfferRepository()
    offer = _offer(inquiry.inquiry_id)
    offers.save(offer)
    panel = OfficePanel(
        inquiries,
        InMemoryOrderRepository(),
        offer_repo=offers,
        ui_version="v2",
    )
    page = panel.render_angebote()

    assert "Aktion erforderlich" in page
    assert "Frist überschritten" in page
    assert "<details" in page
    assert "Abgeschlossen / Verlauf" in page
    assert "Vorbereitet — versenden" in page
    assert "Als gesendet markieren" in page
    assert "Angebot v1" in page
    assert f"/offer/{offer.offer_id}" in page


def test_angebote_queue_empty_state() -> None:
    offers = InMemoryOfferRepository()
    panel = OfficePanel(
        InMemoryInquiryRepository(),
        InMemoryOrderRepository(),
        offer_repo=offers,
        ui_version="v2",
    )
    page = panel.render_angebote()
    assert "Keine Angebote vorhanden" in page

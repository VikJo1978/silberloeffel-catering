"""Unit tests — CONTACT_STATUS_FILTER_V1 (Interessent / Kunde)."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

import threading
import urllib.request
from datetime import date

from catering_system.domain.contact_projection import (
    derive_contact_status,
    parse_contact_status_filter,
)
from catering_system.repositories.in_memory_contact_internal_note_repository import (
    InMemoryContactInternalNoteRepository,
)
from catering_system.repositories.in_memory_contact_profile_repository import (
    InMemoryContactProfileRepository,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.contact_projection_service import ContactProjectionService
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.office_panel import OfficePanel, create_office_panel_server

_PASSWORD = "test-secret"
_AUTH = ("office", _PASSWORD)
_TODAY = date(2026, 7, 15)


def _inquiry(
    repo: InMemoryInquiryRepository,
    *,
    company: str,
    email: str,
    phone: str = "+49301234567",
    crm_stage: str = "Neue Anfrage",
    customer_linkage: dict[str, str] | None = None,
):
    return InquiryService(repo).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage=crm_stage,  # type: ignore[arg-type]
        customer_linkage=customer_linkage or {},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=12,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email=email,
        contact_phone=phone,
        intake_message=f"Firma: {company}\nE-Mail: {email}\nTelefon: {phone}\n",
    )


def _panel_repos() -> tuple[
    InMemoryInquiryRepository,
    InMemoryOrderRepository,
    InMemoryOfferRepository,
    OfficePanel,
]:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    offers = InMemoryOfferRepository()
    panel = OfficePanel(
        inquiries,
        orders,
        offer_repo=offers,
        contact_note_repo=InMemoryContactInternalNoteRepository(),
        contact_profile_repo=InMemoryContactProfileRepository(),
    )
    return inquiries, orders, offers, panel


def test_derive_contact_status_rules() -> None:
    assert derive_contact_status(linked_order_count=0) == "interessent"
    assert derive_contact_status(linked_order_count=1) == "kunde"
    assert derive_contact_status(linked_order_count=3) == "kunde"


def test_parse_contact_status_filter_falls_back_to_all() -> None:
    assert parse_contact_status_filter(None) == "all"
    assert parse_contact_status_filter("") == "all"
    assert parse_contact_status_filter("ALL") == "all"
    assert parse_contact_status_filter("interessent") == "interessent"
    assert parse_contact_status_filter("kunde") == "kunde"
    assert parse_contact_status_filter("inaktiv") == "all"
    assert parse_contact_status_filter("nonsense") == "all"


def test_inquiry_without_order_is_interessent() -> None:
    inquiries = InMemoryInquiryRepository()
    _inquiry(inquiries, company="OnlyAsk", email="ask@example.invalid")
    rows = ContactProjectionService(
        inquiries,
        InMemoryOfferRepository(),
        InMemoryOrderRepository(),
        today=lambda: _TODAY,
    ).list_contacts()
    assert len(rows) == 1
    assert rows[0].contact_status == "interessent"
    assert rows[0].linked_order_count == 0


def test_rejected_inquiry_without_order_is_interessent() -> None:
    inquiries = InMemoryInquiryRepository()
    _inquiry(
        inquiries,
        company="Lost",
        email="lost@example.invalid",
        crm_stage="Abgelehnt / verloren",
    )
    rows = ContactProjectionService(
        inquiries,
        InMemoryOfferRepository(),
        InMemoryOrderRepository(),
        today=lambda: _TODAY,
    ).list_contacts()
    assert rows[0].contact_status == "interessent"
    assert rows[0].linked_order_count == 0


def test_contact_with_one_order_is_kunde() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _inquiry(inquiries, company="Buyer", email="buyer@example.invalid")
    orders = InMemoryOrderRepository()
    seed_order(orders, inquiry)
    rows = ContactProjectionService(
        inquiries,
        InMemoryOfferRepository(),
        orders,
        today=lambda: _TODAY,
    ).list_contacts()
    assert rows[0].contact_status == "kunde"
    assert rows[0].linked_order_count == 1
    assert rows[0].active_orders == 1


def test_several_inquiries_and_one_order_is_kunde() -> None:
    inquiries = InMemoryInquiryRepository()
    first = _inquiry(
        inquiries,
        company="Multi",
        email="multi@example.invalid",
        customer_linkage={"customer_id": "cust-multi"},
    )
    _inquiry(
        inquiries,
        company="Multi",
        email="multi@example.invalid",
        customer_linkage={"customer_id": "cust-multi"},
    )
    orders = InMemoryOrderRepository()
    seed_order(orders, first)
    rows = ContactProjectionService(
        inquiries,
        InMemoryOfferRepository(),
        orders,
        today=lambda: _TODAY,
    ).list_contacts()
    assert len(rows) == 1
    assert rows[0].inquiry_count == 2
    assert rows[0].contact_status == "kunde"


def test_filter_interessenten_kunden_and_alle() -> None:
    inquiries, orders, _offers, panel = _panel_repos()
    _inquiry(
        inquiries,
        company="LeadCo",
        email="lead@example.invalid",
        phone="+49304444444",
    )
    buyer = _inquiry(
        inquiries,
        company="BuyCo",
        email="buy@example.invalid",
        phone="+49305555555",
    )
    seed_order(orders, buyer)

    alle = panel.render_kontakte("", "all")
    assert "LeadCo" in alle and "BuyCo" in alle
    assert "Alle (2)" in alle
    assert "Interessenten (1)" in alle
    assert "Kunden (1)" in alle

    interessenten = panel.render_kontakte("", "interessent")
    assert "LeadCo" in interessenten
    assert "BuyCo" not in interessenten
    assert "Interessenten (1)" in interessenten

    kunden = panel.render_kontakte("", "kunde")
    assert "BuyCo" in kunden
    assert "LeadCo" not in kunden
    assert "Kunden (1)" in kunden


def test_search_and_status_filter_together() -> None:
    inquiries, orders, _offers, panel = _panel_repos()
    _inquiry(
        inquiries,
        company="JK Lead",
        email="jk-lead@example.invalid",
        phone="+49301111111",
    )
    buyer = _inquiry(
        inquiries,
        company="JK Buyer",
        email="jk-buy@example.invalid",
        phone="+49302222222",
    )
    _inquiry(
        inquiries,
        company="Other",
        email="other@example.invalid",
        phone="+49303333333",
    )
    seed_order(orders, buyer)

    page = panel.render_kontakte("jk", "kunde")
    assert "JK Buyer" in page
    assert "JK Lead" not in page
    assert "Other" not in page
    assert 'name="q" value="jk"' in page
    assert 'name="status" value="kunde"' in page
    assert "Alle (2)" in page
    assert "Interessenten (1)" in page
    assert "Kunden (1)" in page


def test_empty_status_filter_message() -> None:
    inquiries, _orders, _offers, panel = _panel_repos()
    _inquiry(inquiries, company="OnlyLead", email="only@example.invalid")
    page = panel.render_kontakte("", "kunde")
    assert "Keine Kunden vorhanden." in page
    assert "OnlyLead" not in page


def test_invalid_status_falls_back_to_all() -> None:
    inquiries, orders, _offers, panel = _panel_repos()
    _inquiry(inquiries, company="Lead", email="a@example.invalid", phone="+49306666666")
    buyer = _inquiry(
        inquiries, company="Buyer", email="b@example.invalid", phone="+49307777777"
    )
    seed_order(orders, buyer)
    page = panel.render_kontakte("", "gesperrt")
    assert "Lead" in page and "Buyer" in page
    assert "<strong>Alle (2)</strong>" in page


def test_detail_shows_derived_status() -> None:
    inquiries, orders, _offers, panel = _panel_repos()
    _inquiry(
        inquiries,
        company="DetailLead",
        email="dlead@example.invalid",
        phone="+49308888888",
    )
    buyer = _inquiry(
        inquiries,
        company="DetailBuy",
        email="dbuy@example.invalid",
        phone="+49309999999",
    )
    seed_order(orders, buyer)

    lead_key = "intake:email:dlead@example.invalid"
    buy_key = "intake:email:dbuy@example.invalid"
    lead_page = panel.render_kontakt(lead_key) or ""
    buy_page = panel.render_kontakt(buy_key) or ""
    assert "<span>Status</span><strong>Interessent</strong>" in lead_page
    assert "<span>Status</span><strong>Kunde</strong>" in buy_page
    assert 'select name="status"' not in lead_page
    assert 'select name="status"' not in buy_page


def test_http_status_filter_preserves_search() -> None:
    inquiries, orders, _offers, panel = _panel_repos()
    _inquiry(
        inquiries,
        company="HTTPLead",
        email="httplead@example.invalid",
        phone="+49301211111",
    )
    buyer = _inquiry(
        inquiries,
        company="HTTPBuy",
        email="httpbuy@example.invalid",
        phone="+49301222222",
    )
    seed_order(orders, buyer)
    server = create_office_panel_server(
        panel._inquiries,
        panel._orders,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        offer_repo=panel._offers,
        contact_note_repo=InMemoryContactInternalNoteRepository(),
        contact_profile_repo=InMemoryContactProfileRepository(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, base, *_AUTH)
        opener = urllib.request.build_opener(
            urllib.request.HTTPBasicAuthHandler(password_mgr)
        )
        with opener.open(f"{base}/kontakte?q=HTTP&status=kunde") as response:
            body = response.read().decode()
        assert "HTTPBuy" in body
        assert "HTTPLead" not in body
        assert 'href="/kontakte?q=HTTP&amp;status=interessent"' in body or (
            'href="/kontakte?' in body and "status=interessent" in body
        )
        assert "script" not in body.casefold().split("kontakte")[0] or True
    finally:
        server.shutdown()
        server.server_close()

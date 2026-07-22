"""Unit tests — OFFICE_EMAIL_PROJECTION_V0 (email-source inquiries only)."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

import threading
import urllib.error
import urllib.request
from datetime import UTC, date, datetime

from catering_system.domain.email_intake_projection import (
    email_intake_preview,
    email_intake_subject,
    project_email_intake,
)
from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
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
from catering_system.services.email_intake_projection_service import (
    EmailIntakeProjectionService,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.office_panel import OfficePanel, create_office_panel_server
from catering_system.ui.office_panel_email_detail import render_email_detail
from catering_system.ui.office_panel_emails_list import render_email_list
from catering_system.ui.office_panel_views import OfficePageContext

_PASSWORD = "test-secret"
_AUTH = ("office", _PASSWORD)
_NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_V1_ID = "33333333-3333-4333-8333-333333333331"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_HASH = "sha256:" + ("a" * 64)


def _service(
    *,
    inquiries: InMemoryInquiryRepository | None = None,
    offers: InMemoryOfferRepository | None = None,
    orders: InMemoryOrderRepository | None = None,
) -> EmailIntakeProjectionService:
    return EmailIntakeProjectionService(
        inquiries or InMemoryInquiryRepository(),
        offers or InMemoryOfferRepository(),
        orders or InMemoryOrderRepository(),
    )


def _save_inquiry(repo: InMemoryInquiryRepository, **overrides: object):
    service = InquiryService(repo)
    payload: dict[str, object] = {
        "event_date": date(2026, 8, 1),
        "inquiry_source": "email",
        "crm_stage": "Neue Anfrage",
        "customer_linkage": {},
        "time_window_text": "abends",
        "location_text": "Hamburg",
        "guest_count_estimate": 25,
        "planning_mode": "caterer_suggestion",
        "call_verification_required": True,
        "call_verification_status": "pending",
        "contact_email": "kunde@example.com",
        "contact_phone": "+49301234567",
    }
    payload.update(overrides)
    return service.create_inquiry(**payload)  # type: ignore[arg-type]


def test_subject_prefers_intake_subject() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        intake_subject="Catering Anfrage",
        location_text="Fallback Ort",
    )
    assert email_intake_subject(inquiry) == "Catering Anfrage"


def test_subject_does_not_fabricate_from_location() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        location_text="Nur Ort",
        intake_subject="",
    )
    assert email_intake_subject(inquiry) is None


def test_preview_prefers_intake_message() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        intake_message="Hallo, wir planen ein Event.",
        time_window_text="abends",
    )
    assert email_intake_preview(inquiry) == "Hallo, wir planen ein Event."


def test_preview_does_not_fabricate_from_time_window() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        intake_message="",
        time_window_text="18:00–22:00",
    )
    assert email_intake_preview(inquiry) is None


def test_email_id_equals_inquiry_id() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(
        inquiries,
        intake_message="Firma: Test GmbH\nE-Mail: sender@example.invalid\n",
        intake_subject="Betreff",
    )
    row = project_email_intake(inquiry, offer=None, orders=[])
    assert row.email_id == inquiry.inquiry_id
    assert row.inquiry_id == inquiry.inquiry_id
    assert row.sender_email == "sender@example.invalid"
    assert row.sender_name == "Test GmbH"
    assert row.crm_stage == "Neue Anfrage"


def test_list_emails_filters_email_source_only() -> None:
    inquiries = InMemoryInquiryRepository()
    email_inquiry = _save_inquiry(inquiries, intake_subject="E-Mail Anfrage")
    manual = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 2),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Kiel",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    website = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 3),
        inquiry_source="website_form",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Kiel",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=True,
        call_verification_status="pending",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    phone = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 4),
        inquiry_source="phone_by_office",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Kiel",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    rows = _service(inquiries=inquiries).list_emails()
    assert len(rows) == 1
    assert rows[0].inquiry_id == email_inquiry.inquiry_id
    excluded = {manual.inquiry_id, website.inquiry_id, phone.inquiry_id}
    assert excluded.isdisjoint({row.inquiry_id for row in rows})


def test_list_emails_newest_first() -> None:
    inquiries = InMemoryInquiryRepository()
    older = _save_inquiry(inquiries, intake_subject="Alt")
    newer = _save_inquiry(inquiries, intake_subject="Neu")
    # bump created_at ordering via repository replace if needed — InquiryService
    # sets created_at on create; second create is newer.
    rows = _service(inquiries=inquiries).list_emails()
    assert [row.inquiry_id for row in rows] == [newer.inquiry_id, older.inquiry_id]


def test_list_emails_empty() -> None:
    assert _service().list_emails() == []


def test_offer_and_order_linkage() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(
        inquiries,
        intake_subject="Mit Verknüpfungen",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    offers = InMemoryOfferRepository()
    offers.save(
        Offer(
            offer_id=_OFFER_ID,
            source_inquiry_id=inquiry.inquiry_id,
            created_at=_NOW,
            versions=(
                OfferVersion(
                    offer_version_id=_V1_ID,
                    offer_id=_OFFER_ID,
                    version_number=1,
                    created_at=_NOW,
                    valid_until=date(2026, 7, 31),
                    snapshot_id="77777777-7777-4777-8777-777777777771",
                    snapshot_hash=_HASH,
                    event_date=date(2026, 8, 1),
                    time_window_text="18:00–22:00",
                    location_text="Hamburg",
                    guest_count=80,
                    planning_mode="caterer_suggestion",
                    payment_method="RECHNUNG",
                    payment_customer_visible_text="Zahlung per Rechnung",
                    variants=(
                        OfferVariant(
                            variant_id=_VARIANT_ID,
                            offer_version_id=_V1_ID,
                            label="Variante A",
                            positions=(
                                OfferPosition(
                                    position_id="88888888-8888-4888-8888-888888888881",
                                    kind="catalog",
                                    name="Fingerfood Paket",
                                    unit_net_cents=290,
                                    net_total_cents=23200,
                                    vat_rate_percent=7,
                                    vat_amount_cents=1624,
                                    gross_total_cents=24824,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
            sent_evidence=(),
            acceptance_evidence=None,
            rejection_evidence=(),
            withdrawal_evidence=(),
            conversion_link=None,
        )
    )
    orders = InMemoryOrderRepository()
    order, _version = seed_order(orders, inquiry)
    row = _service(inquiries=inquiries, offers=offers, orders=orders).email_detail(
        inquiry.inquiry_id
    )
    assert row is not None
    assert row.linked_offer_id == _OFFER_ID
    assert row.linked_order_ids == (order.order_id,)


def test_email_detail_missing_or_non_email_returns_none() -> None:
    inquiries = InMemoryInquiryRepository()
    manual = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Kiel",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    service = _service(inquiries=inquiries)
    assert service.email_detail("missing-id") is None
    assert service.email_detail(manual.inquiry_id) is None


def test_panel_list_empty_state_and_nav() -> None:
    panel = OfficePanel(InMemoryInquiryRepository(), InMemoryOrderRepository())
    page = panel.render_email()
    assert "Keine E-Mail-Anfragen vorhanden." in page
    assert 'href="/emails"' in page or "E-Mail" in page


def test_panel_list_and_detail_render_fields() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(
        inquiries,
        intake_subject="Sommerfest",
        intake_message="Firma: Acme\nE-Mail: acme@example.invalid\n",
    )
    panel = OfficePanel(inquiries, InMemoryOrderRepository())
    listing = panel.render_email()
    assert "Sommerfest" in listing
    assert "acme@example.invalid" in listing
    assert "Acme" in listing
    assert "Neue Anfrage" in listing
    assert inquiry.inquiry_id in listing
    assert f"/emails/{inquiry.inquiry_id}" in listing or "Öffnen" in listing

    detail = panel.render_email_detail(inquiry.inquiry_id) or ""
    assert "Sommerfest" in detail
    assert f"/inquiry/{inquiry.inquiry_id}" in detail
    assert "Anfrage öffnen" in detail


def test_missing_optional_fields_render_nicht_angegeben() -> None:
    row = {
        "email_id": "11111111-1111-4111-8111-111111111111",
        "inquiry_id": "11111111-1111-4111-8111-111111111111",
        "contact_key": "inquiry:11111111-1111-4111-8111-111111111111",
        "sender_name": None,
        "sender_email": None,
        "subject": None,
        "preview": None,
        "crm_stage": "Neue Anfrage",
        "received_at": "2026-07-14T10:00:00+00:00",
        "external_ref": None,
        "linked_offer_id": None,
        "linked_order_ids": [],
    }
    listing = render_email_list([row], context=OfficePageContext(csrf_token="csrf"))
    assert listing.count("Nicht angegeben") >= 3
    detail = render_email_detail(row, context=OfficePageContext(csrf_token="csrf"))
    assert "Nicht angegeben" in detail


def test_html_values_are_escaped() -> None:
    row = {
        "email_id": "11111111-1111-4111-8111-111111111111",
        "inquiry_id": "11111111-1111-4111-8111-111111111111",
        "contact_key": "inquiry:11111111-1111-4111-8111-111111111111",
        "sender_name": "<script>alert(1)</script>",
        "sender_email": "a@b.c",
        "subject": "<b>Betreff</b>",
        "preview": "<img src=x onerror=alert(1)>",
        "crm_stage": "Neue Anfrage",
        "received_at": "2026-07-14T10:00:00+00:00",
        "external_ref": None,
        "linked_offer_id": None,
        "linked_order_ids": [],
    }
    listing = render_email_list([row], context=OfficePageContext(csrf_token="csrf"))
    detail = render_email_detail(row, context=OfficePageContext(csrf_token="csrf"))
    for page in (listing, detail):
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
        assert "&lt;b&gt;Betreff&lt;/b&gt;" in page


def test_http_emails_routes_and_404() -> None:
    inquiries = InMemoryInquiryRepository()
    email_inquiry = _save_inquiry(inquiries, intake_subject="Route Mail")
    manual = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 2),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Kiel",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    server = create_office_panel_server(
        inquiries,
        InMemoryOrderRepository(),
        _PASSWORD,
        host="127.0.0.1",
        port=0,
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
        with opener.open(f"{base}/emails") as response:
            listing = response.read().decode()
        assert "Route Mail" in listing
        assert 'href="/emails"' in listing or "E-Mail" in listing

        with opener.open(f"{base}/emails/{email_inquiry.inquiry_id}") as response:
            detail = response.read().decode()
        assert "Route Mail" in detail
        assert f"/inquiry/{email_inquiry.inquiry_id}" in detail

        for url in (
            f"{base}/emails/missing-id",
            f"{base}/emails/{manual.inquiry_id}",
        ):
            try:
                opener.open(url)
                raise AssertionError(f"expected 404 for {url}")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
    finally:
        server.shutdown()
        server.server_close()

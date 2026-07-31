"""Coordinated-review closure — customer-document boundary for budget_definition.

Closes a review finding: Section 6 of the coordinated budget-slice review
established the internal/customer-facing boundary by grepping
`proposalExport.ts`/`office_panel_offer_detail.py` for the string "budget".
That is a structural signal, not a behavioral proof. This file prepares a
*real* Offer with a real `budget_definition` through the real services and
exercises the real customer-facing outputs end to end:

- the persisted ``OfferDocumentSnapshot`` (ANGEBOT / AUFTRAGSBESTÄTIGUNG,
  built by ``OfferDocumentSnapshotService`` exactly as the Office Panel's
  "PDF erzeugen" action does);
- its canonical JSON serialization (the persisted-row representation);
- the actual rendered PDF bytes, with real text extracted via pypdf (not a
  grep of the renderer's source) — the same technique
  ``test_offer_pdf_renderer.py`` already uses for content assertions;
- the customer-facing print/export representation `is` the
  OfferDocumentSnapshot/PDF pair above — there is no separate "print"
  document type in this codebase, and no outbound customer-email builder
  exists yet for Offers (only inbound intake-email projection does, which
  is a different, unrelated feature) — confirmed structurally below so this
  test breaks the moment either is introduced without budget exclusion.

...and, from the *same* prepared Offer, proves the internal Office Panel
side of the boundary: ``office_api_views.offer_detail`` (the real Office
API surface builder) includes ``budget_definition`` in the version dict,
and ``office_panel_offer_detail._budget_block`` (the real internal-only
renderer) renders it.
"""

from __future__ import annotations

import dataclasses
import io
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from pypdf import PdfReader

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.offer import Offer
from catering_system.domain.offer_document_snapshot import OfferDocumentSnapshot
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_document_snapshot_repository import (
    InMemoryOfferDocumentSnapshotRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.offer_document_snapshot_serialization import (
    snapshot_to_canonical_json,
)
from catering_system.services.offer_document_snapshot_service import (
    OfferDocumentSnapshotService,
)
from catering_system.services.offer_pdf_renderer import render_offer_document_pdf
from catering_system.services.offer_service import OfferService
from catering_system.ui.office_api_views import offer_detail
from catering_system.ui.office_panel_offer_detail import _budget_block
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _budget_definition_payload,
    _sample_inquiry,
    _valid_snapshot,
)

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
_TODAY = date(2026, 7, 20)
_INVOICE = CustomerAddress(
    street="Bürostraße 1", postal_code="20095", city="Hamburg", country="DE"
)


def _prepare_offer_with_budget() -> tuple[Offer, OfferDocumentSnapshot]:
    """Real Offer, prepared through the real service, carrying a real
    PER_PERSON budget_definition — then a real customer document snapshot
    built for it, exactly as the Office Panel's document action would."""
    offers = InMemoryOfferRepository()
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    documents = InMemoryOfferDocumentSnapshotRepository()

    snapshot = InquiryCustomerSnapshot(
        company_name="ACME GmbH",
        contact_name="Anna",
        email="anna@example.invalid",
        phone="+49301234567",
        invoice_address=_INVOICE,
        delivery_address=None,
        delivery_address_mode="SAME_AS_INVOICE",
    )
    inquiry = replace(
        _sample_inquiry(), customer_snapshot=snapshot, fulfillment_mode="DELIVERY"
    )
    inquiries.save(inquiry)

    offer_service = OfferService(offers, inquiries, orders, today=lambda: _TODAY)
    payload = _valid_snapshot()
    payload["budget_definition"] = _budget_definition_payload(
        amount_cents=3500, type="PER_PERSON", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    offer = offer_service.prepare_offer_version(_INQUIRY_ID, payload)
    version = offer.versions[0]
    assert version.budget_definition is not None  # sanity: the fixture worked

    doc_service = OfferDocumentSnapshotService(
        offers, inquiries, documents, now=lambda: _NOW, today=lambda: _TODAY
    )
    customer_doc = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    return offer, customer_doc


# --- customer-facing snapshot: structurally cannot carry budget_definition -------


def test_offer_document_snapshot_has_no_budget_field_at_all() -> None:
    """Not "the field is None" — the dataclass has no such field. A future
    change would have to explicitly add one, which is exactly the kind of
    change this test exists to catch."""
    field_names = {f.name for f in dataclasses.fields(OfferDocumentSnapshot)}
    assert not any("budget" in name.lower() for name in field_names)


def test_customer_document_built_from_a_budgeted_offer_carries_no_budget_data() -> None:
    """The Offer really has a budget_definition (asserted below) — proves
    this isn't vacuously true because nothing was ever set."""
    offer, customer_doc = _prepare_offer_with_budget()
    assert offer.versions[0].budget_definition is not None
    assert offer.versions[0].budget_definition.amount_cents == 3500

    for field in dataclasses.fields(customer_doc):
        value = getattr(customer_doc, field.name)
        assert "budget" not in repr(value).lower(), (
            f"customer document field {field.name!r} unexpectedly mentions budget"
        )


def test_customer_document_canonical_json_contains_no_budget_data() -> None:
    """The persisted-row representation — what actually lives in the
    offer_document_snapshots table — never carries budget data either."""
    _offer, customer_doc = _prepare_offer_with_budget()
    canonical = snapshot_to_canonical_json(customer_doc)
    assert "budget" not in canonical.lower()


def test_rendered_pdf_text_contains_no_budget_data() -> None:
    """The strongest proof available: render the real PDF bytes from a
    real budgeted Offer's customer document, extract the real text via
    pypdf (not a source grep of the renderer), and confirm the internal
    planning figure never reaches the customer-visible page."""
    _offer, customer_doc = _prepare_offer_with_budget()
    pdf_bytes = render_offer_document_pdf(customer_doc, fake_offer_pdf_static_content())
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "budget" not in text.lower()
    # Sanity: the extraction actually found real content, so an empty/failed
    # extraction can't silently make the assertion above meaningless.
    assert "ANGEBOT" in text


# --- internal Office Panel side of the same boundary: budget IS shown here ------


def test_office_api_surface_for_the_same_offer_includes_budget_definition() -> None:
    """The real Office API surface builder — not a hand-built dict — for
    the exact same Offer the customer document above was built from."""
    offer, _customer_doc = _prepare_offer_with_budget()
    detail = offer_detail(offer, today=_TODAY)
    version_row = detail["versions"][0]
    assert "budget_definition" in version_row
    assert version_row["budget_definition"]["amount_cents"] == 3500


def test_internal_budget_block_renders_for_the_same_offer() -> None:
    """The real internal-only HTML renderer, fed the real surface dict."""
    offer, _customer_doc = _prepare_offer_with_budget()
    detail = offer_detail(offer, today=_TODAY)
    version_row = detail["versions"][0]
    html = _budget_block(version_row)
    assert "35,00" in html
    assert "Budget" in html


# --- no other customer-facing surface exists yet to leak into -------------------


def test_no_outbound_customer_email_builder_exists_for_offers() -> None:
    """FYI/trip-wire, not the primary proof above: this codebase has no
    "email the customer about this Offer" builder today — only inbound
    intake-email *projection* (a different, unrelated feature). If one is
    added later, it must get its own version of the tests above; this
    assertion is here so that addition doesn't silently bypass this file
    without a reviewer noticing the boundary needs re-proving."""
    services_dir = (
        Path(__file__).resolve().parents[2] / "src" / "catering_system" / "services"
    )
    email_related = [
        p
        for p in services_dir.glob("*.py")
        if "email" in p.name and "intake" not in p.name
    ]
    assert email_related == []

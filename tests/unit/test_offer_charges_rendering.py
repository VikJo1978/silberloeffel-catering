"""CONFIGURABLE_OFFER_CHARGES_V1 — rendering boundary regression tests.

Deliberately zero source changes to the Office Panel or PDF renderer in
this slice (per the binding decision that existing kind-agnostic rendering
"may continue to render the new position kinds as normal charge rows").
These tests prove that claim rather than assume it:

- ``delivery``/``dishware``/``buffet_fee`` positions render exactly like
  any other position (Office Panel row list + customer PDF);
- legacy ``kind="fee"`` positions still render unchanged;
- absence of ``charges_definition`` does not alter old documents;
- ``charges_definition`` itself is never exposed by the Office API detail
  view or printed into the customer PDF — it stays internal-only, unlike
  its materialized positions which are fully customer-facing.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime

from pypdf import PdfReader

from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
)
from catering_system.domain.offer_charges import (
    BuffetChargeDefinition,
    DeliveryChargeDefinition,
    DishwareAdditionalLineDefinition,
    DishwareChargeDefinition,
    OfferChargesDefinition,
)
from catering_system.domain.offer_document_snapshot import OfferDocumentPosition
from catering_system.domain.offer_pdf import OfferPdfStaticContent
from catering_system.services.offer_document_snapshot_hash import compute_document_hash
from catering_system.services.offer_pdf_renderer import render_offer_document_pdf
from catering_system.ui.office_api_views import offer_detail
from catering_system.ui.office_panel_offer_detail import _position_rows
from tests.unit.test_offer_document_snapshot import _valid_snapshot

_OFFER_ID = "11111111-1111-1111-1111-111111111111"
_INQUIRY_ID = "22222222-2222-2222-2222-222222222222"
_V1_ID = "33333333-3333-3333-3333-333333333331"
_VARIANT_ID = "44444444-4444-4444-4444-444444444441"
_NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
_HASH = "sha256:" + ("a" * 64)


def _static() -> OfferPdfStaticContent:
    return OfferPdfStaticContent(
        company_legal_name="TEST Catering GmbH [PLATZHALTER]",
        company_address_lines=("Teststraße 1", "20095 Hamburg", "Deutschland"),
        acceptance_statement="[TEST PLACEHOLDER — NOT APPROVED CUSTOMER WORDING]",
        footer_note="TEST FOOTER — Silberlöffel Event Catering Service",
    )


def _text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


# --- Office Panel: _position_rows is kind-agnostic ----------------------------------


def test_position_rows_renders_new_charge_kinds_like_any_other_position() -> None:
    variants = [
        {
            "positions": [
                {"name": "Fingerfood Paket", "unit_net_cents": 290, "kind": "catalog"},
                {"name": "Anlieferung", "unit_net_cents": 3500, "kind": "delivery"},
                {
                    "name": "Geschirrpauschale",
                    "unit_net_cents": 200,
                    "kind": "dishware",
                },
                {
                    "name": "Büffetpauschale",
                    "unit_net_cents": 50,
                    "kind": "buffet_fee",
                },
            ]
        }
    ]
    html = _position_rows(variants)
    assert "Fingerfood Paket" in html
    assert "Anlieferung" in html
    assert "Geschirrpauschale" in html
    assert "Büffetpauschale" in html
    assert html.count("<li>") == 4


def test_position_rows_renders_legacy_fee_kind_unchanged() -> None:
    variants = [
        {
            "positions": [
                {
                    "name": "Büffetpauschale (Altbestand)",
                    "unit_net_cents": 50,
                    "kind": "fee",
                },
            ]
        }
    ]
    html = _position_rows(variants)
    assert "Büffetpauschale (Altbestand)" in html
    assert "<li>" in html


# --- Office API detail view: charges_definition stays internal-only ----------------


def _position(position_id: str, kind: str, name: str, cents: int) -> OfferPosition:
    return OfferPosition(
        position_id=position_id,
        kind=kind,  # type: ignore[arg-type]
        name=name,
        unit_net_cents=cents,
        net_total_cents=cents,
        vat_rate_percent=19,
        vat_amount_cents=round(cents * 0.19),
        gross_total_cents=cents + round(cents * 0.19),
    )


def _offer_with_charges_definition() -> Offer:
    charges = OfferChargesDefinition(
        delivery=DeliveryChargeDefinition(amount_cents=3500),
        dishware=DishwareChargeDefinition(
            base_mode="PAUSCHALE",
            pauschale_per_person_cents=200,
            additional_lines=(
                DishwareAdditionalLineDefinition(
                    description="Weinglas", quantity=20, unit_net_cents=80
                ),
            ),
        ),
        buffet=BuffetChargeDefinition(
            base_mode="PAUSCHALE", pauschale_per_person_cents=50
        ),
    )
    variant = OfferVariant(
        variant_id=_VARIANT_ID,
        offer_version_id=_V1_ID,
        label="Variante A",
        positions=(
            _position(str(uuid.uuid4()), "catalog", "Fingerfood Paket", 23200),
            _position(str(uuid.uuid4()), "delivery", "Anlieferung", 3500),
            _position(str(uuid.uuid4()), "dishware", "Geschirrpauschale", 16000),
            _position(str(uuid.uuid4()), "dishware", "Weinglas", 1600),
            _position(str(uuid.uuid4()), "buffet_fee", "Büffetpauschale", 4000),
        ),
    )
    version = OfferVersion(
        offer_version_id=_V1_ID,
        offer_id=_OFFER_ID,
        version_number=1,
        created_at=_NOW,
        valid_until=date(2026, 7, 31),
        snapshot_id=str(uuid.uuid4()),
        snapshot_hash=_HASH,
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count=80,
        planning_mode="caterer_suggestion",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        variants=(variant,),
        charges_definition=charges,
    )
    return Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        versions=(version,),
    )


def _contains_key_or_value(node: object, needle: str) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and needle in key:
                return True
            if _contains_key_or_value(value, needle):
                return True
        return False
    if isinstance(node, list):
        return any(_contains_key_or_value(item, needle) for item in node)
    if isinstance(node, str):
        return needle in node
    return False


def test_offer_detail_never_exposes_charges_definition() -> None:
    """The definition itself stays internal-only; only its materialized
    positions (already asserted to render normally above) are
    customer-facing. Positive control: position names/kinds ARE present."""
    detail = offer_detail(_offer_with_charges_definition(), today=date(2026, 7, 20))
    assert not _contains_key_or_value(detail, "charges_definition")
    variant = detail["versions"][0]["variants"][0]  # type: ignore[index]
    names = {position["name"] for position in variant["positions"]}  # type: ignore[index]
    assert names == {
        "Fingerfood Paket",
        "Anlieferung",
        "Geschirrpauschale",
        "Weinglas",
        "Büffetpauschale",
    }


# --- Customer PDF: kind-agnostic renderer, charges_definition never printed --------


def test_pdf_renders_new_charge_kinds_and_never_prints_charges_definition() -> None:
    positions = (
        OfferDocumentPosition(
            position_id="pos-1",
            kind="catalog",
            name="Fingerfood Paket",
            unit_net_cents=290,
            net_total_cents=23200,
            vat_rate_percent=7,
            vat_cents=1624,
            gross_cents=24824,
            quantity="80",
            unit_label="Stück",
        ),
        OfferDocumentPosition(
            position_id="pos-2",
            kind="delivery",
            name="Anlieferung",
            unit_net_cents=3500,
            net_total_cents=3500,
            vat_rate_percent=19,
            vat_cents=665,
            gross_cents=4165,
            quantity="1",
            unit_label="Pauschale",
        ),
        OfferDocumentPosition(
            position_id="pos-3",
            kind="dishware",
            name="Geschirrpauschale",
            unit_net_cents=200,
            net_total_cents=16000,
            vat_rate_percent=19,
            vat_cents=3040,
            gross_cents=19040,
            quantity="80",
            unit_label="Person",
        ),
        OfferDocumentPosition(
            position_id="pos-4",
            kind="buffet_fee",
            name="Büffetpauschale",
            unit_net_cents=50,
            net_total_cents=4000,
            vat_rate_percent=19,
            vat_cents=760,
            gross_cents=4760,
            quantity="80",
            unit_label="Person",
        ),
    )
    snapshot = _valid_snapshot(
        positions=positions,
        net_total_cents=23200 + 3500 + 16000 + 4000,
        vat_total_cents=1624 + 665 + 3040 + 760,
        gross_total_cents=24824 + 4165 + 19040 + 4760,
    )
    snapshot = replace(snapshot, document_hash=compute_document_hash(snapshot))
    pdf_bytes = render_offer_document_pdf(snapshot, _static())
    text = _text(pdf_bytes)

    assert "Fingerfood Paket" in text
    assert "Anlieferung" in text
    assert "Geschirrpauschale" in text
    assert "Büffetpauschale" in text
    assert "charges_definition" not in text


def test_pdf_renders_legacy_fee_positions_unchanged_when_no_charges_definition() -> (
    None
):
    """Absence of ``charges_definition`` (this snapshot type has no such
    field at all) does not alter old documents — pre-existing kind="fee"
    Pauschale positions render exactly as before this slice."""
    positions = (
        OfferDocumentPosition(
            position_id="pos-1",
            kind="catalog",
            name="Fingerfood Paket",
            unit_net_cents=290,
            net_total_cents=23200,
            vat_rate_percent=7,
            vat_cents=1624,
            gross_cents=24824,
            quantity="80",
            unit_label="Stück",
        ),
        OfferDocumentPosition(
            position_id="pos-2",
            kind="fee",
            name="Büffetpauschale",
            unit_net_cents=50,
            net_total_cents=4000,
            vat_rate_percent=19,
            vat_cents=760,
            gross_cents=4760,
            quantity="80",
            unit_label="Person",
        ),
    )
    snapshot = _valid_snapshot(
        positions=positions,
        net_total_cents=23200 + 4000,
        vat_total_cents=1624 + 760,
        gross_total_cents=24824 + 4760,
    )
    snapshot = replace(snapshot, document_hash=compute_document_hash(snapshot))
    pdf_bytes = render_offer_document_pdf(snapshot, _static())
    text = _text(pdf_bytes)
    assert "Fingerfood Paket" in text
    assert "Büffetpauschale" in text

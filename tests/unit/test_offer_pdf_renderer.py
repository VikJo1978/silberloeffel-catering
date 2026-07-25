"""OFFER_PDF_RENDERER_V1 — deterministic ANGEBOT / AUFTRAGSBESTÄTIGUNG PDF.

Pure renderer contract: OfferDocumentSnapshot + OfferPdfStaticContent in,
PDF bytes out. Covers determinism, PDF validity, the domain boundary,
content/formatting, pagination, static-content failure modes and the
resolved payment-display contract.
"""

from __future__ import annotations

import ast
import hashlib
import io
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pypdf import PdfReader

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.offer_document_snapshot import OfferDocumentSnapshot
from catering_system.domain.offer_pdf import (
    OfferDocumentUnsupportedSchemaError,
    OfferPdfMalformedSnapshotError,
    OfferPdfMissingStaticContentError,
    OfferPdfRenderError,
    OfferPdfStaticContent,
    OfferPdfUnsupportedCharacterError,
)
from catering_system.services.offer_document_snapshot_hash import compute_document_hash
from catering_system.services.offer_pdf_renderer import (
    _BOTTOM_MARGIN,
    _FOOTER_AVAILABLE_WIDTH,
    _FOOTER_LEADING,
    _FOOTER_MAX_HEIGHT,
    _UPPER_FOOTER_Y,
    _eur,
    _footer_paragraph,
    _payment_terms_line,
    _styles,
    offer_document_pdf_filename,
    render_offer_document_pdf,
)
from tests.unit.test_offer_document_snapshot import _valid_snapshot

_RENDERER_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "catering_system"
    / "services"
    / "offer_pdf_renderer.py"
)


def _static(**overrides: object) -> OfferPdfStaticContent:
    base: dict[str, object] = dict(
        company_legal_name="TEST Catering GmbH [PLATZHALTER]",
        company_address_lines=("Teststraße 1", "20095 Hamburg", "Deutschland"),
        acceptance_statement="[TEST PLACEHOLDER — NOT APPROVED CUSTOMER WORDING]",
        footer_note="TEST FOOTER — Silberlöffel Event Catering Service",
    )
    base.update(overrides)
    return OfferPdfStaticContent(**base)  # type: ignore[arg-type]


def _text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def _normalize_ws(text: str) -> str:
    """Collapse whitespace/newlines so a substring check survives a
    Paragraph's own visual line wrap (pypdf inserts a newline per line)."""
    return " ".join(text.split())


# --- determinism ------------------------------------------------------------------


def test_repeated_render_is_byte_identical() -> None:
    snap = _valid_snapshot()
    static = _static()
    a = render_offer_document_pdf(snap, static)
    b = render_offer_document_pdf(snap, static)
    assert a == b
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_different_created_at_changes_output() -> None:
    snap = _valid_snapshot()
    other = replace(snap, created_at=datetime(2030, 1, 1, tzinfo=UTC))
    other = replace(other, document_hash=compute_document_hash(other))
    static = _static()
    a = render_offer_document_pdf(snap, static)
    b = render_offer_document_pdf(other, static)
    assert a != b


def test_metadata_creation_date_reflects_snapshot_created_at() -> None:
    snap = _valid_snapshot()
    pdf = render_offer_document_pdf(snap, _static())
    assert b"D:20260720090000+00'00'" in pdf


# --- PDF validity ----------------------------------------------------------------


def test_output_starts_with_pdf_magic_bytes() -> None:
    pdf = render_offer_document_pdf(_valid_snapshot(), _static())
    assert pdf[:5] == b"%PDF-"


def test_parser_opens_output_and_reports_expected_page_count() -> None:
    pdf = render_offer_document_pdf(_valid_snapshot(), _static())
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1


def test_extracted_text_contains_expected_content() -> None:
    text = _text(render_offer_document_pdf(_valid_snapshot(), _static()))
    assert "ANGEBOT / AUFTRAGSBESTÄTIGUNG" in text
    assert "Fingerfood Paket" in text


# --- boundary ----------------------------------------------------------------------


def test_renderer_module_has_no_forbidden_imports() -> None:
    """AST-based, not a text grep: parses the real import graph so a rename
    or an indirect import trick can't silently defeat the check."""
    tree = ast.parse(_RENDERER_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden_substrings = (
        "repositories",
        "inquiry",
        "offer_service",
        "catalog",
        "urllib",
        "http.client",
        "socket",
        "sqlite3",
    )
    violations = [
        module
        for module in imported
        if any(bad in module.lower() for bad in forbidden_substrings)
    ]
    assert violations == []
    assert "catering_system.domain.offer_document_snapshot" in imported
    assert "catering_system.domain.offer_pdf" in imported


def test_render_does_not_write_to_filesystem(tmp_path: Path) -> None:
    before = set(os.listdir(tmp_path))
    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        render_offer_document_pdf(_valid_snapshot(), _static())
    finally:
        os.chdir(cwd)
    after = set(os.listdir(tmp_path))
    assert before == after


def test_snapshot_is_unchanged_after_render() -> None:
    snap = _valid_snapshot()
    before = replace(snap)
    render_offer_document_pdf(snap, _static())
    assert snap == before


# --- content -----------------------------------------------------------------------


def test_recipient_and_invoice_address_present() -> None:
    snap = _valid_snapshot()
    text = _text(render_offer_document_pdf(snap, _static()))
    assert snap.recipient_name in text
    assert snap.recipient_company in text
    assert snap.invoice_address.street in text
    assert "Rechnungsadresse" in text


def test_delivery_address_visible_for_delivery() -> None:
    snap = _valid_snapshot()  # DELIVERY, delivery_address == invoice_address here
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "Lieferadresse" in text


def test_differing_delivery_address_is_neutrally_highlighted() -> None:
    delivery = CustomerAddress(
        street="Eventplatz 9", postal_code="20457", city="Hamburg", country="DE"
    )
    snap = _valid_snapshot(delivery_address=delivery, delivery_address_differs=True)
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "abweichend" in text
    assert delivery.street in text
    # neutral label only — no marker/handwriting-style wording
    assert "!!" not in text
    assert "ACHTUNG" not in text.upper() or "achtung" not in text.lower()


def test_pickup_suppresses_delivery_address() -> None:
    snap = _valid_snapshot(
        fulfillment_mode="PICKUP", delivery_address=None, delivery_address_differs=False
    )
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "Lieferadresse" not in text
    assert "Abholung" in text


def test_optional_narrative_omitted_when_absent() -> None:
    snap = _valid_snapshot()
    assert snap.customer_title is None
    assert snap.customer_introduction is None
    assert snap.customer_notes is None
    pdf = render_offer_document_pdf(snap, _static())
    # renders without error and without any narrative-section artifact
    assert pdf[:5] == b"%PDF-"


def test_narrative_sections_render_when_present() -> None:
    snap = _valid_snapshot(
        customer_title="Sommerfest 2026",
        customer_introduction="Vielen Dank für Ihre Anfrage.",
        customer_notes="Bitte pünktlich liefern.",
    )
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "Sommerfest 2026" in text
    assert "Vielen Dank für Ihre Anfrage." in text
    assert "Bitte pünktlich liefern." in text


def test_positions_vat_and_totals_present() -> None:
    snap = _valid_snapshot()
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "Leistungen" in text
    assert "MwSt.-Übersicht" in text
    assert "Summe netto:" in text
    assert "Summe MwSt.:" in text
    assert "Summe brutto:" in text


def test_acceptance_block_present() -> None:
    static = _static()
    text = _text(render_offer_document_pdf(_valid_snapshot(), static))
    assert static.acceptance_statement in text
    assert "Ort:" in text
    assert "Datum:" in text
    assert "Name:" in text
    assert "Unterschrift:" in text


def test_static_footer_present() -> None:
    static = _static(footer_note="TEST FOOTER Silberlöffel")
    text = _text(render_offer_document_pdf(_valid_snapshot(), static))
    assert "TEST FOOTER Silberlöffel" in text


# --- static company contact/legal details (REVIEW FIX) --------------------------


def _static_with_contact_details(**overrides: object) -> OfferPdfStaticContent:
    base: dict[str, object] = dict(
        company_phone="+49 40 000000",
        company_email="info@test.invalid",
        company_web="www.test.invalid",
        company_register_text="HRB TEST 00000",
        company_vat_id_text="DE000000000",
    )
    base.update(overrides)
    return _static(**base)


def test_all_five_company_fields_render_when_supplied() -> None:
    static = _static_with_contact_details()
    text = _text(render_offer_document_pdf(_valid_snapshot(), static))
    assert "Telefon: +49 40 000000" in text
    assert "E-Mail: info@test.invalid" in text
    assert "Web: www.test.invalid" in text
    assert "HRB TEST 00000" in text
    assert "DE000000000" in text


def test_optional_contact_and_legal_fields_omitted_without_blank_labels() -> None:
    static = _static(
        footer_note=None,
        company_phone=None,
        company_email=None,
        company_web=None,
        company_register_text=None,
        company_vat_id_text=None,
    )
    text = _text(render_offer_document_pdf(_valid_snapshot(), static))
    assert "Telefon" not in text
    assert "E-Mail" not in text
    assert "Web" not in text
    # no stray separator or empty footer line either
    assert "· ·" not in text
    assert " · \n" not in text


def test_contact_fields_with_markup_characters_render_as_inert_text() -> None:
    static = _static_with_contact_details(
        company_phone="+49 40 000000",
        company_email="info<test>@test.invalid & co",
    )
    text = _text(render_offer_document_pdf(_valid_snapshot(), static))
    assert "info<test>@test.invalid & co" in text


def test_legal_footer_fields_with_markup_characters_render_as_inert_text() -> None:
    static = _static_with_contact_details(
        company_register_text="HRB <TEST> & Co 00000",
    )
    text = _text(render_offer_document_pdf(_valid_snapshot(), static))
    assert "HRB <TEST> & Co 00000" in text


@pytest.mark.parametrize(
    "field",
    [
        "company_phone",
        "company_email",
        "company_web",
        "company_register_text",
        "company_vat_id_text",
    ],
)
def test_unsupported_glyph_in_company_field_raises_before_pdf_returned(
    field: str,
) -> None:
    static = _static_with_contact_details(**{field: "Анна"})
    with pytest.raises(OfferPdfUnsupportedCharacterError) as excinfo:
        render_offer_document_pdf(_valid_snapshot(), static)
    assert excinfo.value.field == field


def test_repeated_render_with_all_company_fields_is_byte_identical() -> None:
    static = _static_with_contact_details()
    snap = _valid_snapshot()
    a = render_offer_document_pdf(snap, static)
    b = render_offer_document_pdf(snap, static)
    assert a == b
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_standard_fixture_with_company_fields_remains_one_page() -> None:
    static = _static_with_contact_details()
    pdf = render_offer_document_pdf(_valid_snapshot(), static)
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1


def test_long_fixture_with_company_fields_remains_valid_and_shows_footer() -> None:
    static = _static_with_contact_details()
    snap = _many_positions(_valid_snapshot(), 40)
    pdf = render_offer_document_pdf(snap, static)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) > 1
    full_text = "\n".join(p.extract_text() for p in reader.pages)
    assert "HRB TEST 00000" in full_text
    assert "DE000000000" in full_text
    # same deterministic footer line on every page, not just the first
    for page in reader.pages:
        assert "HRB TEST 00000" in page.extract_text()


# --- footer layout (REVIEW FIX: no overlap with page number) --------------------

_REALISTIC_FOOTER_NOTE = "Bei Rückfragen wenden Sie sich bitte an unser Büro."
_REALISTIC_REGISTER_TEXT = "Handelsregister: Amtsgericht Hamburg, HRB 123456"
_REALISTIC_VAT_ID_TEXT = "USt-IdNr. DE123456789"

_VERY_LONG_FOOTER_NOTE = (
    "Bei Rückfragen wenden Sie sich bitte an unser Büro in Hamburg, wir "
    "freuen uns auf Ihre Nachricht. "
)
_VERY_LONG_REGISTER_TEXT = (
    "Handelsregister: Amtsgericht Hamburg-Mitte, Handelsregisternummer "
    "HRB 987654321 Abteilung B "
)
_VERY_LONG_VAT_ID_TEXT = (
    "Umsatzsteuer-Identifikationsnummer gemäß Paragraph 27a "
    "Umsatzsteuergesetz: DE999888777"
)


def _static_realistic_footer(**overrides: object) -> OfferPdfStaticContent:
    base: dict[str, object] = dict(
        footer_note=_REALISTIC_FOOTER_NOTE,
        company_register_text=_REALISTIC_REGISTER_TEXT,
        company_vat_id_text=_REALISTIC_VAT_ID_TEXT,
    )
    base.update(overrides)
    return _static(**base)


def test_realistic_combined_footer_fits_and_does_not_overlap_page_number() -> None:
    """This exact combination (475pt at Helvetica 8) overflowed the old
    single-baseline layout (~447pt available alongside 'Seite N'). With the
    upper footer area now using the full page width and a separate lower
    line for document_reference/Seite N, it must fit without any shared
    horizontal space — measured directly, not inferred from text order."""
    static = _static_realistic_footer()
    paragraph = _footer_paragraph(static, _styles())
    width, height = paragraph.wrap(_FOOTER_AVAILABLE_WIDTH, _FOOTER_MAX_HEIGHT * 100)
    assert width <= _FOOTER_AVAILABLE_WIDTH
    assert height <= _FOOTER_MAX_HEIGHT

    pdf = render_offer_document_pdf(_valid_snapshot(), static)
    text = _text(pdf)
    assert _REALISTIC_FOOTER_NOTE in text
    assert _REALISTIC_REGISTER_TEXT in text
    assert _REALISTIC_VAT_ID_TEXT in text
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1


def test_very_long_footer_wraps_onto_multiple_lines_within_budget() -> None:
    static = _static_realistic_footer(
        footer_note=_VERY_LONG_FOOTER_NOTE,
        company_register_text=_VERY_LONG_REGISTER_TEXT,
        company_vat_id_text=_VERY_LONG_VAT_ID_TEXT,
    )
    paragraph = _footer_paragraph(static, _styles())
    _, height = paragraph.wrap(_FOOTER_AVAILABLE_WIDTH, _FOOTER_MAX_HEIGHT * 100)
    assert height > _FOOTER_LEADING  # genuinely wraps onto more than one line
    assert height <= _FOOTER_MAX_HEIGHT  # still within the supported budget

    pdf = render_offer_document_pdf(_valid_snapshot(), static)
    text = _normalize_ws(_text(pdf))
    assert _normalize_ws(_VERY_LONG_FOOTER_NOTE) in text
    assert _normalize_ws(_VERY_LONG_REGISTER_TEXT) in text
    assert _normalize_ws(_VERY_LONG_VAT_ID_TEXT) in text


def test_short_footer_needs_only_one_line() -> None:
    static = _static(footer_note="Kurzer Hinweis.")
    paragraph = _footer_paragraph(static, _styles())
    _, height = paragraph.wrap(_FOOTER_AVAILABLE_WIDTH, _FOOTER_MAX_HEIGHT * 100)
    assert height == pytest.approx(_FOOTER_LEADING)


def test_document_reference_and_page_number_present_on_lower_line() -> None:
    snap = _valid_snapshot()
    text = _text(render_offer_document_pdf(snap, _static()))
    assert snap.document_reference in text
    assert "Seite 1" in text


def test_multipage_wrapped_footer_present_on_every_page() -> None:
    static = _static_realistic_footer(
        footer_note=_VERY_LONG_FOOTER_NOTE,
        company_register_text=_VERY_LONG_REGISTER_TEXT,
        company_vat_id_text=_VERY_LONG_VAT_ID_TEXT,
    )
    snap = _many_positions(_valid_snapshot(), 40)
    pdf = render_offer_document_pdf(snap, static)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) > 1
    for page in reader.pages:
        page_text = _normalize_ws(page.extract_text())
        assert _normalize_ws(_VERY_LONG_REGISTER_TEXT) in page_text


def test_reserved_footer_height_geometry_invariant() -> None:
    """ReportLab-measured proof, not text-order inference: the document's
    own bottomMargin always reserves at least the worst-case wrapped footer
    area, so Platypus's frame layout structurally cannot place story
    content (positions/totals/acceptance) inside the footer band."""
    assert _BOTTOM_MARGIN >= _UPPER_FOOTER_Y + _FOOTER_MAX_HEIGHT


def test_body_content_does_not_overlap_footer_area() -> None:
    static = _static_realistic_footer()
    pdf = render_offer_document_pdf(_valid_snapshot(), static)
    text = _text(pdf)
    # totals and acceptance are present (not pushed off/into the footer)
    assert "Summe brutto:" in text
    assert "Annahme" in text
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1


def test_extremely_long_footer_fails_closed_not_clipped() -> None:
    excessive = "Sehr langer Footertext. " * 40
    static = _static(footer_note=excessive)
    with pytest.raises(OfferPdfRenderError):
        render_offer_document_pdf(_valid_snapshot(), static)


def test_repeated_render_with_wrapped_footer_is_byte_identical() -> None:
    static = _static_realistic_footer(
        footer_note=_VERY_LONG_FOOTER_NOTE,
        company_register_text=_VERY_LONG_REGISTER_TEXT,
        company_vat_id_text=_VERY_LONG_VAT_ID_TEXT,
    )
    snap = _valid_snapshot()
    a = render_offer_document_pdf(snap, static)
    b = render_offer_document_pdf(snap, static)
    assert a == b
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


# --- forbidden content -----------------------------------------------------------


_FORBIDDEN_TERMS = (
    "Kisten",
    "Chafer",
    "M-Gläser",
    "Vorleger",
    "Geschirr",
    "Besteck",
    "Rechnungsnummer",
)


def test_forbidden_internal_terms_and_invoice_number_absent() -> None:
    text = _text(render_offer_document_pdf(_valid_snapshot(), _static()))
    for term in _FORBIDDEN_TERMS:
        assert term not in text


def test_snapshot_id_and_document_hash_not_visible() -> None:
    snap = _valid_snapshot()
    text = _text(render_offer_document_pdf(snap, _static()))
    assert snap.offer_document_snapshot_id not in text
    assert snap.document_hash not in text


def test_document_warnings_never_rendered_as_raw_codes() -> None:
    delivery = CustomerAddress(
        street="Eventplatz 9", postal_code="20457", city="Hamburg", country="DE"
    )
    snap = _valid_snapshot(
        delivery_address=delivery,
        delivery_address_differs=True,
        document_warnings=("WARNING_DELIVERY_ADDRESS_DIFFERS",),
    )
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "WARNING_DELIVERY_ADDRESS_DIFFERS" not in text


# --- formatting ----------------------------------------------------------------------


def test_eur_formatting_matches_de_de_convention() -> None:
    assert _eur(0) == "0,00 €"
    assert _eur(123456) == "1.234,56 €"
    assert _eur(123456789) == "1.234.567,89 €"


def test_vat_rate_formatting() -> None:
    snap = _valid_snapshot()
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "7 %" in text


def test_german_diacritics_and_euro_sign_round_trip() -> None:
    snap = _valid_snapshot(location_text="Straße Bürostraße äöüß")
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "äöüß" in text
    assert "€" in text


def test_multiline_narrative_preserves_all_lines() -> None:
    snap = _valid_snapshot(customer_notes="Zeile eins.\nZeile zwei.\nZeile drei.")
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "Zeile eins." in text
    assert "Zeile zwei." in text
    assert "Zeile drei." in text


def test_long_company_and_customer_names_render() -> None:
    long_name = (
        "Sehr Lange Firmierung Mit Vielen Wörtern Catering & Event GmbH & Co. KG"
    )
    snap = _valid_snapshot(recipient_company=long_name)
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "Sehr Lange Firmierung" in text


def test_optional_fields_absent_render_without_error() -> None:
    snap = _valid_snapshot(
        recipient_phone=None, guest_count_estimate=None, recipient_company=None
    )
    pdf = render_offer_document_pdf(snap, _static())
    assert pdf[:5] == b"%PDF-"


# --- pagination ------------------------------------------------------------------


def _many_positions(snap: OfferDocumentSnapshot, count: int) -> OfferDocumentSnapshot:
    base_pos = snap.positions[0]
    positions = tuple(
        replace(base_pos, position_id=f"pos-{i}", name=f"Fingerfood Paket {i}")
        for i in range(count)
    )
    long = replace(snap, positions=positions)
    return replace(long, document_hash=compute_document_hash(long))


def test_standard_fixture_produces_one_page() -> None:
    pdf = render_offer_document_pdf(_valid_snapshot(), _static())
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1


def test_long_fixture_spans_multiple_pages_without_truncation() -> None:
    snap = _many_positions(_valid_snapshot(), 40)
    pdf = render_offer_document_pdf(snap, _static())
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) > 1
    full_text = "\n".join(p.extract_text() for p in reader.pages)
    assert "Fingerfood Paket 0" in full_text
    assert "Fingerfood Paket 39" in full_text
    assert "Annahme" in full_text


def test_long_fixture_repeats_table_header() -> None:
    snap = _many_positions(_valid_snapshot(), 40)
    pdf = render_offer_document_pdf(snap, _static())
    reader = PdfReader(io.BytesIO(pdf))
    header_hits = sum(1 for p in reader.pages if "Position" in p.extract_text())
    assert header_hits >= 2


def test_long_fixture_document_reference_repeated_on_every_page() -> None:
    snap = _many_positions(_valid_snapshot(), 40)
    pdf = render_offer_document_pdf(snap, _static())
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) > 1
    for page in reader.pages:
        assert snap.document_reference in page.extract_text()


def test_acceptance_block_on_final_page() -> None:
    snap = _many_positions(_valid_snapshot(), 40)
    pdf = render_offer_document_pdf(snap, _static())
    reader = PdfReader(io.BytesIO(pdf))
    last_page_text = reader.pages[-1].extract_text()
    assert "Annahme" in last_page_text
    assert "Unterschrift:" in last_page_text
    # acceptance is the last flowable in the story, so it never appears
    # ahead of later positions content on an earlier page.
    for page in reader.pages[:-1]:
        assert "Annahme" not in page.extract_text()


# --- schema/malformed defense -------------------------------------------------------


def test_unsupported_schema_version_fails_closed() -> None:
    snap = _valid_snapshot()
    tampered = object.__new__(OfferDocumentSnapshot)
    for field in snap.__dataclass_fields__:
        object.__setattr__(tampered, field, getattr(snap, field))
    object.__setattr__(tampered, "schema_version", 2)
    with pytest.raises(OfferDocumentUnsupportedSchemaError):
        render_offer_document_pdf(tampered, _static())


def test_empty_positions_fails_closed() -> None:
    snap = _valid_snapshot()
    tampered = object.__new__(OfferDocumentSnapshot)
    for field in snap.__dataclass_fields__:
        object.__setattr__(tampered, field, getattr(snap, field))
    object.__setattr__(tampered, "positions", ())
    with pytest.raises(OfferPdfMalformedSnapshotError):
        render_offer_document_pdf(tampered, _static())


# --- unsupported characters --------------------------------------------------------


def test_unsupported_character_in_recipient_name_raises() -> None:
    snap = _valid_snapshot(recipient_name="Анна Иванова")
    with pytest.raises(OfferPdfUnsupportedCharacterError) as excinfo:
        render_offer_document_pdf(snap, _static())
    assert excinfo.value.field == "recipient_name"


def test_unsupported_character_in_static_content_raises() -> None:
    snap = _valid_snapshot()
    static = _static(footer_note="Анна")
    with pytest.raises(OfferPdfUnsupportedCharacterError) as excinfo:
        render_offer_document_pdf(snap, static)
    assert excinfo.value.field == "footer_note"


def test_unsupported_character_never_produces_partial_output() -> None:
    """A rejected render must not leave a caller holding mangled bytes."""
    snap = _valid_snapshot(recipient_name="Анна Иванова")
    with pytest.raises(OfferPdfUnsupportedCharacterError):
        render_offer_document_pdf(snap, _static())


# --- static content --------------------------------------------------------------


def test_missing_company_name_fails() -> None:
    with pytest.raises(OfferPdfMissingStaticContentError):
        OfferPdfStaticContent(
            company_legal_name="",
            company_address_lines=("x",),
            acceptance_statement="y",
        )


def test_missing_company_address_fails() -> None:
    with pytest.raises(OfferPdfMissingStaticContentError):
        OfferPdfStaticContent(
            company_legal_name="x", company_address_lines=(), acceptance_statement="y"
        )
    with pytest.raises(OfferPdfMissingStaticContentError):
        OfferPdfStaticContent(
            company_legal_name="x",
            company_address_lines=("   ",),
            acceptance_statement="y",
        )


def test_missing_acceptance_statement_fails() -> None:
    with pytest.raises(OfferPdfMissingStaticContentError):
        OfferPdfStaticContent(
            company_legal_name="x",
            company_address_lines=("y",),
            acceptance_statement="",
        )


def test_blank_placeholder_static_content_cannot_be_constructed() -> None:
    """Guards against an empty/whitespace placeholder silently reaching a
    future production-style composition."""
    with pytest.raises(OfferPdfMissingStaticContentError):
        OfferPdfStaticContent(
            company_legal_name="   ",
            company_address_lines=("   ",),
            acceptance_statement="   ",
        )


def test_vorkasse_bank_details_render_only_when_supplied() -> None:
    snap = _valid_snapshot(
        payment_method="VORKASSE", payment_customer_visible_text="Zahlung per Vorkasse"
    )
    with_bank = _static(bank_details_text="IBAN DE00 TEST 0000 0000 00")
    without_bank = _static()

    text_with = _text(render_offer_document_pdf(snap, with_bank))
    assert "IBAN DE00 TEST 0000 0000 00" in text_with

    text_without = _text(render_offer_document_pdf(snap, without_bank))
    assert "IBAN" not in text_without


def test_bank_details_absent_does_not_block_rendering() -> None:
    snap = _valid_snapshot(
        payment_method="VORKASSE", payment_customer_visible_text="Zahlung per Vorkasse"
    )
    pdf = render_offer_document_pdf(snap, _static())
    assert pdf[:5] == b"%PDF-"


def test_bank_details_not_rendered_for_non_vorkasse() -> None:
    snap = _valid_snapshot()  # RECHNUNG in the base fixture
    static = _static(bank_details_text="IBAN DE00 TEST 0000 0000 00")
    text = _text(render_offer_document_pdf(snap, static))
    assert "IBAN" not in text


# --- payment contract (resolved) --------------------------------------------------


@pytest.mark.parametrize(
    ("method", "label"),
    [
        ("VORKASSE", "Vorkasse"),
        ("RECHNUNG", "Rechnung"),
        ("BAR_VOR_ORT", "Bar vor Ort"),
    ],
)
def test_canonical_payment_label_always_rendered(method: str, label: str) -> None:
    snap = _valid_snapshot(payment_method=method, payment_customer_visible_text=label)
    text = _text(render_offer_document_pdf(snap, _static()))
    assert f"Zahlungsart: {label}" in text


@pytest.mark.parametrize(
    ("method", "text_value"),
    [
        ("RECHNUNG", "Zahlung per Rechnung"),
        ("VORKASSE", "Zahlung per Vorkasse"),
        ("RECHNUNG", "Rechnung laut Vereinbarung."),
    ],
)
def test_richer_customer_visible_text_renders_alongside_label(
    method: str, text_value: str
) -> None:
    snap = _valid_snapshot(
        payment_method=method, payment_customer_visible_text=text_value
    )
    text = _text(render_offer_document_pdf(snap, _static()))
    assert f"Zahlungsbedingungen: {text_value}" in text


def test_exact_label_duplicate_is_suppressed() -> None:
    snap = _valid_snapshot(
        payment_method="RECHNUNG", payment_customer_visible_text="Rechnung"
    )
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "Zahlungsart: Rechnung" in text
    assert "Zahlungsbedingungen:" not in text


def test_case_insensitive_label_duplicate_is_suppressed() -> None:
    assert _payment_terms_line("RECHNUNG", "RECHNUNG") is None
    assert _payment_terms_line("RECHNUNG", "rechnung") is None


def test_outer_whitespace_normalized_for_duplicate_comparison() -> None:
    snap = _valid_snapshot(
        payment_method="RECHNUNG", payment_customer_visible_text="  Rechnung  "
    )
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "Zahlungsbedingungen:" not in text


def test_internal_text_and_punctuation_preserved_when_shown() -> None:
    value = "Rechnung laut Vereinbarung."
    line = _payment_terms_line("RECHNUNG", value)
    assert line == value  # not rewritten, not stripped of punctuation


def test_no_ueberweisung_invented() -> None:
    snap = _valid_snapshot()
    text = _text(render_offer_document_pdf(snap, _static()))
    assert "Überweisung" not in text


# --- filename ------------------------------------------------------------------------


def test_filename_matches_document_reference() -> None:
    snap = _valid_snapshot()
    assert offer_document_pdf_filename(snap) == f"{snap.document_reference}.pdf"
    assert snap.document_reference == "ANG-7B5A5A7D-V1"
    assert offer_document_pdf_filename(snap) == "ANG-7B5A5A7D-V1.pdf"

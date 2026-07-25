"""OFFER_PDF_RENDERER_V1 — deterministic ANGEBOT / AUFTRAGSBESTÄTIGUNG PDF.

Pure function: OfferDocumentSnapshot + OfferPdfStaticContent in, PDF bytes
out. No repositories, no Inquiry/Offer/catalog access, no network, no
environment/file reads, no mutation of the snapshot, no price/VAT
recomputation — every cent and every VAT bucket is formatted, never
recalculated.

Determinism: ReportLab's ``invariant=1`` mode fixes object ordering and the
trailer ``/ID``, but pins ``/CreationDate``/``/ModDate`` to a hardcoded
placeholder rather than any real date. This module overrides the
document's internal timestamp with one derived from ``snapshot.created_at``
so metadata dates are both fixed *and* meaningful. Same snapshot + same
static content must always produce byte-identical output — proven in
tests, not merely claimed.

Fonts: base-14 Helvetica (WinAnsi encoding) is used deliberately — no
external font asset ships in this slice. Every user-supplied text field is
preflighted against cp1252 (a very close proxy for WinAnsi) before any draw
call; ReportLab itself does not raise for unsupported glyphs, it silently
draws replacement boxes, so this module fails closed instead.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.offer_document_snapshot import (
    SCHEMA_VERSION,
    OfferDocumentSnapshot,
)
from catering_system.domain.offer_pdf import (
    OfferDocumentUnsupportedSchemaError,
    OfferPdfMalformedSnapshotError,
    OfferPdfRenderError,
    OfferPdfStaticContent,
    OfferPdfUnsupportedCharacterError,
)
from catering_system.domain.order_payment_reminder import PAYMENT_METHOD_LABELS

_TITLE = "ANGEBOT / AUFTRAGSBESTÄTIGUNG"
_FULFILLMENT_LABELS = {"DELIVERY": "Lieferung", "PICKUP": "Abholung"}
_MONTHS_DE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)  # fmt: skip

_PAGE_SIZE = A4
_LEFT_MARGIN = 20 * mm
_RIGHT_MARGIN = 20 * mm
_TOP_MARGIN = 18 * mm
_BOTTOM_MARGIN = 16 * mm


class _FixedTimeStamp:
    """Mimics reportlab.pdfbase.pdfdoc.TimeStamp's public shape, but derived
    from snapshot.created_at instead of wall-clock time or SOURCE_DATE_EPOCH."""

    def __init__(self, created_at: datetime) -> None:
        utc = created_at.astimezone(timezone.utc)
        self.YMDhms = (utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second)
        self.dhh = 0
        self.dmm = 0


def offer_document_pdf_filename(snapshot: OfferDocumentSnapshot) -> str:
    return f"{snapshot.document_reference}.pdf"


def render_offer_document_pdf(
    snapshot: OfferDocumentSnapshot,
    static_content: OfferPdfStaticContent,
) -> bytes:
    """Render one frozen offer document to PDF bytes.

    Deterministic for a fixed ReportLab version: identical snapshot and
    static content always produce identical bytes (see module docstring).
    """
    if snapshot.schema_version != SCHEMA_VERSION:
        raise OfferDocumentUnsupportedSchemaError(
            f"unsupported offer document schema version {snapshot.schema_version!r}"
        )
    if not snapshot.positions:
        raise OfferPdfMalformedSnapshotError(
            "offer document snapshot has no positions to render"
        )

    _check_all_text(snapshot, static_content)

    styles = _styles()
    story = _build_story(snapshot, static_content, styles)

    buf = io.BytesIO()
    try:
        doc = SimpleDocTemplate(
            buf,
            pagesize=_PAGE_SIZE,
            leftMargin=_LEFT_MARGIN,
            rightMargin=_RIGHT_MARGIN,
            topMargin=_TOP_MARGIN,
            bottomMargin=_BOTTOM_MARGIN,
            invariant=1,
            title=_TITLE,
            author=static_content.company_legal_name,
            subject=snapshot.document_reference,
            creator="silberloeffel-catering-offer-pdf-renderer",
            producer="silberloeffel-catering-offer-pdf-renderer",
        )
        on_page = _page_decorator(snapshot, static_content)
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    except (
        OfferDocumentUnsupportedSchemaError,
        OfferPdfMalformedSnapshotError,
        OfferPdfUnsupportedCharacterError,
    ):
        raise
    except Exception as exc:  # pragma: no cover - defensive, no path leak
        raise OfferPdfRenderError("failed to render offer document PDF") from exc
    return buf.getvalue()


# --- character preflight (fail closed, never silently mangled) ----------------


def _ensure_renderable(value: str | None, field: str) -> None:
    if not value:
        return
    try:
        value.encode("cp1252")
    except UnicodeEncodeError as exc:
        raise OfferPdfUnsupportedCharacterError(field=field, text=value) from exc


def _check_all_text(
    snapshot: OfferDocumentSnapshot, static_content: OfferPdfStaticContent
) -> None:
    _ensure_renderable(snapshot.recipient_name, "recipient_name")
    _ensure_renderable(snapshot.recipient_company, "recipient_company")
    _ensure_renderable(snapshot.recipient_email, "recipient_email")
    _ensure_renderable(snapshot.recipient_phone, "recipient_phone")
    for label, address in (
        ("invoice_address", snapshot.invoice_address),
        ("delivery_address", snapshot.delivery_address),
    ):
        if address is None:
            continue
        _ensure_renderable(address.street, f"{label}.street")
        _ensure_renderable(address.postal_code, f"{label}.postal_code")
        _ensure_renderable(address.city, f"{label}.city")
        _ensure_renderable(address.country, f"{label}.country")
    _ensure_renderable(snapshot.time_window_text, "time_window_text")
    _ensure_renderable(snapshot.location_text, "location_text")
    _ensure_renderable(snapshot.customer_title, "customer_title")
    _ensure_renderable(snapshot.customer_introduction, "customer_introduction")
    _ensure_renderable(snapshot.customer_notes, "customer_notes")
    _ensure_renderable(
        snapshot.payment_customer_visible_text, "payment_customer_visible_text"
    )
    for index, position in enumerate(snapshot.positions):
        prefix = f"positions[{index}]"
        _ensure_renderable(position.name, f"{prefix}.name")
        _ensure_renderable(position.description, f"{prefix}.description")
        _ensure_renderable(position.composition, f"{prefix}.composition")
        _ensure_renderable(position.quantity, f"{prefix}.quantity")
        _ensure_renderable(position.unit_label, f"{prefix}.unit_label")

    _ensure_renderable(static_content.company_legal_name, "company_legal_name")
    for i, line in enumerate(static_content.company_address_lines):
        _ensure_renderable(line, f"company_address_lines[{i}]")
    _ensure_renderable(static_content.company_phone, "company_phone")
    _ensure_renderable(static_content.company_email, "company_email")
    _ensure_renderable(static_content.company_web, "company_web")
    _ensure_renderable(static_content.company_register_text, "company_register_text")
    _ensure_renderable(static_content.company_vat_id_text, "company_vat_id_text")
    _ensure_renderable(static_content.footer_note, "footer_note")
    _ensure_renderable(static_content.acceptance_statement, "acceptance_statement")
    _ensure_renderable(static_content.bank_details_text, "bank_details_text")


# --- formatting -----------------------------------------------------------------


def _eur(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    grouped = f"{whole:,}".replace(",", ".")
    return f"{sign}{grouped},{frac:02d} €"


def _vat_percent(rate_percent: int) -> str:
    return f"{rate_percent} %"


def _de_date(value: date) -> str:
    return f"{value.day}. {_MONTHS_DE[value.month - 1]} {value.year}"


def _de_date_short(value: date) -> str:
    return f"{value.day:02d}.{value.month:02d}.{value.year:04d}"


def _de_created_at(value: datetime) -> str:
    utc = value.astimezone(timezone.utc)
    return f"{_de_date_short(utc.date())}"


def _payment_label(method: str) -> str:
    return PAYMENT_METHOD_LABELS[method]  # type: ignore[index]


def _payment_terms_line(method: str, customer_visible_text: str) -> str | None:
    """None means: identical to the canonical label, suppress the duplicate."""
    normalized = customer_visible_text.strip()
    if not normalized:
        return None
    if normalized.casefold() == _payment_label(method).casefold():
        return None
    return normalized


def _company_contact_line(static: OfferPdfStaticContent) -> str | None:
    """Compact labeled 'Telefon: ... · E-Mail: ... · Web: ...' header line.

    None when no contact value was supplied — never an empty label."""
    parts: list[str] = []
    if static.company_phone and static.company_phone.strip():
        parts.append(f"Telefon: {static.company_phone.strip()}")
    if static.company_email and static.company_email.strip():
        parts.append(f"E-Mail: {static.company_email.strip()}")
    if static.company_web and static.company_web.strip():
        parts.append(f"Web: {static.company_web.strip()}")
    return " · ".join(parts) if parts else None


def _company_footer_line(static: OfferPdfStaticContent) -> str | None:
    """Compact footer line: footer_note, then register/VAT-ID facts
    verbatim, each only when supplied. No labels are invented for the
    legal facts — they are rendered exactly as approved."""
    parts: list[str] = []
    if static.footer_note and static.footer_note.strip():
        parts.append(static.footer_note.strip())
    if static.company_register_text and static.company_register_text.strip():
        parts.append(static.company_register_text.strip())
    if static.company_vat_id_text and static.company_vat_id_text.strip():
        parts.append(static.company_vat_id_text.strip())
    return " · ".join(parts) if parts else None


# --- document assembly -----------------------------------------------------------


@dataclass(frozen=True)
class _Styles:
    title: ParagraphStyle
    h2: ParagraphStyle
    body: ParagraphStyle
    small: ParagraphStyle
    right: ParagraphStyle
    right_bold: ParagraphStyle
    table_header: ParagraphStyle


def _styles() -> _Styles:
    base = getSampleStyleSheet()
    return _Styles(
        title=ParagraphStyle(
            "OfferTitle", parent=base["Title"], fontSize=16, leading=19
        ),
        h2=ParagraphStyle(
            "OfferH2",
            parent=base["Heading2"],
            fontSize=10.5,
            leading=12,
            spaceBefore=6,
            spaceAfter=2,
        ),
        body=ParagraphStyle(
            "OfferBody", parent=base["Normal"], fontSize=9.5, leading=13
        ),
        small=ParagraphStyle(
            "OfferSmall", parent=base["Normal"], fontSize=8, leading=10
        ),
        right=ParagraphStyle(
            "OfferRight", parent=base["Normal"], fontSize=9.5, leading=13, alignment=2
        ),
        right_bold=ParagraphStyle(
            "OfferRightBold",
            parent=base["Normal"],
            fontSize=10.5,
            leading=13,
            alignment=2,
            fontName="Helvetica-Bold",
        ),
        table_header=ParagraphStyle(
            "OfferTableHeader",
            parent=base["Normal"],
            fontSize=8.5,
            leading=10,
            fontName="Helvetica-Bold",
        ),
    )


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    """Wrap one raw (unescaped) string. Internal newlines become <br/>."""
    return Paragraph(_esc(text).replace("\n", "<br/>"), style)


def _p_lines(lines: list[str], style: ParagraphStyle) -> Paragraph:
    """Wrap several raw (unescaped) lines, each escaped individually and
    joined with a real line break — never re-escape the joined markup."""
    return Paragraph("<br/>".join(_esc(line) for line in lines if line), style)


def _build_story(
    snapshot: OfferDocumentSnapshot,
    static: OfferPdfStaticContent,
    styles: _Styles,
) -> list[Flowable]:
    story: list[Flowable] = []
    story.extend(_header_block(snapshot, static, styles))
    story.extend(_recipient_block(snapshot, styles))
    story.extend(_event_block(snapshot, styles))
    story.extend(_address_block(snapshot, styles))
    story.extend(_narrative_block(snapshot, styles))
    story.extend(_positions_block(snapshot, styles))
    story.append(Spacer(1, 4))
    story.append(KeepTogether(_totals_block(snapshot, styles)))
    story.append(Spacer(1, 4))
    story.append(KeepTogether(_payment_block(snapshot, static, styles)))
    story.append(Spacer(1, 8))
    story.append(KeepTogether(_acceptance_block(static, styles)))
    return story


def _header_block(
    snapshot: OfferDocumentSnapshot, static: OfferPdfStaticContent, styles: _Styles
) -> list[Flowable]:
    blocks: list[Flowable] = []
    if static.logo_png_bytes is not None:
        img = Image(io.BytesIO(static.logo_png_bytes))
        img.drawHeight = 16 * mm
        img.drawWidth = img.drawHeight * (img.imageWidth / img.imageHeight)
        blocks.append(img)
    else:
        blocks.append(_p(static.company_legal_name, styles.h2))
    for line in static.company_address_lines:
        if line.strip():
            blocks.append(_p(line, styles.small))
    contact_line = _company_contact_line(static)
    if contact_line is not None:
        blocks.append(_p(contact_line, styles.small))
    blocks.append(Spacer(1, 6))
    blocks.append(_p(_TITLE, styles.title))
    blocks.append(
        _p(
            f"Referenz: {snapshot.document_reference} · "
            f"Datum: {_de_created_at(snapshot.created_at)}",
            styles.body,
        )
    )
    blocks.append(Spacer(1, 4))
    return blocks


def _address_lines(address: CustomerAddress) -> list[str]:
    """CustomerAddress fields are typed optional, but structural completeness
    is already guaranteed by OfferDocumentSnapshot's own invariants for any
    address reaching this renderer — the ``or ""`` fallback is defensive
    typing, not an expected runtime path."""
    return [
        address.street or "",
        f"{address.postal_code or ''} {address.city or ''}".strip(),
        address.country or "",
    ]


def _recipient_block(
    snapshot: OfferDocumentSnapshot, styles: _Styles
) -> list[Flowable]:
    blocks: list[Flowable] = [_p("Kunde", styles.h2)]
    lines: list[str] = []
    if snapshot.recipient_company:
        lines.append(snapshot.recipient_company)
    if snapshot.recipient_name:
        lines.append(snapshot.recipient_name)
    lines.extend(_address_lines(snapshot.invoice_address))
    if snapshot.recipient_email:
        lines.append(snapshot.recipient_email)
    if snapshot.recipient_phone:
        lines.append(snapshot.recipient_phone)
    blocks.append(_p_lines(lines, styles.body))
    return blocks


def _event_block(snapshot: OfferDocumentSnapshot, styles: _Styles) -> list[Flowable]:
    guests = (
        f"ca. {snapshot.guest_count_estimate} Gäste"
        if snapshot.guest_count_estimate is not None
        else "–"
    )
    fulfillment = _FULFILLMENT_LABELS[snapshot.fulfillment_mode]
    lines = [
        f"Datum: {_de_date(snapshot.event_date)}",
        f"Zeit: {snapshot.time_window_text}",
        f"Ort: {snapshot.location_text}",
        f"Gäste: {guests}",
        f"Art: {fulfillment}",
    ]
    return [
        _p("Veranstaltung", styles.h2),
        _p_lines(lines, styles.body),
    ]


def _address_block(snapshot: OfferDocumentSnapshot, styles: _Styles) -> list[Flowable]:
    blocks: list[Flowable] = [_p("Adressen", styles.h2)]
    invoice_lines = _address_lines(snapshot.invoice_address)
    invoice_table = Table(
        [
            [_p("Rechnungsadresse", styles.table_header)],
            [_p_lines(invoice_lines, styles.body)],
        ],
        colWidths=[80 * mm],
    )
    invoice_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    row = [invoice_table]

    if snapshot.fulfillment_mode == "DELIVERY":
        delivery = snapshot.delivery_address
        assert delivery is not None  # guaranteed by snapshot invariants
        delivery_lines = _address_lines(delivery)
        header_text = "Lieferadresse"
        if snapshot.delivery_address_differs:
            header_text = "Lieferadresse (abweichend)"
        delivery_table = Table(
            [
                [_p(header_text, styles.table_header)],
                [_p_lines(delivery_lines, styles.body)],
            ],
            colWidths=[80 * mm],
        )
        border_color = (
            colors.HexColor("#888888")
            if snapshot.delivery_address_differs
            else colors.HexColor("#bbbbbb")
        )
        bg_color = (
            colors.HexColor("#f0f0f0")
            if snapshot.delivery_address_differs
            else colors.white
        )
        delivery_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.5, border_color),
                    ("BACKGROUND", (0, 0), (-1, -1), bg_color),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        row.append(delivery_table)

    outer = Table([row], colWidths=None)
    outer.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    blocks.append(outer)
    return blocks


def _narrative_block(
    snapshot: OfferDocumentSnapshot, styles: _Styles
) -> list[Flowable]:
    blocks: list[Flowable] = []
    if snapshot.customer_title:
        blocks.append(_p(snapshot.customer_title, styles.h2))
    if snapshot.customer_introduction:
        blocks.append(_p(snapshot.customer_introduction, styles.body))
        blocks.append(Spacer(1, 4))
    if snapshot.customer_notes:
        blocks.append(_p(snapshot.customer_notes, styles.body))
        blocks.append(Spacer(1, 4))
    return blocks


def _positions_block(
    snapshot: OfferDocumentSnapshot, styles: _Styles
) -> list[Flowable]:
    header: list[Flowable] = [
        _p("Position", styles.table_header),
        _p("Menge", styles.table_header),
        _p("Einzelpreis", styles.table_header),
        _p("Netto", styles.table_header),
        _p("MwSt.", styles.table_header),
        _p("Brutto", styles.table_header),
    ]
    rows: list[list[Flowable]] = [header]
    for position in snapshot.positions:
        name_parts = [position.name]
        if position.description:
            name_parts.append(position.description)
        if position.composition:
            name_parts.append(position.composition)
        name_cell = _p_lines(name_parts, styles.body)
        quantity_text = (
            f"{position.quantity} {position.unit_label or ''}".strip()
            if position.quantity
            else "–"
        )
        rows.append(
            [
                name_cell,
                _p(quantity_text, styles.body),
                _p(_eur(position.unit_net_cents), styles.right),
                _p(_eur(position.net_total_cents), styles.right),
                _p(_vat_percent(position.vat_rate_percent), styles.right),
                _p(_eur(position.gross_cents), styles.right),
            ]
        )
    table = Table(
        rows,
        colWidths=[62 * mm, 20 * mm, 22 * mm, 22 * mm, 15 * mm, 22 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return [_p("Leistungen", styles.h2), table]


def _totals_block(snapshot: OfferDocumentSnapshot, styles: _Styles) -> list[Flowable]:
    rows: list[list[Flowable]] = [
        [
            _p("Satz", styles.table_header),
            _p("Netto", styles.table_header),
            _p("MwSt.", styles.table_header),
        ]
    ]
    for bucket in snapshot.vat_buckets:
        rows.append(
            [
                _p(_vat_percent(bucket.rate_percent), styles.body),
                _p(_eur(bucket.base_net_cents), styles.right),
                _p(_eur(bucket.vat_cents), styles.right),
            ]
        )
    table = Table(rows, colWidths=[30 * mm, 30 * mm, 30 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    summary = Table(
        [
            [
                _p("Summe netto:", styles.body),
                _p(_eur(snapshot.net_total_cents), styles.right),
            ],
            [
                _p("Summe MwSt.:", styles.body),
                _p(_eur(snapshot.vat_total_cents), styles.right),
            ],
            [
                _p("Summe brutto:", styles.right_bold),
                _p(_eur(snapshot.gross_total_cents), styles.right_bold),
            ],
        ],
        colWidths=[60 * mm, 30 * mm],
    )
    summary.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 4)]))
    return [_p("MwSt.-Übersicht", styles.h2), table, Spacer(1, 6), summary]


def _payment_block(
    snapshot: OfferDocumentSnapshot,
    static: OfferPdfStaticContent,
    styles: _Styles,
) -> list[Flowable]:
    blocks: list[Flowable] = [_p("Zahlung", styles.h2)]
    label = _payment_label(snapshot.payment_method)
    blocks.append(_p(f"Zahlungsart: {label}", styles.body))
    terms = _payment_terms_line(
        snapshot.payment_method, snapshot.payment_customer_visible_text
    )
    if terms is not None:
        blocks.append(_p(f"Zahlungsbedingungen: {terms}", styles.body))
    if snapshot.payment_method == "VORKASSE" and static.bank_details_text:
        blocks.append(_p(static.bank_details_text, styles.body))
    return blocks


def _acceptance_block(static: OfferPdfStaticContent, styles: _Styles) -> list[Flowable]:
    return [
        _p("Annahme", styles.h2),
        _p(static.acceptance_statement, styles.body),
        Spacer(1, 12),
        _p("Ort: _______________________  Datum: _______________________", styles.body),
        Spacer(1, 10),
        _p("Name: _______________________", styles.body),
        Spacer(1, 10),
        _p("Unterschrift: _______________________", styles.body),
    ]


def _page_decorator(snapshot: OfferDocumentSnapshot, static: OfferPdfStaticContent):
    def _on_page(pdf_canvas, doc) -> None:  # noqa: ANN001
        # invariant=1 alone pins /CreationDate + /ModDate to a hardcoded
        # placeholder (2000-01-01), not a real date. Override with the
        # frozen snapshot timestamp so metadata is both fixed and
        # meaningful — idempotent across every page callback invocation.
        pdf_canvas._doc._timeStamp = _FixedTimeStamp(snapshot.created_at)
        pdf_canvas.saveState()
        pdf_canvas.setFont("Helvetica", 8)
        pdf_canvas.setFillGray(0.35)
        page_width, page_height = _PAGE_SIZE
        pdf_canvas.drawString(
            _LEFT_MARGIN,
            page_height - 12 * mm,
            f"{_TITLE} · {snapshot.document_reference}",
        )
        pdf_canvas.drawRightString(
            page_width - _RIGHT_MARGIN, 12 * mm, f"Seite {doc.page}"
        )
        footer_line = _company_footer_line(static)
        if footer_line is not None:
            pdf_canvas.drawString(_LEFT_MARGIN, 12 * mm, footer_line)
        pdf_canvas.restoreState()

    return _on_page

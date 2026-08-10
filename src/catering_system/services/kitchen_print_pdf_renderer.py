"""Deterministic PDF renderer for immutable kitchen print artifacts."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from catering_system.services.order_print_projection_service import OrderPrintProjection

_TITLE = "Küchenzettel"
_PAGE_SIZE = A4
_LEFT_MARGIN = 18 * mm
_RIGHT_MARGIN = 18 * mm
_TOP_MARGIN = 16 * mm
_BOTTOM_MARGIN = 14 * mm


class KitchenPrintPdfUnsupportedCharacterError(Exception):
    def __init__(self, *, field: str) -> None:
        self.field = field
        super().__init__(f"unsupported character(s) in {field}")


class KitchenPrintPdfRenderError(Exception):
    """Wraps unexpected ReportLab failures without exposing internals."""


class _FixedTimeStamp:
    def __init__(self, created_at: datetime) -> None:
        utc = created_at.astimezone(UTC)
        self.YMDhms = (utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second)
        self.dhh = 0
        self.dmm = 0


@dataclass(frozen=True)
class _Styles:
    title: ParagraphStyle
    h2: ParagraphStyle
    body: ParagraphStyle
    body_bold: ParagraphStyle
    small: ParagraphStyle
    table_header: ParagraphStyle


def render_kitchen_print_pdf(
    projection: OrderPrintProjection,
    *,
    created_at: datetime,
) -> bytes:
    """Render one kitchen_job projection to printer-ready PDF bytes."""

    _check_all_text(projection)
    styles = _styles()
    story = _build_story(projection, styles)

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
            author="Silberlöffel Catering",
            subject=projection.event.order_version_id,
            creator="silberloeffel-catering-kitchen-print-pdf-renderer",
            producer="silberloeffel-catering-kitchen-print-pdf-renderer",
        )
        on_page = _page_decorator(created_at)
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    except KitchenPrintPdfUnsupportedCharacterError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise KitchenPrintPdfRenderError("failed to render kitchen print PDF") from exc
    return buf.getvalue()


def _styles() -> _Styles:
    base = getSampleStyleSheet()
    return _Styles(
        title=ParagraphStyle(
            "KitchenTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            spaceAfter=10,
        ),
        h2=ParagraphStyle(
            "KitchenH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=14,
            spaceBefore=8,
            spaceAfter=4,
        ),
        body=ParagraphStyle(
            "KitchenBody", parent=base["Normal"], fontSize=10, leading=13
        ),
        body_bold=ParagraphStyle(
            "KitchenBodyBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
        ),
        small=ParagraphStyle(
            "KitchenSmall", parent=base["Normal"], fontSize=8, leading=10
        ),
        table_header=ParagraphStyle(
            "KitchenTableHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
        ),
    )


def _build_story(projection: OrderPrintProjection, styles: _Styles) -> list[Flowable]:
    event = projection.event
    guests = (
        str(event.guest_count_estimate)
        if event.guest_count_estimate is not None
        else "-"
    )
    story: list[Flowable] = []
    if event.order_cancelled_at is not None:
        story.append(_p("STORNIERT", styles.title))
        story.append(Spacer(1, 4 * mm))

    story.append(_p("SILBERLÖFFEL", styles.small))
    story.append(_p(_TITLE, styles.title))
    story.append(
        Table(
            [
                [
                    _p("Datum", styles.table_header),
                    _p(_format_date(event.event_date), styles.body),
                ],
                [
                    _p("Zeit", styles.table_header),
                    _p(event.time_window_text, styles.body),
                ],
                [_p("Ort", styles.table_header), _p(event.location_text, styles.body)],
                [_p("Gäste", styles.table_header), _p(guests, styles.body)],
                [
                    _p("Planung", styles.table_header),
                    _p(event.planning_mode, styles.body),
                ],
                [
                    _p("Stand", styles.table_header),
                    _p(f"Version {event.version_number}", styles.body),
                ],
                [
                    _p("Auftrag", styles.table_header),
                    _p(event.order_id, styles.small),
                ],
                [
                    _p("Version-ID", styles.table_header),
                    _p(event.order_version_id, styles.small),
                ],
            ],
            colWidths=(32 * mm, 120 * mm),
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        )
    )
    if projection.flags.watermark is not None:
        story.append(Spacer(1, 4 * mm))
        story.append(_p(projection.flags.watermark, styles.title))
    if event.change_reason is not None or event.changed_fields:
        story.append(Spacer(1, 4 * mm))
        story.append(_p("Änderung", styles.h2))
        story.append(_p(f"Grund: {event.change_reason or '-'}", styles.body))
        fields = ", ".join(event.changed_fields) or "-"
        story.append(_p(f"Felder: {fields}", styles.body))

    story.append(Spacer(1, 6 * mm))
    story.append(_p("MENÜ", styles.h2))
    if not projection.commercial.positions:
        story.append(_p("Keine Positionen.", styles.body))
    for position in projection.commercial.positions:
        story.append(_p(position.name, styles.body_bold))
        details = [
            value
            for value in (
                position.description or position.composition,
                position.quantity_display,
            )
            if value
        ]
        for detail in details:
            story.append(_p(detail, styles.body))
        story.append(Spacer(1, 3 * mm))
    return story


def _page_decorator(created_at: datetime):
    def _on_page(pdf_canvas, _doc) -> None:
        pdf_canvas._doc._timeStamp = _FixedTimeStamp(created_at)
        pdf_canvas.saveState()
        pdf_canvas.setFont("Helvetica", 8)
        pdf_canvas.setFillGray(0.35)
        pdf_canvas.drawRightString(
            _PAGE_SIZE[0] - _RIGHT_MARGIN,
            8 * mm,
            f"Seite {pdf_canvas.getPageNumber()}",
        )
        pdf_canvas.restoreState()

    return _on_page


def _format_date(value: object) -> str:
    return value.strftime("%d.%m.%Y")  # type: ignore[attr-defined]


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_esc(text).replace("\n", "<br/>"), style)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ensure_renderable(value: str | None, field: str) -> None:
    if not value:
        return
    try:
        value.encode("cp1252")
    except UnicodeEncodeError as exc:
        raise KitchenPrintPdfUnsupportedCharacterError(field=field) from exc


def _check_all_text(projection: OrderPrintProjection) -> None:
    event = projection.event
    _ensure_renderable(event.time_window_text, "time_window_text")
    _ensure_renderable(event.location_text, "location_text")
    _ensure_renderable(event.planning_mode, "planning_mode")
    _ensure_renderable(event.change_reason, "change_reason")
    for index, field in enumerate(event.changed_fields):
        _ensure_renderable(field, f"changed_fields[{index}]")
    for index, position in enumerate(projection.commercial.positions):
        prefix = f"positions[{index}]"
        _ensure_renderable(position.name, f"{prefix}.name")
        _ensure_renderable(position.description, f"{prefix}.description")
        _ensure_renderable(position.composition, f"{prefix}.composition")
        _ensure_renderable(position.notes, f"{prefix}.notes")
        _ensure_renderable(position.quantity_display, f"{prefix}.quantity_display")

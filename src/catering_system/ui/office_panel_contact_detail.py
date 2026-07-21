"""Kontakt detail presentation — projection context plus internal notes (5C-1 / V1)."""

from __future__ import annotations

from typing import cast
from urllib.parse import quote

from catering_system.domain.contact_internal_note import (
    CONTACT_INTERNAL_NOTE_CATEGORIES,
)
from catering_system.ui.office_api_views import offer_state_label
from catering_system.ui.office_panel_contacts_list import (
    format_contact_status_for_display,
)
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _csrf_input,
    _e,
    _page,
)


def _short_date(raw: str) -> str:
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return f"{raw[8:10]}.{raw[5:7]}.{raw[0:4]}"
    return raw


def _format_note_timestamp(raw: str) -> str:
    text = raw.strip()
    if "T" in text:
        date_part, time_part = text.split("T", 1)
        clock = time_part[:5]
        if len(date_part) == 10 and date_part[4] == "-" and date_part[7] == "-":
            return f"{_short_date(date_part)} {clock} UTC"
    return text


def _nl2br_escaped(text: str) -> str:
    return "<br>".join(_e(line) for line in text.splitlines()) or _e(text)


def _notes_section(detail: dict[str, object], context: OfficePageContext) -> str:
    contact_key = str(detail["contact_key"])
    notes = cast(list[dict[str, object]], detail.get("internal_notes") or [])
    encoded = quote(contact_key, safe="")
    options = "".join(
        f'<option value="{_e(category)}">{_e(category)}</option>'
        for category in CONTACT_INTERNAL_NOTE_CATEGORIES
    )
    note_rows = (
        "".join(
            '<article class="contact-note">'
            f"<p><strong>{_e(str(row['category']))}</strong>"
            f" · {_e(_format_note_timestamp(str(row['created_at'])))}"
            f" · {_e(str(row['created_by']))}</p>"
            f"<p>{_nl2br_escaped(str(row['note_text']))}</p>"
            "</article>"
            for row in notes
        )
        or "<p>Keine internen Notizen.</p>"
    )
    return (
        '<section class="offer-detail-section">'
        "<h2>Interne Notizen</h2>"
        f'<form method="post" action="/kontakt/{_e(encoded)}/notizen">'
        f"{_csrf_input(context)}"
        f'<p><label>Kategorie</label><select name="category">{options}</select></p>'
        "<p><label>Notiz</label>"
        '<textarea name="note_text" rows="4" maxlength="4000" required></textarea></p>'
        '<p><button type="submit">Notiz speichern</button></p>'
        "</form>"
        f"{note_rows}"
        "</section>"
    )


def render_kontakt_detail(
    detail: dict[str, object],
    *,
    context: OfficePageContext,
) -> str:
    contact_key = str(detail["contact_key"])
    inquiry_rows = (
        "".join(
            "<li>"
            f'<a href="/inquiry/{_e(str(row["inquiry_id"]))}">'
            f"{_e(str(row.get('intake_subject') or str(row['inquiry_id'])[:8]))}</a>"
            f" · {_e(_short_date(str(row['event_date'])))}"
            f" · {_e(str(row['crm_stage']))}"
            "</li>"
            for row in cast(list[dict[str, object]], detail["inquiries"])
        )
        or "<li>Keine Anfragen</li>"
    )
    offer_rows = (
        "".join(
            "<li>"
            f'<a href="/offer/{_e(str(row["offer_id"]))}">'
            f"{_e(offer_state_label(str(row['state'])))}</a>"  # type: ignore[arg-type]
            f" · Anfrage {_e(str(row['inquiry_id'])[:8])}"
            "</li>"
            for row in cast(list[dict[str, object]], detail["offers"])
        )
        or "<li>Keine Angebote</li>"
    )
    order_rows = (
        "".join(
            "<li>"
            f'<a href="/order/{_e(str(row["order_id"]))}">'
            f"Auftrag {_e(str(row['order_id'])[:8])}</a>"
            + (" · Storniert" if row.get("cancelled_at") is not None else " · Aktiv")
            + "</li>"
            for row in cast(list[dict[str, object]], detail["orders"])
        )
        or "<li>Keine Aufträge</li>"
    )
    email = detail.get("email")
    phone = detail.get("phone")
    status_label = format_contact_status_for_display(detail.get("contact_status"))
    body = (
        f'<p class="subtitle">Projection {_e(contact_key)}</p>'
        '<section class="offer-detail-section">'
        "<h2>Kontakt-Profil</h2>"
        f"<p><span>Name</span><strong>{_e(str(detail['display_name']))}</strong></p>"
        f"<p><span>Status</span><strong>{_e(status_label)}</strong></p>"
        f"<p><span>Telefon</span><strong>{_e(str(phone) if phone else '–')}</strong></p>"
        f"<p><span>E-Mail</span><strong>{_e(str(email) if email else '–')}</strong></p>"
        "</section>"
        + _notes_section(detail, context)
        + '<section class="offer-detail-section">'
        "<h2>Anfragen</h2>"
        f'<ul class="offer-variant-list">{inquiry_rows}</ul>'
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Angebote</h2>"
        f'<ul class="offer-variant-list">{offer_rows}</ul>'
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Aufträge</h2>"
        f'<ul class="offer-history-list">{order_rows}</ul>'
        "</section>" + '<p><a href="/kontakte">← Zurück zu Kontakten</a></p>'
    )
    return _page("Kontakt", body, active_section="contacts", context=context)

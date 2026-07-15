"""Kontakt detail presentation — read-only projection context (5C-1)."""

from __future__ import annotations

from typing import cast

from catering_system.ui.office_api_views import offer_state_label
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)


def _short_date(raw: str) -> str:
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return f"{raw[8:10]}.{raw[5:7]}.{raw[0:4]}"
    return raw


def render_kontakt_detail(
    detail: dict[str, object],
    *,
    context: OfficePageContext,
) -> str:
    contact_key = str(detail["contact_key"])
    inquiry_rows = "".join(
        "<li>"
        f'<a href="/inquiry/{_e(str(row["inquiry_id"]))}">'
        f"{_e(str(row.get('intake_subject') or str(row['inquiry_id'])[:8]))}</a>"
        f" · {_e(_short_date(str(row['event_date'])))}"
        f" · {_e(str(row['crm_stage']))}"
        "</li>"
        for row in cast(list[dict[str, object]], detail["inquiries"])
    ) or "<li>Keine Anfragen</li>"
    offer_rows = "".join(
        "<li>"
        f'<a href="/offer/{_e(str(row["offer_id"]))}">'
        f"{_e(offer_state_label(str(row['state'])))}</a>"  # type: ignore[arg-type]
        f" · Anfrage {_e(str(row['inquiry_id'])[:8])}"
        "</li>"
        for row in cast(list[dict[str, object]], detail["offers"])
    ) or "<li>Keine Angebote</li>"
    order_rows = "".join(
        "<li>"
        f'<a href="/order/{_e(str(row["order_id"]))}">'
        f"Auftrag {_e(str(row['order_id'])[:8])}</a>"
        + (
            " · Storniert"
            if row.get("cancelled_at") is not None
            else " · Aktiv"
        )
        + "</li>"
        for row in cast(list[dict[str, object]], detail["orders"])
    ) or "<li>Keine Aufträge</li>"
    email = detail.get("email")
    phone = detail.get("phone")
    body = (
        f'<p class="subtitle">Projection {_e(contact_key)}</p>'
        '<section class="offer-detail-section">'
        "<h2>Kontakt-Profil</h2>"
        f"<p><span>Name</span><strong>{_e(str(detail['display_name']))}</strong></p>"
        f"<p><span>Telefon</span><strong>{_e(str(phone) if phone else '–')}</strong></p>"
        f"<p><span>E-Mail</span><strong>{_e(str(email) if email else '–')}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
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
        "</section>"
        + '<p><a href="/kontakte">← Zurück zu Kontakten</a></p>'
    )
    return _page("Kontakt", body, active_section="contacts", context=context)

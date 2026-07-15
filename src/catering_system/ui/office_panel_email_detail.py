"""E-Mail intake detail presentation — read-only Zuordnung (5C-2)."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from urllib.parse import quote
from zoneinfo import ZoneInfo

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

_BERLIN = ZoneInfo("Europe/Berlin")


def _long_received(raw: str) -> str:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    local = value.astimezone(_BERLIN)
    return (
        f"{local.day:02d}.{local.month:02d}.{local.year} "
        f"{local.hour:02d}:{local.minute:02d}"
    )


def render_email_detail(
    detail: dict[str, object],
    *,
    context: OfficePageContext,
) -> str:
    inquiry_id = str(detail["inquiry_id"])
    contact_key = str(detail["contact_key"])
    sender = detail.get("sender_email")
    message = str(detail.get("preview") or "–")
    offer_id = detail.get("linked_offer_id")
    order_ids = cast(list[str], detail.get("linked_order_ids") or [])
    offer_link = (
        f'<p><a href="/offer/{_e(str(offer_id))}">Angebot öffnen</a></p>'
        if offer_id is not None
        else "<p>Kein Angebot verknüpft</p>"
    )
    if order_ids:
        order_links = "".join(
            f'<li><a href="/order/{_e(order_id)}">Auftrag {_e(order_id[:8])}</a></li>'
            for order_id in order_ids
        )
        orders_block = f"<ul>{order_links}</ul>"
    else:
        orders_block = "<p>Keine Aufträge verknüpft</p>"
    body = (
        f'<p class="subtitle">E-Mail-Anfrage {_e(inquiry_id[:8])}</p>'
        '<section class="offer-detail-section">'
        "<h2>Absender</h2>"
        f"<p><strong>{_e(str(sender) if sender else '–')}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Betreff</h2>"
        f"<p><strong>{_e(str(detail['subject']))}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Eingang</h2>"
        f"<p><strong>{_e(_long_received(str(detail['received_at'])))}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Nachricht</h2>"
        f"<pre class=\"email-message\">{_e(message)}</pre>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Zuordnung</h2>"
        f'<p><a href="/inquiry/{_e(inquiry_id)}">Anfrage öffnen</a></p>'
        f'<p><a href="/kontakt/{_e(quote(contact_key, safe=""))}">Kontakt öffnen</a></p>'
        + offer_link
        + orders_block
        + "</section>"
        + '<p><a href="/email">← Zurück zu E-Mail</a></p>'
    )
    return _page("E-Mail", body, active_section="email", context=context)

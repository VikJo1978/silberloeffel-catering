"""E-Mail intake detail — read-only projection of inquiry_source=email (V0)."""

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
_MISSING = "Nicht angegeben"


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


def _display(value: object | None) -> str:
    if value is None:
        return _MISSING
    text = str(value).strip()
    return text if text else _MISSING


def _nl2br_escaped(text: str) -> str:
    return "<br>".join(_e(line) for line in text.splitlines()) or _e(text)


def render_email_detail(
    detail: dict[str, object],
    *,
    context: OfficePageContext,
) -> str:
    inquiry_id = str(detail["inquiry_id"])
    contact_key = str(detail["contact_key"])
    message = detail.get("preview")
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
    message_body = (
        f"<p>{_nl2br_escaped(str(message))}</p>"
        if message is not None and str(message).strip()
        else f"<p>{_e(_MISSING)}</p>"
    )
    body = (
        f'<p class="subtitle">E-Mail-Anfrage {_e(inquiry_id)}</p>'
        '<section class="offer-detail-section">'
        "<h2>Absender</h2>"
        f"<p><span>Name</span><strong>{_e(_display(detail.get('sender_name')))}</strong></p>"
        f"<p><span>E-Mail</span><strong>{_e(_display(detail.get('sender_email')))}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Betreff</h2>"
        f"<p><strong>{_e(_display(detail.get('subject')))}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Eingang</h2>"
        f"<p><strong>{_e(_long_received(str(detail['received_at'])))}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>CRM-Stufe</h2>"
        f"<p><strong>{_e(_display(detail.get('crm_stage')))}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Nachricht</h2>"
        f"{message_body}"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Zuordnung</h2>"
        f'<p><a href="/inquiry/{_e(inquiry_id)}">Anfrage öffnen</a></p>'
        f'<p><a href="/kontakt/{_e(quote(contact_key, safe=""))}">Kontakt öffnen</a></p>'
        + offer_link
        + orders_block
        + "</section>"
        + '<p><a href="/emails">← Zurück zu E-Mail</a></p>'
    )
    return _page("E-Mail", body, active_section="email", context=context)

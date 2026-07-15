"""Angebot detail presentation — read-only commercial history (5B-2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import cast
from zoneinfo import ZoneInfo

from catering_system.ui.office_api_views import offer_state_label
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

_BERLIN = ZoneInfo("Europe/Berlin")
_PLANNING_LABELS = {
    "caterer_suggestion": "Vorschlag durch Silberlöffel",
    "self_select": "Selbstauswahl",
}


def _long_date(raw: str) -> str:
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        return raw
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


def _history_date(raw: str) -> str:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    local = value.astimezone(_BERLIN)
    return f"{local.day:02d}.{local.month:02d}"


def _surface_version(detail: dict[str, object]) -> dict[str, object]:
    versions = cast(list[dict[str, object]], detail["versions"])
    commercial = str(detail["commercial_state"])
    for version in reversed(versions):
        if str(version["state"]) == commercial:
            return version
    return versions[-1]


def render_offer_detail(
    detail: dict[str, object],
    *,
    context: OfficePageContext,
) -> str:
    offer_id = str(detail["offer_id"])
    inquiry_id = str(detail["inquiry_id"])
    state = str(detail["commercial_state"])
    surface = _surface_version(detail)
    guest_count = surface.get("guest_count")
    guest_text = (
        str(guest_count) if guest_count is not None else "noch offen"
    )
    planning = _PLANNING_LABELS.get(
        str(surface.get("planning_mode", "")), str(surface.get("planning_mode", "–"))
    )
    variants = cast(list[dict[str, object]], surface["variants"])
    variant_rows = "".join(
        f"<li>{_e(str(variant['name']))}</li>" for variant in variants
    ) or "<li>Keine Varianten</li>"
    history_rows = "".join(
        f"<li><span>{_e(_history_date(str(entry['at'])))}</span> "
        f"{_e(str(entry['label']))}</li>"
        for entry in cast(list[dict[str, object]], detail["history"])
    ) or "<li>Noch keine Historie</li>"
    order_id = detail.get("order_id")
    order_link = (
        f'<p><a href="/order/{_e(str(order_id))}">Auftrag öffnen</a></p>'
        if order_id is not None
        else ""
    )
    body = (
        f'<p class="subtitle">Angebot {_e(offer_id[:8])}</p>'
        '<section class="offer-detail-section">'
        "<h2>Status</h2>"
        f"<p><strong>{_e(offer_state_label(state))}</strong></p>"  # type: ignore[arg-type]
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Veranstaltung</h2>"
        f"<p><span>Datum</span><strong>{_e(_long_date(str(surface['event_date'])))}</strong></p>"
        f"<p><span>Ort</span><strong>{_e(str(surface['location_text']))}</strong></p>"
        f"<p><span>Gäste</span><strong>{_e(guest_text)}</strong></p>"
        f"<p><span>Zeitfenster</span><strong>{_e(str(surface['time_window_text']))}</strong></p>"
        f"<p><span>Planung</span><strong>{_e(planning)}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Angebotsvarianten</h2>"
        f"<ul class=\"offer-variant-list\">{variant_rows}</ul>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Historie</h2>"
        f'<ul class="offer-history-list">{history_rows}</ul>'
        "</section>"
        + order_link
        + f'<p><a href="/inquiry/{_e(inquiry_id)}">Anfrage öffnen</a></p>'
        + '<p><a href="/angebote">← Zurück zu Angeboten</a></p>'
    )
    return _page(
        "Angebot",
        body,
        active_section="inquiries",
        context=context,
    )

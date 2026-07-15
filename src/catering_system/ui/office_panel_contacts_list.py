"""Kontakte list presentation — read-only contact projection rows (5C-1)."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

_BERLIN = ZoneInfo("Europe/Berlin")


def _contact_line(email: object | None, phone: object | None) -> str:
    parts = [str(value) for value in (email, phone) if value]
    return " · ".join(parts) if parts else "–"


def _short_activity(raw: str) -> str:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    local = value.astimezone(_BERLIN)
    return f"{local.day:02d}.{local.month:02d}.{local.year}"


def render_kontakte_list(
    rows: list[dict[str, object]],
    *,
    context: OfficePageContext,
) -> str:
    table_rows = []
    for row in rows:
        contact_key = str(row["contact_key"])
        table_rows.append(
            "<tr>"
            f"<td>{_e(str(row['display_name']))}</td>"
            f"<td>{_e(_contact_line(row.get('email'), row.get('phone')))}</td>"
            f"<td>{_e(str(row['inquiry_count']))}</td>"
            f"<td>{_e(str(row['active_orders']))}</td>"
            f"<td>{_e(_short_activity(str(row['last_activity'])))}</td>"
            f'<td><a href="/kontakt/{_e(quote(contact_key, safe=""))}">Öffnen</a></td>'
            "</tr>"
        )
    body = (
        '<p class="subtitle">Übersicht aus Anfragen — keine CRM-Stammdaten.</p>'
        "<table><tr><th>Name</th><th>Kontakt</th><th>Anfragen</th>"
        "<th>Aufträge</th><th>Letzte Aktivität</th><th></th></tr>"
        + "".join(
            table_rows or ['<tr><td colspan="6">Keine Kontakte vorhanden.</td></tr>']
        )
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Kontakte", body, active_section="contacts", context=context)

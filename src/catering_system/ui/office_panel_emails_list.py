"""E-Mail intake list — read-only projection of inquiry_source=email (V0)."""

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
_MISSING = "Nicht angegeben"


def _short_received(raw: str) -> str:
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


def render_email_list(
    rows: list[dict[str, object]],
    *,
    context: OfficePageContext,
) -> str:
    table_rows = []
    for row in rows:
        inquiry_id = str(row["inquiry_id"])
        table_rows.append(
            "<tr>"
            f"<td>{_e(_short_received(str(row['received_at'])))}</td>"
            f"<td>{_e(_display(row.get('sender_name')))}</td>"
            f"<td>{_e(_display(row.get('sender_email')))}</td>"
            f"<td>{_e(_display(row.get('subject')))}</td>"
            f"<td>{_e(_display(row.get('crm_stage')))}</td>"
            f"<td>{_e(inquiry_id)}</td>"
            f'<td><a href="/emails/{_e(quote(inquiry_id, safe=""))}">Öffnen</a></td>'
            "</tr>"
        )
    if not table_rows:
        table_body = '<tr><td colspan="7">Keine E-Mail-Anfragen vorhanden.</td></tr>'
    else:
        table_body = "".join(table_rows)
    body = (
        '<p class="subtitle">Nur Anfragen mit Kanal E-Mail — '
        "read-only Projektion, kein Postfach.</p>"
        "<table><tr><th>Eingang</th><th>Name</th><th>E-Mail</th>"
        "<th>Betreff</th><th>CRM-Stufe</th><th>Anfrage-ID</th><th></th></tr>"
        + table_body
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("E-Mail", body, active_section="email", context=context)

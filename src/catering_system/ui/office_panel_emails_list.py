"""E-Mail intake list presentation — read-only rows (5C-2)."""

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


def _short_received(raw: str) -> str:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    local = value.astimezone(_BERLIN)
    return f"{local.day:02d}.{local.month:02d}.{local.year}"


def _preview_line(raw: str) -> str:
    text = raw.strip().replace("\n", " ")
    if len(text) <= 80:
        return text or "–"
    return text[:77] + "…"


def render_email_list(
    rows: list[dict[str, object]],
    *,
    context: OfficePageContext,
) -> str:
    table_rows = []
    for row in rows:
        inquiry_id = str(row["inquiry_id"])
        sender = row.get("sender_email") or "–"
        table_rows.append(
            "<tr>"
            f"<td>{_e(_short_received(str(row['received_at'])))}</td>"
            f"<td>{_e(str(sender))}</td>"
            f"<td>{_e(str(row['subject']))}</td>"
            f"<td>{_e(_preview_line(str(row['preview'])))}</td>"
            f'<td><a href="/email/{_e(quote(inquiry_id, safe=""))}">Öffnen</a></td>'
            "</tr>"
        )
    body = (
        '<p class="subtitle">Eingegangene E-Mail-Anfragen (inquiry_source=email).</p>'
        "<table><tr><th>Eingang</th><th>Absender</th><th>Betreff</th>"
        "<th>Vorschau</th><th></th></tr>"
        + "".join(
            table_rows or ['<tr><td colspan="5">Keine E-Mails vorhanden.</td></tr>']
        )
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("E-Mail", body, active_section="email", context=context)

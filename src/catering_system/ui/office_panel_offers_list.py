"""Angebotsliste presentation — read-only rows from offer list projection (5B-1)."""

from __future__ import annotations

from datetime import date

from catering_system.ui.office_api_views import offer_state_label
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)


def _short_date(raw: str) -> str:
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        return raw
    return f"{value.day:02d}.{value.month:02d}"


def render_angebote_list(
    rows: list[dict[str, object]],
    titles_by_inquiry: dict[str, str],
    *,
    context: OfficePageContext,
) -> str:
    table_rows = []
    for row in rows:
        inquiry_id = str(row["inquiry_id"])
        state = str(row["state"])
        title = titles_by_inquiry.get(inquiry_id, "–")
        table_rows.append(
            "<tr>"
            f"<td>{_e(offer_state_label(state))}</td>"  # type: ignore[arg-type]
            f"<td>{_e(title)}</td>"
            f"<td>{_e(_short_date(str(row['event_date'])))}</td>"
            f'<td><a href="/offer/{_e(str(row["offer_id"]))}">Öffnen</a></td>'
            "</tr>"
        )
    body = (
        '<p class="subtitle">Übersicht aller Angebote im Vertrieb.</p>'
        "<table><tr><th>Status</th><th>Veranstaltung</th><th>Datum</th><th></th></tr>"
        + "".join(table_rows or ['<tr><td colspan="4">Keine Angebote vorhanden.</td></tr>'])
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Angebote", body, active_section="inquiries", context=context)

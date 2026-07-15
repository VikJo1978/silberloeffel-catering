"""Kalender list presentation — read-only event calendar projection rows (5E-1a)."""

from __future__ import annotations

from datetime import date

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

def _format_date(raw: object) -> str:
    if isinstance(raw, str):
        try:
            value = date.fromisoformat(raw)
        except ValueError:
            return raw
    elif isinstance(raw, date):
        value = raw
    else:
        return "–"
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


def _format_guests(raw: object | None) -> str:
    if raw is None:
        return "–"
    return str(raw)


def render_kalender_list(
    rows: list[dict[str, object]],
    *,
    context: OfficePageContext,
) -> str:
    table_rows = []
    for row in rows:
        href = str(row["action_href"])
        table_rows.append(
            "<tr>"
            f"<td>{_e(_format_date(row['event_date']))}</td>"
            f"<td>{_e(str(row['status_label']))}</td>"
            f"<td>{_e(str(row['title']))}</td>"
            f"<td>{_e(str(row['time_window_text']))}</td>"
            f"<td>{_e(str(row['location_text']))}</td>"
            f"<td>{_e(_format_guests(row.get('guest_count_estimate')))}</td>"
            f'<td><a href="{_e(href)}">{_e(str(row["action_label"]))}</a></td>'
            "</tr>"
        )
    body = (
        '<p class="subtitle">Veranstaltungstermine aus Anfragen, Angeboten '
        "und Aufträgen — ohne Zahlungs- oder Aufgabenfristen.</p>"
        "<table><tr><th>Datum</th><th>Status</th><th>Veranstaltung</th>"
        "<th>Zeitfenster</th><th>Ort</th><th>Gäste</th><th></th></tr>"
        + "".join(
            table_rows or ['<tr><td colspan="7">Keine Termine im Zeitraum.</td></tr>']
        )
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Kalender", body, active_section="calendar", context=context)

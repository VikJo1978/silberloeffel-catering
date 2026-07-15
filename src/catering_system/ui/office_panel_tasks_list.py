"""Aufgaben list presentation — read-only system task projection rows (5D-1a)."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

_BERLIN = ZoneInfo("Europe/Berlin")


def _format_due(raw: object | None) -> str:
    if raw is None:
        return "–"
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


def _urgency_label(raw: object) -> str:
    if raw == "overdue":
        return "Überfällig"
    return "Normal"


def render_aufgaben_list(
    rows: list[dict[str, object]],
    *,
    context: OfficePageContext,
) -> str:
    table_rows = []
    for row in rows:
        href = str(row["action_href"])
        table_rows.append(
            "<tr>"
            f"<td>{_e(_urgency_label(row['urgency']))}</td>"
            f"<td>{_e(str(row['title']))}</td>"
            f"<td>{_e(str(row['subtitle']))}</td>"
            f"<td>{_e(_format_due(row.get('due_at')))}</td>"
            f'<td><a href="{_e(href)}">{_e(str(row["action_label"]))}</a></td>'
            "</tr>"
        )
    body = (
        '<p class="subtitle">Abgeleitete Büro-Aufgaben aus Anfragen, Aufträgen '
        "und Zahlungserinnerungen.</p>"
        "<table><tr><th>Dringlichkeit</th><th>Aufgabe</th><th>Bezug</th>"
        "<th>Fällig</th><th></th></tr>"
        + "".join(
            table_rows or ['<tr><td colspan="5">Keine offenen Aufgaben.</td></tr>']
        )
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Aufgaben", body, active_section="tasks", context=context)

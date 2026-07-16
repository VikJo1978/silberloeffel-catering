"""Gerichte list — read-only catalog projection (6D-1)."""

from __future__ import annotations

from urllib.parse import quote

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)


def _allergen_cell(labels: object) -> str:
    if isinstance(labels, list) and labels:
        return ", ".join(_e(str(label)) for label in labels)
    return "–"


def render_gerichte_list(
    payload: dict[str, object],
    *,
    context: OfficePageContext,
) -> str:
    rows = payload.get("dishes")
    if not isinstance(rows, list):
        rows = []
    table_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dish_id = str(row["dish_id"])
        status = "Aktiv" if row.get("active") else "Inaktiv"
        table_rows.append(
            "<tr>"
            f"<td>{_e(str(row['name']))}</td>"
            f"<td>{_e(str(row.get('price_display', '–')))}</td>"
            f"<td>{_allergen_cell(row.get('allergen_labels'))}</td>"
            f"<td>{_e(status)}</td>"
            f'<td><a href="/gerichte/{_e(quote(dish_id, safe=""))}">Öffnen</a></td>'
            "</tr>"
        )
    body = (
        '<p class="subtitle">Stammdaten — nur Lesen. Änderungen folgen in Verwaltung.</p>'
        "<table><tr><th>Name</th><th>Preis</th><th>Allergene</th>"
        "<th>Status</th><th></th></tr>"
        + "".join(
            table_rows
            or ['<tr><td colspan="5">Keine Gerichte vorhanden.</td></tr>']
        )
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Gerichte", body, active_section="catalog", context=context)

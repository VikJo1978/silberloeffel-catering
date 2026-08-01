"""Gerichte list — catalog administration surface (6D-1, CATALOG_ADMIN_PANEL_V1)."""

from __future__ import annotations

from urllib.parse import quote

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

# CATALOG_ADMIN_PANEL_V1: German labels for the closed pricing_unit set. The
# codes themselves stay the domain's (per_person/stueck/pauschal) — this is
# presentation only, so an unknown code degrades to the raw value rather than
# raising, keeping the page rendering even against unexpected data.
PRICING_UNIT_LABELS = {
    "per_person": "pro Person",
    "stueck": "Stück",
    "pauschal": "Pauschal",
}

_STATUS_TABS = (
    ("all", "Alle"),
    ("active", "Aktiv"),
    ("inactive", "Inaktiv"),
)

# CATALOG_ADMIN_PANEL_V1: the read layer caps a page at 100 rows. Filtering
# now happens in the query, so a full page means "there are more matches",
# never "the filter silently dropped them" — but the page still must not
# imply it is showing the whole catalog.
CATALOG_PAGE_LIMIT = 100
_LIMIT_NOTICE = (
    "Die Liste ist auf 100 Gerichte begrenzt. "
    "Bitte verwenden Sie die Suche, um weitere Gerichte zu finden."
)


def _allergen_cell(labels: object) -> str:
    if isinstance(labels, list) and labels:
        return ", ".join(_e(str(label)) for label in labels)
    return "–"


def _optional_cell(value: object) -> str:
    """Legacy rows predate category/pricing_unit/vat_rate_percent and carry
    NULL for them (CATALOG_ADMIN_COMPLETION_V1A decision #2/#3) — they render
    as a dash instead of breaking the page."""
    if value is None:
        return "–"
    text = str(value).strip()
    return _e(text) if text else "–"


def pricing_unit_label(value: object) -> str:
    if value is None:
        return "–"
    return _e(PRICING_UNIT_LABELS.get(str(value), str(value)))


def vat_label(value: object) -> str:
    if value is None:
        return "–"
    return f"{_e(str(value))} %"


def _status_tabs(search_query: str, status_filter: str) -> str:
    links = []
    for value, label in _STATUS_TABS:
        params = {"status": value}
        if search_query:
            params["q"] = search_query
        query = "&".join(
            f"{key}={quote(str(param_value), safe='')}"
            for key, param_value in params.items()
        )
        if value == status_filter:
            links.append(f"<strong>{_e(label)}</strong>")
        else:
            links.append(f'<a href="/gerichte?{_e(query)}">{_e(label)}</a>')
    return '<p class="catalog-filter">' + " | ".join(links) + "</p>"


def _search_form(search_query: str, status_filter: str) -> str:
    return (
        '<form method="get" action="/gerichte" class="catalog-search">'
        f'<input type="hidden" name="status" value="{_e(status_filter)}">'
        '<label for="q">Suche nach Name</label> '
        f'<input id="q" name="q" value="{_e(search_query)}" size="30">'
        '<button type="submit">Suchen</button>'
        "</form>"
    )


def render_gerichte_list(
    payload: dict[str, object],
    *,
    search_query: str = "",
    status_filter: str = "all",
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
            f"<td>{_optional_cell(row.get('category'))}</td>"
            f"<td>{pricing_unit_label(row.get('pricing_unit'))}</td>"
            '<td class="catalog-price">'
            f"{_e(str(row.get('price_display', '–')))}</td>"
            f"<td>{vat_label(row.get('vat_rate_percent'))}</td>"
            f"<td>{_allergen_cell(row.get('allergen_labels'))}</td>"
            f"<td>{_e(status)}</td>"
            f'<td><a href="/gerichte/{_e(quote(dish_id, safe=""))}">Öffnen</a></td>'
            "</tr>"
        )
    empty_text = (
        "Keine Gerichte gefunden."
        if search_query or status_filter != "all"
        else "Keine Gerichte vorhanden."
    )
    limit_notice = (
        f'<p class="catalog-limit">{_e(_LIMIT_NOTICE)}</p>'
        if len(table_rows) >= CATALOG_PAGE_LIMIT
        else ""
    )
    body = (
        '<p class="subtitle">Stammdaten — Gerichte anlegen, bearbeiten und '
        "aktivieren.</p>"
        + (
            '<p><a href="/gerichte/new">Neues Gericht anlegen</a></p>'
            if context.can("catalog.edit")
            else ""
        )
        + _search_form(search_query, status_filter)
        + _status_tabs(search_query, status_filter)
        + limit_notice
        + "<table><tr><th>Name</th><th>Kategorie</th><th>Preiseinheit</th>"
        "<th>Netto-Preis</th><th>MwSt</th><th>Allergene</th>"
        "<th>Status</th><th></th></tr>"
        + "".join(table_rows or [f'<tr><td colspan="8">{_e(empty_text)}</td></tr>'])
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Gerichte", body, active_section="catalog", context=context)

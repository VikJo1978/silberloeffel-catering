"""Gericht edit form — catalog write surface (6D-2)."""

from __future__ import annotations

from catering_system.domain.catalog import ALLERGEN_CODES, ALLERGEN_LABELS
from catering_system.ui.office_api_views import catalog_price_input_value
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)


def _textarea(name: str, label: str, value: object | None) -> str:
    text = str(value) if value is not None else ""
    return (
        f"<p><label for=\"{_e(name)}\">{_e(label)}</label><br>"
        f'<textarea id="{_e(name)}" name="{_e(name)}" rows="4" cols="60">'
        f"{_e(text)}</textarea></p>"
    )


def _text_input(name: str, label: str, value: str) -> str:
    return (
        f"<p><label for=\"{_e(name)}\">{_e(label)}</label><br>"
        f'<input id="{_e(name)}" name="{_e(name)}" value="{_e(value)}" size="60"></p>'
    )


def _allergen_checkboxes(selected: object) -> str:
    selected_codes = set()
    if isinstance(selected, list):
        selected_codes = {str(code).upper() for code in selected}
    items = []
    for code in ALLERGEN_CODES:
        checked = " checked" if code in selected_codes else ""
        label = ALLERGEN_LABELS[code]
        items.append(
            f'<label><input type="checkbox" name="allergen_{_e(code)}" value="1"{checked}> '
            f"{_e(code)} {_e(label)}</label>"
        )
    return (
        "<p><strong>Allergene</strong></p>"
        '<div class="allergen-grid">' + "".join(items) + "</div>"
    )


def render_gericht_edit(
    detail: dict[str, object],
    *,
    command_fields: str,
    context: OfficePageContext,
    error_message: str | None = None,
) -> str:
    name = str(detail.get("name", "Gericht"))
    dish_id = str(detail.get("dish_id", ""))
    cents = int(detail.get("current_unit_net_cents", 0))
    active = bool(detail.get("active"))
    effective_default = str(detail.get("effective_from_default", ""))
    error_html = (
        f'<p class="error">{_e(error_message)}</p>' if error_message else ""
    )
    body = (
        error_html
        + f'<p class="subtitle"><a href="/gerichte/{_e(dish_id)}">← Zurück zum Gericht</a></p>'
        + f'<form method="post" action="/gerichte/{_e(dish_id)}/update">'
        + command_fields
        + _text_input("name", "Name", name)
        + _textarea("description", "Beschreibung", detail.get("description"))
        + _textarea("composition", "Zusammensetzung", detail.get("composition"))
        + _textarea("notes", "Notizen", detail.get("notes"))
        + _text_input(
            "price_net",
            "Preis netto (€)",
            catalog_price_input_value(cents),
        )
        + _allergen_checkboxes(detail.get("allergens"))
        + (
            f'<p><label><input type="checkbox" name="active" value="1"'
            f'{" checked" if active else ""}> Aktiv</label></p>'
        )
        + _text_input("effective_from", "Gültig ab (Preis)", effective_default)
        + '<p><button type="submit">Speichern</button></p>'
        + "</form>"
    )
    return _page(
        f"{name} bearbeiten",
        body,
        active_section="catalog",
        context=context,
    )

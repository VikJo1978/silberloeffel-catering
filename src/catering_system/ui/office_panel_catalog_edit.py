"""Gericht edit form — catalog write surface (6D-2)."""

from __future__ import annotations

from catering_system.domain.catalog import ALLERGEN_CODES, ALLERGEN_LABELS
from catering_system.ui.office_api_views import catalog_price_input_value
from catering_system.ui.office_panel_catalog_list import (
    pricing_unit_label,
    vat_label,
)
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)


def _textarea(
    name: str,
    label: str,
    value: object | None,
    *,
    editable: bool,
) -> str:
    text = str(value) if value is not None else ""
    if editable:
        return (
            f'<p><label for="{_e(name)}">{_e(label)}</label><br>'
            f'<textarea id="{_e(name)}" name="{_e(name)}" rows="4" cols="60">'
            f"{_e(text)}</textarea></p>"
        )
    return (
        f'<p><strong>{_e(label)}:</strong> {_e(text) if text else "–"}</p>'
        f'<input type="hidden" name="{_e(name)}" value="{_e(text)}">'
    )


def _text_input(
    name: str,
    label: str,
    value: str,
    *,
    editable: bool,
) -> str:
    if editable:
        return (
            f'<p><label for="{_e(name)}">{_e(label)}</label><br>'
            f'<input id="{_e(name)}" name="{_e(name)}" value="{_e(value)}" size="60"></p>'
        )
    return (
        f'<p><strong>{_e(label)}:</strong> {_e(value)}</p>'
        f'<input type="hidden" name="{_e(name)}" value="{_e(value)}">'
    )


def _allergen_checkboxes(selected: object, *, editable: bool) -> str:
    selected_codes = set()
    if isinstance(selected, list):
        selected_codes = {str(code).upper() for code in selected}
    if not editable:
        labels = []
        for code in ALLERGEN_CODES:
            if code in selected_codes:
                labels.append(f"{code} {ALLERGEN_LABELS[code]}")
        display = ", ".join(_e(label) for label in labels) if labels else "–"
        hidden = "".join(
            f'<input type="hidden" name="allergen_{_e(code)}" value="1">'
            for code in ALLERGEN_CODES
            if code in selected_codes
        )
        return (
            f"<p><strong>Allergene:</strong> {display}</p>{hidden}"
        )
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
    cents = int(str(detail.get("current_unit_net_cents", 0)))
    active = bool(detail.get("active"))
    effective_default = str(detail.get("effective_from_default", ""))
    can_edit_metadata = context.can("catalog.edit")
    can_edit_price = context.can("prices.edit")
    error_html = f'<p class="error">{_e(error_message)}</p>' if error_message else ""
    submit_html = ""
    if can_edit_metadata or can_edit_price:
        submit_html = '<p><button type="submit">Speichern</button></p>'
    body = (
        error_html
        + f'<p class="subtitle"><a href="/gerichte/{_e(dish_id)}">← Zurück zum Gericht</a></p>'
        # CATALOG_ADMIN_PANEL_V1: status and the creation-time fields are shown
        # here for orientation but are not editable on this form — status has
        # its own Aktivieren/Deaktivieren commands on the detail page, and
        # Kategorie/Preiseinheit/MwSt have no edit path in this slice. A
        # checkbox for `active` would additionally be unsafe: an unchecked box
        # is indistinguishable from an absent one, so a plain save would read
        # as "deactivate".
        + '<p class="catalog-readonly"><strong>Status:</strong> '
        + f"{_e('Aktiv' if active else 'Inaktiv')} — "
        + f'<a href="/gerichte/{_e(dish_id)}">Status ändern</a></p>'
        + '<p class="catalog-readonly"><strong>Kategorie:</strong> '
        + f"{_e(str(detail.get('category') or '–'))}</p>"
        + '<p class="catalog-readonly"><strong>Preiseinheit:</strong> '
        + f"{pricing_unit_label(detail.get('pricing_unit'))}</p>"
        + '<p class="catalog-readonly"><strong>MwSt:</strong> '
        + f"{vat_label(detail.get('vat_rate_percent'))}</p>"
        + f'<form method="post" action="/gerichte/{_e(dish_id)}/update">'
        + command_fields
        + _text_input("name", "Name", name, editable=can_edit_metadata)
        + _textarea(
            "description",
            "Beschreibung",
            detail.get("description"),
            editable=can_edit_metadata,
        )
        + _textarea(
            "composition",
            "Zusammensetzung",
            detail.get("composition"),
            editable=can_edit_metadata,
        )
        + _textarea("notes", "Notizen", detail.get("notes"), editable=can_edit_metadata)
        + _text_input(
            "price_net",
            "Preis netto (€)",
            catalog_price_input_value(cents),
            editable=can_edit_price,
        )
        + _allergen_checkboxes(detail.get("allergens"), editable=can_edit_metadata)
        + _text_input(
            "effective_from",
            "Gültig ab (Preis)",
            effective_default,
            editable=can_edit_price,
        )
        + submit_html
        + "</form>"
    )
    return _page(
        f"{name} bearbeiten",
        body,
        active_section="catalog",
        context=context,
    )

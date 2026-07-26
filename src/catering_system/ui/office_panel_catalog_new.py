"""Neues Gericht form — catalog create surface (CATALOG_ADMIN_PANEL_V1)."""

from __future__ import annotations

from catering_system.domain.catalog import (
    ALLERGEN_CODES,
    ALLERGEN_LABELS,
    PRICING_UNITS,
)
from catering_system.ui.office_panel_catalog_list import PRICING_UNIT_LABELS
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

# CATALOG_ADMIN_PANEL_V1: the selectable VAT rates. The domain keeps its own
# authoritative tuple private and validates every submission through
# CatalogDishCreatePayload, so this list only decides what the dropdown
# offers — it can never widen what the domain accepts.
VAT_RATE_OPTIONS = (7, 19)

_CATEGORY_HINT = (
    "Kleinbuchstaben, Ziffern und - oder _ als Trenner, z. B. "
    "„fingerfood“ oder „warme_speisen“."
)


def _text_input(name: str, label: str, value: str, *, hint: str = "") -> str:
    hint_html = f"<br><small>{_e(hint)}</small>" if hint else ""
    return (
        f'<p><label for="{_e(name)}">{_e(label)}</label><br>'
        f'<input id="{_e(name)}" name="{_e(name)}" value="{_e(value)}" size="60">'
        f"{hint_html}</p>"
    )


def _textarea(name: str, label: str, value: str) -> str:
    return (
        f'<p><label for="{_e(name)}">{_e(label)}</label><br>'
        f'<textarea id="{_e(name)}" name="{_e(name)}" rows="4" cols="60">'
        f"{_e(value)}</textarea></p>"
    )


def _pricing_unit_select(selected: str) -> str:
    options = []
    for code in PRICING_UNITS:
        chosen = " selected" if code == selected else ""
        label = PRICING_UNIT_LABELS.get(code, code)
        options.append(f'<option value="{_e(code)}"{chosen}>{_e(label)}</option>')
    return (
        '<p><label for="pricing_unit">Preiseinheit</label><br>'
        '<select id="pricing_unit" name="pricing_unit">'
        + "".join(options)
        + "</select></p>"
    )


def _vat_select(selected: str) -> str:
    options = []
    for rate in VAT_RATE_OPTIONS:
        chosen = " selected" if str(rate) == selected else ""
        options.append(f'<option value="{rate}"{chosen}>{rate} %</option>')
    return (
        '<p><label for="vat_rate_percent">MwSt</label><br>'
        '<select id="vat_rate_percent" name="vat_rate_percent">'
        + "".join(options)
        + "</select></p>"
    )


def _allergen_checkboxes(form: dict[str, str]) -> str:
    items = []
    for code in ALLERGEN_CODES:
        checked = " checked" if form.get(f"allergen_{code}") == "1" else ""
        label = ALLERGEN_LABELS[code]
        items.append(
            f'<label><input type="checkbox" name="allergen_{_e(code)}" '
            f'value="1"{checked}> {_e(code)} {_e(label)}</label>'
        )
    return (
        "<p><strong>Allergene</strong></p>"
        '<div class="allergen-grid">' + "".join(items) + "</div>"
    )


def render_gericht_new(
    *,
    command_fields: str,
    context: OfficePageContext,
    form: dict[str, str] | None = None,
    error_message: str | None = None,
) -> str:
    """Renders the create form, re-filling every field from `form` so a
    rejected submission never silently discards what was typed."""
    values = form or {}
    error_html = f'<p class="error">{_e(error_message)}</p>' if error_message else ""
    body = (
        error_html
        + '<p class="subtitle">Neues Gericht wird zunächst <strong>inaktiv</strong> '
        "angelegt und kann danach aktiviert werden.</p>"
        + '<form method="post" action="/gerichte/new">'
        + command_fields
        + _text_input("name", "Name", values.get("name", ""))
        + _textarea("description", "Beschreibung", values.get("description", ""))
        + _textarea("composition", "Zusammensetzung", values.get("composition", ""))
        + _textarea("notes", "Hinweise", values.get("notes", ""))
        + _text_input(
            "category",
            "Kategorie",
            values.get("category", ""),
            hint=_CATEGORY_HINT,
        )
        + _pricing_unit_select(values.get("pricing_unit", ""))
        + _text_input("price_net", "Netto-Preis (€)", values.get("price_net", ""))
        + _vat_select(values.get("vat_rate_percent", ""))
        + _allergen_checkboxes(values)
        + '<p><button type="submit">Gericht anlegen</button></p>'
        + "</form>"
        + '<p><a href="/gerichte">← Zurück zu Gerichte</a></p>'
    )
    return _page(
        "Neues Gericht",
        body,
        active_section="catalog",
        context=context,
    )

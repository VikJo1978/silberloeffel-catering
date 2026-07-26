"""Gericht detail — catalog projection and status commands (6D-1)."""

from __future__ import annotations

from catering_system.ui.office_panel_catalog_list import (
    pricing_unit_label,
    vat_label,
)
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)


def _text_block(label: str, value: object | None) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return f"<p><strong>{_e(label)}:</strong> –</p>"
    return f"<p><strong>{_e(label)}:</strong> {_e(text)}</p>"


def _allergen_block(labels: object) -> str:
    if isinstance(labels, list) and labels:
        items = "".join(f"<li>{_e(str(label))}</li>" for label in labels)
        return f"<p><strong>Allergene:</strong></p><ul>{items}</ul>"
    return "<p><strong>Allergene:</strong> –</p>"


def _price_history_block(history: object) -> str:
    if not isinstance(history, list) or not history:
        return "<p><strong>Preisänderungen:</strong> noch keine</p>"
    items = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        old_display = entry.get("old_price_display")
        new_display = entry.get("new_price_display")
        if old_display is None and entry.get("old_unit_net_cents") is not None:
            old_display = str(entry.get("old_unit_net_cents"))
        if new_display is None:
            new_display = str(entry.get("new_unit_net_cents"))
        changed_at = _e(str(entry.get("changed_at", "")))
        changed_by = _e(str(entry.get("changed_by", "")))
        effective = entry.get("effective_from")
        effective_html = (
            f", gültig ab {_e(str(effective))}" if effective is not None else ""
        )
        items.append(
            "<li>"
            f"{_e(str(old_display))} → {_e(str(new_display))} "
            f"({changed_at}, {changed_by}{effective_html})"
            "</li>"
        )
    if not items:
        return "<p><strong>Preisänderungen:</strong> noch keine</p>"
    return "<p><strong>Preisänderungen:</strong></p><ul>" + "".join(items) + "</ul>"


def _status_command_form(
    dish_id: str,
    *,
    active: bool,
    command_fields: str,
) -> str:
    """CATALOG_ADMIN_PANEL_V1: exactly one status command is offered at a
    time — the one that would actually change something. Both carry the same
    optimistic-concurrency token the edit form uses, so a stale page cannot
    flip a status that somebody else already changed."""
    action = "deactivate" if active else "activate"
    label = "Deaktivieren" if active else "Aktivieren"
    return (
        f'<form method="post" action="/gerichte/{_e(dish_id)}/{action}">'
        + command_fields
        + f'<button type="submit">{_e(label)}</button>'
        + "</form>"
    )


def render_gericht_detail(
    detail: dict[str, object],
    *,
    context: OfficePageContext,
    command_fields: str = "",
    error_message: str | None = None,
) -> str:
    name = str(detail.get("name", "Gericht"))
    active = bool(detail.get("active"))
    status = "Aktiv" if active else "Inaktiv"
    dish_id = str(detail.get("dish_id", ""))
    error_html = f'<p class="error">{_e(error_message)}</p>' if error_message else ""
    body = (
        error_html
        + f'<p class="subtitle">Status: {_e(status)}</p>'
        + _status_command_form(dish_id, active=active, command_fields=command_fields)
        + _text_block("Beschreibung", detail.get("description"))
        + _text_block("Zusammensetzung", detail.get("composition"))
        + _text_block("Hinweise", detail.get("notes"))
        # CATALOG_ADMIN_PANEL_V1: read-only in this slice — these are set once
        # at creation and have no edit path yet.
        + f"<p><strong>Kategorie:</strong> "
        f"{_e(str(detail.get('category') or '–'))}</p>"
        + f"<p><strong>Preiseinheit:</strong> "
        f"{pricing_unit_label(detail.get('pricing_unit'))}</p>"
        + f"<p><strong>MwSt:</strong> "
        f"{vat_label(detail.get('vat_rate_percent'))}</p>"
        + _allergen_block(detail.get("allergen_labels"))
        + f"<p><strong>Preis:</strong> {_e(str(detail.get('price_display', '–')))}</p>"
        + _price_history_block(detail.get("price_history"))
        + f'<p><a href="/gerichte/{_e(dish_id)}/edit">Bearbeiten</a></p>'
        + '<p><a href="/gerichte">← Zurück zu Gerichte</a></p>'
    )
    return _page(name, body, active_section="catalog", context=context)

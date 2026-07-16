"""Gericht detail — read-only catalog projection (6D-1)."""

from __future__ import annotations

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


def render_gericht_detail(
    detail: dict[str, object],
    *,
    context: OfficePageContext,
) -> str:
    name = str(detail.get("name", "Gericht"))
    status = "Aktiv" if detail.get("active") else "Inaktiv"
    body = (
        f'<p class="subtitle">Status: {_e(status)}</p>'
        + _text_block("Beschreibung", detail.get("description"))
        + _text_block("Zusammensetzung", detail.get("composition"))
        + _allergen_block(detail.get("allergen_labels"))
        + f"<p><strong>Preis:</strong> {_e(str(detail.get('price_display', '–')))}</p>"
        + _price_history_block(detail.get("price_history"))
        + f'<p><a href="/gerichte/{_e(str(detail.get("dish_id", "")))}/edit">Bearbeiten</a></p>'
        + '<p><a href="/gerichte">← Zurück zu Gerichte</a></p>'
    )
    return _page(name, body, active_section="catalog", context=context)

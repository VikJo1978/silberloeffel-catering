"""Angebotsliste presentation — grouped operational queue (OFFER_OPERATIONAL_QUEUE_V1)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import cast

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

_ACTION_SUBGROUPS: tuple[tuple[str, str], ...] = (
    ("prepared", "Vorbereitet — versenden"),
    ("sent", "Wartet auf Kunde"),
    ("accepted", "Umwandeln"),
)


def _short_date(raw: str) -> str:
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        return raw
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


def _queue_table(items: list[dict[str, object]]) -> str:
    rows = []
    for item in items:
        offer_id = str(item["offer_id"])
        subtitle = item.get("intake_subject")
        customer = str(item["customer_display"])
        label = customer
        if subtitle and str(subtitle) != customer:
            label = f"{customer} — {subtitle}"
        overdue_note = ""
        days_overdue = item.get("days_overdue")
        if days_overdue is not None and int(cast(int, days_overdue)) > 0:
            overdue_note = f" ({int(cast(int, days_overdue))} Tage)"
        rows.append(
            "<tr>"
            f"<td>{_e(label)}</td>"
            f"<td>{_e(_short_date(str(item['event_date'])))}</td>"
            f"<td>{_e(str(item['state_label']))}</td>"
            f"<td>{_e(str(item['next_action_label']))}{_e(overdue_note)}</td>"
            f'<td><a href="/offer/{_e(offer_id)}">Öffnen</a></td>'
            "</tr>"
        )
    return (
        "<table><tr><th>Kunde</th><th>Termin</th><th>Status</th>"
        "<th>Nächste Aktion</th><th></th></tr>" + "".join(rows) + "</table>"
    )


def _render_action_required(section: dict[str, object]) -> str:
    label = str(section["label"])
    count = int(cast(int, section["count"]))
    items = cast(list[dict[str, object]], section["items"])
    html = f'<section class="offer-queue-section"><h2>{_e(label)} ({count})</h2>'
    if count == 0:
        html += '<p class="muted">Keine offenen Aktionen.</p>'
        return html + "</section>"

    by_subkind: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        by_subkind[str(item["queue_subkind"])].append(item)

    for subkind, sublabel in _ACTION_SUBGROUPS:
        if subkind == "accepted":
            subitems = by_subkind.get("accepted", []) + by_subkind.get(
                "accepted_contact_blocked", []
            )
        else:
            subitems = by_subkind.get(subkind, [])
        if not subitems:
            continue
        html += f'<h3 class="offer-queue-subgroup">{_e(sublabel)}</h3>'
        html += _queue_table(subitems)
    return html + "</section>"


def _render_overdue(section: dict[str, object]) -> str:
    label = str(section["label"])
    count = int(cast(int, section["count"]))
    items = cast(list[dict[str, object]], section["items"])
    html = f'<section class="offer-queue-section"><h2>{_e(label)} ({count})</h2>'
    if count == 0:
        html += '<p class="muted">Keine überfälligen Angebote.</p>'
    else:
        html += _queue_table(items)
    return html + "</section>"


def _render_history(section: dict[str, object]) -> str:
    count = int(cast(int, section["count"]))
    items = cast(list[dict[str, object]], section["items"])
    summary = f"Abgeschlossen / Verlauf ({count})"
    if count == 0:
        return (
            '<details class="offer-queue-history">'
            f"<summary>{_e(summary)}</summary>"
            '<p class="muted">Noch keine abgeschlossenen Angebote.</p>'
            "</details>"
        )
    return (
        '<details class="offer-queue-history">'
        f"<summary>{_e(summary)}</summary>" + _queue_table(items) + "</details>"
    )


def render_angebote_queue(
    snapshot: dict[str, object],
    *,
    context: OfficePageContext,
) -> str:
    sections = cast(list[dict[str, object]], snapshot["sections"])
    total_count = int(cast(int, snapshot["total_count"]))
    counters: dict[str, int] = {
        str(s["group"]): int(cast(int, s["count"])) for s in sections
    }
    action_count = counters.get("action_required", 0)
    overdue_count = counters.get("overdue", 0)
    history_count = counters.get("history", 0)

    parts = [
        '<p class="subtitle">Operative Warteschlange für Angebote im Vertrieb.</p>',
        '<div class="offer-queue-counters">'
        f"<span><strong>{action_count}</strong> Aktion erforderlich</span>"
        f"<span><strong>{overdue_count}</strong> Frist überschritten</span>"
        f"<span><strong>{history_count}</strong> Verlauf</span>"
        "</div>",
    ]
    if total_count == 0:
        parts.append("<p>Keine Angebote vorhanden.</p>")
    else:
        for section in sections:
            group = str(section["group"])
            if group == "action_required":
                parts.append(_render_action_required(section))
            elif group == "overdue":
                parts.append(_render_overdue(section))
            elif group == "history":
                parts.append(_render_history(section))

    parts.append('<p><a href="/">← Zurück zur Arbeitszentrale</a></p>')
    return _page("Angebote", "".join(parts), active_section="offers", context=context)

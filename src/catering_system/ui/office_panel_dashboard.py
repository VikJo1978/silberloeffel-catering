"""Arbeitszentrale dashboard — presentation over existing read projections.

Every number and row here is derived from already-shipped, mode-parity data
sources (WorkCenterSnapshot, task projection rows, calendar projection rows,
Inquiry contact completeness). No new domain concepts, no writes — the same
inputs render byte-identically in direct and remote mode.
"""

from __future__ import annotations

import calendar as _calendar
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from catering_system.domain.work_center import WorkCenterSnapshot
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

_MONTHS = (
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

# Task-category → monochrome sprite icon (office_panel_shell.py sprite).
_TASK_ICONS = {
    "verify": "phone",
    "convert": "doc",
    "convert_accepted": "doc",
    "order_print": "printer",
    "order_effective": "check",
    "payment": "briefcase",
}

_MAX_NEXT_TASKS = 6
_MAX_NEXT_EVENTS = 5


@dataclass(frozen=True)
class ArbeitszentraleData:
    """View model for the office dashboard; plain rows, no service handles."""

    context: OfficePageContext
    today: date
    snapshot: WorkCenterSnapshot
    tasks: list[dict[str, object]] = field(default_factory=list)
    calendar_entries: list[dict[str, object]] = field(default_factory=list)
    contact_check_open: int = 0
    open_inquiries_open: int = 0
    kalender_view: str = "woche"


def _icon(name: str) -> str:
    return f'<svg aria-hidden="true"><use href="#office-i-{name}"></use></svg>'


def _task_counts(tasks: list[dict[str, object]]) -> Counter[str]:
    return Counter(str(task.get("category", "")) for task in tasks)


def _attention_card(
    *, icon: str, name: str, count: int, label: str, href: str, action: str
) -> str:
    return (
        '<article class="dashboard-attention-card">'
        f'<span class="dashboard-attention-icon">{_icon(icon)}</span>'
        f'<span class="dashboard-attention-name">{_e(name)}</span>'
        f"<strong>{count}</strong>"
        f"<span>{_e(label)}</span>"
        f'<a href="{_e(href)}">{_e(action)}</a>'
        "</article>"
    )


def _attention_section(data: ArbeitszentraleData) -> str:
    counts = _task_counts(data.tasks)
    snapshot = data.snapshot
    cards: list[str] = []
    if snapshot.missed_calls_open:
        cards.append(
            _attention_card(
                icon="phone",
                name="Rückrufe",
                count=snapshot.missed_calls_open,
                label="Rückrufe erforderlich",
                href="/rueckruf",
                action="Öffnen",
            )
        )
    if data.open_inquiries_open:
        cards.append(
            _attention_card(
                icon="doc",
                name="Offene Anfragen",
                count=data.open_inquiries_open,
                label="Anfragen prüfen",
                href="/anfragen",
                action="Öffnen",
            )
        )
    if data.contact_check_open:
        cards.append(
            _attention_card(
                icon="users",
                name="Kundenprüfung",
                count=data.contact_check_open,
                label="offen",
                href="/anfragen",
                action="Öffnen",
            )
        )
    auftraege = counts["order_effective"] + counts["payment"]
    if auftraege:
        cards.append(
            _attention_card(
                icon="check",
                name="Aufträge",
                count=auftraege,
                label="nächster Schritt",
                href="/auftraege",
                action="Öffnen",
            )
        )
    if counts["order_print"]:
        cards.append(
            _attention_card(
                icon="printer",
                name="Küchendruck",
                count=counts["order_print"],
                label="prüfen",
                href="/aufgaben",
                action="Öffnen",
            )
        )
    if not cards:
        body = '<p class="dashboard-empty">Aktuell braucht nichts Aufmerksamkeit.</p>'
    else:
        body = f'<div class="dashboard-attention">{"".join(cards)}</div>'
    return "<h2>Was braucht Aufmerksamkeit?</h2>" + body


def _task_rows(tasks: list[dict[str, object]]) -> str:
    rows: list[str] = []
    for task in tasks[:_MAX_NEXT_TASKS]:
        icon = _TASK_ICONS.get(str(task.get("category", "")), "doc")
        href = str(task.get("action_href", ""))
        rows.append(
            '<div class="dashboard-work-row">'
            f'<span class="dashboard-work-kind">{_icon(icon)}</span>'
            '<div class="dashboard-work-copy">'
            f'<h3><a href="{_e(href)}">{_e(str(task.get("title", "")))}</a></h3>'
            f"<p>{_e(str(task.get('subtitle', '')))}</p></div>"
            f'<a class="dashboard-button secondary" href="{_e(href)}">'
            f"{_e(str(task.get('action_label', 'Öffnen')))}</a>"
            "</div>"
        )
    if not rows:
        return '<p class="dashboard-empty">Keine offenen Schritte.</p>'
    return "".join(rows)


def _next_step_by_entity(
    tasks: list[dict[str, object]],
) -> dict[tuple[str, str], str]:
    steps: dict[tuple[str, str], str] = {}
    for task in tasks:
        key = (str(task.get("entity_type", "")), str(task.get("entity_id", "")))
        steps.setdefault(key, str(task.get("title", "")))
    return steps


def _event_rows(data: ArbeitszentraleData) -> str:
    steps = _next_step_by_entity(data.tasks)
    rows: list[str] = []
    for entry in data.calendar_entries:
        event_date = date.fromisoformat(str(entry["event_date"]))
        if event_date < data.today:
            continue
        if len(rows) >= _MAX_NEXT_EVENTS:
            break
        key = (str(entry.get("entity_type", "")), str(entry.get("entity_id", "")))
        next_step = steps.get(key) or str(entry.get("status_label", ""))
        guest_count = entry.get("guest_count_estimate")
        meta_parts = [
            part
            for part in (
                str(entry.get("time_window_text", "")).strip(),
                f"{guest_count} Gäste" if guest_count else "",
                next_step,
            )
            if part
        ]
        href = str(entry.get("action_href", ""))
        rows.append(
            '<div class="dashboard-event-row">'
            '<span class="dashboard-date-tile">'
            f"<strong>{event_date.day}</strong>"
            f"<span>{_e(_MONTHS[event_date.month][:3])}</span></span>"
            '<div class="dashboard-event-copy">'
            f'<h3><a href="{_e(href)}">{_e(str(entry.get("title", "")))}</a></h3>'
            f"<p>{_e(' · '.join(meta_parts))}</p></div>"
            f'<a class="dashboard-button secondary" href="{_e(href)}">Öffnen</a>'
            "</div>"
        )
    if not rows:
        return '<p class="dashboard-empty">Keine anstehenden Veranstaltungen.</p>'
    return "".join(rows)


def _entries_per_day(entries: list[dict[str, object]]) -> Counter[date]:
    return Counter(date.fromisoformat(str(entry["event_date"])) for entry in entries)


def _calendar_toggle(view: str) -> str:
    woche = ' aria-current="true"' if view != "monat" else ""
    monat = ' aria-current="true"' if view == "monat" else ""
    return (
        '<nav class="dashboard-calendar-toggle" aria-label="Kalenderansicht">'
        f'<a href="/"{woche}>Diese Woche</a>'
        f'<a href="/?kalender=monat"{monat}>Dieser Monat</a></nav>'
    )


def _week_strip(data: ArbeitszentraleData) -> str:
    per_day = _entries_per_day(data.calendar_entries)
    monday = data.today - timedelta(days=data.today.weekday())
    cells: list[str] = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        classes = (
            "dashboard-week-day today" if day == data.today else "dashboard-week-day"
        )
        count = per_day.get(day, 0)
        badge = f"<small>{count}</small>" if count else ""
        cells.append(
            f'<span class="{classes}">{_WEEKDAYS[offset]}'
            f"<strong>{day.day}</strong>{badge}</span>"
        )
    return f'<div class="dashboard-week-days">{"".join(cells)}</div>'


def _month_grid(data: ArbeitszentraleData) -> str:
    per_day = _entries_per_day(data.calendar_entries)
    year, month = data.today.year, data.today.month
    first_weekday, day_count = _calendar.monthrange(year, month)
    cells: list[str] = [
        f'<span class="dashboard-month-head">{label}</span>' for label in _WEEKDAYS
    ]
    cells.extend(
        '<span class="dashboard-month-day outside"></span>'
        for _blank in range(first_weekday)
    )
    for day_number in range(1, day_count + 1):
        day = date(year, month, day_number)
        classes = (
            "dashboard-month-day today" if day == data.today else "dashboard-month-day"
        )
        count = per_day.get(day, 0)
        badge = f"<small>{count}</small>" if count else ""
        cells.append(f'<span class="{classes}">{day_number}{badge}</span>')
    return (
        f'<div class="dashboard-month-days" aria-label="{_MONTHS[month]} {year}">'
        + "".join(cells)
        + "</div>"
    )


def _calendar_card(data: ArbeitszentraleData) -> str:
    if data.kalender_view == "monat":
        body = _month_grid(data)
        subtitle = f"{_MONTHS[data.today.month]} {data.today.year}"
    else:
        body = _week_strip(data)
        iso = data.today.isocalendar()
        subtitle = f"KW {iso.week}"
    return (
        '<section class="dashboard-card" id="diese-woche">'
        '<div class="dashboard-card-head"><div>'
        f"<h2>Kalender</h2><p>{_e(subtitle)}</p></div>"
        + _calendar_toggle(data.kalender_view)
        + "</div>"
        + body
        + "</section>"
    )


def _systemstatus_card() -> str:
    # Honest presentation only: the panel has no live probes for the other
    # services — "Core" is truthful (this page rendered from Core data),
    # everything else states plainly that no live check exists yet. No
    # ok/unavailable coloring on purpose (approved design: no status colors).
    def row(name: str, state: str) -> str:
        return (
            '<div class="dashboard-service-state">'
            f"<strong>{_e(name)}</strong><span>{_e(state)}</span></div>"
        )

    return (
        '<section class="dashboard-card">'
        '<div class="dashboard-card-head"><div><h2>Systemstatus</h2>'
        "<p>Betriebsdienste im Überblick.</p></div></div>"
        + row("Core", "Verbunden — Daten geladen.")
        + row("Website Intake", "Keine Live-Prüfung eingerichtet.")
        + row("Kiosk", "Keine Live-Prüfung eingerichtet.")
        + row("Drucker", "Keine Live-Prüfung eingerichtet.")
        + "</section>"
    )


def render_arbeitszentrale(data: ArbeitszentraleData) -> str:
    """Render the v2 Arbeitszentrale (Heute im Büro) from projection rows."""

    today = data.today
    header_date = (
        f"{_WEEKDAYS[today.weekday()]}, {today.day}. "
        f"{_MONTHS[today.month]} {today.year}"
    )
    header = (
        '<header class="dashboard-page-header"><div>'
        f'<div class="dashboard-eyebrow">{_e(header_date)}</div>'
        "<h1>Heute im Büro</h1>"
        "<p>Anfragen, Rückrufe und operative Aufgaben im Blick.</p></div>"
        '<div class="dashboard-header-actions">'
        '<a class="dashboard-button secondary" href="/orders">Alle Aufträge</a>'
        '<a class="dashboard-button" href="/inquiry/new">+ Neue Anfrage</a>'
        "</div></header>"
    )
    main_column = (
        '<div class="dashboard-main">'
        '<section class="dashboard-card">'
        '<div class="dashboard-card-head"><div>'
        "<h2>Was als Nächstes ansteht</h2>"
        "<p>Die wichtigsten offenen Schritte.</p></div>"
        '<a class="dashboard-text-link" href="/aufgaben">Alle Aufgaben</a></div>'
        + _task_rows(data.tasks)
        + "</section>"
        '<section class="dashboard-card">'
        '<div class="dashboard-card-head"><div>'
        "<h2>Nächste Veranstaltungen</h2>"
        "<p>Kommende Termine mit nächstem Schritt.</p></div>"
        '<a class="dashboard-text-link" href="/kalender">Kalender öffnen</a></div>'
        + _event_rows(data)
        + "</section></div>"
    )
    side_column = (
        '<div class="dashboard-side">'
        + _calendar_card(data)
        + _systemstatus_card()
        + "</div>"
    )
    body = (
        header
        + _attention_section(data)
        + f'<div class="dashboard-layout">{main_column}{side_column}</div>'
    )
    return _page(
        "Arbeitszentrale",
        body,
        active_section="home",
        context=data.context,
        show_title=False,
        auto_refresh_seconds=60,
    )

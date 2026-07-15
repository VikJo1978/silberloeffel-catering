"""Premium Arbeitszentrale renderer for the Office Panel UI v2.

The renderer consumes the existing frozen QueueView.  It derives presentation
only: no repositories, Core services, or remote reads are available here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, cast
from urllib.parse import quote

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _csrf_input,
    _e,
    _page,
    _ready_to_send_blocker_label,
    _source_label,
)


@dataclass(frozen=True)
class DashboardUi:
    """Request-local presentation services, deliberately outside QueueView."""

    context: OfficePageContext
    command_fields: Callable[[dict[str, str] | None], str]
    callbacks: list[dict[str, Any]] | None
    callback_error: str | None
    kiosk_url: str
    today: date


_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
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


def _date_text(raw: object) -> str:
    try:
        value = date.fromisoformat(str(raw))
    except ValueError:
        return str(raw) or "–"
    return f"{value.day}. {_MONTHS[value.month]} {value.year}"


def _inquiry_action(inquiry: Mapping[str, Any], ui: DashboardUi) -> tuple[str, str]:
    inquiry_id = str(inquiry["inquiry_id"])
    action_name = inquiry["next_action"]
    if action_name == "verify":
        label, suffix = "Rückruf bestätigen", "verify"
    elif action_name == "convert":
        label, suffix = "Auftrag anlegen", "convert"
    elif action_name == "offer-pending":
        return (
            '<span class="dashboard-status">Angebot ausstehend</span>',
            f"/inquiry/{quote(inquiry_id, safe='')}",
        )
    elif action_name == "convert-accepted":
        return (
            '<span class="dashboard-status">Angebot angenommen</span>',
            f"/inquiry/{quote(inquiry_id, safe='')}",
        )
    else:
        return "Anfrage öffnen", f"/inquiry/{quote(inquiry_id, safe='')}"
    form = (
        f'<form method="post" action="/inquiry/{_e(inquiry_id)}/{suffix}">'
        f"{_csrf_input(ui.context)}{ui.command_fields(None)}"
        f'<button class="dashboard-button secondary" type="submit">{label}</button>'
        "</form>"
    )
    return form, ""


def _order_action(order: Mapping[str, Any], ui: DashboardUi) -> str:
    action = cast(dict[str, str] | None, order.get("next_action"))
    order_id = str(order["order_id"])
    if action is None:
        return (
            f'<a class="dashboard-button secondary" href="/order/{_e(order_id)}">'
            "Auftrag öffnen</a>"
        )
    action_name = action["action"]
    label = "Druck bestätigen" if action_name == "print-confirm" else "Wirksam machen"
    expect = (
        {"effective_version_id": str(order.get("effective_order_version_id") or "")}
        if action_name == "effective"
        else None
    )
    return (
        f'<form method="post" action="/order/{_e(order_id)}/{_e(action_name)}">'
        f"{_csrf_input(ui.context)}{ui.command_fields(expect)}"
        '<input type="hidden" name="order_version_id" '
        f'value="{_e(action["order_version_id"])}">'
        f'<button class="dashboard-button secondary" type="submit">{label}</button>'
        "</form>"
    )


def _attention_cards(view: Mapping[str, object], ui: DashboardUi) -> str:
    attention = cast(Mapping[str, int], view["attention"])
    if ui.callback_error is not None:
        callback_value = "–"
        callback_label = "Dienst nicht erreichbar"
        callback_class = " unavailable"
    else:
        callback_value = str(len(ui.callbacks or []))
        callback_label = "Rückrufe offen"
        callback_class = ""
    return (
        '<section class="dashboard-attention" aria-label="Was Aufmerksamkeit braucht">'
        '<article class="dashboard-attention-card">'
        '<span class="dashboard-attention-icon"><svg aria-hidden="true">'
        '<use href="#office-i-doc"></use></svg></span>'
        f"<strong>{attention['neue_anfragen']}</strong><span>Offene Anfragen</span>"
        '<a href="/anfragen">Anfragen ansehen <span aria-hidden="true">→</span></a>'
        "</article>"
        f'<article class="dashboard-attention-card{callback_class}">'
        '<span class="dashboard-attention-icon warm"><svg aria-hidden="true">'
        '<use href="#office-i-phone"></use></svg></span>'
        f"<strong>{_e(callback_value)}</strong><span>{_e(callback_label)}</span>"
        '<a href="/rueckruf">Rückrufliste öffnen <span aria-hidden="true">→</span></a>'
        "</article>"
        '<article class="dashboard-attention-card">'
        '<span class="dashboard-attention-icon"><svg aria-hidden="true">'
        '<use href="#office-i-briefcase"></use></svg></span>'
        f"<strong>{attention['versand_blockiert']}</strong><span>Aufträge zu prüfen</span>"
        '<a href="/auftraege">Aufträge ansehen <span aria-hidden="true">→</span></a>'
        "</article></section>"
    )


def _work_rows(view: Mapping[str, object], ui: DashboardUi) -> str:
    rows: list[str] = []
    for callback in (ui.callbacks or [])[:2]:
        phone = str(callback.get("phone", ""))
        contact = (
            str(callback.get("contact_name", ""))
            if callback.get("contact_found")
            else "Unbekannter Kontakt"
        )
        when = " ".join(
            part
            for part in (str(callback.get("date", "")), str(callback.get("time", "")))
            if part
        )
        rows.append(
            '<article class="dashboard-work-row">'
            '<span class="dashboard-work-kind warm"><svg aria-hidden="true">'
            '<use href="#office-i-phone"></use></svg></span>'
            f'<div class="dashboard-work-copy"><h3>{_e(contact)}</h3>'
            f"<p>{_e(when or 'Offener Rückruf')} · {_e(phone or 'Nummer nicht verfügbar')}</p></div>"
            f'<a class="dashboard-button secondary" href="/inquiry/new?phone={quote(phone)}">'
            "Anfrage erfassen</a></article>"
        )
    for inquiry in cast(list[dict[str, Any]], view["neue_anfragen_top"]):
        action, href = _inquiry_action(inquiry, ui)
        action_html = (
            action
            if not href
            else f'<a class="dashboard-button secondary" href="{_e(href)}">{action}</a>'
        )
        facts = " · ".join(
            part
            for part in (
                _date_text(inquiry["event_date"]),
                str(inquiry.get("location_text") or "Ort noch offen"),
                (
                    f"{inquiry['guest_count_estimate']} Gäste"
                    if inquiry.get("guest_count_estimate") is not None
                    else "Gästezahl noch offen"
                ),
            )
            if part
        )
        rows.append(
            '<article class="dashboard-work-row">'
            '<span class="dashboard-work-kind"><svg aria-hidden="true">'
            '<use href="#office-i-doc"></use></svg></span>'
            '<div class="dashboard-work-copy">'
            f'<h3><a href="/inquiry/{_e(inquiry["inquiry_id"])}">'
            f"{_e(_source_label(str(inquiry['inquiry_source'])))}</a></h3>"
            f"<p>{_e(facts)}</p></div>{action_html}</article>"
        )
    for order in cast(list[dict[str, Any]], view["auftraege_top"]):
        blocker = order.get("blocker_reason")
        reason = (
            _ready_to_send_blocker_label(str(blocker))
            if blocker is not None
            else "Nächsten Schritt prüfen"
        )
        rows.append(
            '<article class="dashboard-work-row">'
            '<span class="dashboard-work-kind"><svg aria-hidden="true">'
            '<use href="#office-i-briefcase"></use></svg></span>'
            '<div class="dashboard-work-copy">'
            f'<h3><a href="/order/{_e(order["order_id"])}">'
            f"Auftrag {_e(str(order['order_id'])[:8])}</a></h3>"
            f"<p>{_e(reason)}</p></div>{_order_action(order, ui)}</article>"
        )
    if not rows:
        return '<div class="dashboard-empty">Aktuell sind keine nächsten Schritte offen.</div>'
    return '<div class="dashboard-work-list">' + "".join(rows) + "</div>"


def _week_content(view: Mapping[str, object], ui: DashboardUi) -> tuple[str, str]:
    week = cast(Mapping[str, Any], view["week"])
    entries = cast(list[dict[str, Any]], week["entries"])
    counts: dict[str, int] = {}
    for entry in entries:
        key = str(entry["event_date"])
        counts[key] = counts.get(key, 0) + 1
    monday = date.fromisocalendar(int(week["iso_year"]), int(week["iso_week"]), 1)
    days = []
    for offset, label in enumerate(_WEEKDAYS):
        day = monday + timedelta(days=offset)
        count = counts.get(day.isoformat(), 0)
        today_class = " today" if day == ui.today else ""
        count_html = (
            f'<small aria-label="{count} Veranstaltung{("en" if count != 1 else "")}">{count}</small>'
            if count
            else ""
        )
        days.append(
            f'<div class="dashboard-week-day{today_class}"><span>{label}</span>'
            f"<strong>{day.day}</strong>{count_html}</div>"
        )
    title = f"KW {week['iso_week']} / {week['iso_year']}"
    content = '<div class="dashboard-week-days">' + "".join(days) + "</div>"
    if week["truncated"]:
        content += (
            '<p class="dashboard-notice"><strong>Ansicht unvollständig:</strong> '
            f"{len(entries)} von {_e(week['total_count'])} Aufträgen werden angezeigt.</p>"
        )
    return title, content


def _events(view: Mapping[str, object]) -> str:
    week = cast(Mapping[str, Any], view["week"])
    entries = cast(list[dict[str, Any]], week["entries"])
    if not entries:
        return '<div class="dashboard-empty">Keine wirksamen Aufträge in dieser Woche.</div>'
    rows = []
    for entry in entries:
        event_date = date.fromisoformat(str(entry["event_date"]))
        guest_text = (
            f"{entry['guest_count_estimate']} Gäste"
            if entry.get("guest_count_estimate") is not None
            else "Gästezahl offen"
        )
        rows.append(
            '<article class="dashboard-event-row">'
            f'<div class="dashboard-date-tile"><strong>{event_date.day}</strong>'
            f"<span>{_WEEKDAYS[event_date.weekday()]}</span></div>"
            '<div class="dashboard-event-copy">'
            f'<h3><a href="/order/{_e(entry["order_id"])}">'
            f"Auftrag {_e(str(entry['order_id'])[:8])}</a></h3>"
            f"<p>{_e(entry.get('time_window_text') or 'Zeit noch offen')} · "
            f"{_e(entry.get('location_text') or 'Ort noch offen')}</p></div>"
            f'<span class="dashboard-guest-count">{_e(guest_text)}</span></article>'
        )
    return '<div class="dashboard-event-list">' + "".join(rows) + "</div>"


def _callback_card(ui: DashboardUi) -> str:
    if ui.callback_error is not None:
        return (
            '<div class="dashboard-service-state unavailable"><strong>Dienst nicht erreichbar</strong>'
            "<span>Die Rückrufliste ist derzeit nicht verfügbar.</span></div>"
        )
    callbacks = ui.callbacks or []
    if not callbacks:
        return (
            '<div class="dashboard-service-state ok"><strong>0 offen</strong>'
            "<span>Keine offenen Rückrufe.</span></div>"
        )
    rows = []
    for callback in callbacks[:3]:
        contact = (
            str(callback.get("contact_name", ""))
            if callback.get("contact_found")
            else "Unbekannter Kontakt"
        )
        rows.append(
            '<article class="dashboard-callback-row">'
            f"<div><strong>{_e(callback.get('time') or '–')}</strong>"
            f"<span>{_e(callback.get('date') or '')}</span></div>"
            f"<p><strong>{_e(contact)}</strong><span>{_e(callback.get('phone') or 'Nummer nicht verfügbar')}</span></p>"
            "</article>"
        )
    return '<div class="dashboard-callback-list">' + "".join(rows) + "</div>"


def render_arbeitszentrale(view: Mapping[str, object], *, ui: DashboardUi) -> str:
    """Render UI2B from QueueView and request-local presentation parameters."""

    week_title, week_content = _week_content(view, ui)
    kiosk_link = (
        f'<a class="dashboard-text-link" href="{_e(ui.kiosk_url)}">Ganze Woche</a>'
        if ui.kiosk_url
        else ""
    )
    header_date = (
        f"{_WEEKDAYS[ui.today.weekday()]}, {ui.today.day}. "
        f"{_MONTHS[ui.today.month]} {ui.today.year}"
    )
    body = (
        '<div class="dashboard-page-header"><div>'
        f'<div class="dashboard-eyebrow">{_e(header_date)}</div>'
        "<h1>Heute im Büro</h1>"
        "<p>Anfragen, Rückrufe und die nächsten Veranstaltungen im Blick.</p></div>"
        '<a class="dashboard-button" href="/inquiry/new">Neue Anfrage</a></div>'
        + _attention_cards(view, ui)
        + '<div class="dashboard-layout"><div class="dashboard-main">'
        '<section class="dashboard-card"><div class="dashboard-card-head"><div>'
        "<h2>Was als Nächstes ansteht</h2>"
        "<p>Die wichtigsten offenen Arbeitsschritte</p></div></div>"
        + _work_rows(view, ui)
        + '</section><section class="dashboard-card" id="diese-woche">'
        '<div class="dashboard-card-head"><div><h2>Nächste Veranstaltungen</h2>'
        "<p>Wirksame Aufträge in der aktuellen Woche</p></div>"
        + kiosk_link
        + "</div>"
        + _events(view)
        + '</section></div><aside class="dashboard-side">'
        '<section class="dashboard-card"><div class="dashboard-card-head"><div>'
        f"<h2>Diese Woche</h2><p>{_e(week_title)}</p></div></div>{week_content}</section>"
        '<section class="dashboard-card"><div class="dashboard-card-head"><div>'
        "<h2>Rückrufe</h2><p>Offene Rückrufe aus dem Telefondienst</p></div>"
        '<a class="dashboard-text-link" href="/rueckruf">Alle öffnen</a></div>'
        + _callback_card(ui)
        + "</section></aside></div>"
    )
    return _page(
        "Arbeitszentrale",
        body,
        active_section="home",
        context=ui.context,
        show_title=False,
    )

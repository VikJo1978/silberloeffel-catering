"""Arbeitszentrale dashboard — WorkCenterSnapshot presentation only (5A-2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

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


@dataclass(frozen=True)
class WorkCenterDashboardUi:
    context: OfficePageContext
    today: date
    week_order_count: int


def _card_action(href: str, label: str) -> str:
    return f'<a class="wc-card-action" href="{_e(href)}">{_e(label)}</a>'


def _rueckrufe_card(snapshot: WorkCenterSnapshot) -> str:
    total = snapshot.rueckrufe_open + snapshot.missed_calls_open
    return (
        '<section class="wc-card" aria-labelledby="wc-rueckrufe">'
        '<div class="wc-card-head"><span class="wc-card-mark" aria-hidden="true">'
        '🔴</span><h2 id="wc-rueckrufe">Rückrufe</h2></div>'
        '<hr class="wc-card-rule">'
        f'<p class="wc-card-summary"><strong>{total}</strong> offen</p>'
        '<ul class="wc-card-lines">'
        f"<li><span>📞 Kunden-Rückrufe</span><strong>{snapshot.rueckrufe_open}</strong></li>"
        f"<li><span>☎ Verpasste Anrufe</span><strong>{snapshot.missed_calls_open}</strong></li>"
        "</ul>" + _card_action("/rueckruf", "Öffnen") + "</section>"
    )


def _angebote_card(snapshot: WorkCenterSnapshot) -> str:
    return (
        '<section class="wc-card" aria-labelledby="wc-angebote">'
        '<div class="wc-card-head"><span class="wc-card-mark" aria-hidden="true">'
        '📥</span><h2 id="wc-angebote">Angebote</h2></div>'
        '<hr class="wc-card-rule">'
        f"<p>{snapshot.offers_waiting} warten auf Antwort</p>"
        f"<p>{snapshot.offers_accepted} angenommen</p>"
        + _card_action("/angebote", "Angebote öffnen")
        + "</section>"
    )


def _auftraege_card(snapshot: WorkCenterSnapshot, ui: WorkCenterDashboardUi) -> str:
    count = ui.week_order_count
    label = f"{count} diese Woche" if count != 1 else "1 diese Woche"
    return (
        '<section class="wc-card" aria-labelledby="wc-auftraege">'
        '<div class="wc-card-head"><span class="wc-card-mark" aria-hidden="true">'
        '🍽</span><h2 id="wc-auftraege">Aufträge</h2></div>'
        '<hr class="wc-card-rule">'
        f'<p class="wc-card-summary">{_e(label)}</p>'
        f"<p>{snapshot.pending_order_changes} Änderungen warten auf Küchendruck</p>"
        + _card_action("/auftraege", "Aufträge öffnen")
        + "</section>"
    )


def _aufgaben_card(snapshot: WorkCenterSnapshot) -> str:
    body = (
        f"<p>{snapshot.open_tasks} offene Aufgaben</p>"
        if snapshot.open_tasks
        else "<p>Keine offenen Aufgaben</p>"
    )
    return (
        '<section class="wc-card" aria-labelledby="wc-aufgaben">'
        '<div class="wc-card-head"><span class="wc-card-mark" aria-hidden="true">'
        '🟡</span><h2 id="wc-aufgaben">Aufgaben</h2></div>'
        '<hr class="wc-card-rule">'
        + body
        + _card_action("/aufgaben", "Öffnen")
        + "</section>"
    )


def _kalender_card(snapshot: WorkCenterSnapshot) -> str:
    body = (
        f"<p>{snapshot.today_calendar_entries} Termine heute</p>"
        if snapshot.today_calendar_entries
        else "<p>Keine Termine heute</p>"
    )
    return (
        '<section class="wc-card" aria-labelledby="wc-kalender">'
        '<div class="wc-card-head"><span class="wc-card-mark" aria-hidden="true">'
        '📅</span><h2 id="wc-kalender">Kalender</h2></div>'
        '<hr class="wc-card-rule">'
        + body
        + _card_action("/kalender", "Öffnen")
        + "</section>"
    )


def render_work_center_arbeitszentrale(
    snapshot: WorkCenterSnapshot,
    *,
    ui: WorkCenterDashboardUi,
) -> str:
    """Render the v2 Arbeitszentrale from WorkCenterSnapshot facts only."""

    header_date = (
        f"{_WEEKDAYS[ui.today.weekday()]}, {ui.today.day}. "
        f"{_MONTHS[ui.today.month]} {ui.today.year}"
    )
    body = (
        '<div class="wc-page">'
        '<header class="wc-page-header">'
        f'<div class="wc-eyebrow">{_e(header_date)}</div>'
        "<h1>Arbeitszentrale</h1>"
        "<p>Überblick über Rückrufe, Angebote und Aufträge im Büro.</p>"
        "</header>"
        '<div class="wc-cards">'
        + _rueckrufe_card(snapshot)
        + _angebote_card(snapshot)
        + _auftraege_card(snapshot, ui)
        + _aufgaben_card(snapshot)
        + _kalender_card(snapshot)
        + "</div></div>"
    )
    return _page(
        "Arbeitszentrale",
        body,
        active_section="home",
        context=ui.context,
        show_title=False,
    )

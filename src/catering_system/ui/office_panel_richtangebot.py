"""Server-rendered views for preliminary Richtangebote."""

from __future__ import annotations

from catering_system.domain.richtangebot import Richtangebot
from catering_system.ui.office_panel_views import OfficePageContext, _e, _page


def _money(cents: int | None) -> str:
    if cents is None:
        return "Nicht angegeben"
    return f"{cents / 100:.2f} €".replace(".", ",")


def _date_text(value: Richtangebot) -> str:
    if value.event_date is not None:
        return value.event_date.strftime("%d.%m.%Y")
    return value.event_date_text or "Noch offen"


def _time_text(value: Richtangebot) -> str:
    if value.event_start is not None:
        return value.event_start.strftime("%H:%M")
    return value.event_time_text or "Noch offen"


def _guest_text(value: Richtangebot) -> str:
    if value.guest_count is not None:
        return str(value.guest_count)
    if value.guest_count_min is not None and value.guest_count_max is not None:
        return f"ca. {value.guest_count_min}–{value.guest_count_max}"
    return "Noch offen"


def render_richtangebot_detail(
    value: Richtangebot,
    *,
    context: OfficePageContext,
) -> str:
    body = (
        '<a class="inquiry-back" href="/angebote">← Angebote</a>'
        '<section class="inquiry-hero">'
        '<div><div class="inquiry-eyebrow">Richtangebot</div>'
        f"<h1>{_e(value.contact_name or value.caller_phone or 'Unbekannter Kunde')}</h1>"
        '<div class="inquiry-hero-facts">'
        f"<span>{_e(_date_text(value))}</span>"
        f"<span>{_e(_time_text(value))}</span>"
        f"<span>{_e(_guest_text(value))} Gäste</span>"
        "</div></div>"
        '<div class="inquiry-state-panel"><span>Status</span><strong>Richtangebot</strong>'
        '<p>Unverbindliche Budget- und Leistungsorientierung</p></div>'
        "</section>"
        '<div class="inquiry-detail-layout"><div class="inquiry-detail-main">'
        '<section class="inquiry-card inquiry-content-card"><h2>Rahmendaten</h2>'
        '<dl class="inquiry-facts-list">'
        f"<div><dt>Veranstaltung</dt><dd>{_e(value.event_type or 'Nicht angegeben')}</dd></div>"
        f"<div><dt>Datum</dt><dd>{_e(_date_text(value))}</dd></div>"
        f"<div><dt>Zeit</dt><dd>{_e(_time_text(value))}</dd></div>"
        f"<div><dt>Gäste</dt><dd>{_e(_guest_text(value))}</dd></div>"
        f"<div><dt>Ort</dt><dd>{_e(value.location or 'Nicht angegeben')}</dd></div>"
        f"<div><dt>Budget</dt><dd>{_e(_money(value.budget_per_person_cents))} / Person</dd></div>"
        "</dl></section>"
        '<section class="inquiry-card inquiry-content-card"><h2>Wünsche / Besonderheiten</h2>'
        f'<p class="inquiry-message">{_e(value.customer_request or "Nicht angegeben")}</p></section>'
        '<section class="inquiry-card inquiry-content-card"><h2>Hinweis</h2>'
        f'<p class="inquiry-message">{_e(value.disclaimer)}</p></section>'
        "</div><aside class="inquiry-detail-side">"
        '<section class="inquiry-card inquiry-content-card"><h2>Kontakt</h2>'
        '<dl class="inquiry-facts-list single">'
        f"<div><dt>Name</dt><dd>{_e(value.contact_name or 'Nicht angegeben')}</dd></div>"
        f"<div><dt>Telefon</dt><dd>{_e(value.caller_phone or 'Nicht angegeben')}</dd></div>"
        f"<div><dt>E-Mail</dt><dd>{_e(value.email or 'Nicht angegeben')}</dd></div>"
        "</dl></section>"
        '<section class="inquiry-next-step"><h2>Nächster Schritt</h2>'
        '<p>Sobald Datum, Zeit, Gästezahl und Leistungsumfang konkret sind, kann daraus eine normale Anfrage und anschließend ein verbindliches Angebot entstehen.</p>'
        "</section></aside></div>"
    )
    return _page(
        f"Richtangebot · {value.contact_name or value.caller_phone}",
        body,
        active_section="offers",
        context=context,
    )


def render_richtangebote_section(values: list[Richtangebot]) -> str:
    if not values:
        return ""
    rows = []
    for value in values:
        rows.append(
            "<tr>"
            f"<td>{_e(value.contact_name or value.caller_phone or 'Unbekannter Kunde')}"
            '<br><span class="muted">Richtangebot</span></td>'
            f"<td>{_e(_date_text(value))}</td>"
            f"<td>{_e(_time_text(value))}</td>"
            f"<td>{_e(_guest_text(value))}</td>"
            f"<td>{_e(_money(value.budget_per_person_cents))} / Person</td>"
            f'<td><a href="/richtangebot/{_e(value.richtangebot_id)}">Öffnen</a></td>'
            "</tr>"
        )
    return (
        '<section class="offer-queue-section">'
        f"<h2>Richtangebote ({len(values)})</h2>"
        '<p class="muted">Unverbindliche Budget- und Leistungsorientierung bei noch offenen Eckdaten.</p>'
        '<table><tr><th>Kunde</th><th>Datum</th><th>Zeit</th><th>Gäste</th><th>Budget</th><th></th></tr>'
        + "".join(rows)
        + "</table></section>"
    )

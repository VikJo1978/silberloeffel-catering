"""Server-rendered KI Telefonassistent inbox views."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import cast

from catering_system.domain.ai_telefon_call import AiTelefonCall
from catering_system.ui.office_panel_shell import OfficeSection
from catering_system.ui.office_panel_views import (
    _EMPTY_PAGE_CONTEXT,
    OfficePageContext,
    _csrf_input,
    _e,
    _page,
)

_ACTIVE_SECTION = cast(OfficeSection, "ai_phone")
_STATUS_LABELS = {
    "NEW": "Neu",
    "PROCESSED": "Übernommen",
    "DONE": "Erledigt",
}
_RESULT_LABELS = {
    "INQUIRY": "Anfrage",
    "RICHTANGEBOT": "Richtangebot",
    "TASK": "Aufgabe",
    "LINKED": "Verknüpft",
}
_LINK_TYPE_LABELS = {
    "INQUIRY": "Anfrage",
    "OFFER": "Angebot",
    "ORDER": "Auftrag",
}


@dataclass(frozen=True)
class AiTelefonLinkCandidate:
    linked_type: str
    linked_id: str
    title: str
    details: str = ""


def render_ai_telefon_calls(
    calls: list[AiTelefonCall],
    *,
    context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
) -> str:
    if not calls:
        body = (
            '<p class="subtitle">Gespräche des STRATO Smart-Telefonassistenten.</p>'
            '<div class="inquiry-card inquiry-content-card">'
            "<h2>Noch keine Gespräche</h2>"
            '<p class="inquiry-section-note">Neue STRATO-Zusammenfassungen erscheinen hier automatisch.</p>'
            "</div>"
        )
        return _page(
            "KI Telefonassistent", body, active_section=_ACTIVE_SECTION, context=context
        )

    new_count = sum(call.status == "NEW" for call in calls)
    rows = []
    for call in calls:
        customer = call.contact_name or call.caller_phone or "Unbekannter Anrufer"
        received = _format_datetime(call.received_at)
        status = _STATUS_LABELS.get(call.status, call.status)
        result = _RESULT_LABELS.get(call.result_type or "", "")
        result_text = f" · {result}" if result else ""
        rows.append(
            '<a class="chat-thread-row{}" href="/ki-telefonassistent/{}">'
            '<div class="chat-thread-head"><span class="chat-thread-title">{}</span>'
            '<span class="chat-meta">{}{}</span></div>'
            '<div class="chat-preview">{}</div>'
            '<div class="chat-meta">{} · {}</div>'
            "</a>".format(
                " unread" if call.status == "NEW" else "",
                _e(call.call_id),
                _e(customer),
                _e(status),
                _e(result_text),
                _e(call.subject or call.summary[:120]),
                _e(received),
                _e(call.caller_phone),
            )
        )

    body = (
        '<div class="dashboard-page-header">'
        "<div><h1>KI Telefonassistent</h1>"
        '<p class="subtitle">STRATO-Gespräche prüfen und anschließend gezielt übernehmen.</p></div>'
        f'<span class="dashboard-button">{new_count} neu</span>'
        "</div>"
        '<div class="chat-layout">'
        '<div class="chat-thread-list">' + "".join(rows) + "</div>"
        '<div class="chat-thread-view">'
        '<p class="chat-empty">Gespräch links auswählen.</p>'
        "</div></div>"
    )
    return _page(
        "KI Telefonassistent", body, active_section=_ACTIVE_SECTION, context=context
    )


def render_ai_telefon_call_detail(
    call: AiTelefonCall,
    *,
    context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    error_message: str = "",
    link_query: str = "",
    link_candidates: tuple[AiTelefonLinkCandidate, ...] = (),
) -> str:
    customer = call.contact_name or call.caller_phone or "Unbekannter Anrufer"
    status = _STATUS_LABELS.get(call.status, call.status)
    result = _RESULT_LABELS.get(call.result_type or "", "")

    facts = [
        ("Veranstaltungsart", call.event_type),
        ("Datum", _format_date(call.event_date)),
        ("Zeitraum", call.event_period),
        ("Beginn", _format_time(call.event_start)),
        ("Zeit / Zeitfenster", call.event_time_text),
        ("Gäste", _guest_text(call)),
        ("Ort", call.location),
        ("Budget", _format_budget(call.budget_per_person_cents)),
        ("Lieferung / Abholung", _fulfillment_label(call.fulfillment_mode)),
        ("Wünsche / Besonderheiten", call.customer_request),
        ("Rückruf", _callback_label(call)),
    ]
    fact_html = "".join(
        "<div><dt>{}</dt><dd>{}</dd></div>".format(
            _e(label), _e(value or "Nicht angegeben")
        )
        for label, value in facts
    )

    actions = []
    if call.status == "NEW":
        if call.event_date is not None and call.contact_name and call.caller_phone:
            actions.append(
                '<form method="post" action="/ki-telefonassistent/{}/anfrage">{}'
                '<button class="inquiry-button">Als Anfrage übernehmen</button></form>'.format(
                    _e(call.call_id), _csrf_input(context)
                )
            )
        else:
            missing = []
            if call.event_date is None:
                missing.append("Datum")
            if not call.contact_name:
                missing.append("Name")
            if not call.caller_phone:
                missing.append("Telefon")
            actions.append(
                '<p class="inquiry-section-note">Anfrage noch nicht direkt übernehmbar. '
                "Fehlt: {}.</p>".format(_e(", ".join(missing)))
            )

        commercial_missing = _commercial_missing(call)
        if commercial_missing:
            actions.append(
                '<p class="inquiry-section-note">Für ein konkretes Angebot noch offen: {}. '
                "Ein Richtangebot kann ohne erfundene Werte erstellt werden.</p>".format(
                    _e(", ".join(commercial_missing))
                )
            )
            actions.append(
                '<form method="post" action="/ki-telefonassistent/{}/richtangebot">{}'
                '<button class="inquiry-button">Richtangebot erstellen</button></form>'.format(
                    _e(call.call_id), _csrf_input(context)
                )
            )

        if context.employee_account_id:
            actions.append(
                '<form method="post" action="/ki-telefonassistent/{}/aufgabe">{}'
                '<button class="inquiry-button secondary">Als Aufgabe übernehmen</button></form>'.format(
                    _e(call.call_id), _csrf_input(context)
                )
            )
        actions.append(
            _render_link_existing(call, context, link_query, link_candidates)
        )
        actions.append(
            '<form method="post" action="/ki-telefonassistent/{}/erledigt">{}'
            '<button class="inquiry-button secondary">Erledigt</button></form>'.format(
                _e(call.call_id), _csrf_input(context)
            )
        )
    elif call.result_type and call.result_id:
        href = _result_href(call.result_type, call.result_id)
        if href:
            actions.append(
                '<a class="inquiry-button" href="{}">{} öffnen</a>'.format(
                    _e(href), _e(result or "Vorgang")
                )
            )
        elif call.result_type == "LINKED" and call.linked_type and call.linked_id:
            label = _LINK_TYPE_LABELS.get(call.linked_type, call.linked_type)
            actions.append(
                '<p class="inquiry-section-note">Verknüpft mit {} · {}</p>'.format(
                    _e(label), _e(call.linked_id)
                )
            )

    error_html = (
        f'<div class="inquiry-notice blocked">{_e(error_message)}</div>'
        if error_message
        else ""
    )
    body = (
        '<a class="inquiry-back" href="/ki-telefonassistent">← Alle Gespräche</a>'
        + error_html
        + '<section class="inquiry-hero">'
        '<div><div class="inquiry-eyebrow">KI Telefonassistent</div>'
        f"<h1>{_e(customer)}</h1>"
        '<div class="inquiry-hero-facts">'
        f"<span>{_e(call.caller_phone or 'Keine Telefonnummer')}</span>"
        f"<span>{_e(_format_datetime(call.received_at))}</span>"
        f"<span>STRATO-ID {_e(call.strato_id)}</span>"
        "</div></div>"
        '<div class="inquiry-state-panel"><span>Status</span>'
        f"<strong>{_e(status)}</strong>"
        f"<p>{_e(call.subject or 'Telefonat')}</p></div>"
        "</section>"
        '<div class="inquiry-detail-layout"><div class="inquiry-detail-main">'
        '<section class="inquiry-card inquiry-content-card"><h2>Gespräch</h2>'
        f'<p class="inquiry-message">{_e(call.summary)}</p></section>'
        '<section class="inquiry-card inquiry-content-card"><h2>Veranstaltung</h2>'
        f'<dl class="inquiry-facts-list">{fact_html}</dl></section>'
        '<details class="inquiry-edit"><summary>Technische Originaldaten</summary>'
        '<div class="inquiry-edit-body">'
        f"<p><strong>Gmail Message-ID:</strong> {_e(call.gmail_message_id)}</p>"
        f'<pre class="inquiry-message">{_e(call.raw_message)}</pre>'
        "</div></details></div>"
        '<aside class="inquiry-detail-side">'
        '<section class="inquiry-card inquiry-content-card"><h2>Kontakt</h2>'
        '<dl class="inquiry-facts-list single">'
        f"<div><dt>Name</dt><dd>{_e(call.contact_name or 'Nicht angegeben')}</dd></div>"
        f"<div><dt>Telefon</dt><dd>{_e(call.caller_phone or 'Nicht angegeben')}</dd></div>"
        f"<div><dt>E-Mail</dt><dd>{_e(call.email or 'Nicht angegeben')}</dd></div>"
        "</dl></section>"
        '<section class="inquiry-next-step"><h2>Weiterverarbeiten</h2>'
        "<p>Erst hier wird aus dem Gespräch ein echter Geschäftsvorgang.</p>"
        '<div class="chat-composer-actions">'
        + "".join(actions)
        + "</div></section></aside></div>"
    )
    return _page(
        f"KI Telefonassistent · {customer}",
        body,
        active_section=_ACTIVE_SECTION,
        context=context,
    )


def _commercial_missing(call: AiTelefonCall) -> list[str]:
    missing = []
    if call.event_date is None:
        missing.append("genaues Datum")
    if call.event_start is None:
        missing.append("genaue Zeit")
    if call.guest_count is None:
        missing.append("genaue Gästezahl")
    return missing


def _guest_text(call: AiTelefonCall) -> str:
    if call.guest_count is not None:
        return str(call.guest_count)
    if call.guest_count_min is not None and call.guest_count_max is not None:
        return f"ca. {call.guest_count_min}–{call.guest_count_max}"
    return ""


def _render_link_existing(
    call: AiTelefonCall,
    context: OfficePageContext,
    query: str,
    candidates: tuple[AiTelefonLinkCandidate, ...],
) -> str:
    search = (
        '<details class="inquiry-edit"><summary>Mit bestehendem Vorgang verknüpfen</summary>'
        '<div class="inquiry-edit-body">'
        '<p class="inquiry-section-note">Sucht nur vorhandene Anfragen, Angebote und Aufträge. '
        "Der gewählte Vorgang wird nicht verändert.</p>"
        '<form method="get" action="/ki-telefonassistent/{}">'
        '<label for="ai-link-search">Name, Telefon, Datum, Ort oder Vorgangs-ID</label><br>'
        '<input id="ai-link-search" name="q" value="{}" autocomplete="off"> '
        '<button class="inquiry-button secondary" type="submit">Suchen</button>'
        "</form>"
    ).format(_e(call.call_id), _e(query))

    if not query:
        results = '<p class="inquiry-section-note">Noch keine Suche ausgeführt.</p>'
    elif not candidates:
        results = '<p class="inquiry-section-note">Kein passender Vorgang gefunden.</p>'
    else:
        rows = []
        for candidate in candidates:
            details = (
                f'<div class="chat-meta">{_e(candidate.details)}</div>'
                if candidate.details
                else ""
            )
            rows.append(
                '<form method="post" action="/ki-telefonassistent/{}/verknuepfen">{}'
                '<input type="hidden" name="linked_type" value="{}">'
                '<input type="hidden" name="linked_id" value="{}">'
                "<div><strong>{}</strong>{}</div>"
                '<button class="inquiry-button secondary" type="submit">Verknüpfen</button>'
                "</form>".format(
                    _e(call.call_id),
                    _csrf_input(context),
                    _e(candidate.linked_type),
                    _e(candidate.linked_id),
                    _e(candidate.title),
                    details,
                )
            )
        results = "".join(rows)
    return search + results + "</div></details>"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone().strftime("%d.%m.%Y %H:%M")


def _format_date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _format_time(value: time | None) -> str:
    return value.strftime("%H:%M") if value else ""


def _format_budget(cents: int | None) -> str:
    if cents is None:
        return ""
    return f"{cents / 100:.2f} € / Person".replace(".", ",")


def _fulfillment_label(value: str) -> str:
    return {"DELIVERY": "Lieferung", "PICKUP": "Abholung", "UNKNOWN": ""}.get(
        value, value
    )


def _callback_label(call: AiTelefonCall) -> str:
    if call.callback_requested is None:
        return ""
    if not call.callback_requested:
        return "Nein"
    bits = ["Ja"]
    if call.callback_date:
        bits.append(call.callback_date.strftime("%d.%m.%Y"))
    if call.callback_time:
        bits.append(call.callback_time.strftime("%H:%M"))
    return " · ".join(bits)


def _result_href(result_type: str, result_id: str) -> str:
    if result_type == "INQUIRY":
        return f"/inquiry/{result_id}"
    if result_type == "RICHTANGEBOT":
        return f"/richtangebot/{result_id}"
    if result_type == "TASK":
        return f"/aufgaben/{result_id}"
    return ""

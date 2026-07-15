"""Pure premium presentation renderer for the Office Panel Inquiry detail."""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass

from catering_system.domain.inquiry import (
    CRM_PIPELINE,
    Inquiry,
    InquiryOfficeState,
    inquiry_shows_convert_accepted_button,
)
from catering_system.domain.order import Order

_SOURCE_LABELS = {
    "website_form": "Website-Anfrage",
    "configurator": "Angebots-Import",
    "manual": "Manuell erfasst",
    "phone_by_office": "Telefon (Büro)",
    "email": "E-Mail",
    "phone": "Telefon",
    "wix_form": "Website-Anfrage",
    "missed_call": "Verpasster Anruf",
    "ai_telefonist": "Telefonservice",
}
_PLANNING_MODE_LABELS = {
    "caterer_suggestion": "Vorschlag durch Silberlöffel",
    "self_select": "Auswahl durch den Kunden",
}
_VERIFICATION_LABELS = {
    "not_required": "Keine Rückrufprüfung nötig",
    "pending": "Rückrufprüfung ausstehend",
    "verified": "Telefonisch verifiziert",
    "failed": "Rückrufprüfung fehlgeschlagen",
    "blocked": "Rückrufprüfung blockiert",
}
_BLOCKER_LABELS = {
    "inquiry_call_verification_unsatisfied": "Rückrufprüfung noch nicht erfüllt",
    "inquiry_rejected": "Anfrage wurde abgelehnt",
}


@dataclass(frozen=True)
class InquiryDetailFormFields:
    """Trusted hidden fields produced by the existing Office Panel helpers."""

    csrf_input: str
    primary_command_fields: str
    update_command_fields: str


@dataclass(frozen=True)
class InquiryDetailPage:
    """Page title and body ready for the shared server-rendered shell."""

    title: str
    body: str


def _e(value: object) -> str:
    return html.escape(str(value))


def _date_text(inquiry: Inquiry) -> str:
    return inquiry.event_date.strftime("%d.%m.%Y")


def _source_label(value: str) -> str:
    return _SOURCE_LABELS.get(value, "Weitere Anfrage")


def _planning_label(value: str) -> str:
    return _PLANNING_MODE_LABELS.get(value, "Planung noch prüfen")


def _verification_label(value: str) -> str:
    return _VERIFICATION_LABELS.get(value, "Rückrufprüfung noch prüfen")


def _blocker_label(value: str) -> str:
    return _BLOCKER_LABELS.get(value, "Der Vorgang kann noch nicht fortgesetzt werden")


def _state_copy(
    inquiry: Inquiry,
    state: InquiryOfficeState,
    *,
    has_active_order: bool,
) -> tuple[str, str]:
    if state.next_action == "verify":
        return (
            "Rückruf erforderlich",
            "Die Angaben müssen vor dem nächsten Schritt telefonisch bestätigt werden.",
        )
    if state.next_action == "convert":
        return (
            "Bereit für Auftrag",
            "Die vorhandenen Angaben erlauben die Umwandlung in einen Auftrag.",
        )
    if state.next_action == "offer-pending":
        return (
            "Angebot ausstehend",
            "Für diese Anfrage läuft der Angebotsprozess. "
            "Ein direkter Legacy-Auftrag ist derzeit nicht vorgesehen.",
        )
    if state.next_action == "convert-accepted":
        if state.offer is not None and state.offer.commercial_state == "Converted":
            return (
                "Auftrag bereits erstellt",
                "Der Auftrag aus diesem angenommenen Angebot existiert bereits. "
                "Bei Storno den verknüpften Auftrag unten öffnen.",
            )
        return (
            "Angebot angenommen",
            "Das angenommene Angebot kann jetzt in einen Auftrag überführt werden.",
        )
    if has_active_order:
        return (
            "Auftrag vorhanden",
            "Diese Anfrage ist mit einem aktiven Auftrag verbunden.",
        )
    if inquiry.crm_stage == "Abgelehnt / verloren":
        return (
            "Anfrage abgeschlossen",
            "Die Anfrage wurde abgelehnt und hat keine weitere Hauptaktion.",
        )
    return (
        inquiry.crm_stage,
        f"Rückrufprüfung: {_verification_label(inquiry.call_verification_status)}.",
    )


def _primary_action(
    inquiry: Inquiry,
    state: InquiryOfficeState,
    forms: InquiryDetailFormFields,
) -> str:
    if state.next_action == "verify":
        heading = "Angaben telefonisch bestätigen"
        explanation = (
            "Datum, Ort und Gästezahl gemeinsam prüfen. Erst nach dem Gespräch "
            "die Rückrufprüfung bestätigen."
        )
        path = "verify"
        label = "Telefonisch verifiziert"
    elif state.next_action == "convert":
        heading = "Anfrage in einen Auftrag übernehmen"
        explanation = (
            "Die Prüfung ist erfüllt. Mit diesem Schritt wird der bestehende "
            "Auftragsprozess gestartet."
        )
        path = "convert"
        label = "In Auftrag umwandeln"
    elif inquiry_shows_convert_accepted_button(state):
        return (
            '<section class="inquiry-next-step">'
            '<div class="inquiry-eyebrow">Nächster Schritt</div>'
            "<h2>Angenommenes Angebot in Auftrag überführen</h2>"
            "<p>Dieses angenommene Angebot wird jetzt in einen Auftrag umgewandelt.</p>"
            f'<form method="post" action="/inquiry/{_e(inquiry.inquiry_id)}/convert-accepted" '
            'onsubmit="return confirm('
            "'Dieses angenommene Angebot wird jetzt in einen Auftrag umgewandelt.'"
            ');">'
            f"{forms.csrf_input}{forms.primary_command_fields}"
            '<button class="inquiry-button" type="submit">'
            "Angenommenes Angebot in Auftrag überführen"
            "</button></form></section>"
        )
    elif state.next_action == "convert-accepted":
        return (
            '<section class="inquiry-next-step">'
            '<div class="inquiry-eyebrow">Nächster Schritt</div>'
            "<h2>Auftrag bereits erstellt</h2>"
            "<p>Es wird kein zweiter Auftrag erzeugt. "
            "Den verknüpften Auftrag finden Sie unten.</p>"
            "</section>"
        )
    elif state.next_action == "offer-pending":
        return (
            '<section class="inquiry-next-step">'
            '<div class="inquiry-eyebrow">Nächster Schritt</div>'
            "<h2>Angebot ausstehend</h2>"
            "<p>Der Angebotsprozess ist noch offen. "
            "Es gibt derzeit keine direkte Legacy-Umwandlung in einen Auftrag.</p>"
            "</section>"
        )
    else:
        return ""
    return (
        '<section class="inquiry-next-step">'
        '<div class="inquiry-eyebrow">Nächster Schritt</div>'
        f"<h2>{heading}</h2><p>{explanation}</p>"
        f'<form method="post" action="/inquiry/{_e(inquiry.inquiry_id)}/{path}">'
        f"{forms.csrf_input}{forms.primary_command_fields}"
        f'<button class="inquiry-button" type="submit">{label}</button>'
        "</form></section>"
    )


def _linked_orders(linked_orders: Sequence[Order]) -> str:
    if not linked_orders:
        return ""
    links = []
    for order in linked_orders:
        if order.cancelled_at is None:
            label = "Aktiven Auftrag öffnen"
            status = "Aktiver Auftrag"
        else:
            label = "Stornierten Auftrag öffnen"
            status = "Storniert"
        links.append(
            '<li><span class="inquiry-order-status">'
            f"{status}</span>"
            f'<a class="inquiry-button secondary" href="/order/{_e(order.order_id)}">'
            f"{label}</a></li>"
        )
    return (
        '<section class="inquiry-card inquiry-content-card">'
        "<h2>Verknüpfte Aufträge</h2>"
        '<ul class="inquiry-order-list">' + "".join(links) + "</ul></section>"
    )


def _checks(inquiry: Inquiry, blockers: Sequence[str]) -> str:
    items = [
        (
            "open",
            _blocker_label(reason),
        )
        for reason in blockers
    ]
    if not inquiry.time_window_text:
        items.append(("open", "Zeitfenster noch prüfen"))
    if not inquiry.location_text:
        items.append(("open", "Ort noch prüfen"))
    if inquiry.guest_count_estimate is None:
        items.append(("open", "Gästezahl noch prüfen"))
    if not items:
        return '<p class="inquiry-no-checks">Keine offenen Prüfhinweise.</p>'
    lead = (
        '<p class="inquiry-blocker-lead">Konvertierung blockiert</p>'
        if blockers
        else ""
    )
    return (
        lead
        + '<ul class="inquiry-check-list">'
        + "".join(
            '<li><span class="inquiry-check-icon '
            f'{kind}" aria-hidden="true">!</span><span>{_e(label)}</span></li>'
            for kind, label in items
        )
        + "</ul>"
    )


def _planning_mode_select(selected: str) -> str:
    options = "".join(
        f'<option value="{_e(value)}"{" selected" if value == selected else ""}>'
        f"{_e(label)}</option>"
        for value, label in _PLANNING_MODE_LABELS.items()
    )
    return f'<select name="planning_mode">{options}</select>'


def _crm_stage_select(selected: str) -> str:
    options = "".join(
        f'<option value="{_e(value)}"{" selected" if value == selected else ""}>'
        f"{_e(value)}</option>"
        for value in CRM_PIPELINE
    )
    return f'<select name="crm_stage">{options}</select>'


def _edit_form(
    inquiry: Inquiry,
    forms: InquiryDetailFormFields,
    *,
    has_active_order: bool,
) -> str:
    guests = (
        str(inquiry.guest_count_estimate)
        if inquiry.guest_count_estimate is not None
        else ""
    )
    crm_stage_field = (
        f'{_e(inquiry.crm_stage)}<input type="hidden" name="crm_stage" '
        f'value="{_e(inquiry.crm_stage)}">'
        if has_active_order
        else _crm_stage_select(inquiry.crm_stage)
    )
    return (
        '<details class="inquiry-edit">'
        "<summary>Daten bearbeiten</summary>"
        '<div class="inquiry-edit-body">'
        f'<form method="post" action="/inquiry/{_e(inquiry.inquiry_id)}/update">'
        f"{forms.csrf_input}{forms.update_command_fields}<fieldset>"
        f'<p><label>Datum</label><input type="date" name="event_date" '
        f'value="{_e(inquiry.event_date.isoformat())}"></p>'
        f'<p><label>Zeitfenster</label><input name="time_window_text" '
        f'value="{_e(inquiry.time_window_text)}"></p>'
        f'<p><label>Ort</label><input name="location_text" '
        f'value="{_e(inquiry.location_text)}"></p>'
        f'<p><label>Gäste (ca.)</label><input name="guest_count_estimate" '
        f'value="{_e(guests)}"></p>'
        f"<p><label>Planung</label>{_planning_mode_select(inquiry.planning_mode)}</p>"
        f"<p><label>Arbeitsstand</label>{crm_stage_field}</p>"
        '<p class="subtitle">Intake-Kontext — keine Auftrags- oder Küchenfreigabe.</p>'
        f'<p><label>Betreff</label><input name="intake_subject" '
        f'value="{_e(inquiry.intake_subject or "")}"></p>'
        f'<p><label>Nachricht</label><textarea name="intake_message" rows="4">'
        f"{_e(inquiry.intake_message or '')}</textarea></p>"
        f'<p><label>Zusammenfassung</label><textarea name="intake_summary" rows="3">'
        f"{_e(inquiry.intake_summary or '')}</textarea></p>"
        f'<p><label>Externe Referenz</label><input name="intake_external_ref" '
        f'value="{_e(inquiry.intake_external_ref or "")}"></p>'
        '<p><button type="submit">Speichern</button></p>'
        "</fieldset></form></div></details>"
    )


def render_inquiry_detail(
    inquiry: Inquiry,
    linked_orders: Sequence[Order],
    state: InquiryOfficeState,
    progression_blockers: Sequence[str],
    *,
    forms: InquiryDetailFormFields,
    linked_orders_total_count: int | None = None,
    linked_orders_truncated: bool = False,
    offer_url: str | None = None,
) -> InquiryDetailPage:
    """Render existing Inquiry facts and actions without performing any reads."""

    subject = (inquiry.intake_subject or "").strip()
    title = subject or f"Anfrage vom {_date_text(inquiry)}"
    source = _source_label(inquiry.inquiry_source)
    guests = (
        f"ca. {inquiry.guest_count_estimate} Gäste"
        if inquiry.guest_count_estimate is not None
        else "Gästezahl noch offen"
    )
    has_active_order = any(order.cancelled_at is None for order in linked_orders)
    state_title, state_description = _state_copy(
        inquiry, state, has_active_order=has_active_order
    )
    warning = ""
    if linked_orders_truncated:
        warning = (
            '<div class="inquiry-notice blocked"><strong>Unvollständige Ansicht:</strong> '
            f"Nicht alle {_e(linked_orders_total_count or '')} verknüpften "
            "Aufträge sind in der Detailansicht enthalten.</div>"
        )
    website_banner = (
        '<div class="inquiry-notice">Die Angaben stammen aus dem Website-Formular '
        "und müssen geprüft werden.</div>"
        if inquiry.inquiry_source == "website_form"
        else ""
    )
    message = inquiry.intake_message or "Keine Nachricht übermittelt."
    summary = ""
    if inquiry.intake_summary or inquiry.intake_external_ref:
        summary_parts = []
        if inquiry.intake_summary:
            summary_parts.append(
                "<div><dt>Zusammenfassung</dt>"
                f"<dd>{_e(inquiry.intake_summary)}</dd></div>"
            )
        if inquiry.intake_external_ref:
            summary_parts.append(
                "<div><dt>Referenz aus der Anfrage</dt>"
                f"<dd>{_e(inquiry.intake_external_ref)}</dd></div>"
            )
        summary = (
            '<section class="inquiry-card inquiry-content-card">'
            "<h2>Weitere Angaben</h2>"
            '<dl class="inquiry-facts-list single">'
            + "".join(summary_parts)
            + "</dl></section>"
        )
    offer = ""
    if offer_url:
        offer = (
            '<section class="inquiry-card inquiry-content-card">'
            "<h2>Angebot</h2>"
            '<p class="inquiry-section-note">Öffnet einen bearbeitbaren Entwurf. '
            "Es wird noch kein Auftrag erzeugt.</p>"
            f'<a class="inquiry-button secondary" href="{_e(offer_url)}">'
            "Angebot vorbereiten</a></section>"
        )
    blocker_card = (
        '<section class="inquiry-card inquiry-content-card">'
        "<h2>Noch zu prüfen</h2>"
        f"{_checks(inquiry, progression_blockers)}</section>"
    )
    body = (
        '<a class="inquiry-back" href="/anfragen">← Zurück zu den Anfragen</a>'
        + warning
        + website_banner
        + '<section class="inquiry-hero"><div>'
        f'<div class="inquiry-eyebrow">{_e(source)}</div>'
        f"<h1>{_e(title)}</h1>"
        '<div class="inquiry-hero-facts">'
        f"<span>Datum: {_e(_date_text(inquiry))}</span>"
        f"<span>Ort: {_e(inquiry.location_text or 'Noch offen')}</span>"
        f"<span>{_e(guests)}</span></div></div>"
        '<div class="inquiry-state-panel"><span>Aktueller Stand</span>'
        f"<strong>{_e(state_title)}</strong><p>{_e(state_description)}</p></div>"
        "</section>"
        '<div class="inquiry-detail-layout"><div class="inquiry-detail-main">'
        '<section class="inquiry-card inquiry-content-card">'
        "<h2>Nachricht des Kunden</h2>"
        f'<p class="inquiry-message">{_e(message)}</p></section>'
        '<section class="inquiry-card inquiry-content-card">'
        '<h2>Veranstaltung</h2><dl class="inquiry-facts-list">'
        f"<div><dt>Datum</dt><dd>{_e(_date_text(inquiry))}</dd></div>"
        f"<div><dt>Zeit</dt><dd>{_e(inquiry.time_window_text or 'Noch offen')}</dd></div>"
        f"<div><dt>Ort</dt><dd>{_e(inquiry.location_text or 'Noch offen')}</dd></div>"
        f"<div><dt>Gäste</dt><dd>{_e(guests)}</dd></div>"
        f"<div><dt>Planung</dt><dd>{_e(_planning_label(inquiry.planning_mode))}</dd></div>"
        f"<div><dt>Arbeitsstand</dt><dd>{_e(inquiry.crm_stage)}</dd></div>"
        "</dl></section>" + summary + "</div>"
        '<aside class="inquiry-detail-side">'
        + _primary_action(inquiry, state, forms)
        + _linked_orders(linked_orders)
        + blocker_card
        + offer
        + "</aside></div>"
        + _edit_form(inquiry, forms, has_active_order=has_active_order)
    )
    return InquiryDetailPage(title=title, body=body)

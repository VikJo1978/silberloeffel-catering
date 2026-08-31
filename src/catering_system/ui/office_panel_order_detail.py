"""Pure premium presentation renderer for the Office Panel Order detail."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from catering_system.domain.customer_document_preview import CustomerDocumentPreview
from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import FULFILLMENT_MODES, PLANNING_MODES, Inquiry
from catering_system.domain.order import (
    Order,
    OrderVersion,
    is_order_version_superseded,
)
from catering_system.domain.order_payment_reminder import (
    PAYMENT_METHOD_LABELS,
    PAYMENT_METHODS,
    PaymentReminderView,
)
from catering_system.domain.ready_to_send import ReadyToSendEvaluation
from catering_system.services.customer_document_projection import (
    build_customer_document_recipient,
)
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentEligibility,
)
from catering_system.services.order_confirmation_outbound_service import (
    OutboundSendEligibility,
)
from catering_system.services.order_print_projection_service import PrintPositionLine
from catering_system.ui.office_panel_views import OfficePageContext
from catering_system.ui.operational_pause_labels import (
    PAUSE_REASON_LABELS,
    pause_reason_label,
)

_CONFIRMATION_STATE_LABELS = {
    "nicht_verfuegbar": "Nicht verfügbar",
    "aenderung_wartet": "Änderung wartet auf Küchendruck",
    "empfaenger_fehlt": "Empfänger-E-Mail fehlt",
    "bereit_zur_vorschau": "Bereit zur Vorschau",
    "dokument_erstellt": "Dokument erstellt",
}

_DOCUMENT_BLOCKER_LABELS = {
    "MISSING_COMMERCIAL_SNAPSHOT": "Kommerzieller Snapshot fehlt",
    "MISSING_CUSTOMER_NAME": "Kundenname fehlt",
    "MISSING_CUSTOMER_CONTACT": "Kundenkontakt fehlt",
    "INVALID_ORDER_STATE": "Auftrag nicht bereit für Kundendokument",
    "FULFILLMENT_MODE_REQUIRED": "Auftragsart (Lieferung/Abholung) fehlt",
    "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY": "Lieferadresse fehlt für Lieferung",
}

_FULFILLMENT_MODE_LABELS = {
    "UNKNOWN": "Nicht festgelegt",
    "DELIVERY": "Lieferung",
    "PICKUP": "Abholung",
}

_DOCUMENT_WARNING_LABELS = {
    "DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE": (
        "Lieferadresse weicht von Rechnungsadresse ab"
    ),
}

_DELIVERY_MODE_LABELS = {
    "UNKNOWN": "Unbekannt",
    "SAME_AS_INVOICE": "Wie Rechnungsadresse",
    "SEPARATE": "Abweichende Lieferadresse",
}

_NO_SEPARATE_DELIVERY = "keine separate Adresse"
_NO_EFFECTIVE_DELIVERY = "nicht festgelegt"


_OUTBOUND_STATE_LABELS = {
    "dokument_fehlt": "Dokument fehlt",
    "testversand_bereit": "Testversand möglich",
    "testversand_protokolliert": "Testversand protokolliert",
    "empfaenger_fehlt": "Empfänger-E-Mail fehlt",
    "pending_order_version_change": "Änderung wartet auf Küchendruck",
    "kitchen_print_not_confirmed": "Küchendruck fehlt",
    "order_not_ready_to_send": "Versandfreigabe blockiert",
    "order_storniert": "Auftrag storniert",
    "confirmation_document_not_current": "Dokument nicht aktuell",
}

_PLANNING_MODE_LABELS = {
    "caterer_suggestion": "Vorschlag durch Silberlöffel",
    "self_select": "Auswahl durch den Kunden",
}
_READY_BLOCKER_LABELS = {
    "ready_to_send_order_not_found": "Die Auftragsdaten sind nicht verfügbar.",
    "order_cancelled": "Der Auftrag ist storniert.",
    "no_effective_version": "Noch kein Stand ist als aktueller Küchenstand festgelegt.",
    "effective_version_not_resolvable": (
        "Der aktuelle Küchenstand kann nicht geladen werden."
    ),
    "kitchen_print_not_confirmed": (
        "Für den aktuellen Küchenstand fehlt die Druckbestätigung."
    ),
    "pending_order_version_change": ("Eine Änderung wartet noch auf Küchendruck."),
    "operational_pause": "Der Auftrag ist betrieblich pausiert.",
}

_RESUME_REASON_LABELS = {
    "operator_cleared": "Sperre aufgehoben",
    "customer_confirmed": "Kunde bestätigt",
    "issue_resolved": "Problem gelöst",
    "other": "Sonstiges",
}

_CHANGED_FIELD_LABELS = {
    "event_date": "Datum",
    "time_window_text": "Zeitfenster",
    "location_text": "Ort",
    "guest_count_estimate": "Gästezahl",
    "planning_mode": "Planungsmodus",
}


@dataclass(frozen=True)
class OrderVersionChangePrefill:
    """Defaults for the append-only OrderVersion change form."""

    event_date: str
    time_window_text: str
    location_text: str
    guest_count_estimate: str
    planning_mode: str
    latest_version_number: int


ConfirmationLivePreviewState = Literal[
    "ready",
    "unavailable",
    "parse_error",
    "not_found",
]


@dataclass(frozen=True)
class ConfirmationLivePreviewView:
    """Live CDP preview load result for Order Detail (V1-E)."""

    state: ConfirmationLivePreviewState
    preview: CustomerDocumentPreview | None = None

    def __post_init__(self) -> None:
        if self.state == "ready" and self.preview is None:
            raise ValueError("ready live preview requires preview payload")
        if self.state != "ready" and self.preview is not None:
            raise ValueError("non-ready live preview must not carry payload")


@dataclass(frozen=True)
class OrderDetailFormFields:
    """Trusted hidden fields produced by the existing Office Panel helpers."""

    csrf_input: str
    print_confirm_command_fields: Mapping[str, str]
    effective_command_fields: Mapping[str, str]
    ready_command_fields: str
    cancel_command_fields: str
    version_command_fields: str
    payment_command_fields: str
    payment_method_command_fields: str = ""
    payment_correction_command_fields: str = ""
    confirmation_command_fields: str = ""
    print_confirm_button_labels: Mapping[str, str] = field(default_factory=dict)
    print_status_messages: Mapping[str, str] = field(default_factory=dict)
    print_action_available: Mapping[str, bool] = field(default_factory=dict)
    send_command_fields: str = ""
    pause_command_fields: str = ""
    resume_command_fields: str = ""
    customer_addresses_command_fields: str = ""
    delivery_address_command_fields: str = ""
    fulfillment_mode_command_fields: str = ""
    version_change_prefill: OrderVersionChangePrefill | None = None


@dataclass(frozen=True)
class OrderDetailPage:
    """Page title and body ready for the shared server-rendered shell."""

    title: str
    body: str


@dataclass(frozen=True)
class OrderDetailOperationalData:
    """Exact target-version data prepared by the Office Panel read boundary."""

    company_name: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    delivery_address_lines: tuple[str, ...] = ()
    operational_context_available: bool = False
    variant_label: str | None = None
    positions: tuple[PrintPositionLine, ...] = ()
    positions_available: bool = False


def _e(value: object) -> str:
    return html.escape(str(value))


def _date_text(version: OrderVersion) -> str:
    return version.event_date.strftime("%d.%m.%Y")


def _created_text(version: OrderVersion) -> str:
    return version.created_at.strftime("%d.%m.%Y · %H:%M")


def _planning_label(value: str) -> str:
    return _PLANNING_MODE_LABELS.get(value, "Planung noch prüfen")


def _ready_blocker_label(value: str) -> str:
    return _READY_BLOCKER_LABELS.get(
        value, "Die Versandfreigabe kann derzeit nicht bestätigt werden."
    )


def target_order_version(
    order: Order, versions: Sequence[OrderVersion]
) -> OrderVersion | None:
    """Office progression target: explicit candidate, else highest version_number."""
    return _target_version(order, versions)


def version_change_prefill(
    order: Order,
    versions: Sequence[OrderVersion],
    *,
    latest_version_number: int,
) -> OrderVersionChangePrefill | None:
    target = _target_version(order, versions)
    if target is None:
        return None
    return OrderVersionChangePrefill(
        event_date=target.event_date.isoformat(),
        time_window_text=target.time_window_text,
        location_text=target.location_text,
        guest_count_estimate=(
            str(target.guest_count_estimate)
            if target.guest_count_estimate is not None
            else ""
        ),
        planning_mode=target.planning_mode,
        latest_version_number=latest_version_number,
    )


def _target_version(
    order: Order, versions: Sequence[OrderVersion]
) -> OrderVersion | None:
    candidate = next(
        (
            version
            for version in versions
            if version.order_version_id == order.candidate_order_version_id
        ),
        None,
    )
    if candidate is not None:
        return candidate
    return max(versions, key=lambda version: version.version_number, default=None)


def _kitchen_print_waiting(
    target: OrderVersion | None,
    next_action: Mapping[str, str] | None,
    forms: OrderDetailFormFields,
) -> bool:
    return (
        target is not None
        and next_action is not None
        and next_action.get("action") == "print-confirm"
        and not forms.print_action_available.get(target.order_version_id, True)
    )


def _state_copy(
    order: Order,
    target: OrderVersion | None,
    next_action: Mapping[str, str] | None,
    ready: ReadyToSendEvaluation,
    confirmation: OrderConfirmationDocumentEligibility,
    live_preview: ConfirmationLivePreviewView,
    source_inquiry: Inquiry | None,
    operational_data: OrderDetailOperationalData | None,
    operational_pause: Mapping[str, object],
) -> tuple[str, str]:
    if order.cancelled_at is not None:
        return (
            "Auftrag storniert",
            "Historie und Küchenzettel bleiben zur Einsicht verfügbar.",
        )
    if operational_pause.get("active"):
        reason = _pause_reason_label(
            operational_pause.get("reason_code") or operational_pause.get("reason")
        )
        return (
            "Betrieblich pausiert",
            f"Der Auftrag bleibt sichtbar, die Versandfreigabe ist gesperrt. Grund: {reason}.",
        )
    if _requires_fulfillment_choice(source_inquiry):
        return (
            "Auftragsart festlegen",
            "Bitte auswählen, ob der Auftrag geliefert oder abgeholt wird.",
        )
    if _requires_delivery_address(source_inquiry, operational_data):
        return (
            "Lieferadresse ergänzen",
            "Für eine Lieferung muss eine Lieferadresse hinterlegt sein.",
        )
    if next_action is not None and next_action.get("action") == "print-confirm":
        return (
            "Küchendruck erforderlich",
            "Den Küchenzettel prüfen und den Küchendruck starten.",
        )
    if next_action is not None and next_action.get("action") == "effective":
        return (
            "Küchenstand wird übernommen",
            "Der Ausdruck ist bestätigt. Der geprüfte Stand wird automatisch übernommen.",
        )
    if _requires_confirmation_document(confirmation, live_preview):
        return (
            "Auftragsbestätigung erstellen",
            "Der Küchenstand ist bestätigt. Erstellen Sie jetzt die Auftragsbestätigung für den Kunden.",
        )
    if confirmation.available and confirmation.snapshot is None:
        return (
            "Auftragsbestätigung prüfen",
            _confirmation_state_label(confirmation.state),
        )
    if ready.ready:
        return (
            "Vorbereitung vollständig",
            "Der aktuelle Küchenstand erfüllt die Versandfreigabe.",
        )
    return (
        "Versandfreigabe blockiert",
        "Die offenen Hinweise müssen vor der Freigabe geklärt werden.",
    )


def _primary_action(
    order: Order,
    target: OrderVersion | None,
    next_action: Mapping[str, str] | None,
    forms: OrderDetailFormFields,
    *,
    ready: ReadyToSendEvaluation,
    confirmation: OrderConfirmationDocumentEligibility,
    live_preview: ConfirmationLivePreviewView,
    source_inquiry: Inquiry | None,
    operational_data: OrderDetailOperationalData | None,
    operational_pause: Mapping[str, object],
    context: OfficePageContext,
) -> str:
    if order.cancelled_at is not None:
        return (
            '<section class="order-next-step muted">'
            '<div class="order-eyebrow">Nächster Schritt</div>'
            "<h2>Keine weitere Bearbeitung</h2>"
            "<p>Der Auftrag ist storniert und bleibt schreibgeschützt.</p>"
            "</section>"
        )
    if operational_pause.get("active"):
        pause_action = (
            '<a class="order-button" href="#order-pause-controls">Pause aufheben</a>'
            if context.can("orders.pause")
            else ""
        )
        return (
            '<section class="order-next-step muted">'
            '<div class="order-eyebrow">Nächster Schritt</div>'
            "<h2>Auftragspause klären</h2>"
            "<p>Prüfen Sie den Pausengrund und setzen Sie den Auftrag anschließend fort.</p>"
            f'<div class="order-next-actions">{pause_action}</div></section>'
        )
    if target is None:
        return (
            '<section class="order-next-step muted">'
            '<div class="order-eyebrow">Nächster Schritt</div>'
            "<h2>Auftragsdaten prüfen</h2>"
            "<p>Für diesen Auftrag ist kein gültiger Stand verfügbar.</p>"
            "</section>"
        )
    if source_inquiry is not None and _requires_fulfillment_choice(source_inquiry):
        action = (
            f'<form method="post" action="/inquiry/{_e(source_inquiry.inquiry_id)}/fulfillment-mode">'
            f"{forms.csrf_input}{forms.fulfillment_mode_command_fields}"
            f'<input type="hidden" name="return_order_id" value="{_e(order.order_id)}">'
            "<fieldset>"
            "<p><label>Auftragsart</label>"
            '<select name="fulfillment_mode">'
            f'<option value="DELIVERY">{_e(_FULFILLMENT_MODE_LABELS["DELIVERY"])}</option>'
            f'<option value="PICKUP">{_e(_FULFILLMENT_MODE_LABELS["PICKUP"])}</option>'
            "</select></p>"
            '<p><button class="order-button" type="submit">Auftragsart speichern</button></p>'
            "</fieldset></form>"
            if context.can("inquiries.edit")
            else ""
        )
        return (
            '<section class="order-next-step muted">'
            '<div class="order-eyebrow">Nächster Schritt</div>'
            "<h2>Auftragsart festlegen</h2>"
            "<p>Bitte auswählen, ob der Auftrag geliefert oder abgeholt wird.</p>"
            f'<div class="order-next-actions">{action}</div></section>'
        )
    if _requires_delivery_address(source_inquiry, operational_data):
        action = (
            _customer_addresses_form(order, target, forms)
            if context.can("inquiries.view") and context.can("orders.version.create")
            else ""
        )
        return (
            '<section class="order-next-step muted">'
            '<div class="order-eyebrow">Nächster Schritt</div>'
            "<h2>Lieferadresse ergänzen</h2>"
            "<p>Für eine Lieferung muss eine Lieferadresse hinterlegt sein.</p>"
            f'<div class="order-next-actions">{action}</div></section>'
        )
    if next_action is None:
        if not ready.ready:
            blockers = " ".join(
                _ready_blocker_label(reason) for reason in ready.reasons
            )
            return (
                '<section class="order-next-step muted">'
                '<div class="order-eyebrow">Nächster Schritt</div>'
                "<h2>Auftragsdaten prüfen</h2>"
                f"<p>{_e(blockers)}</p>"
                "</section>"
            )
        document_action = _confirmation_create_form(
            order,
            confirmation,
            forms,
            live_preview,
            context=context,
            button_class="order-button",
        )
        if document_action:
            return (
                '<section class="order-next-step">'
                '<div class="order-eyebrow">Nächster Schritt</div>'
                "<h2>Auftragsbestätigung erstellen</h2>"
                "<p>Der Küchenstand ist bestätigt. Erstellen Sie jetzt die "
                "Auftragsbestätigung für den Kunden.</p>"
                f'<div class="order-next-actions">{document_action}</div></section>'
            )
        if confirmation.available and confirmation.snapshot is None:
            return (
                '<section class="order-next-step muted">'
                '<div class="order-eyebrow">Nächster Schritt</div>'
                "<h2>Auftragsbestätigung prüfen</h2>"
                f"<p>{_e(_confirmation_state_label(confirmation.state))}</p>"
                "</section>"
            )
        ready_action = ""
        if context.can("orders.ready.release"):
            ready_action = (
                f'<form method="post" action="/order/{_e(order.order_id)}/ready">'
                f"{forms.csrf_input}{forms.ready_command_fields}"
                '<button class="order-button" type="submit">'
                "Versandfreigabe prüfen</button></form>"
            )
        return (
            '<section class="order-next-step complete">'
            '<div class="order-eyebrow">Nächster Schritt</div>'
            "<h2>Vorbereitung vollständig</h2>"
            "<p>Der Küchenstand ist bestätigt. Prüfen Sie jetzt die Versandfreigabe.</p>"
            f'<div class="order-next-actions">{ready_action}</div>'
            "</section>"
        )
    next_action_name = next_action.get("action")
    if next_action_name == "print-confirm":
        if (
            not context.can("orders.print.confirm")
            or target.order_version_id not in forms.print_confirm_command_fields
        ):
            return (
                '<section class="order-next-step muted">'
                '<div class="order-eyebrow">Nächster Schritt</div>'
                "<h2>Küchendruck erforderlich</h2>"
                "<p>Der aktuelle Stand muss vor der weiteren Bearbeitung gedruckt werden.</p>"
                "</section>"
            )
        command_fields = forms.print_confirm_command_fields.get(
            target.order_version_id, ""
        )
        button_label = forms.print_confirm_button_labels.get(
            target.order_version_id, "Küchendruck starten"
        )
        status_message = forms.print_status_messages.get(
            target.order_version_id,
            "",
        )
        action_available = forms.print_action_available.get(
            target.order_version_id, True
        )
        if action_available:
            heading = "Küchenzettel für den aktuellen Stand drucken"
            status_html = f"<p>{_e(status_message)}</p>" if status_message else ""
            auto_refresh = ""
        else:
            heading = "Druckauftrag gesendet"
            status_html = (
                '<p aria-live="polite">Druckauftrag wird verarbeitet – '
                "warte auf Druckbestätigung…</p>"
            )
            auto_refresh = (
                "<script>window.setTimeout(function () { "
                "window.location.reload(); }, 1500);</script>"
            )
        primary = (
            f'<form method="post" action="/order/{_e(order.order_id)}/print-confirm">'
            f"{forms.csrf_input}{command_fields}"
            f'<input type="hidden" name="order_version_id" '
            f'value="{_e(target.order_version_id)}">'
            f'<button class="order-button" type="submit">{_e(button_label)}</button>'
            "</form>"
            if button_label and action_available
            else ""
        )
        secondary = (
            f'<a class="order-button secondary" target="_blank" rel="noopener" '
            f'href="/order/{_e(order.order_id)}/print?version='
            f'{_e(target.order_version_id)}">Küchenzettel öffnen</a>'
        )
        return (
            '<section class="order-next-step">'
            '<div class="order-eyebrow">Nächster Schritt</div>'
            f"<h2>{heading}</h2>"
            f"{status_html}"
            '<div class="order-next-actions">'
            f"{primary}{secondary}</div></section>"
            f"{auto_refresh}"
        )
    if next_action_name == "effective":
        return (
            '<section class="order-next-step">'
            '<div class="order-eyebrow">Nächster Schritt</div>'
            "<h2>Küchenstand wird automatisch übernommen</h2>"
            "<p>Der Ausdruck ist bestätigt. Dieser Stand wird ohne weiteren "
            "manuellen Schritt zur Arbeitsgrundlage für die Küche.</p></section>"
        )
    return ""


def _requires_fulfillment_choice(source_inquiry: Inquiry | None) -> bool:
    return source_inquiry is not None and source_inquiry.fulfillment_mode == "UNKNOWN"


def _requires_delivery_address(
    source_inquiry: Inquiry | None,
    operational_data: OrderDetailOperationalData | None,
) -> bool:
    return (
        source_inquiry is not None
        and source_inquiry.fulfillment_mode == "DELIVERY"
        and (
            operational_data is None
            or not operational_data.operational_context_available
            or not operational_data.delivery_address_lines
        )
    )


def _confirmation_create_action_available(
    confirmation: OrderConfirmationDocumentEligibility,
    live_preview: ConfirmationLivePreviewView,
    *,
    context: OfficePageContext,
) -> bool:
    return _requires_confirmation_document(
        confirmation,
        live_preview,
    ) and context.can("documents.prepare")


def _requires_confirmation_document(
    confirmation: OrderConfirmationDocumentEligibility,
    live_preview: ConfirmationLivePreviewView,
) -> bool:
    return (
        confirmation.snapshot is None
        and live_preview.state == "ready"
        and live_preview.preview is not None
        and live_preview.preview.eligible
    )


def _progress_item(
    css_class: str,
    mark: str,
    heading: str,
    description: str,
) -> str:
    return (
        f'<li class="order-progress-item {css_class}">'
        f'<span class="order-progress-mark" aria-hidden="true">{mark}</span>'
        f"<div><strong>{heading}</strong><span>{description}</span></div></li>"
    )


def _operational_progress(
    order: Order,
    target: OrderVersion | None,
    ready: ReadyToSendEvaluation,
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext,
) -> str:
    if target is None:
        steps = '<p class="order-section-note">Keine Auftragsstände vorhanden.</p>'
    else:
        printed = target.kitchen_print_confirmed_at is not None
        effective = target.order_version_id == order.effective_order_version_id
        steps = '<ol class="order-progress-list">'
        steps += _progress_item(
            "done" if printed else "current",
            "✓" if printed else "1",
            f"Druck für Stand {target.version_number} bestätigen",
            (
                "Der Ausdruck wurde bestätigt."
                if printed
                else "Küchenzettel drucken und den tatsächlichen Ausdruck bestätigen."
            ),
        )
        steps += _progress_item(
            "done" if effective else ("current" if printed else "waiting"),
            "✓" if effective else "2",
            "Küchenstand automatisch übernehmen",
            (
                "Die Küche arbeitet mit diesem Stand."
                if effective
                else "Nach erfolgreichem Druck wird dieser Stand automatisch übernommen."
            ),
        )
        steps += _progress_item(
            "done" if ready.ready else ("current" if effective else "waiting"),
            "✓" if ready.ready else "3",
            "Versandfreigabe prüfen",
            (
                "Die Versandfreigabe ist erfüllt."
                if ready.ready
                else "Die Freigabe bleibt blockiert, bis alle Hinweise geklärt sind."
            ),
        )
        steps += "</ol>"
        if ready.ready and not effective:
            steps += (
                '<p class="order-context-note">Die Versandfreigabe gilt für den '
                "bisherigen Küchenstand. Der neue Stand ist noch nicht übernommen.</p>"
            )
    blocker_html = ""
    if not ready.ready:
        reasons = "".join(
            f"<li>{_e(_ready_blocker_label(reason))}</li>" for reason in ready.reasons
        )
        blocker_html = (
            '<div class="order-blockers"><strong>Offene Hinweise</strong>'
            f"<ul>{reasons}</ul></div>"
        )
    ready_form = ""
    if order.cancelled_at is None and context.can("orders.ready.release"):
        ready_form = (
            f'<form class="order-ready-form" method="post" '
            f'action="/order/{_e(order.order_id)}/ready">'
            f"{forms.csrf_input}{forms.ready_command_fields}"
            '<button class="order-button secondary" type="submit">'
            "Versandfreigabe prüfen</button></form>"
        )
    return (
        '<section class="order-card order-content-card">'
        "<h2>Operative Vorbereitung</h2>"
        f"{steps}{blocker_html}{ready_form}</section>"
    )


def _stale_print_notice(order: Order, versions: Sequence[OrderVersion]) -> str:
    if order.candidate_order_version_id is None:
        return ""
    stale_prints = [
        version
        for version in versions
        if version.kitchen_print_confirmed_at is not None
        and version.order_version_id != order.effective_order_version_id
        and version.order_version_id != order.candidate_order_version_id
    ]
    if not stale_prints:
        return ""
    latest = max(stale_prints, key=lambda version: version.version_number)
    return (
        '<div class="order-notice blocked">'
        "<strong>Küchendruck nicht übernommen:</strong> "
        f"Stand {_e(latest.version_number)} wurde gedruckt, aber inzwischen gibt es "
        "einen neueren Stand. Der ältere Stand wurde nicht als aktueller "
        "Küchenstand übernommen.</div>"
    )


def _version_actions(
    order: Order,
    version: OrderVersion,
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext,
) -> str:
    actions = [
        f'<a class="order-button ghost" target="_blank" rel="noopener" '
        f'href="/order/{_e(order.order_id)}/print?version='
        f'{_e(version.order_version_id)}">Küchenzettel öffnen</a>',
        f'<a class="order-button ghost" target="_blank" rel="noopener" '
        f'href="/order/{_e(order.order_id)}/buffet-cards?version='
        f'{_e(version.order_version_id)}">Buffetschilder öffnen</a>',
    ]
    print_fields = forms.print_confirm_command_fields.get(version.order_version_id)
    button_label = forms.print_confirm_button_labels.get(
        version.order_version_id, "Küchendruck starten"
    )
    action_available = forms.print_action_available.get(version.order_version_id, True)
    if (
        print_fields is not None
        and button_label
        and action_available
        and context.can("orders.print.confirm")
    ):
        actions.append(
            f'<form method="post" action="/order/{_e(order.order_id)}/print-confirm">'
            f"{forms.csrf_input}{print_fields}"
            f'<input type="hidden" name="order_version_id" '
            f'value="{_e(version.order_version_id)}">'
            '<button class="order-button ghost" type="submit">'
            f"{_e(button_label)}</button></form>"
        )
    return '<div class="order-version-actions">' + "".join(actions) + "</div>"


def _version_history(
    order: Order,
    versions: Sequence[OrderVersion],
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext,
) -> str:
    rows = []
    target = _target_version(order, versions)
    for version in sorted(versions, key=lambda item: item.version_number, reverse=True):
        statuses = []
        if target is not None and version.order_version_id == target.order_version_id:
            statuses.append("Aktueller Bearbeitungsstand")
        if version.order_version_id == order.effective_order_version_id:
            statuses.append("Aktueller Küchenstand")
        if version.order_version_id == order.candidate_order_version_id:
            statuses.append("Nächster Stand")
        if is_order_version_superseded(order, version, list(versions)):
            statuses.append("Durch neuere Änderung ersetzt")
        statuses.append(
            "Druck bestätigt"
            if version.kitchen_print_confirmed_at is not None
            else "Druck offen"
        )
        status_html = "".join(
            f'<span class="order-version-status">{_e(status)}</span>'
            for status in statuses
        )
        guests = (
            f"ca. {version.guest_count_estimate}"
            if version.guest_count_estimate is not None
            else "Noch offen"
        )
        rows.append(
            '<article class="order-version-row">'
            '<div class="order-version-head">'
            f"<div><strong>Stand {version.version_number}</strong>"
            f"<span>{_e(_created_text(version))}</span></div>"
            f'<div class="order-version-statuses">{status_html}</div></div>'
            '<dl class="order-version-facts">'
            f"<div><dt>Datum</dt><dd>{_e(_date_text(version))}</dd></div>"
            f"<div><dt>Zeit</dt><dd>{_e(version.time_window_text or 'Noch offen')}</dd></div>"
            f"<div><dt>Ort</dt><dd>{_e(version.location_text or 'Noch offen')}</dd></div>"
            f"<div><dt>Gäste</dt><dd>{_e(guests)}</dd></div>"
            "</dl>"
            + (
                '<div class="order-version-change">'
                f"<strong>Änderungsgrund:</strong> {_e(version.change_reason)}<br>"
                "<strong>Geändert:</strong> "
                + _e(
                    ", ".join(
                        _CHANGED_FIELD_LABELS.get(field, field)
                        for field in version.changed_fields
                    )
                    or "–"
                )
                + "</div>"
                if version.change_reason is not None
                else ""
            )
            + f"{_version_actions(order, version, forms, context=context)}</article>"
        )
    return (
        '<details class="order-history">'
        f"<summary>Alle Auftragsstände ({len(versions)})</summary>"
        '<div class="order-history-body">'
        + (
            "".join(rows)
            if rows
            else '<p class="order-section-note">Keine Auftragsstände vorhanden.</p>'
        )
        + "</div></details>"
    )


def _payment_form(
    order: Order,
    payment: PaymentReminderView,
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext,
) -> str:
    if order.cancelled_at is not None:
        return ""
    if not context.can("orders.payment.reminder"):
        return ""

    if payment.payment_method is None:
        options = ['<option value="">Bitte wählen</option>']
        for method in PAYMENT_METHODS:
            options.append(
                f'<option value="{method}">{_e(PAYMENT_METHOD_LABELS[method])}</option>'
            )
        method_field = (
            "<p><label>Zahlungsart*</label>"
            '<select name="payment_method" required>'
            f"{''.join(options)}</select></p>"
        )
    else:
        method_field = (
            f"<p><strong>Zahlungsart:</strong> {_e(payment.payment_method_label)}</p>"
            f'<input type="hidden" name="payment_method" '
            f'value="{_e(payment.payment_method)}">'
        )

    quittung = ""
    if payment.payment_method == "BAR_VOR_ORT":
        quittung = (
            f'<p><label><input type="checkbox" name="quittung_printed" value="1"'
            f"{' checked' if payment.quittung_printed else ''}> "
            "Quittung gedruckt</label></p>"
        )
    escalation = ""
    if payment.payment_method != "BAR_VOR_ORT":
        escalation += (
            f'<p><label><input type="checkbox" name="payment_reminder_sent" value="1"'
            f"{' checked' if payment.payment_reminder_sent_at else ''}> "
            "Zahlungserinnerung gesendet</label></p>"
        )
    if payment.payment_method == "RECHNUNG":
        escalation += (
            f'<p><label><input type="checkbox" name="mahnung_sent" value="1"'
            f"{' checked' if payment.mahnung_sent_at else ''}> "
            "Mahnung gesendet</label></p>"
        )
    return (
        '<details class="order-payment-edit"><summary>Zahlungsdaten bearbeiten</summary>'
        f'<form method="post" action="/order/{_e(order.order_id)}/payment-reminder">'
        f"{forms.csrf_input}{forms.payment_command_fields}<fieldset>"
        + method_field
        + f'<p><label><input type="checkbox" name="invoice_created" value="1"'
        f"{' checked' if payment.invoice_created else ''}> "
        "Rechnung in der Buchhaltung erstellt</label></p>"
        f'<p><label>Rechnungsnummer</label><input name="invoice_number" '
        f'maxlength="200" value="{_e(payment.invoice_number or "")}"></p>'
        f'<p><label>Versendet am</label><input type="date" name="sent_on" '
        f'value="{_e(payment.sent_on.isoformat() if payment.sent_on else "")}"></p>'
        "<p>Fälligkeit wird automatisch berechnet.</p>"
        f'<p><label>Bezahlt am</label><input type="date" name="paid_on" '
        f'value="{_e(payment.paid_on.isoformat() if payment.paid_on else "")}"></p>'
        + quittung
        + f'<p><label><input type="checkbox" name="cash_received" value="1"'
        f"{' checked' if payment.cash_received else ''}> "
        "Barzahlung erhalten</label></p>"
        + escalation
        + '<p><button type="submit">Zahlungshinweis speichern</button></p>'
        "</fieldset></form></details>"
    )


def _payment_method_change_form(
    order: Order,
    payment: PaymentReminderView,
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext,
) -> str:
    if (
        order.cancelled_at is not None
        or not context.can("orders.payment.reminder")
        or payment.payment_method is None
        or payment.paid_on is not None
        or payment.cash_received
    ):
        return ""
    options = ['<option value="">Neue Zahlungsart wählen</option>']
    for method in PAYMENT_METHODS:
        if method == payment.payment_method:
            continue
        options.append(
            f'<option value="{method}">{_e(PAYMENT_METHOD_LABELS[method])}</option>'
        )
    return (
        '<details class="order-payment-method-change">'
        "<summary>Zahlungsart ändern</summary>"
        f'<form method="post" action="/order/{_e(order.order_id)}/payment-method">'
        f"{forms.csrf_input}{forms.payment_method_command_fields}<fieldset>"
        "<p><label>Neue Zahlungsart*</label>"
        '<select name="new_payment_method" required>'
        f"{''.join(options)}</select></p>"
        "<p><label>Grund*</label>"
        '<textarea name="reason" maxlength="500" required></textarea></p>'
        '<p class="order-context-note">'
        "Die bisherige Zahlungsart und ihre Dokument-/Reminder-Fakten "
        "bleiben in der Historie erhalten.</p>"
        '<p><button type="submit">Zahlungsart ändern</button></p>'
        "</fieldset></form></details>"
    )


def _payment_correction_form(
    order: Order,
    payment: PaymentReminderView,
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext,
) -> str:
    if (
        order.cancelled_at is not None
        or not context.can("orders.payment.reminder")
        or (payment.paid_on is None and not payment.cash_received)
    ):
        return ""
    return (
        '<details class="order-payment-correction">'
        "<summary>Zahlungsstatus korrigieren</summary>"
        f'<form method="post" action="/order/{_e(order.order_id)}/payment-correction">'
        f"{forms.csrf_input}{forms.payment_correction_command_fields}<fieldset>"
        "<p>Die bisherige Zahlungsbestätigung bleibt in der Historie erhalten.</p>"
        "<p><label>Grund*</label>"
        '<textarea name="reason" maxlength="500" required></textarea></p>'
        '<p><button type="submit">Zahlungsstatus korrigieren</button></p>'
        "</fieldset></form></details>"
    )


def _payment_correction_history(payment: PaymentReminderView) -> str:
    if not payment.payment_corrections:
        return ""
    rows: list[str] = []
    for correction in payment.payment_corrections:
        previous = correction.previous_reminder
        previous_paid = (
            previous.paid_on.strftime("%d.%m.%Y")
            if previous.paid_on is not None
            else "Barzahlung erfasst"
        )
        rows.append(
            "<li>"
            f"<strong>Zahlungsbestätigung korrigiert</strong>"
            f" · {_e(correction.corrected_at.strftime('%d.%m.%Y · %H:%M'))}"
            f" · {_e(correction.actor_reference)}"
            f"<br>Vorher: {_e(previous_paid)}"
            f"<br>Grund: {_e(correction.reason)}"
            "</li>"
        )
    return (
        '<details class="order-payment-correction-history">'
        f"<summary>Zahlungskorrekturen ({len(rows)})</summary>"
        f"<ul>{''.join(rows)}</ul></details>"
    )


def _payment_method_history(payment: PaymentReminderView) -> str:
    if not payment.method_changes:
        return ""
    rows: list[str] = []
    for change in payment.method_changes:
        previous = change.previous_reminder
        old_facts: list[str] = []
        if previous.invoice_number:
            old_facts.append(f"Rechnung {previous.invoice_number}")
        if previous.sent_on is not None:
            old_facts.append(f"versendet {previous.sent_on.strftime('%d.%m.%Y')}")
        if previous.quittung_printed:
            old_facts.append("Quittung gedruckt")
        if change.retired_task_title:
            old_facts.append(f"Aufgabe beendet: {change.retired_task_title}")
        details = " · ".join(old_facts) if old_facts else "Keine Dokumentfakten"
        rows.append(
            "<li>"
            f"<strong>{_e(PAYMENT_METHOD_LABELS[change.from_method])} → "
            f"{_e(PAYMENT_METHOD_LABELS[change.to_method])}</strong>"
            f" · {_e(change.changed_at.strftime('%d.%m.%Y · %H:%M'))}"
            f" · {_e(change.actor_reference)}"
            f"<br>Grund: {_e(change.reason)}"
            f"<br>{_e(details)}"
            "</li>"
        )
    return (
        '<details class="order-payment-method-history">'
        f"<summary>Zahlungsarten-Historie ({len(rows)})</summary>"
        f"<ul>{''.join(rows)}</ul></details>"
    )


def _payment_card(
    order: Order,
    payment: PaymentReminderView,
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext,
) -> str:
    facts = [
        ("Zahlungsart", payment.payment_method_label),
        ("Reminder-Status", payment.payment_state_label),
    ]
    if payment.invoice_state_label is not None:
        facts.append(("Rechnung", payment.invoice_state_label))
    if payment.payment_method == "BAR_VOR_ORT":
        facts.append(
            (
                "Quittung",
                "Gedruckt" if payment.quittung_printed else "Noch nicht gedruckt",
            )
        )
    if payment.invoice_number:
        facts.append(("Rechnungsnummer", payment.invoice_number))
    if payment.sent_on is not None:
        facts.append(("Versendet am", payment.sent_on.strftime("%d.%m.%Y")))
    if payment.due_on is not None:
        facts.append(("Fällig am", payment.due_on.strftime("%d.%m.%Y")))
    if payment.paid_on is not None:
        facts.append(("Bezahlt am", payment.paid_on.strftime("%d.%m.%Y")))

    for label, timestamp, actor in (
        ("Rechnung erstellt", payment.invoice_created_at, payment.invoice_created_by),
        (
            "Rechnungsversand erfasst",
            payment.invoice_sent_recorded_at,
            payment.invoice_sent_recorded_by,
        ),
        (
            "Zahlungserinnerung",
            payment.payment_reminder_sent_at,
            payment.payment_reminder_sent_by,
        ),
        ("Mahnung", payment.mahnung_sent_at, payment.mahnung_sent_by),
        (
            "Quittung gedruckt",
            payment.quittung_printed_at,
            payment.quittung_printed_by,
        ),
        ("Zahlung erfasst", payment.paid_recorded_at, payment.paid_recorded_by),
    ):
        if timestamp is not None:
            facts.append(
                (
                    label,
                    f"{timestamp.strftime('%d.%m.%Y · %H:%M')} · {actor or 'unbekannt'}",
                )
            )

    next_step = payment.next_step or "Keine offene Zahlungsaufgabe."
    if payment.next_step_due_on is not None and payment.next_step is not None:
        next_step += f" · {payment.next_step_due_on.strftime('%d.%m.%Y')}"
    return (
        '<section class="order-card order-content-card order-payment-card">'
        '<div class="order-section-kicker">Separater Bereich</div>'
        "<h2>Zahlung</h2>"
        '<dl class="order-payment-facts">'
        + "".join(
            f"<div><dt>{_e(label)}</dt><dd>{_e(value)}</dd></div>"
            for label, value in facts
        )
        + "</dl>"
        '<div class="order-payment-next"><span>Nächste Zahlungsaufgabe</span>'
        f"<strong>{_e(next_step)}</strong></div>"
        + _payment_form(order, payment, forms, context=context)
        + _payment_method_change_form(order, payment, forms, context=context)
        + _payment_correction_form(order, payment, forms, context=context)
        + _payment_method_history(payment)
        + _payment_correction_history(payment)
        + "</section>"
    )


def _document_blocker_label(code: str) -> str:
    return _DOCUMENT_BLOCKER_LABELS.get(code, code)


def _document_warning_label(code: str) -> str:
    return _DOCUMENT_WARNING_LABELS.get(code, code)


def _confirmation_state_label(state: str) -> str:
    if state in _CONFIRMATION_STATE_LABELS:
        return _CONFIRMATION_STATE_LABELS[state]
    return _document_blocker_label(state)


def _confirmation_create_form(
    order: Order,
    confirmation: OrderConfirmationDocumentEligibility,
    forms: OrderDetailFormFields,
    live_preview: ConfirmationLivePreviewView,
    *,
    context: OfficePageContext,
    button_class: str | None = None,
) -> str:
    if not _confirmation_create_action_available(
        confirmation,
        live_preview,
        context=context,
    ):
        return ""
    class_attr = f' class="{_e(button_class)}"' if button_class else ""
    return (
        f'<form method="post" action="/order/{_e(order.order_id)}/confirmation-document">'
        f"{forms.csrf_input}{forms.confirmation_command_fields}"
        f'<button{class_attr} type="submit">Auftragsbestätigung erstellen</button>'
        "</form>"
    )


def _confirmation_card(
    order: Order,
    confirmation: OrderConfirmationDocumentEligibility,
    forms: OrderDetailFormFields,
    live_preview: ConfirmationLivePreviewView,
    *,
    compact: bool = False,
    show_create_action: bool = True,
    context: OfficePageContext,
) -> str:
    state_label = _confirmation_state_label(confirmation.state)
    facts: list[tuple[str, str]] = [("Status", state_label)]
    snapshot = confirmation.snapshot
    if snapshot is not None:
        facts.extend(
            [
                ("Referenz", snapshot.document_reference),
                ("Empfänger", snapshot.recipient_email_masked or "–"),
                ("Stand", f"Version {snapshot.effective_version_number}"),
                (
                    "Summe brutto",
                    f"{snapshot.gross_total_cents / 100:.2f} €".replace(".", ","),
                ),
                ("Erstellt", snapshot.created_at.strftime("%d.%m.%Y · %H:%M")),
            ]
        )
        if not compact:
            facts.insert(3, ("Hash", snapshot.document_hash_short))
    live_html = _live_preview_diagnostics(live_preview)
    actions: list[str] = []
    if show_create_action:
        create_form = _confirmation_create_form(
            order,
            confirmation,
            forms,
            live_preview,
            context=context,
        )
        if create_form:
            actions.append(create_form)
    if snapshot is not None:
        actions.append(
            f'<p><a class="order-action-link" '
            f'href="/order/{_e(order.order_id)}/confirmation-document/preview" '
            f'target="_blank" rel="noopener">Vorschau öffnen</a></p>'
        )
    return (
        '<section class="order-card order-content-card order-confirmation-card">'
        '<div class="order-section-kicker">Kundendokument</div>'
        "<h2>Auftragsbestätigung</h2>"
        '<dl class="order-payment-facts">'
        + "".join(
            f"<div><dt>{_e(label)}</dt><dd>{_e(value)}</dd></div>"
            for label, value in facts
        )
        + "</dl>"
        + live_html
        + "".join(actions)
        + "</section>"
    )


def _live_preview_diagnostics(live_preview: ConfirmationLivePreviewView) -> str:
    if live_preview.state == "unavailable":
        return (
            '<p class="order-context-note blocked">'
            "Live-Vorschau derzeit nicht verfügbar.</p>"
        )
    if live_preview.state == "parse_error":
        return (
            '<p class="order-context-note blocked">'
            "Live-Vorschau konnte nicht gelesen werden.</p>"
        )
    if live_preview.state == "not_found":
        return (
            '<p class="order-context-note blocked">'
            "Auftrag für Live-Vorschau nicht gefunden.</p>"
        )
    preview = live_preview.preview
    assert preview is not None
    parts: list[str] = []
    if preview.blockers:
        items = "".join(
            f"<li>{_e(_document_blocker_label(blocker.code))}</li>"
            for blocker in preview.blockers
        )
        parts.append(
            '<div class="order-blockers"><strong>Erstellung blockiert</strong>'
            f"<ul>{items}</ul></div>"
        )
    if preview.warnings:
        items = "".join(
            f"<li>{_e(_document_warning_label(code))}</li>" for code in preview.warnings
        )
        parts.append(
            '<div class="order-context-note"><strong>Hinweise</strong>'
            f"<ul>{items}</ul></div>"
        )
    if (
        preview.commercial_reference is not None
        and preview.gross_total_cents is not None
    ):
        parts.append(
            '<p class="order-context-note">'
            f"Vorschau brutto: "
            f"{_e(f'{preview.gross_total_cents / 100:.2f} €'.replace('.', ','))}"
            f" · {_e(preview.commercial_reference.variant_label)}</p>"
        )
    elif preview.recipient.name:
        parts.append(
            '<p class="order-context-note">'
            f"Empfänger (Vorschau): {_e(preview.recipient.name)}</p>"
        )
    return "".join(parts)


def _format_customer_address(address: CustomerAddress | None) -> str:
    if address is None:
        return "–"
    lines = [
        value
        for value in (
            (address.street or "").strip(),
            " ".join(
                part
                for part in (
                    (address.postal_code or "").strip(),
                    (address.city or "").strip(),
                )
                if part
            ),
            (address.country or "").strip(),
        )
        if value
    ]
    return "\n".join(lines) if lines else "–"


def _address_input_block(prefix: str, address: CustomerAddress | None) -> str:
    street = address.street if address is not None else ""
    postal = address.postal_code if address is not None else ""
    city = address.city if address is not None else ""
    country = address.country if address is not None else ""
    return (
        f'<p><label>Straße</label><input name="{prefix}_street" '
        f'value="{_e(street or "")}"></p>'
        f'<p><label>PLZ</label><input name="{prefix}_postal_code" '
        f'value="{_e(postal or "")}"></p>'
        f'<p><label>Ort</label><input name="{prefix}_city" '
        f'value="{_e(city or "")}"></p>'
        f'<p><label>Land</label><input name="{prefix}_country" '
        f'value="{_e(country or "")}"></p>'
    )


def _customer_addresses_form(
    order: Order,
    target_version: OrderVersion,
    forms: OrderDetailFormFields,
) -> str:
    delivery: CustomerAddress | None = None
    return (
        '<details class="order-edit"><summary>Ändern</summary>'
        '<div class="order-edit-body">'
        f'<form method="post" action="/order/{_e(order.order_id)}/delivery-address" '
        'onsubmit="return confirm('
        "'Die geänderte Lieferadresse legt einen neuen Auftragsstand an.'"
        ');">'
        f"{forms.csrf_input}{forms.delivery_address_command_fields}"
        '<input type="hidden" name="parent_order_version_id" '
        f'value="{_e(target_version.order_version_id)}">'
        "<fieldset>"
        + _address_input_block("delivery", delivery)
        + '<p><button type="submit">Lieferadresse speichern</button></p>'
        "</fieldset></form></div></details>"
    )


def render_customer_addresses_card(
    inquiry: Inquiry | None,
    order: Order,
    forms: OrderDetailFormFields,
    *,
    target_version: OrderVersion | None = None,
    editable: bool = True,
    context: OfficePageContext | None = None,
) -> str:
    """Show stored vs effective delivery addresses for confirmation context."""
    page_context = context or OfficePageContext()
    if inquiry is None:
        return (
            '<section class="order-card order-content-card order-addresses-card">'
            "<h2>Kundenadressen</h2>"
            '<p class="order-section-note">Keine Anfrage verknüpft.</p>'
            "</section>"
        )
    snapshot = inquiry.customer_snapshot
    mode = snapshot.delivery_address_mode if snapshot is not None else "UNKNOWN"
    invoice = snapshot.invoice_address if snapshot is not None else None
    stored_delivery = snapshot.delivery_address if snapshot is not None else None
    recipient = build_customer_document_recipient(inquiry)
    effective_delivery = recipient.delivery_address
    if mode == "SEPARATE":
        stored_label = _format_customer_address(stored_delivery)
    else:
        stored_label = _NO_SEPARATE_DELIVERY
    if mode == "UNKNOWN":
        effective_label = _NO_EFFECTIVE_DELIVERY
    else:
        effective_label = _format_customer_address(effective_delivery)
    facts = (
        f"<div><dt>Rechnungsadresse</dt>"
        f'<dd style="white-space:pre-line">{_e(_format_customer_address(invoice))}</dd></div>'
        f"<div><dt>Liefermodus</dt><dd>{_e(_DELIVERY_MODE_LABELS.get(mode, mode))}</dd></div>"
        f"<div><dt>Gespeicherte Lieferadresse</dt>"
        f'<dd style="white-space:pre-line">{_e(stored_label)}</dd></div>'
        f"<div><dt>Effektive Lieferadresse</dt>"
        f'<dd style="white-space:pre-line">{_e(effective_label)}</dd></div>'
    )
    form = (
        _customer_addresses_form(order, target_version, forms)
        if (
            editable
            and order.cancelled_at is None
            and target_version is not None
            and page_context.can("inquiries.view")
            and page_context.can("orders.version.create")
        )
        else ""
    )
    return (
        '<section class="order-card order-content-card order-addresses-card">'
        "<h2>Kundenadressen</h2>"
        f'<dl class="order-payment-facts">{facts}</dl>' + form + "</section>"
    )


def _fulfillment_mode_form(
    inquiry: Inquiry,
    order: Order,
    forms: OrderDetailFormFields,
) -> str:
    mode = inquiry.fulfillment_mode
    options = "".join(
        f'<option value="{_e(value)}"{" selected" if value == mode else ""}>'
        f"{_e(_FULFILLMENT_MODE_LABELS[value])}</option>"
        for value in FULFILLMENT_MODES
    )
    return (
        '<details class="order-edit"><summary>Auftragsart bearbeiten</summary>'
        '<div class="order-edit-body">'
        f'<form method="post" action="/inquiry/{_e(inquiry.inquiry_id)}/fulfillment-mode">'
        f"{forms.csrf_input}{forms.fulfillment_mode_command_fields}"
        f'<input type="hidden" name="return_order_id" value="{_e(order.order_id)}">'
        "<fieldset>"
        "<p><label>Auftragsart</label>"
        f'<select name="fulfillment_mode">{options}</select></p>'
        '<p><button type="submit">Auftragsart speichern</button></p>'
        "</fieldset></form></div></details>"
    )


def render_fulfillment_mode_card(
    inquiry: Inquiry | None,
    order: Order,
    forms: OrderDetailFormFields,
    *,
    editable: bool = True,
    context: OfficePageContext | None = None,
) -> str:
    """Auftragsart (Lieferung/Abholung) — never guessed, always explicit."""
    page_context = context or OfficePageContext()
    if inquiry is None:
        return (
            '<section class="order-card order-content-card order-fulfillment-card">'
            "<h2>Auftragsart</h2>"
            '<p class="order-section-note">Keine Anfrage verknüpft.</p>'
            "</section>"
        )
    label = _FULFILLMENT_MODE_LABELS.get(
        inquiry.fulfillment_mode, inquiry.fulfillment_mode
    )
    form = (
        _fulfillment_mode_form(inquiry, order, forms)
        if (
            editable
            and order.cancelled_at is None
            and page_context.can("inquiries.edit")
        )
        else ""
    )
    return (
        '<section class="order-card order-content-card order-fulfillment-card">'
        "<h2>Auftragsart</h2>"
        f'<dl class="order-payment-facts">'
        f"<div><dt>Auftragsart</dt><dd>{_e(label)}</dd></div></dl>"
        + form
        + "</section>"
    )


def render_confirmation_card(
    order: Order,
    confirmation: OrderConfirmationDocumentEligibility,
    forms: OrderDetailFormFields,
    live_preview: ConfirmationLivePreviewView,
    *,
    context: OfficePageContext | None = None,
) -> str:
    """Shared Auftragsbestätigung card for v2 and legacy Order Detail."""
    page_context = context or OfficePageContext()
    return _confirmation_card(
        order, confirmation, forms, live_preview, context=page_context
    )


def render_confirmation_outbound_card(
    order: Order,
    confirmation: OrderConfirmationDocumentEligibility,
    outbound: OutboundSendEligibility,
    forms: OrderDetailFormFields,
    *,
    operational_pause: Mapping[str, object] | None = None,
    context: OfficePageContext | None = None,
) -> str:
    """Fake-outbox test send card — never implies real customer delivery."""
    page_context = context or OfficePageContext()
    if not page_context.can("documents.send"):
        return ""
    pause_view = operational_pause or {"active": False}
    state_label = _OUTBOUND_STATE_LABELS.get(outbound.state, outbound.state)
    facts: list[tuple[str, str]] = [("Status", state_label)]
    summary = outbound.send_summary
    if summary is not None:
        facts.extend(
            [
                ("Empfänger", summary.recipient_email_masked),
                ("Transport", "Fake Outbox"),
                ("Payload-Hash", summary.payload_hash_short),
                (
                    "Protokolliert",
                    summary.accepted_at.replace("T", " · ")[:16],
                ),
            ]
        )
    actions: list[str] = []
    if pause_view.get("active"):
        actions.append(
            '<p class="order-context-note blocked">'
            "Testversand blockiert: Auftrag pausiert</p>"
        )
    elif (
        outbound.can_send
        and confirmation.snapshot is not None
        and page_context.can("documents.send")
    ):
        actions.append(
            '<p class="order-context-note">Es wird keine E-Mail an den Kunden gesendet.</p>'
        )
        actions.append(
            f'<form method="post" action="/order/{_e(order.order_id)}/confirmation-document/send">'
            f"{forms.csrf_input}{forms.send_command_fields}"
            f'<input type="hidden" name="document_snapshot_id" '
            f'value="{_e(confirmation.snapshot.document_snapshot_id)}">'
            '<button type="submit">Testversand erzeugen</button></form>'
        )
    if summary is not None:
        actions.append('<p class="order-context-note">Keine echte Zustellung.</p>')
        actions.append(
            f'<p><a class="order-action-link" '
            f'href="/order/{_e(order.order_id)}/confirmation-document/fake-outbox" '
            f'target="_blank" rel="noopener">Testnachricht ansehen</a></p>'
        )
    card = (
        '<section class="order-technical-card order-confirmation-outbound-card">'
        '<div class="order-section-kicker">Testversand</div>'
        "<h2>Fake Outbox</h2>"
        '<dl class="order-payment-facts">'
        + "".join(
            f"<div><dt>{_e(label)}</dt><dd>{_e(value)}</dd></div>"
            for label, value in facts
        )
        + "</dl>"
        + "".join(actions)
        + "</section>"
    )
    return (
        '<details class="order-technical"><summary>Technik / Test</summary>'
        f'<div class="order-technical-body">{card}</div></details>'
    )


def _planning_mode_select(selected: str) -> str:
    options = []
    for value in PLANNING_MODES:
        mark = " selected" if value == selected else ""
        options.append(
            f'<option value="{_e(value)}"{mark}>'
            f"{_e(_PLANNING_MODE_LABELS[value])}</option>"
        )
    return f'<select name="planning_mode">{"".join(options)}</select>'


def _version_change_form(
    order: Order,
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext,
) -> str:
    prefill = forms.version_change_prefill
    if prefill is None or not context.can("orders.version.create"):
        return ""
    return (
        '<details class="order-version-edit"><summary>Neuen Stand anlegen</summary>'
        "<p>Die Felder übernehmen den aktuellen Bearbeitungsstand. "
        "Speichern legt einen neuen unveränderlichen Stand an.</p>"
        '<p class="order-context-note">Die Änderung wird erst nach '
        "Küchendruck und Bestätigung wirksam.</p>"
        f'<form method="post" action="/order/{_e(order.order_id)}/version">'
        f"{forms.csrf_input}{forms.version_command_fields}"
        f'<input type="hidden" name="latest_version_number" '
        f'value="{_e(prefill.latest_version_number)}"><fieldset>'
        f'<p><label>Datum*</label><input type="date" name="event_date" '
        f'required value="{_e(prefill.event_date)}"></p>'
        f'<p><label>Zeitfenster</label><input name="time_window_text" '
        f'value="{_e(prefill.time_window_text)}"></p>'
        f'<p><label>Ort</label><input name="location_text" '
        f'value="{_e(prefill.location_text)}"></p>'
        f'<p><label>Gäste (ca.)</label><input name="guest_count_estimate" '
        f'inputmode="numeric" value="{_e(prefill.guest_count_estimate)}"></p>'
        f"<p><label>Planung</label>"
        f"{_planning_mode_select(prefill.planning_mode)}</p>"
        '<p><label>Änderungsgrund*</label><textarea name="change_reason" '
        'maxlength="1000" required></textarea></p>'
        '<p><button type="submit">Stand anlegen</button></p>'
        "</fieldset></form></details>"
    )


def _pause_reason_select(name: str = "reason_code") -> str:
    options = "".join(
        f'<option value="{_e(code)}">{_e(label)}</option>'
        for code, label in PAUSE_REASON_LABELS.items()
    )
    return f'<select name="{name}" required>{options}</select>'


def _resume_reason_select(name: str = "reason_code") -> str:
    options = "".join(
        f'<option value="{_e(code)}">{_e(label)}</option>'
        for code, label in _RESUME_REASON_LABELS.items()
    )
    return f'<select name="{name}" required>{options}</select>'


def _pause_reason_label(code: object) -> str:
    return pause_reason_label(code)


def render_operational_pause_card(
    order: Order,
    operational_pause: Mapping[str, object],
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext | None = None,
) -> str:
    """Shared pause/resume card for legacy and v2 Order Detail."""
    page_context = context or OfficePageContext()
    if order.cancelled_at is not None:
        return ""
    if operational_pause.get("active"):
        facts: list[tuple[str, str]] = [
            ("Grund", _pause_reason_label(operational_pause.get("reason_code"))),
        ]
        note = operational_pause.get("note")
        if note:
            facts.append(("Notiz", str(note)))
        paused_at = operational_pause.get("paused_at")
        if paused_at:
            facts.append(("Pausiert seit", str(paused_at).replace("T", " · ")[:16]))
        actor = operational_pause.get("actor_reference")
        if actor:
            facts.append(("Bearbeiter", str(actor)))
        resume_form = ""
        if page_context.can("orders.pause"):
            resume_form = (
                f'<form method="post" action="/order/{_e(order.order_id)}/resume">'
                f"{forms.csrf_input}{forms.resume_command_fields}"
                "<p><label>Fortsetzungsgrund</label>"
                f"{_resume_reason_select()}</p>"
                '<p><label>Notiz</label><textarea name="note" maxlength="2000"></textarea></p>'
                '<button type="submit">Pause aufheben</button>'
                "</form>"
            )
        return (
            '<section class="order-card order-content-card order-pause-card">'
            '<div class="order-paused-banner">Auftrag pausiert</div>'
            "<h2>Operative Pause</h2>"
            '<dl class="order-payment-facts">'
            + "".join(
                f"<div><dt>{_e(label)}</dt><dd>{_e(value)}</dd></div>"
                for label, value in facts
            )
            + "</dl>"
            + resume_form
            + "</section>"
        )
    if not page_context.can("orders.pause"):
        return ""
    return (
        '<section class="order-card order-content-card order-pause-card">'
        "<h2>Operative Pause</h2>"
        "<p>Der Auftrag bleibt sichtbar, blockiert aber die Versandfreigabe "
        "und den Testversand.</p>"
        f'<form method="post" action="/order/{_e(order.order_id)}/pause">'
        f"{forms.csrf_input}{forms.pause_command_fields}"
        "<p><label>Pausegrund</label>"
        f"{_pause_reason_select()}</p>"
        '<p><label>Notiz</label><textarea name="note" maxlength="2000"></textarea></p>'
        '<button type="submit">Auftrag pausieren</button>'
        "</form></section>"
    )


def _operational_pause_controls(
    order: Order,
    operational_pause: Mapping[str, object],
    forms: OrderDetailFormFields,
    *,
    context: OfficePageContext,
) -> str:
    controls = render_operational_pause_card(
        order, operational_pause, forms, context=context
    )
    return f'<div id="order-pause-controls">{controls}</div>' if controls else ""


def _secondary_actions(
    order: Order,
    forms: OrderDetailFormFields,
    *,
    operational_pause: Mapping[str, object],
    delete_confirmation_name: str,
    context: OfficePageContext,
) -> str:
    inquiry_link = (
        f'<a class="order-text-link" href="/inquiry/{_e(order.source_inquiry_id)}">'
        "Zugehörige Anfrage öffnen</a>"
    )
    delete_block = ""
    if context.can("orders.delete") and delete_confirmation_name:
        delete_block = (
            '<details class="order-danger"><summary>Auftrag dauerhaft löschen</summary>'
            "<p><strong>Nur für Test- oder versehentlich angelegte Aufträge.</strong> "
            "Diese Aktion kann nicht rückgängig gemacht werden. Die verknüpfte "
            "Anfrage und das Angebot bleiben erhalten.</p>"
            "<p>Zur Bestätigung exakt <strong>"
            f"{_e(delete_confirmation_name)}</strong> eingeben.</p>"
            f'<form method="post" action="/order/{_e(order.order_id)}/delete">'
            f"{forms.csrf_input}"
            '<p><label>Kunde / Firma</label><input name="confirmation_name" '
            'autocomplete="off" required></p>'
            '<button type="submit">Auftrag endgültig löschen</button>'
            "</form></details>"
        )
    if order.cancelled_at is not None:
        return (
            '<details class="order-lower-section order-more-actions">'
            "<summary>Weitere Aktionen</summary>"
            f'<div class="order-lower-body"><p>{inquiry_link}</p>'
            + delete_block
            + "</div></details>"
        )
    cancel_block = ""
    if context.can("orders.cancel"):
        cancel_block = (
            '<details class="order-danger"><summary>Auftrag stornieren</summary>'
            "<p>Dieser Schritt kann nicht rückgängig gemacht werden. Historie und "
            "Küchenzettel bleiben zur Einsicht erhalten.</p>"
            f'<form method="post" action="/order/{_e(order.order_id)}/cancel">'
            f"{forms.csrf_input}{forms.cancel_command_fields}"
            '<button type="submit">Auftrag endgültig stornieren</button>'
            "</form></details>"
        )
    return (
        '<details class="order-lower-section order-more-actions">'
        "<summary>Weitere Aktionen</summary>"
        f'<div class="order-lower-body"><p>{inquiry_link}</p>'
        + _version_change_form(order, forms, context=context)
        + _operational_pause_controls(order, operational_pause, forms, context=context)
        + cancel_block
        + delete_block
        + "</div></details>"
    )


def _event_card(target: OrderVersion | None) -> str:
    if target is None:
        content = '<p class="order-section-note">Nicht verfügbar.</p>'
    else:
        content = (
            '<dl class="order-facts-list">'
            f"<div><dt>Uhrzeit</dt><dd>{_e(target.time_window_text or 'Noch offen')}</dd></div>"
            f"<div><dt>Ort</dt><dd>{_e(target.location_text or 'Noch offen')}</dd></div>"
            f"<div><dt>Planung</dt><dd>{_e(_planning_label(target.planning_mode))}</dd></div>"
            f"<div><dt>Stand erstellt</dt><dd>{_e(_created_text(target))}</dd></div>"
            "</dl>"
        )
    return (
        '<section class="order-card order-content-card order-event-card">'
        "<h2>Veranstaltung</h2>"
        f"{content}</section>"
    )


def _customer_delivery_card(
    order: Order,
    target: OrderVersion | None,
    operational_data: OrderDetailOperationalData | None,
    source_inquiry: Inquiry | None,
    forms: OrderDetailFormFields,
    *,
    show_edit_action: bool = True,
    context: OfficePageContext,
) -> str:
    company = operational_data.company_name if operational_data is not None else None
    contact = operational_data.contact_name if operational_data is not None else None
    phone = operational_data.phone if operational_data is not None else None
    customer_lines = [value for value in (company, contact, phone) if value]
    customer_html = (
        "<br>".join(_e(value) for value in customer_lines)
        if customer_lines
        else '<span class="order-unavailable">Nicht verfügbar</span>'
    )
    address_lines = (
        operational_data.delivery_address_lines
        if operational_data is not None
        and operational_data.operational_context_available
        else ()
    )
    address_html = (
        "<br>".join(_e(line) for line in address_lines)
        if address_lines
        else '<span class="order-unavailable">Nicht verfügbar</span>'
    )
    fulfillment = (
        _FULFILLMENT_MODE_LABELS.get(
            source_inquiry.fulfillment_mode, source_inquiry.fulfillment_mode
        )
        if source_inquiry is not None
        else "Nicht verfügbar"
    )
    edit = (
        _customer_addresses_form(order, target, forms)
        if (
            show_edit_action
            and target is not None
            and order.cancelled_at is None
            and context.can("inquiries.view")
            and context.can("orders.version.create")
        )
        else ""
    )
    return (
        '<section class="order-card order-content-card order-customer-card">'
        "<h2>Kunde &amp; Lieferung</h2>"
        '<div class="order-customer-grid">'
        f'<div><span class="order-field-label">Kunde</span><p>{customer_html}</p></div>'
        f'<div><span class="order-field-label">Auftragsart</span><p>{_e(fulfillment)}</p></div>'
        '<div class="order-delivery-address">'
        '<span class="order-field-label">Lieferadresse</span>'
        f"<address>{address_html}</address>{edit}</div></div></section>"
    )


def _positions_card(operational_data: OrderDetailOperationalData | None) -> str:
    if operational_data is None or not operational_data.positions_available:
        content = '<p class="order-section-note">Bestellung nicht verfügbar.</p>'
    elif not operational_data.positions:
        content = '<p class="order-section-note">Keine Positionen vorhanden.</p>'
    else:
        rows = []
        for position in operational_data.positions:
            details = [
                value
                for value in (
                    position.description,
                    position.composition,
                    position.notes,
                )
                if value
            ]
            quantity = (
                f'<span class="order-position-quantity">{_e(position.quantity_display)}</span>'
                if position.quantity_display
                else ""
            )
            detail_html = f"<p>{_e(' · '.join(details))}</p>" if details else ""
            rows.append(
                '<li class="order-position-row">'
                f"<div><strong>{_e(position.name)}</strong>{detail_html}</div>"
                f"{quantity}</li>"
            )
        variant = (
            f'<p class="order-section-note">{_e(operational_data.variant_label)}</p>'
            if operational_data.variant_label
            else ""
        )
        content = f'{variant}<ul class="order-position-list">{"".join(rows)}</ul>'
    return (
        '<section class="order-card order-content-card order-positions-card">'
        f"<h2>Bestellung</h2>{content}</section>"
    )


def _changes_card(target: OrderVersion | None, ready: ReadyToSendEvaluation) -> str:
    items: list[str] = []
    if target is not None and target.change_reason:
        items.append(f"Änderung: {target.change_reason}")
    if target is not None and target.changed_fields:
        labels = ", ".join(
            _CHANGED_FIELD_LABELS.get(field, field) for field in target.changed_fields
        )
        items.append(f"Geändert: {labels}")
    if not ready.ready:
        items.extend(_ready_blocker_label(reason) for reason in ready.reasons)
    content = (
        "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>"
        if items
        else '<p class="order-section-note">Keine offenen Hinweise.</p>'
    )
    return (
        '<section class="order-card order-content-card order-changes-card">'
        f"<h2>Hinweise / Änderungen</h2>{content}</section>"
    )


def _status_card(state_title: str, state_description: str) -> str:
    return (
        '<section class="order-card order-content-card order-status-card">'
        "<h2>Status</h2>"
        f"<strong>{_e(state_title)}</strong><p>{_e(state_description)}</p></section>"
    )


def render_order_detail(
    order: Order,
    versions: Sequence[OrderVersion],
    ready: ReadyToSendEvaluation,
    payment: PaymentReminderView,
    next_action: Mapping[str, str] | None,
    confirmation: OrderConfirmationDocumentEligibility,
    outbound: OutboundSendEligibility,
    forms: OrderDetailFormFields,
    live_preview: ConfirmationLivePreviewView,
    *,
    source_inquiry: Inquiry | None = None,
    operational_data: OrderDetailOperationalData | None = None,
    operational_pause: Mapping[str, object] | None = None,
    versions_total_count: int,
    versions_truncated: bool,
    context: OfficePageContext | None = None,
) -> OrderDetailPage:
    """Render existing Order facts and actions without performing any reads."""
    page_context = context or OfficePageContext()

    pause_view = operational_pause or {"active": False}
    target = _target_version(order, versions)
    customer_label = "Kunde nicht verfügbar"
    delete_confirmation_name = ""
    if operational_data is not None:
        customer_label = (
            operational_data.company_name
            or operational_data.contact_name
            or customer_label
        )
        delete_confirmation_name = (
            operational_data.company_name or operational_data.contact_name or ""
        ).strip()
    title = f"Auftrag · {customer_label}"
    state_title, state_description = _state_copy(
        order,
        target,
        next_action,
        ready,
        confirmation,
        live_preview,
        source_inquiry,
        operational_data,
        pause_view,
    )
    if _kitchen_print_waiting(target, next_action, forms):
        state_title = "Druckauftrag gesendet"
        state_description = "Warte auf die Druckbestätigung der Küche."
    delivery_address_promoted = (
        order.cancelled_at is None
        and not pause_view.get("active")
        and target is not None
        and not _requires_fulfillment_choice(source_inquiry)
        and _requires_delivery_address(source_inquiry, operational_data)
    )
    document_creation_promoted = (
        order.cancelled_at is None
        and not pause_view.get("active")
        and target is not None
        and not _requires_fulfillment_choice(source_inquiry)
        and not _requires_delivery_address(source_inquiry, operational_data)
        and next_action is None
        and ready.ready
        and _confirmation_create_action_available(
            confirmation,
            live_preview,
            context=page_context,
        )
    )
    truncation_warning = (
        '<div class="order-notice blocked"><strong>Unvollständige Ansicht:</strong> '
        f"Es werden {len(versions)} von {_e(versions_total_count)} Auftragsständen "
        "angezeigt.</div>"
        if versions_truncated
        else ""
    )
    if target is None:
        meta = "Veranstaltungsdaten nicht verfügbar"
        stand_badge = ""
    else:
        guests = (
            f"{target.guest_count_estimate} Gäste"
            if target.guest_count_estimate is not None
            else "Gästezahl offen"
        )
        meta = f"{_date_text(target)} · {guests}"
        stand_badge = (
            f'<span class="order-header-badge">Stand {_e(target.version_number)}</span>'
        )
    status_badge = (
        "Storniert"
        if order.cancelled_at is not None
        else "Pausiert"
        if pause_view.get("active")
        else state_title
    )
    technical = render_confirmation_outbound_card(
        order,
        confirmation,
        outbound,
        forms,
        operational_pause=pause_view,
        context=page_context,
    )
    body = (
        '<a class="order-back" href="/auftraege">← Zurück zu den Aufträgen</a>'
        + '<header class="order-header"><div class="order-header-main">'
        f"<h1>{_e(title)}</h1><p>{_e(meta)}</p></div>"
        '<div class="order-header-badges">'
        f'<span class="order-header-badge status">{_e(status_badge)}</span>'
        f"{stand_badge}</div></header>"
        + _primary_action(
            order,
            target,
            next_action,
            forms,
            ready=ready,
            confirmation=confirmation,
            live_preview=live_preview,
            source_inquiry=source_inquiry,
            operational_data=operational_data,
            operational_pause=pause_view,
            context=page_context,
        )
        + truncation_warning
        + _stale_print_notice(order, versions)
        + '<div class="order-work-layout"><div class="order-main-stack">'
        + _event_card(target)
        + _customer_delivery_card(
            order,
            target,
            operational_data,
            source_inquiry,
            forms,
            show_edit_action=not delivery_address_promoted,
            context=page_context,
        )
        + _positions_card(operational_data)
        + _changes_card(target, ready)
        + '</div><aside class="order-sidebar">'
        + _status_card(state_title, state_description)
        + _confirmation_card(
            order,
            confirmation,
            forms,
            live_preview,
            compact=True,
            show_create_action=not document_creation_promoted,
            context=page_context,
        )
        + _payment_card(order, payment, forms, context=page_context)
        + "</aside></div>"
        + '<div class="order-lower-sections">'
        + _version_history(order, versions, forms, context=page_context)
        + _secondary_actions(
            order,
            forms,
            operational_pause=pause_view,
            delete_confirmation_name=delete_confirmation_name,
            context=page_context,
        )
        + technical
        + "</div>"
    )
    return OrderDetailPage(title=title, body=body)

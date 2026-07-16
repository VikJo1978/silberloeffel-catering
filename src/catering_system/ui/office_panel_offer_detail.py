"""Angebot detail presentation — commercial history and lifecycle actions (5B-3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from zoneinfo import ZoneInfo

from catering_system.domain.offer import ACCEPTANCE_CHANNELS, SENT_CHANNELS
from catering_system.ui.office_api_views import offer_state_label
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
    default_datetime_local_berlin,
)

_BERLIN = ZoneInfo("Europe/Berlin")
_PLANNING_LABELS = {
    "caterer_suggestion": "Vorschlag durch Silberlöffel",
    "self_select": "Selbstauswahl",
}
_SENT_CHANNEL_LABELS = {
    "email": "E-Mail",
    "postal": "Post",
    "in_person": "Persönlich",
    "other": "Sonstiges",
}
_ACCEPTANCE_CHANNEL_LABELS = {
    "email": "E-Mail",
    "phone": "Telefon",
    "signed_document": "Unterschriebenes Dokument",
    "in_person": "Persönlich",
    "other": "Sonstiges",
}


@dataclass(frozen=True)
class OfferDetailFormFields:
    """Trusted hidden fields produced by the existing Office Panel helpers."""

    csrf_input: str
    command_fields: str


def _long_date(raw: str) -> str:
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        return raw
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


def _history_date(raw: str) -> str:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    local = value.astimezone(_BERLIN)
    return f"{local.day:02d}.{local.month:02d}"


def _surface_version(detail: dict[str, object]) -> dict[str, object]:
    versions = cast(list[dict[str, object]], detail["versions"])
    commercial = str(detail["commercial_state"])
    for version in reversed(versions):
        if str(version["state"]) == commercial:
            return version
    return versions[-1]


def _select_options(
    values: tuple[str, ...],
    labels: dict[str, str],
    *,
    selected: str | None = None,
) -> str:
    options = []
    for value in values:
        mark = ' selected' if value == selected else ""
        options.append(
            f'<option value="{_e(value)}"{mark}>{_e(labels.get(value, value))}</option>'
        )
    return "".join(options)


def _mark_sent_form(offer_id: str, *, forms: OfferDetailFormFields) -> str:
    default_at = default_datetime_local_berlin()
    return (
        '<section class="offer-detail-section offer-action-section">'
        "<h2>Als gesendet markieren</h2>"
        f'<form method="post" action="/offer/{_e(offer_id)}/mark-sent">'
        f"{forms.csrf_input}{forms.command_fields}"
        "<fieldset>"
        f'<label>Versandzeitpunkt <input type="datetime-local" name="sent_at" '
        f'value="{_e(default_at)}" required></label>'
        f'<label>Kanal <select name="channel" required>'
        f"{_select_options(SENT_CHANNELS, _SENT_CHANNEL_LABELS)}"
        "</select></label>"
        '<label>Empfänger <input name="recipient_reference" required '
        'maxlength="500" placeholder="kunde@example.invalid"></label>'
        '<label>Nachweis / Referenz <input name="evidence_reference" required '
        'maxlength="1000" placeholder="E-Mail vom 16.07.2026"></label>'
        "</fieldset>"
        '<button type="submit">Als gesendet markieren</button>'
        "</form></section>"
    )


def _record_acceptance_form(
    offer_id: str,
    variants: list[dict[str, object]],
    *,
    forms: OfferDetailFormFields,
) -> str:
    default_at = default_datetime_local_berlin()
    variant_options = "".join(
        f'<option value="{_e(str(variant["variant_id"]))}">'
        f'{_e(str(variant["name"]))}</option>'
        for variant in variants
    )
    if not variant_options:
        variant_options = '<option value="">Keine Variante</option>'
    return (
        '<section class="offer-detail-section offer-action-section">'
        "<h2>Annahme erfassen</h2>"
        f'<form method="post" action="/offer/{_e(offer_id)}/record-acceptance">'
        f"{forms.csrf_input}{forms.command_fields}"
        "<fieldset>"
        f'<label>Angenommene Variante <select name="accepted_variant_id" required>'
        f"{variant_options}"
        "</select></label>"
        f'<label>Annahmezeitpunkt <input type="datetime-local" name="accepted_at" '
        f'value="{_e(default_at)}" required></label>'
        f'<label>Kanal <select name="channel" required>'
        f"{_select_options(ACCEPTANCE_CHANNELS, _ACCEPTANCE_CHANNEL_LABELS)}"
        "</select></label>"
        '<label>Nachweis / Referenz <input name="evidence_reference" required '
        'maxlength="1000" placeholder="Telefonische Bestätigung"></label>'
        '<label>Notiz (optional) <textarea name="note" rows="3" maxlength="20000">'
        "</textarea></label>"
        "</fieldset>"
        '<button type="submit">Annahme erfassen</button>'
        "</form></section>"
    )


def _convert_form(
    offer_id: str,
    *,
    accepted_variant_id: str,
    acceptance_id: str,
    forms: OfferDetailFormFields,
) -> str:
    return (
        '<section class="offer-detail-section offer-action-section">'
        "<h2>In Auftrag umwandeln</h2>"
        "<p>Das angenommene Angebot wird in einen Auftrag überführt.</p>"
        f'<form method="post" action="/offer/{_e(offer_id)}/convert" '
        'onsubmit="return confirm('
        "'Das angenommene Angebot wird jetzt in einen Auftrag umgewandelt.'"
        ');">'
        f"{forms.csrf_input}{forms.command_fields}"
        f'<input type="hidden" name="accepted_variant_id" value="{_e(accepted_variant_id)}">'
        f'<input type="hidden" name="acceptance_id" value="{_e(acceptance_id)}">'
        '<button type="submit">In Auftrag umwandeln</button>'
        "</form></section>"
    )


def render_offer_detail(
    detail: dict[str, object],
    *,
    context: OfficePageContext,
    forms: OfferDetailFormFields,
) -> str:
    offer_id = str(detail["offer_id"])
    inquiry_id = str(detail["inquiry_id"])
    state = str(detail["commercial_state"])
    surface = _surface_version(detail)
    guest_count = surface.get("guest_count")
    guest_text = (
        str(guest_count) if guest_count is not None else "noch offen"
    )
    planning = _PLANNING_LABELS.get(
        str(surface.get("planning_mode", "")), str(surface.get("planning_mode", "–"))
    )
    variants = cast(list[dict[str, object]], surface["variants"])
    variant_rows = "".join(
        f"<li>{_e(str(variant['name']))}</li>" for variant in variants
    ) or "<li>Keine Varianten</li>"
    history_rows = "".join(
        f"<li><span>{_e(_history_date(str(entry['at'])))}</span> "
        f"{_e(str(entry['label']))}</li>"
        for entry in cast(list[dict[str, object]], detail["history"])
    ) or "<li>Noch keine Historie</li>"
    order_id = detail.get("order_id")
    order_link = (
        f'<p><a href="/order/{_e(str(order_id))}">Auftrag öffnen</a></p>'
        if order_id is not None
        else ""
    )
    action_section = ""
    if state == "Prepared":
        action_section = _mark_sent_form(offer_id, forms=forms)
    elif state == "Sent":
        action_section = _record_acceptance_form(
            offer_id, variants, forms=forms
        )
    elif state == "Accepted":
        acceptance_id = detail.get("acceptance_id")
        acceptance = cast(dict[str, object] | None, detail.get("acceptance"))
        if (
            isinstance(acceptance_id, str)
            and acceptance is not None
            and acceptance.get("accepted_variant_id") is not None
        ):
            action_section = _convert_form(
                offer_id,
                accepted_variant_id=str(acceptance["accepted_variant_id"]),
                acceptance_id=acceptance_id,
                forms=forms,
            )
    body = (
        f'<p class="subtitle">Angebot {_e(offer_id[:8])}</p>'
        + action_section
        + '<section class="offer-detail-section">'
        "<h2>Status</h2>"
        f"<p><strong>{_e(offer_state_label(state))}</strong></p>"  # type: ignore[arg-type]
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Veranstaltung</h2>"
        f"<p><span>Datum</span><strong>{_e(_long_date(str(surface['event_date'])))}</strong></p>"
        f"<p><span>Ort</span><strong>{_e(str(surface['location_text']))}</strong></p>"
        f"<p><span>Gäste</span><strong>{_e(guest_text)}</strong></p>"
        f"<p><span>Zeitfenster</span><strong>{_e(str(surface['time_window_text']))}</strong></p>"
        f"<p><span>Planung</span><strong>{_e(planning)}</strong></p>"
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Angebotsvarianten</h2>"
        f'<ul class="offer-variant-list">{variant_rows}</ul>'
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Historie</h2>"
        f'<ul class="offer-history-list">{history_rows}</ul>'
        "</section>"
        + order_link
        + f'<p><a href="/inquiry/{_e(inquiry_id)}">Anfrage öffnen</a></p>'
        + '<p><a href="/angebote">← Zurück zu Angeboten</a></p>'
    )
    return _page(
        "Angebot",
        body,
        active_section="inquiries",
        context=context,
    )

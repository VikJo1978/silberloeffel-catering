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
    return f"{local.day:02d}.{local.month:02d}.{local.year}"


def _surface_version(detail: dict[str, object]) -> dict[str, object]:
    versions = cast(list[dict[str, object]], detail["versions"])
    commercial = str(detail["commercial_state"])
    current_id = str(detail["offer_version_id"])
    for version in reversed(versions):
        if str(version.get("offer_version_id", "")) == current_id:
            return version
    for version in reversed(versions):
        if str(version["state"]) == commercial:
            return version
    return versions[-1]


def surface_version_id(detail: dict[str, object]) -> str:
    """Public wrapper: the OfferVersion id actually displayed for this
    detail (same resolution render_offer_detail uses internally) — needed
    by the caller before rendering, to decide whether a PDF download link
    exists for exactly the version about to be shown."""
    return str(_surface_version(detail).get("offer_version_id", ""))


def _version_list(detail: dict[str, object]) -> str:
    versions = cast(list[dict[str, object]], detail["versions"])
    current_id = str(detail["offer_version_id"])
    rows: list[str] = []
    for version in sorted(
        versions, key=lambda item: int(cast(int, item["version"])), reverse=True
    ):
        number = int(cast(int, version["version"]))
        state = str(version["state"])
        state_label = offer_state_label(state)  # type: ignore[arg-type]
        aktuell = ""
        if str(version.get("offer_version_id", "")) == current_id:
            aktuell = '<p class="offer-version-current">✓ Aktuell</p>'
        sent_at = version.get("sent_at")
        sent_line = ""
        if isinstance(sent_at, str) and sent_at:
            sent_line = f"<p><span>Gesendet</span><strong>{_e(_history_date(sent_at))}</strong></p>"
        rows.append(
            '<li class="offer-version-item">'
            f"<h3>Version {number}</h3>"
            f"<p><span>Status</span><strong>{_e(state_label)}</strong></p>"
            f"{aktuell}{sent_line}"
            "</li>"
        )
    return (
        '<section class="offer-detail-section">'
        "<h2>Angebotsversionen</h2>"
        f'<ul class="offer-version-list">{"".join(rows)}</ul>'
        "</section>"
    )


def _allergen_block(labels: object, *, unknown: bool = False) -> str:
    if unknown:
        return "<p><strong>Allergene:</strong> nicht bekannt</p>"
    if isinstance(labels, list) and labels:
        items = "".join(f"<li>{_e(str(label))}</li>" for label in labels)
        return f"<p><strong>Allergene:</strong></p><ul>{items}</ul>"
    return "<p><strong>Allergene:</strong> keine deklarierten Allergene</p>"


def _position_rows(variants: list[dict[str, object]]) -> str:
    rows: list[str] = []
    for variant in variants:
        positions = variant.get("positions")
        if not isinstance(positions, list):
            continue
        for position in positions:
            if not isinstance(position, dict):
                continue
            name = _e(str(position.get("name", "Position")))
            unit_cents = position.get("unit_net_cents")
            unit_text = (
                f"{int(unit_cents) / 100:.2f} €" if isinstance(unit_cents, int) else "–"
            )
            description = position.get("description")
            description_html = (
                f"<p>{_e(str(description))}</p>"
                if isinstance(description, str) and description
                else ""
            )
            composition = position.get("composition")
            composition_html = (
                f"<p><strong>Zusammensetzung:</strong> {_e(str(composition))}</p>"
                if isinstance(composition, str) and composition
                else ""
            )
            allergen_html = _allergen_block(
                position.get("allergen_labels"),
                unknown=bool(position.get("allergens_unknown")),
            )
            rows.append(
                "<li>"
                f"<strong>{name}</strong> "
                f"<span>({_e(unit_text)} netto / Einheit)</span>"
                f"{description_html}"
                f"{composition_html}"
                f"{allergen_html}"
                "</li>"
            )
    return "".join(rows) or "<li>Keine Positionen</li>"


_BUDGET_TAX_BASIS_LABELS = {"GROSS": "brutto", "NET": "netto"}
_BUDGET_COST_SCOPE_LABELS = {
    "FULL_OFFER": "mit allen Kosten",
    "POSITIONS_ONLY": "nur Positionen",
}


def _budget_cents(cents: object) -> str:
    if not isinstance(cents, int) or isinstance(cents, bool):
        return "–"
    return f"{cents / 100:.2f} €".replace(".", ",")


def _budget_block(surface: dict[str, object]) -> str:
    """OFFER_BUDGET_DEFINITION_V1 — compact internal-only planning block.

    Office Panel only, never the customer document. Omitted entirely (no
    empty section) when this OfferVersion has no budget_definition — covers
    both "operator never enabled budget tracking" and "Offer predates this
    feature" the same way.
    """
    budget = surface.get("budget_definition")
    if not isinstance(budget, dict):
        return ""
    per_person = budget.get("type") == "PER_PERSON"
    suffix = " / Person" if per_person else ""
    amount_line = f"<p><span>Budget</span><strong>{_e(_budget_cents(budget.get('amount_cents')))}{suffix}</strong></p>"
    basis_label = _BUDGET_TAX_BASIS_LABELS.get(str(budget.get("tax_basis")), "–")
    scope_label = _BUDGET_COST_SCOPE_LABELS.get(str(budget.get("cost_scope")), "–")
    basis_line = f"<p><span>Basis</span><strong>{_e(basis_label)} · {_e(scope_label)}</strong></p>"
    comparison = budget.get("comparison_amount_cents")
    if comparison is None:
        comparison_line = (
            "<p><span>Aktuell</span><strong>Gästezahl noch offen</strong></p>"
        )
        remaining_line = ""
    else:
        comparison_line = f"<p><span>Aktuell</span><strong>{_e(_budget_cents(comparison))}{suffix}</strong></p>"
        remaining = budget.get("remaining_cents")
        over = bool(budget.get("over"))
        remaining_abs = abs(remaining) if isinstance(remaining, int) else None
        remaining_label = "Überschritten" if over else "Verfügbar"
        remaining_line = (
            f"<p><span>{remaining_label}</span>"
            f"<strong>{_e(_budget_cents(remaining_abs))}{suffix}</strong></p>"
        )
    return (
        '<section class="offer-detail-section offer-budget-section">'
        "<h2>Budget (intern)</h2>"
        f"{amount_line}{basis_line}{comparison_line}{remaining_line}"
        "</section>"
    )


def _select_options(
    values: tuple[str, ...],
    labels: dict[str, str],
    *,
    selected: str | None = None,
) -> str:
    options = []
    for value in values:
        mark = " selected" if value == selected else ""
        options.append(
            f'<option value="{_e(value)}"{mark}>{_e(labels.get(value, value))}</option>'
        )
    return "".join(options)


def _mark_sent_form(
    offer_id: str, *, forms: OfferDetailFormFields, context: OfficePageContext
) -> str:
    if not context.can("offers.send"):
        return ""
    default_at = default_datetime_local_berlin()
    return (
        '<section class="offer-detail-section offer-action-section">'
        "<h2>Als gesendet markieren</h2>"
        f'<form method="post" action="/offer/{_e(offer_id)}/mark-sent">'
        f"{forms.csrf_input}{forms.command_fields}"
        "<fieldset>"
        f'<label>Versandzeitpunkt <input type="datetime-local" name="sent_at" '
        f'step="1" value="{_e(default_at)}" required></label>'
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
    context: OfficePageContext,
) -> str:
    if not context.can("offers.status.change"):
        return ""
    default_at = default_datetime_local_berlin()
    variant_options = "".join(
        f'<option value="{_e(str(variant["variant_id"]))}">'
        f"{_e(str(variant['name']))}</option>"
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
        f'step="1" value="{_e(default_at)}" required></label>'
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


def _record_rejection_form(
    offer_id: str, *, forms: OfferDetailFormFields, context: OfficePageContext
) -> str:
    if not context.can("offers.status.change"):
        return ""
    default_at = default_datetime_local_berlin()
    return (
        '<section class="offer-detail-section offer-action-section">'
        "<h2>Kunde lehnt ab</h2>"
        f'<form method="post" action="/offer/{_e(offer_id)}/record-rejection">'
        f"{forms.csrf_input}{forms.command_fields}"
        "<fieldset>"
        f'<label>Ablehnungszeitpunkt <input type="datetime-local" name="rejected_at" '
        f'step="1" value="{_e(default_at)}" required></label>'
        '<label>Kommentar / Nachweis (optional) <input name="evidence_reference" '
        'maxlength="1000" placeholder="Telefonische Absage"></label>'
        "</fieldset>"
        '<button type="submit">Kunde lehnt ab</button>'
        "</form></section>"
    )


def _record_withdrawal_form(
    offer_id: str, *, forms: OfferDetailFormFields, context: OfficePageContext
) -> str:
    if not context.can("offers.status.change"):
        return ""
    return (
        '<section class="offer-detail-section offer-action-section">'
        "<h2>Angebot zurückziehen</h2>"
        f'<form method="post" action="/offer/{_e(offer_id)}/record-withdrawal">'
        f"{forms.csrf_input}{forms.command_fields}"
        "<fieldset>"
        '<label>Grund (optional) <textarea name="reason" rows="3" maxlength="20000">'
        "</textarea></label>"
        "</fieldset>"
        '<button type="submit">Angebot zurückziehen</button>'
        "</form></section>"
    )


def _prepare_next_version_cta(
    *, revision_prefill_url: str | None, context: OfficePageContext
) -> str:
    if not context.can("offers.version.create"):
        return ""
    if not revision_prefill_url:
        return (
            '<section class="offer-detail-section offer-action-section">'
            "<h2>Neue Version vorbereiten</h2>"
            "<p>Eine neue Angebotsversion wird im Angebots-Editor vorbereitet.</p>"
            "</section>"
        )
    return (
        '<section class="offer-detail-section offer-action-section">'
        "<h2>Neue Version vorbereiten</h2>"
        "<p>Eine neue Angebotsversion wird im Angebots-Editor vorbereitet und "
        "anschließend als nächste Version übernommen.</p>"
        f'<p><a class="offer-revision-link" href="{_e(revision_prefill_url)}">'
        "Neue Version vorbereiten</a></p>"
        "</section>"
    )


def _sent_offer_actions(
    offer_id: str,
    variants: list[dict[str, object]],
    *,
    forms: OfferDetailFormFields,
    revision_prefill_url: str | None = None,
    context: OfficePageContext,
) -> str:
    return (
        _record_acceptance_form(offer_id, variants, forms=forms, context=context)
        + _record_rejection_form(offer_id, forms=forms, context=context)
        + _record_withdrawal_form(offer_id, forms=forms, context=context)
        + _prepare_next_version_cta(
            revision_prefill_url=revision_prefill_url, context=context
        )
    )


def _convert_form(
    offer_id: str,
    *,
    accepted_variant_id: str,
    acceptance_id: str,
    forms: OfferDetailFormFields,
    context: OfficePageContext,
) -> str:
    if not (context.can("offers.view") and context.can("orders.version.create")):
        return ""
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
    revision_prefill_url: str | None = None,
    pdf_download_url: str | None = None,
) -> str:
    offer_id = str(detail["offer_id"])
    inquiry_id = str(detail["inquiry_id"])
    state = str(detail["commercial_state"])
    surface = _surface_version(detail)
    guest_count = surface.get("guest_count")
    guest_text = str(guest_count) if guest_count is not None else "noch offen"
    planning = _PLANNING_LABELS.get(
        str(surface.get("planning_mode", "")), str(surface.get("planning_mode", "–"))
    )
    variants = cast(list[dict[str, object]], surface["variants"])
    variant_rows = (
        "".join(f"<li>{_e(str(variant['name']))}</li>" for variant in variants)
        or "<li>Keine Varianten</li>"
    )
    history_rows = (
        "".join(
            f"<li><span>{_e(_history_date(str(entry['at'])))}</span> "
            f"<strong>{_e(str(entry['label']))}</strong></li>"
            for entry in cast(list[dict[str, object]], detail["history"])
        )
        or "<li>Noch keine Historie</li>"
    )
    order_id = detail.get("order_id")
    order_link = (
        f'<p><a href="/order/{_e(str(order_id))}">Auftrag öffnen</a></p>'
        if order_id is not None
        else ""
    )
    action_section = ""
    if state == "Prepared":
        action_section = _mark_sent_form(offer_id, forms=forms, context=context)
    elif state == "Sent":
        action_section = _sent_offer_actions(
            offer_id,
            variants,
            forms=forms,
            revision_prefill_url=revision_prefill_url,
            context=context,
        )
    elif state in ("Expired", "Rejected", "Withdrawn"):
        action_section = _prepare_next_version_cta(
            revision_prefill_url=revision_prefill_url, context=context
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
                context=context,
            )
    pdf_link = (
        f'<p><a href="{_e(pdf_download_url)}">PDF herunterladen</a></p>'
        if pdf_download_url is not None and context.can("offers.pdf.generate")
        else ""
    )
    body = (
        f'<p class="subtitle">Angebot {_e(offer_id[:8])}</p>'
        + pdf_link
        + action_section
        + '<section class="offer-detail-section">'
        "<h2>Status</h2>"
        f"<p><strong>{_e(offer_state_label(state))}</strong></p>"  # type: ignore[arg-type]
        "</section>" + _version_list(detail) + '<section class="offer-detail-section">'
        "<h2>Veranstaltung</h2>"
        f"<p><span>Datum</span><strong>{_e(_long_date(str(surface['event_date'])))}</strong></p>"
        f"<p><span>Ort</span><strong>{_e(str(surface['location_text']))}</strong></p>"
        f"<p><span>Gäste</span><strong>{_e(guest_text)}</strong></p>"
        f"<p><span>Zeitfenster</span><strong>{_e(str(surface['time_window_text']))}</strong></p>"
        f"<p><span>Planung</span><strong>{_e(planning)}</strong></p>"
        "</section>" + _budget_block(surface) + '<section class="offer-detail-section">'
        "<h2>Positionen (Snapshot)</h2>"
        f'<ul class="offer-position-list">{_position_rows(variants)}</ul>'
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Angebotsvarianten</h2>"
        f'<ul class="offer-variant-list">{variant_rows}</ul>'
        "</section>"
        '<section class="offer-detail-section">'
        "<h2>Angebotshistorie</h2>"
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

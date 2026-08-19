"""Guided Angebot detail presentation for the Office Panel."""

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

_OFFER_DETAIL_STYLE = """
<style>
.offer-guided {
  max-width: 1120px;
  margin: 0 auto;
}
.offer-guided h1,
.offer-guided h2,
.offer-guided h3,
.offer-guided p { overflow-wrap: anywhere; }
.offer-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin: 0 0 22px;
  padding: 24px 26px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.offer-eyebrow {
  margin: 0 0 5px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.offer-hero h1 {
  margin: 0;
  font-size: clamp(28px, 3vw, 38px);
  line-height: 1.12;
  letter-spacing: -.025em;
}
.offer-hero-meta { margin: 8px 0 0; color: var(--muted); }
.offer-status-badge {
  flex: 0 0 auto;
  padding: 7px 11px;
  border-radius: 999px;
  color: var(--accent-deep);
  background: var(--accent-soft);
  font-size: 12px;
  font-weight: 800;
}
.offer-next-step,
.offer-card,
.offer-secondary-panel {
  margin: 0 0 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.offer-next-step {
  padding: 22px 24px;
  border-color: #d7e3da;
  background: #f2f6f3;
}
.offer-next-label {
  margin: 0 0 4px;
  color: var(--accent-deep);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.offer-next-step h2,
.offer-card h2 { margin: 0 0 8px; }
.offer-next-copy { margin: 0 0 16px; color: var(--muted); }
.offer-card { padding: 22px 24px; }
.offer-facts {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.offer-fact {
  min-width: 0;
  padding: 13px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--canvas);
}
.offer-fact span {
  display: block;
  margin-bottom: 3px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.offer-fact strong { display: block; font-size: 14px; }
.offer-form { margin: 0; }
.offer-form fieldset {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin: 0 0 16px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.offer-form label {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: #3c4640;
  font-size: 13px;
  font-weight: 700;
}
.offer-form label.offer-form-wide { grid-column: 1 / -1; }
.offer-form input,
.offer-form select,
.offer-form textarea { width: 100%; min-width: 0; }
.offer-form textarea { resize: vertical; }
.offer-primary-button,
.offer-guided button { min-height: 42px; }
.offer-secondary-actions {
  margin: 0 0 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.offer-secondary-actions > summary,
.offer-secondary-panel > summary,
.offer-position-detail > summary {
  cursor: pointer;
  list-style: none;
}
.offer-secondary-actions > summary::-webkit-details-marker,
.offer-secondary-panel > summary::-webkit-details-marker,
.offer-position-detail > summary::-webkit-details-marker { display: none; }
.offer-secondary-actions > summary,
.offer-secondary-panel > summary {
  padding: 17px 20px;
  color: var(--accent-deep);
  font-weight: 800;
}
.offer-secondary-actions > summary::after,
.offer-secondary-panel > summary::after,
.offer-position-detail > summary::after {
  content: "＋";
  float: right;
  color: var(--muted);
}
.offer-secondary-actions[open] > summary::after,
.offer-secondary-panel[open] > summary::after,
.offer-position-detail[open] > summary::after { content: "−"; }
.offer-secondary-content {
  display: grid;
  gap: 14px;
  padding: 0 20px 20px;
}
.offer-secondary-content .offer-action-section {
  margin: 0;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--canvas);
}
.offer-secondary-content .offer-action-section h2 {
  margin: 0 0 10px;
  font-size: 16px;
}
.offer-variant-grid {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}
.offer-variant-card {
  padding: 15px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--canvas);
}
.offer-variant-card h3 { margin: 0; font-size: 16px; }
.offer-variant-card p { margin: 5px 0 0; color: var(--muted); }
.offer-position-list {
  display: grid;
  gap: 10px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}
.offer-position-detail {
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--surface);
}
.offer-position-detail > summary { padding: 13px 15px; font-weight: 750; }
.offer-position-detail > summary span {
  color: var(--muted);
  font-weight: 550;
}
.offer-position-detail-body {
  padding: 0 15px 14px;
  color: #303732;
}
.offer-position-detail-body > :first-child { margin-top: 0; }
.offer-version-list,
.offer-history-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.offer-version-item,
.offer-history-list li {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--canvas);
}
.offer-version-item h3 { margin: 0 0 6px; font-size: 15px; }
.offer-version-item p { margin: 3px 0; }
.offer-version-item p span { color: var(--muted); margin-right: 6px; }
.offer-version-current { color: var(--accent-deep); font-weight: 750; }
.offer-budget-section {
  margin: 0 0 18px;
  padding: 22px 24px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.offer-budget-section h2 { margin: 0 0 10px; }
.offer-budget-section p { display: flex; gap: 8px; margin: 5px 0; }
.offer-budget-section p span { min-width: 90px; color: var(--muted); }
.offer-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  margin: 22px 0 0;
}
.offer-links a { font-weight: 700; }
.offer-pdf-link { display: inline-block; margin-top: 10px; font-weight: 750; }
@media (max-width: 900px) {
  .offer-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 650px) {
  .offer-hero { display: grid; padding: 19px; }
  .offer-status-badge { justify-self: start; }
  .offer-next-step,
  .offer-card,
  .offer-budget-section { padding: 18px; }
  .offer-facts,
  .offer-form fieldset { grid-template-columns: 1fr; }
  .offer-form label.offer-form-wide { grid-column: auto; }
}
</style>
"""


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
    """Return the OfferVersion id actually displayed by this detail page."""

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
            sent_line = (
                f"<p><span>Gesendet</span>"
                f"<strong>{_e(_history_date(sent_at))}</strong></p>"
            )
        rows.append(
            '<li class="offer-version-item">'
            f"<h3>Version {number}</h3>"
            f"<p><span>Status</span><strong>{_e(state_label)}</strong></p>"
            f"{aktuell}{sent_line}"
            "</li>"
        )
    return (
        '<details class="offer-secondary-panel">'
        "<summary>Angebotsversionen</summary>"
        '<div class="offer-secondary-content">'
        f'<ul class="offer-version-list">{"".join(rows)}</ul>'
        "</div></details>"
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
                '<li><details class="offer-position-detail">'
                f"<summary>{name} <span>({_e(unit_text)} netto / Einheit)</span></summary>"
                '<div class="offer-position-detail-body">'
                f"{description_html}{composition_html}{allergen_html}"
                "</div></details></li>"
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
    """Render the existing internal-only budget comparison, when present."""

    budget = surface.get("budget_definition")
    if not isinstance(budget, dict):
        return ""
    per_person = budget.get("type") == "PER_PERSON"
    suffix = " / Person" if per_person else ""
    amount_line = (
        f"<p><span>Budget</span><strong>"
        f"{_e(_budget_cents(budget.get('amount_cents')))}{suffix}</strong></p>"
    )
    basis_label = _BUDGET_TAX_BASIS_LABELS.get(str(budget.get("tax_basis")), "–")
    scope_label = _BUDGET_COST_SCOPE_LABELS.get(str(budget.get("cost_scope")), "–")
    basis_line = (
        f"<p><span>Basis</span><strong>"
        f"{_e(basis_label)} · {_e(scope_label)}</strong></p>"
    )
    comparison = budget.get("comparison_amount_cents")
    if comparison is None:
        comparison_line = (
            "<p><span>Aktuell</span><strong>Gästezahl noch offen</strong></p>"
        )
        remaining_line = ""
    else:
        comparison_line = (
            f"<p><span>Aktuell</span><strong>"
            f"{_e(_budget_cents(comparison))}{suffix}</strong></p>"
        )
        remaining = budget.get("remaining_cents")
        over = bool(budget.get("over"))
        remaining_abs = abs(remaining) if isinstance(remaining, int) else None
        remaining_label = "Überschritten" if over else "Verfügbar"
        remaining_line = (
            f"<p><span>{remaining_label}</span>"
            f"<strong>{_e(_budget_cents(remaining_abs))}{suffix}</strong></p>"
        )
    return (
        '<section class="offer-budget-section">'
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
        '<section class="offer-action-section">'
        '<form class="offer-form" method="post" '
        f'action="/offer/{_e(offer_id)}/mark-sent">'
        f"{forms.csrf_input}{forms.command_fields}"
        "<fieldset>"
        f'<label>Versandzeitpunkt <input type="datetime-local" name="sent_at" '
        f'step="1" value="{_e(default_at)}" required></label>'
        '<label>Kanal <select name="channel" required>'
        f"{_select_options(SENT_CHANNELS, _SENT_CHANNEL_LABELS)}"
        "</select></label>"
        '<label>Empfänger <input name="recipient_reference" required '
        'maxlength="500" placeholder="kunde@example.invalid"></label>'
        '<label>Nachweis / Referenz <input name="evidence_reference" required '
        'maxlength="1000" placeholder="E-Mail vom 16.07.2026"></label>'
        "</fieldset>"
        '<button class="offer-primary-button" type="submit">'
        "Als gesendet markieren</button>"
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
        '<section class="offer-action-section">'
        '<form class="offer-form" method="post" '
        f'action="/offer/{_e(offer_id)}/record-acceptance">'
        f"{forms.csrf_input}{forms.command_fields}"
        "<fieldset>"
        '<label>Angenommene Variante <select name="accepted_variant_id" required>'
        f"{variant_options}</select></label>"
        f'<label>Annahmezeitpunkt <input type="datetime-local" name="accepted_at" '
        f'step="1" value="{_e(default_at)}" required></label>'
        '<label>Kanal <select name="channel" required>'
        f"{_select_options(ACCEPTANCE_CHANNELS, _ACCEPTANCE_CHANNEL_LABELS)}"
        "</select></label>"
        '<label>Nachweis / Referenz <input name="evidence_reference" required '
        'maxlength="1000" placeholder="Telefonische Bestätigung"></label>'
        '<label class="offer-form-wide">Notiz (optional) '
        '<textarea name="note" rows="3" maxlength="20000"></textarea></label>'
        "</fieldset>"
        '<button class="offer-primary-button" type="submit">'
        "Annahme erfassen</button>"
        "</form></section>"
    )


def _record_rejection_form(
    offer_id: str, *, forms: OfferDetailFormFields, context: OfficePageContext
) -> str:
    if not context.can("offers.status.change"):
        return ""
    default_at = default_datetime_local_berlin()
    return (
        '<section class="offer-action-section">'
        "<h2>Kunde lehnt ab</h2>"
        '<form class="offer-form" method="post" '
        f'action="/offer/{_e(offer_id)}/record-rejection">'
        f"{forms.csrf_input}{forms.command_fields}"
        "<fieldset>"
        f'<label>Ablehnungszeitpunkt <input type="datetime-local" name="rejected_at" '
        f'step="1" value="{_e(default_at)}" required></label>'
        "<label>Kommentar / Nachweis (optional) "
        '<input name="evidence_reference" maxlength="1000" '
        'placeholder="Telefonische Absage"></label>'
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
        '<section class="offer-action-section">'
        "<h2>Angebot zurückziehen</h2>"
        '<form class="offer-form" method="post" '
        f'action="/offer/{_e(offer_id)}/record-withdrawal">'
        f"{forms.csrf_input}{forms.command_fields}"
        "<fieldset>"
        '<label class="offer-form-wide">Grund (optional) '
        '<textarea name="reason" rows="3" maxlength="20000"></textarea></label>'
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
            '<section class="offer-action-section">'
            "<p>Eine neue Angebotsversion wird im Angebots-Editor vorbereitet.</p>"
            "</section>"
        )
    return (
        '<section class="offer-action-section">'
        "<p>Eine neue Angebotsversion wird im Angebots-Editor vorbereitet "
        "und anschließend als nächste Version übernommen.</p>"
        f'<p><a class="offer-revision-link" href="{_e(revision_prefill_url)}">'
        "Neue Version vorbereiten</a></p>"
        "</section>"
    )


def _secondary_sent_actions(
    offer_id: str,
    *,
    forms: OfferDetailFormFields,
    revision_prefill_url: str | None,
    context: OfficePageContext,
) -> str:
    parts = [
        _record_rejection_form(offer_id, forms=forms, context=context),
        _record_withdrawal_form(offer_id, forms=forms, context=context),
    ]
    next_version = _prepare_next_version_cta(
        revision_prefill_url=revision_prefill_url, context=context
    )
    if next_version:
        parts.append(
            '<section class="offer-action-section">'
            "<h2>Neue Version vorbereiten</h2>"
            f"{next_version}"
            "</section>"
        )
    content = "".join(part for part in parts if part)
    if not content:
        return ""
    return (
        '<details class="offer-secondary-actions">'
        "<summary>Weitere Aktionen</summary>"
        f'<div class="offer-secondary-content">{content}</div>'
        "</details>"
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
        '<section class="offer-action-section">'
        "<p>Das angenommene Angebot wird in einen Auftrag überführt.</p>"
        '<form class="offer-form" method="post" '
        f'action="/offer/{_e(offer_id)}/convert" '
        'onsubmit="return confirm('
        "'Das angenommene Angebot wird jetzt in einen Auftrag umgewandelt.'"
        ');">'
        f"{forms.csrf_input}{forms.command_fields}"
        f'<input type="hidden" name="accepted_variant_id" '
        f'value="{_e(accepted_variant_id)}">'
        f'<input type="hidden" name="acceptance_id" value="{_e(acceptance_id)}">'
        '<button class="offer-primary-button" type="submit">'
        "In Auftrag umwandeln</button>"
        "</form></section>"
    )


def _next_step(
    detail: dict[str, object],
    *,
    offer_id: str,
    state: str,
    variants: list[dict[str, object]],
    forms: OfferDetailFormFields,
    revision_prefill_url: str | None,
    context: OfficePageContext,
) -> tuple[str, str, str]:
    if state == "Prepared":
        return (
            "Angebot als gesendet markieren",
            "Sobald das Angebot tatsächlich versendet wurde, den Versand hier dokumentieren.",
            _mark_sent_form(offer_id, forms=forms, context=context),
        )
    if state == "Sent":
        return (
            "Kundenentscheidung erfassen",
            "Wenn der Kunde zugesagt hat, die angenommene Variante und den Nachweis erfassen.",
            _record_acceptance_form(offer_id, variants, forms=forms, context=context),
        )
    if state == "Accepted":
        acceptance_id = detail.get("acceptance_id")
        acceptance = cast(dict[str, object] | None, detail.get("acceptance"))
        if (
            isinstance(acceptance_id, str)
            and acceptance is not None
            and acceptance.get("accepted_variant_id") is not None
        ):
            action = _convert_form(
                offer_id,
                accepted_variant_id=str(acceptance["accepted_variant_id"]),
                acceptance_id=acceptance_id,
                forms=forms,
                context=context,
            )
            if action:
                return (
                    "In Auftrag umwandeln",
                    "Die Kundenannahme ist erfasst. Jetzt den verbindlichen Auftrag anlegen.",
                    action,
                )
            return (
                "Kundenannahme erfasst",
                "Das Angebot wurde vom Kunden angenommen.",
                "",
            )
    if state in ("Expired", "Rejected", "Withdrawn"):
        return (
            "Neue Version vorbereiten",
            "Für die weitere Bearbeitung eine neue Angebotsversion im Angebots-Editor vorbereiten.",
            _prepare_next_version_cta(
                revision_prefill_url=revision_prefill_url, context=context
            ),
        )
    if state == "Converted":
        order_id = detail.get("order_id")
        action = (
            f'<a href="/order/{_e(str(order_id))}"><strong>Auftrag öffnen</strong></a>'
            if order_id is not None
            else ""
        )
        return (
            "Auftrag erstellt",
            "Dieses Angebot wurde bereits in einen Auftrag umgewandelt.",
            action,
        )
    return (
        offer_state_label(state),  # type: ignore[arg-type]
        "Für diesen Angebotsstatus ist derzeit kein weiterer Schritt erforderlich.",
        "",
    )


def _next_step_card(title: str, copy: str, action: str) -> str:
    return (
        '<section class="offer-next-step">'
        '<p class="offer-next-label">Nächster Schritt</p>'
        f"<h2>{_e(title)}</h2>"
        f'<p class="offer-next-copy">{_e(copy)}</p>'
        f"{action}"
        "</section>"
    )


def _event_card(surface: dict[str, object], planning: str, guest_text: str) -> str:
    facts = (
        ("Datum", _long_date(str(surface["event_date"]))),
        ("Zeit", str(surface["time_window_text"])),
        ("Ort", str(surface["location_text"])),
        ("Gäste", guest_text),
        ("Planung", planning),
    )
    fact_html = "".join(
        '<div class="offer-fact">'
        f"<span>{_e(label)}</span><strong>{_e(value)}</strong>"
        "</div>"
        for label, value in facts
    )
    return (
        '<section class="offer-card">'
        "<h2>Veranstaltung</h2>"
        '<div class="offer-facts">'
        f"{fact_html}"
        "</div></section>"
    )


def _variant_card(variants: list[dict[str, object]]) -> str:
    cards: list[str] = []
    total_positions = 0
    for variant in variants:
        positions = variant.get("positions")
        count = len(positions) if isinstance(positions, list) else 0
        total_positions += count
        cards.append(
            '<div class="offer-variant-card">'
            f"<h3>{_e(str(variant.get('name', 'Variante')))}</h3>"
            f"<p>{count} Position{'en' if count != 1 else ''}</p>"
            "</div>"
        )
    if not cards:
        cards.append('<div class="offer-variant-card"><h3>Keine Varianten</h3></div>')
    variant_suffix = "n" if len(variants) != 1 else ""
    position_suffix = "en" if total_positions != 1 else ""
    return (
        '<section class="offer-card">'
        "<h2>Angebotsvarianten</h2>"
        f'<p class="offer-next-copy">{len(variants)} Variante{variant_suffix} · '
        f"{total_positions} Position{position_suffix}</p>"
        f'<div class="offer-variant-grid">{"".join(cards)}</div>'
        "</section>"
    )


def _positions_panel(variants: list[dict[str, object]]) -> str:
    return (
        '<section class="offer-card">'
        "<h2>Positionen</h2>"
        '<p class="offer-next-copy">'
        "Details, Zusammensetzung und Allergene nur bei Bedarf öffnen.</p>"
        f'<ul class="offer-position-list">{_position_rows(variants)}</ul>'
        "</section>"
    )


def _history_panel(detail: dict[str, object]) -> str:
    history_rows = (
        "".join(
            f"<li><span>{_e(_history_date(str(entry['at'])))}</span> "
            f"<strong>{_e(str(entry['label']))}</strong></li>"
            for entry in cast(list[dict[str, object]], detail["history"])
        )
        or "<li>Noch keine Historie</li>"
    )
    return (
        '<details class="offer-secondary-panel">'
        "<summary>Angebotshistorie</summary>"
        '<div class="offer-secondary-content">'
        f'<ul class="offer-history-list">{history_rows}</ul>'
        "</div></details>"
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
        str(surface.get("planning_mode", "")),
        str(surface.get("planning_mode", "–")),
    )
    variants = cast(list[dict[str, object]], surface["variants"])
    version_number = int(cast(int, surface.get("version", 1)))
    state_label = offer_state_label(state)  # type: ignore[arg-type]

    next_title, next_copy, next_action = _next_step(
        detail,
        offer_id=offer_id,
        state=state,
        variants=variants,
        forms=forms,
        revision_prefill_url=revision_prefill_url,
        context=context,
    )

    secondary_actions = ""
    if state == "Sent":
        secondary_actions = _secondary_sent_actions(
            offer_id,
            forms=forms,
            revision_prefill_url=revision_prefill_url,
            context=context,
        )

    pdf_link = (
        f'<a class="offer-pdf-link" href="{_e(pdf_download_url)}">PDF herunterladen</a>'
        if pdf_download_url is not None and context.can("offers.pdf.generate")
        else ""
    )

    hero = (
        '<header class="offer-hero">'
        "<div>"
        '<p class="offer-eyebrow">Angebot</p>'
        f"<h1>Angebot {_e(offer_id[:8])}</h1>"
        f'<p class="offer-hero-meta">Version {version_number} · '
        f"{_e(_long_date(str(surface['event_date'])))} · "
        f"{_e(str(surface['location_text']))}</p>"
        f"{pdf_link}"
        "</div>"
        f'<span class="offer-status-badge">{_e(state_label)}</span>'
        "</header>"
    )

    order_id = detail.get("order_id")
    order_link = (
        f'<a href="/order/{_e(str(order_id))}">Auftrag öffnen</a>'
        if order_id is not None
        else ""
    )
    footer_links = (
        '<nav class="offer-links">'
        f"{order_link}"
        f'<a href="/inquiry/{_e(inquiry_id)}">Anfrage öffnen</a>'
        '<a href="/angebote">← Zurück zu Angeboten</a>'
        "</nav>"
    )

    body = (
        _OFFER_DETAIL_STYLE
        + '<div class="offer-guided">'
        + hero
        + _next_step_card(next_title, next_copy, next_action)
        + secondary_actions
        + _event_card(surface, planning, guest_text)
        + _budget_block(surface)
        + _variant_card(variants)
        + _positions_panel(variants)
        + _version_list(detail)
        + _history_panel(detail)
        + footer_links
        + "</div>"
    )
    return _page(
        "Angebot",
        body,
        active_section="offers",
        context=context,
        show_title=False,
    )

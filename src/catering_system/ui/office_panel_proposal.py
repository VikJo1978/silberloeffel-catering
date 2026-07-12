"""Configurator proposal parsing and read-only preview rendering."""

from __future__ import annotations

import json
from datetime import date

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _csrf_input,
    _e,
    _EMPTY_PAGE_CONTEXT,
    _page,
)

PROPOSAL_PAYLOAD_SCHEMA_VERSION = "proposal_payload_v1"
PROPOSAL_PAYLOAD_SOURCE = "fingerfood-configurator"

_PROPOSAL_PREVIEW_WARNING = (
    '<p class="proposal-banner">Nur Angebots-Vorschau (proposal/import preview) — '
    "keine Core-Daten wurden erstellt oder geändert — Angebotsdaten sind keine "
    "operative Wahrheit (not operational truth).</p>"
)


def parse_proposal_payload(raw: str) -> dict:
    """Validate pasted JSON against the pack's base fields (pack §2); parse only,
    write nothing. Raises ValueError with an office-readable message."""
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ValueError(
            "Ungültiges JSON. Bitte den Inhalt der .json-Datei einfügen, "
            "nicht den Dateinamen und nicht die Datei selbst. "
            f"Technisches Detail: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            "Ungültiges JSON. Erwartet wird ein einzelnes JSON-Objekt von { bis } — "
            "bitte den kompletten Inhalt der .json-Datei einfügen."
        )
    if payload.get("schema_version") != PROPOSAL_PAYLOAD_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version fehlt oder unbekannt (erwartet: {PROPOSAL_PAYLOAD_SCHEMA_VERSION!r})"
        )
    if payload.get("source") != PROPOSAL_PAYLOAD_SOURCE:
        raise ValueError(
            f"source fehlt oder unbekannt (erwartet: {PROPOSAL_PAYLOAD_SOURCE!r})"
        )
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title fehlt oder ist leer")
    event_date = payload.get("event_date")
    if not isinstance(event_date, str):
        raise ValueError("event_date fehlt (erwartet: JJJJ-MM-TT)")
    try:
        date.fromisoformat(event_date)
    except ValueError as exc:
        raise ValueError(
            f"event_date ist kein gültiges Datum (JJJJ-MM-TT): {event_date!r}"
        ) from exc
    guest_count = payload.get("guest_count")
    # bool is an int subclass — true/false must not pass as a guest count.
    if (
        not isinstance(guest_count, int)
        or isinstance(guest_count, bool)
        or guest_count < 1
    ):
        raise ValueError("guest_count fehlt oder ist keine ganze Zahl >= 1")
    items = payload.get("selected_items")
    if not isinstance(items, list):
        raise ValueError("selected_items fehlt oder ist keine Liste")
    for pos, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"selected_items[{pos}] ist kein Objekt")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"selected_items[{pos}]: name fehlt oder ist leer")
    # proposal_id, calculated_total_net/gross, notes and per-item
    # quantity/prices/notes are optional proposal data — displayed if present,
    # never validated beyond that (pack §2).
    return payload


def render_proposal_preview_form(
    *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
) -> str:
    body = _PROPOSAL_PREVIEW_WARNING + (
        "<p><strong>So funktioniert der Büro-Import:</strong></p>"
        "<ol>"
        "<li>Im Configurator „Export fürs Büro (JSON)“ klicken.</li>"
        "<li>Die heruntergeladene .json-Datei öffnen (Doppelklick oder Texteditor).</li>"
        "<li>Den kompletten JSON-Text von <code>{</code> bis <code>}</code> kopieren.</li>"
        "<li>Unten einfügen und „Vorschau anzeigen“ klicken.</li>"
        "</ol>"
        '<p class="subtitle">Keine Datei hier ablegen, keinen Dateinamen einfügen — '
        "nur den Inhalt der .json-Datei. Die Vorschau zeigt die Daten nur an: es wird "
        "nichts gespeichert und kein Vorgang angelegt.</p>"
        '<form method="post" action="/proposal-preview">'
        f"{_csrf_input(context)}"
        '<p><textarea name="payload_json" rows="14" '
        'style="width:100%;box-sizing:border-box;font-family:monospace"></textarea></p>'
        '<p><button type="submit">Vorschau anzeigen</button></p></form>'
    )
    return _page("Angebots-Import (Vorschau)", body, context=context)


def render_proposal_preview(
    payload: dict, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
) -> str:
    def _opt(value: object) -> str:
        return _e(value) if value is not None and value != "" else "–"

    # "Anfrage aus Vorschau vorbereiten" (PROPOSAL_PREVIEW_INTAKE_MAPPING_
    # IMPLEMENTATION_PACK_V1 §3/§6): POST prepare step, not a GET link —
    # title/notes/selected_items summary can be long/multiline, which the
    # 2026-07-09 review already flagged as too fragile for a query string
    # (see PROPOSAL_PREVIEW_MANUAL_INQUIRY_PACK_V1 §9). The hidden field
    # carries the already-validated payload, re-serialized — not the
    # office's original raw textarea text — so /proposal-preview/prepare can
    # re-run parse_proposal_payload() as the single source of validation.
    # Following this form writes nothing; the only write stays the existing
    # explicit /inquiry/new submit.
    prepare_payload_json = json.dumps(payload)

    item_rows = "".join(
        "<tr>"
        f"<td>{_e(item['name'])}</td>"
        f"<td>{_opt(item.get('quantity'))}</td>"
        f"<td>{_opt(item.get('unit_price'))}</td>"
        f"<td>{_opt(item.get('total_price'))}</td>"
        f"<td>{_opt(item.get('notes'))}</td>"
        "</tr>"
        for item in payload["selected_items"]
    )
    body = (
        _PROPOSAL_PREVIEW_WARNING
        + f"""<table>
<tr><th>Quelle</th><td>{_e(payload["source"])}</td></tr>
<tr><th>Titel</th><td>{_e(payload["title"])}</td></tr>
<tr><th>Datum (Vorschlag)</th><td>{_e(payload["event_date"])}</td></tr>
<tr><th>Gäste (Vorschlag)</th><td>{_e(payload["guest_count"])}</td></tr>
<tr><th>Summe netto (berechnet)</th><td>{_opt(payload.get("calculated_total_net"))}</td></tr>
<tr><th>Summe brutto (berechnet)</th><td>{_opt(payload.get("calculated_total_gross"))}</td></tr>
<tr><th>Notizen</th><td>{_opt(payload.get("notes"))}</td></tr>
<tr><th>Proposal-ID (lokal)</th><td>{_opt(payload.get("proposal_id"))}</td></tr>
</table>
<h2>Positionen (Vorschlag)</h2>
<table><tr><th>Name</th><th>Menge</th><th>Einzelpreis</th><th>Gesamt</th><th>Notiz</th></tr>{item_rows}</table>
<form method="post" action="/proposal-preview/prepare">
{_csrf_input(context)}
<input type="hidden" name="payload_json" value="{_e(prepare_payload_json)}">
<button type="submit">Anfrage aus Vorschau vorbereiten</button>
</form>
<p><a href="/proposal-preview">Weitere Vorschau anzeigen</a></p>"""
    )
    return _page("Angebots-Import (Vorschau)", body, context=context)

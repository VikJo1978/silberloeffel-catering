"""Office panel — primary office write surface (OFFICE_PANEL_EXECUTION_PACK_V1).

Thin server-rendered skin over existing Core services; adds no domain semantics
(pack §1). LAN-only write surface with mandatory basic auth (§3, §7). Blocked
reasons are rendered from two separate vocabularies that are never merged (§5):
progression (B7) on inquiry views, operational gate on order views.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import urllib.error
import urllib.request
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse

from catering_system.domain.inquiry import CRM_PIPELINE, Inquiry, PLANNING_MODES
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.progression_service import ProgressionService
from catering_system.services.wochenuebersicht_service import WochenuebersichtService

# Office-visible subset of InquirySource (domain/inquiry.py) — deliberately
# narrower than InquiryService._ALLOWED_SOURCES (INQUIRY_INTAKE_CONTEXT_FIELDS
# _IMPLEMENTATION_PACK_V1 §3/§6): phone/wix_form stay legacy/adapter-only
# (src/catering_system/intake/phone_adapter.py, wix_form_adapter.py already
# write them through the validated path), missed_call/ai_telefonist stay
# adapter-only until their own integration exists — nothing writes them yet,
# so offering them here would be misleading.
_OFFICE_SOURCES = ("manual", "phone_by_office", "email", "website_form", "configurator")

# Brand facelift (2026-07-07): same palette/typography as the fingerfood-app
# configurator (sage accent from the logo, Playfair Display headings) so the
# office panel and the Angebot formular read as one system. Pure presentation
# -- no markup/class names used by tests were touched.
_LOGO_DATA_URI = "data:image/jpeg;base64,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"

_STYLE = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@500;600;700&display=swap');
:root { --accent: #5c6f63; --accent-deep: #4a5b50; --accent-soft: #e9eeea; }
body { font-family: 'DM Sans', system-ui, sans-serif; margin: 0; background: #f6f7f6; color: #1a1f1c; }
.brandbar { background: #fff; border-bottom: 1px solid #e2e5e2; padding: 0.75rem 2rem; }
.brandbar img { height: 44px; display: block; }
.layout { display: flex; align-items: flex-start; max-width: 78rem; margin: 0 auto; }
.sidebar { width: 11rem; flex-shrink: 0; display: flex; flex-direction: column; gap: 0.2rem; padding: 1.5rem 1rem; position: sticky; top: 0; }
.sidebar a { padding: 0.5rem 0.75rem; border-radius: 6px; text-decoration: none; color: #33413a; font-size: 0.9rem; }
.sidebar a:hover { background: var(--accent-soft); }
.sidebar a.rueckruf-link { display: flex; justify-content: space-between; align-items: center; }
.badge { background: var(--accent); color: #fff; border-radius: 999px; font-size: 0.75rem; font-weight: 600; line-height: 1.4; min-width: 1.4rem; padding: 0.05rem 0.45rem; text-align: center; }
.content { flex: 1; min-width: 0; padding: 2rem 2rem 2rem 0; }
a { color: var(--accent); }
h1 { font-family: 'Playfair Display', Georgia, serif; font-size: 1.9rem; font-weight: 600; margin: 0.5rem 0 1.25rem; }
h2 { font-family: 'Playfair Display', Georgia, serif; font-size: 1.3rem; font-weight: 600; margin-top: 2rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 2px rgba(38,48,43,0.05), 0 8px 20px rgba(38,48,43,0.04); }
th, td { border: 1px solid #e2e5e2; padding: 0.55rem 0.9rem; text-align: left; }
th { background: var(--accent-soft); color: #33413a; font-weight: 600; }
form.inline { display: inline; }
.blocked { color: #a3312d; } .ok { color: #3b6d11; } .cancelled { color: #a3312d; font-weight: bold; }
button { padding: 0.4rem 1rem; border-radius: 6px; border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer; font: inherit; }
button:hover { background: var(--accent-deep); border-color: var(--accent-deep); }
fieldset { margin-bottom: 1rem; border: 1px solid #e2e5e2; border-radius: 8px; background: #fff; }
label { display: inline-block; min-width: 12rem; }
input, select { border: 1px solid #d3d6d1; border-radius: 6px; padding: 0.35rem 0.55rem; font: inherit; }
.attention { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1.25rem; }
.attention a, .attention span { background: #fff; border: 1px solid #e2e5e2; border-radius: 8px; padding: 0.5rem 0.9rem; text-decoration: none; color: inherit; font-size: 0.9rem; }
.attention a:hover { border-color: var(--accent); }
.attention strong { color: var(--accent-deep); }
.searchbox { margin-bottom: 1rem; }
.searchbox input { min-width: 16rem; }
.subtitle { color: #5f5e5a; font-size: 0.9rem; margin: -0.75rem 0 1.25rem; }
.proposal-banner { background: #fdf6e3; border: 1px solid #d9c47e; border-radius: 8px; padding: 0.6rem 0.9rem; color: #7a5d00; font-weight: 600; margin-bottom: 1.25rem; }
"""


def _e(text: object) -> str:
    return html.escape(str(text))


# UI-only display labels (OFFICE_PANEL_SAFE_UX_LABELS_AND_GROUPING_V1,
# 2026-07-07). Pure display mapping — the underlying Core/domain values are
# untouched, and the three vocabularies stay separate on purpose (§5,
# "vocabularies not merged"): call-verification status is its own simple
# status, READY_TO_SEND blocker reasons are the operational-gate vocabulary
# (order views only), and progression blocker reasons are the B7 vocabulary
# (inquiry-to-order conversion views only). Never merge these dicts.
CALL_VERIFICATION_STATUS_LABELS: dict[str, str] = {
    "not_required": "keine Rückrufprüfung nötig",
    "pending": "Rückrufprüfung ausstehend",
    "verified": "verifiziert",
    "failed": "Rückrufprüfung fehlgeschlagen",
    "blocked": "Rückrufprüfung blockiert",
}
READY_TO_SEND_BLOCKER_LABELS: dict[str, str] = {
    "ready_to_send_order_not_found": "Auftrag nicht gefunden",
    "order_cancelled": "Auftrag storniert",
    "no_effective_version": "keine wirksame Auftragsversion",
    "effective_version_not_resolvable": "wirksame Version nicht auffindbar",
    "kitchen_print_not_confirmed": "Druckbestätigung fehlt",
}
PROGRESSION_BLOCKER_LABELS: dict[str, str] = {
    "inquiry_call_verification_unsatisfied": "Rückrufprüfung noch nicht erfüllt",
}


def _verification_label(value: str) -> str:
    return CALL_VERIFICATION_STATUS_LABELS.get(value, value or "–")


def _ready_to_send_blocker_label(code: str) -> str:
    return READY_TO_SEND_BLOCKER_LABELS.get(code, f"technischer Blocker: {code}")


def _progression_blocker_label(code: str) -> str:
    return PROGRESSION_BLOCKER_LABELS.get(code, f"technischer Fortschritts-Blocker: {code}")


# Sidebar Rückruf-badge count, current request only. Set once per request
# (do_GET/do_POST's _error_page, before any _page()-rendering call) and read
# here. A plain module global is safe only because the server is guaranteed
# single-threaded, one request at a time (WORKLOG Entry 048) — do not reuse
# this pattern if that invariant ever changes.
_sidebar_rueckruf_count: int | None = None


def _page(title: str, body: str) -> str:
    # Persistent sidebar on every page (owner feedback 2026-07-07: one long
    # stacked page read as clutter). All targets are absolute paths/anchors
    # on "/" so the sidebar works identically from any page, not just "/".
    rueckruf_label = "Rückrufliste"
    if _sidebar_rueckruf_count:  # None or 0 -> no badge, nothing to flag
        rueckruf_label += f' <span class="badge">{_sidebar_rueckruf_count}</span>'
    nav = (
        '<nav class="sidebar">'
        '<a href="/">Start</a>'
        '<a href="/anfragen">Anfragen</a>'
        '<a href="/auftraege">Aufträge</a>'
        '<a href="/#diese-woche">Diese Woche</a>'
        f'<a href="/rueckruf" class="rueckruf-link">{rueckruf_label}</a>'
        '<a href="/proposal-preview">Angebots-Import</a>'
        "</nav>"
    )
    return (
        f'<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
        f"<title>{_e(title)}</title><style>{_STYLE}</style></head>"
        f'<body><div class="brandbar"><img src="{_LOGO_DATA_URI}" alt="Silberlöffel Event Catering Service"></div>'
        f'<div class="layout">{nav}<div class="content"><h1>{_e(title)}</h1>{body}</div></div></body></html>'
    )


def _planning_mode_select(selected: str) -> str:
    opts = "".join(
        f'<option value="{_e(m)}"{" selected" if m == selected else ""}>{_e(m)}</option>'
        for m in PLANNING_MODES
    )
    return f'<select name="planning_mode">{opts}</select>'


def _crm_stage_select(selected: str) -> str:
    opts = "".join(
        f'<option value="{_e(s)}"{" selected" if s == selected else ""}>{_e(s)}</option>'
        for s in CRM_PIPELINE
    )
    return f'<select name="crm_stage">{opts}</select>'


def render_print_sheet(order: Order, version: OrderVersion) -> str:
    """Kitchen order sheet — read-only printable rendering of one version (pack §4)."""
    guests = str(version.guest_count_estimate) if version.guest_count_estimate is not None else "–"
    cancelled_banner = (
        '<p style="color:#a00;font-size:2rem;border:4px solid #a00;padding:0.5rem">STORNIERT</p>'
        if order.cancelled_at is not None
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Küchenzettel</title>
<style>body{{font-family:sans-serif;font-size:1.6rem;margin:2rem}}
td,th{{border:1px solid #000;padding:0.6rem 1rem;text-align:left}}
table{{border-collapse:collapse}}h1{{font-size:1.8rem}}</style></head><body>
{cancelled_banner}
<h1>Küchenzettel — Version {version.version_number}</h1>
<table>
<tr><th>Datum</th><td>{_e(version.event_date.isoformat())}</td></tr>
<tr><th>Zeitfenster</th><td>{_e(version.time_window_text)}</td></tr>
<tr><th>Ort</th><td>{_e(version.location_text)}</td></tr>
<tr><th>Gäste</th><td>{_e(guests)}</td></tr>
<tr><th>Planungsmodus</th><td>{_e(version.planning_mode)}</td></tr>
<tr><th>Auftrag</th><td>{_e(order.order_id)}</td></tr>
<tr><th>Version erstellt</th><td>{_e(version.created_at.isoformat())}</td></tr>
</table>
<p><button onclick="window.print()">Drucken</button></p>
</body></html>"""


# -- Rückrufe: read-only pull from the separate auerswald-sync call-log
# service (own repo/server, NOT Core, NOT EspoCRM). Pre-inquiry office signal
# only — never writes into Core, never creates an Inquiry automatically. The
# only write this makes is the office-initiated "erledigt" resolve, which
# goes to auerswald-sync's own /missed/resolve, not to Core.


def _auth_header(user: str, password: str) -> str | None:
    if not user and not password:
        return None
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def fetch_missed_board(
    url: str, user: str, password: str, limit: int = 100
) -> tuple[list[dict] | None, str | None]:
    if not url:
        return None, "AUERSWALD_SYNC_URL nicht konfiguriert"
    req = urllib.request.Request(f"{url.rstrip('/')}/missed-board.json?limit={limit}")
    auth = _auth_header(user, password)
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("items", []), None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return None, str(exc)


def fetch_rueckruf_count(url: str, user: str, password: str) -> int | None:
    """Sidebar badge count. Same source/call as the Rückrufliste page itself
    (fetch_missed_board) — not a second data source or a new business rule,
    just its length. None means "show no badge": unconfigured, unreachable,
    or genuinely zero open callbacks all render the same (nothing to flag)."""
    items, error = fetch_missed_board(url, user, password)
    if error or not items:
        return None
    return len(items)


class _NoRedirect(urllib.request.HTTPErrorProcessor):
    """auerswald-sync's own /missed/resolve replies 303 to its own HTML
    /missed-board page (fine for a browser, irrelevant here) — don't follow
    it and don't treat it as an error; we only care that the POST landed."""

    def http_response(self, request, response):
        return response

    https_response = http_response


def resolve_missed_call(url: str, user: str, password: str, call_id: str) -> None:
    req = urllib.request.Request(
        f"{url.rstrip('/')}/missed/resolve",
        data=urlencode({"call_id": call_id}).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    auth = _auth_header(user, password)
    if auth:
        req.add_header("Authorization", auth)
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(req, timeout=5):
        pass


_RUECKRUF_SUBTITLE = (
    '<p class="subtitle">Verpasste Anrufe sowie Anrufe außerhalb der Bürozeiten, '
    "die einen Rückruf erfordern.</p>"
)


def render_rueckruf(items: list[dict] | None, error: str | None) -> str:
    if error:
        body = _RUECKRUF_SUBTITLE + (
            f'<p class="blocked">Rückrufliste nicht erreichbar: {_e(error)}</p>'
            "<p>Prüfe AUERSWALD_SYNC_URL / erreichbarkeit des auerswald-sync Servers.</p>"
        )
        return _page("Offene Rückrufe", body)
    if not items:
        body = _RUECKRUF_SUBTITLE + "<p>Keine offenen Rückrufe.</p>"
        return _page("Offene Rückrufe", body)
    rows = []
    for it in items:
        contact = _e(it["contact_name"]) if it.get("contact_found") else "Unbekannt"
        rows.append(
            "<tr>"
            f"<td>{_e(it.get('date', ''))}</td>"
            f"<td>{_e(it.get('time', ''))}</td>"
            f"<td>{_e(it.get('phone', ''))}</td>"
            f"<td>{_e(it.get('reason', ''))}</td>"
            f"<td>{contact}</td>"
            "<td>"
            '<form class="inline" method="post" action="/rueckruf/resolve">'
            f'<input type="hidden" name="call_id" value="{_e(it.get("call_id", ""))}">'
            "<button>Erledigt</button></form>"
            "</td></tr>"
        )
    body = _RUECKRUF_SUBTITLE + (
        "<table><tr><th>Datum</th><th>Zeit</th><th>Nummer</th>"
        "<th>Grund</th><th>Kontakt</th><th></th></tr>"
        + "".join(rows)
        + "</table>"
    )
    return _page("Offene Rückrufe", body)


# -- Proposal preview: read-only import preview for proposal_payload_v1
# (CONFIGURATOR_OFFICE_MANUAL_HANDOFF_PACK_V1, frozen 334cd11). The payload is
# proposal data exported from the separate fingerfood-app configurator — never
# Core truth. This surface parses and renders only: nothing is persisted, no
# Inquiry/Order/OrderVersion is created or changed, and the preview offers no
# action that writes anywhere. Core truth still arises only through the
# regular office-panel forms, after manual office work.

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
        raise ValueError(f"source fehlt oder unbekannt (erwartet: {PROPOSAL_PAYLOAD_SOURCE!r})")
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
    if not isinstance(guest_count, int) or isinstance(guest_count, bool) or guest_count < 1:
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


def render_proposal_preview_form() -> str:
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
        '<p><textarea name="payload_json" rows="14" '
        'style="width:100%;box-sizing:border-box;font-family:monospace"></textarea></p>'
        "<p><button type=\"submit\">Vorschau anzeigen</button></p></form>"
    )
    return _page("Angebots-Import (Vorschau)", body)


def render_proposal_preview(payload: dict) -> str:
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
    body = _PROPOSAL_PREVIEW_WARNING + f"""<table>
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
<input type="hidden" name="payload_json" value="{_e(prepare_payload_json)}">
<button type="submit">Anfrage aus Vorschau vorbereiten</button>
</form>
<p><a href="/proposal-preview">Weitere Vorschau anzeigen</a></p>"""
    return _page("Angebots-Import (Vorschau)", body)


class OfficePanel:
    """Route handling and rendering; kept separate from the HTTP handler for testability."""

    def __init__(
        self, inquiry_repo: InquiryRepository, order_repo: OrderRepository, kiosk_url: str = ""
    ) -> None:
        self._inquiries = inquiry_repo
        self._orders = order_repo
        self.inquiry_service = InquiryService(inquiry_repo)
        self.order_service = OrderService(order_repo)
        self.core = OperationalCoreService(order_repo)
        self.progression = ProgressionService(order_repo)
        self.wochenuebersicht = WochenuebersichtService(order_repo)
        # Single source of truth for the "full week" deep link — the kitchen
        # kiosk (catering_system.ui.kiosk_server) already owns that view via
        # the same WochenuebersichtService (OFFICE_PANEL_EXECUTION_PACK_V1
        # §6: Wochenübersicht stays derived-only, panel may at most link to
        # it). Empty -> no link shown, same graceful-degrade convention as
        # the Rückrufe integration.
        self.kiosk_url = kiosk_url

    def _next_step_action(self, order: Order) -> str:
        """UI action-target resolution for existing routes only — not new
        order semantics. Picks the target OrderVersion (candidate_order_
        version_id if set and real, else the highest version_number — a
        display fallback, not new truth; documented in domain/order.py as
        exactly this: an "office-side progression hint") and returns
        whichever of the two existing, ordered actions applies. Order
        matters: operational_core_service.make_order_version_effective()
        itself refuses a version whose kitchen print isn't confirmed yet
        (raises ValueError) — so print-confirm must be offered first, never
        "Wirksam machen" for an unprinted version, even if that version's
        READY_TO_SEND reason would otherwise be reported as
        no_effective_version rather than kitchen_print_not_confirmed."""
        versions = self._orders.list_order_versions(order.order_id)
        if not versions:
            return ""
        version = next(
            (v for v in versions if v.order_version_id == order.candidate_order_version_id),
            None,
        )
        if version is None:
            version = max(versions, key=lambda v: v.version_number)
        if version.kitchen_print_confirmed_at is None:
            label, action = "Druck bestätigen", "print-confirm"
        elif version.order_version_id != order.effective_order_version_id:
            label, action = "Wirksam machen", "effective"
        else:
            return ""
        return (
            f'<form class="inline" method="post" action="/order/{_e(order.order_id)}/{action}">'
            f'<input type="hidden" name="order_version_id" value="{_e(version.order_version_id)}">'
            f"<button>{label}</button></form>"
        )

    # -- queue -----------------------------------------------------------

    def render_queue(self, rueckruf_items: list[dict] | None) -> str:
        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for o in orders:
            orders_by_inquiry.setdefault(o.source_inquiry_id, []).append(o)

        # -- Heute / Aufmerksamkeit: counts from data already loaded above,
        # no new service calls. Every number here maps onto an existing,
        # already-accepted concept (progression B7 / operational gate) —
        # this is a summary view, not a new domain concept.
        all_inquiries = self._inquiries.list_all()
        neue_anfragen = [i for i in all_inquiries if i.inquiry_id not in orders_by_inquiry]
        active_orders = [o for o in orders if o.cancelled_at is None]
        ohne_druck = [
            o for o in active_orders
            if not any(
                v.kitchen_print_confirmed_at is not None
                for v in self._orders.list_order_versions(o.order_id)
            )
        ]
        nicht_wirksam = [o for o in active_orders if o.effective_order_version_id is None]
        blockiert = [
            o for o in active_orders if not self.core.evaluate_ready_to_send(o.order_id).ready
        ]
        storniert = [o for o in orders if o.cancelled_at is not None]
        # Reuses the same count already fetched for the sidebar badge (set
        # before render_queue() runs, see do_GET) — no second auerswald-sync
        # request. None = not configured/unreachable -> card omitted, same
        # as the sidebar badge; unlike the other cards, 0 is a real fetched
        # value here (they never depend on an external service, so 0 always
        # means "confirmed empty").
        rueckruf_card = (
            f'<a href="/rueckruf"><strong>{_sidebar_rueckruf_count}</strong> Rückrufe offen</a>'
            if _sidebar_rueckruf_count is not None
            else ""
        )
        storniert_card = (
            f'<span><strong>{len(storniert)}</strong> Stornierte Aufträge prüfen</span>'
            if storniert
            else ""
        )
        attention = (
            "<h2>Was braucht Aufmerksamkeit?</h2>"
            '<div class="attention">'
            + rueckruf_card
            + f'<a href="#anfragen"><strong>{len(neue_anfragen)}</strong> Neue Anfragen prüfen</a>'
            f'<a href="#auftraege"><strong>{len(ohne_druck)}</strong> Druckbestätigung fehlt</a>'
            f'<a href="#auftraege"><strong>{len(nicht_wirksam)}</strong> Aufträge noch nicht wirksam</a>'
            f'<a href="#auftraege"><strong>{len(blockiert)}</strong> Versandfreigabe blockiert</a>'
            + storniert_card
            + "</div>"
        )

        iso = date.today().isocalendar()
        week = self.wochenuebersicht.get_week_overview(iso.year, iso.week)
        week_rows = [
            f"<tr><td>{_e(e.event_date.isoformat())}</td><td>{_e(e.time_window_text)}</td>"
            f"<td>{_e(e.location_text)}</td>"
            f"<td>{_e(str(e.guest_count_estimate) if e.guest_count_estimate is not None else '–')}</td>"
            f'<td><a href="/order/{_e(e.order_id)}">{_e(e.order_id[:8])}</a></td></tr>'
            for e in week.entries
        ]
        kiosk_link = (
            f' <a href="{_e(self.kiosk_url)}">Vollständige Wochenübersicht (Küche)</a>'
            if self.kiosk_url
            else ""
        )
        diese_woche = (
            f'<h2 id="diese-woche">Diese Woche (KW {iso.week}/{iso.year})</h2>'
            "<table><tr><th>Datum</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th><th>Auftrag</th></tr>"
            + "".join(week_rows or ['<tr><td colspan="5">keine wirksamen Aufträge diese Woche</td></tr>'])
            + "</table>"
            + kiosk_link
        )

        # -- three action queues (§11 addendum): top 5 rows each, one
        # primary action per row, full lists live at /rueckruf, /anfragen,
        # /auftraege. rueckruf_items is None when auerswald-sync is
        # unconfigured/unreachable -> the whole queue is omitted, same
        # graceful-degrade convention as the sidebar badge (not an error
        # page, the rest of the Startseite still renders).
        rueckruf_section = ""
        if rueckruf_items is not None:
            rows = []
            for it in rueckruf_items[:5]:
                contact = _e(it["contact_name"]) if it.get("contact_found") else "Unbekannt"
                phone = it.get("phone", "")
                rows.append(
                    f"<li>{_e(it.get('date', ''))} {_e(it.get('time', ''))} — "
                    f"{_e(phone)} ({contact}) "
                    '<form class="inline" method="post" action="/rueckruf/resolve">'
                    f'<input type="hidden" name="call_id" value="{_e(it.get("call_id", ""))}">'
                    "<button>Erledigt</button></form> "
                    f'<a href="/inquiry/new?phone={quote(phone)}">Anfrage erfassen</a></li>'
                )
            rueckruf_section = (
                "<h2>Rückruf nötig</h2>"
                + (f"<ul>{''.join(rows)}</ul>" if rows else "<p>keine offenen Rückrufe.</p>")
                + '<p><a href="/rueckruf">Alle anzeigen</a></p>'
            )

        neue_anfragen_rows = []
        for inq in neue_anfragen[:5]:
            if inq.call_verification_required and inq.call_verification_status != "verified":
                action = (
                    f'<form class="inline" method="post" action="/inquiry/{_e(inq.inquiry_id)}/verify">'
                    "<button>Telefonisch verifiziert</button></form>"
                )
            else:
                action = (
                    f'<form class="inline" method="post" action="/inquiry/{_e(inq.inquiry_id)}/convert">'
                    "<button>In Auftrag umwandeln</button></form>"
                )
            neue_anfragen_rows.append(
                f'<li><a href="/inquiry/{_e(inq.inquiry_id)}">{_e(inq.event_date.isoformat())} · '
                f"{_e(inq.location_text)}</a> {action}</li>"
            )
        neue_anfragen_section = (
            "<h2>Neue Anfragen</h2>"
            + (
                f"<ul>{''.join(neue_anfragen_rows)}</ul>"
                if neue_anfragen_rows
                else "<p>keine neuen Anfragen.</p>"
            )
            + '<p><a href="/anfragen">Alle anzeigen</a></p>'
        )

        auftraege_rows = []
        for o in blockiert[:5]:
            ev = self.core.evaluate_ready_to_send(o.order_id)
            reason = _e(_ready_to_send_blocker_label(ev.reasons[0])) if ev.reasons else "–"
            action = self._next_step_action(o)
            auftraege_rows.append(
                f'<li><a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a> — {reason} {action}</li>'
            )
        auftraege_section = (
            "<h2>Aufträge mit nächstem Schritt</h2>"
            + (
                f"<ul>{''.join(auftraege_rows)}</ul>"
                if auftraege_rows
                else "<p>keine offenen Schritte.</p>"
            )
            + '<p><a href="/auftraege">Alle anzeigen</a></p>'
        )

        body = (
            attention
            + diese_woche
            + rueckruf_section
            + neue_anfragen_section
            + auftraege_section
            + '<p><a href="/inquiry/new">+ Neue Anfrage erfassen</a></p>'
        )
        return _page("Büro-Übersicht", body)

    # -- full lists (moved out of the Startseite, §11 addendum §13) ------

    def render_anfragen(self, q: str = "") -> str:
        needle = q.strip().lower()

        def _matches(*fields: str) -> bool:
            if not needle:
                return True
            return any(needle in f.lower() for f in fields)

        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for o in orders:
            orders_by_inquiry.setdefault(o.source_inquiry_id, []).append(o)

        search_box = (
            '<form method="get" action="/anfragen" class="searchbox">'
            f'<input type="text" name="q" value="{_e(q)}" placeholder="Suche: ID, Ort, Datum…">'
            "<button type=\"submit\">Suchen</button>"
            + (' <a href="/anfragen">Zurücksetzen</a>' if q else "")
            + "</form>"
        )

        rows = []
        for inq in self._inquiries.list_all():
            linked_orders = orders_by_inquiry.get(inq.inquiry_id, [])
            has_order = (
                f'<a href="/order/{_e(linked_orders[0].order_id)}">Auftrag öffnen</a>'
                if linked_orders
                else "–"
            )
            if not _matches(
                inq.inquiry_id, inq.location_text, inq.event_date.isoformat(), inq.crm_stage
            ):
                continue
            rows.append(
                f"<tr><td>{_e(inq.event_date.isoformat())}</td><td>{_e(inq.location_text)}</td>"
                f"<td>{_e(inq.crm_stage)}</td><td>{_e(_verification_label(inq.call_verification_status))}</td>"
                f"<td>{has_order}</td>"
                f'<td><a href="/inquiry/{_e(inq.inquiry_id)}">{_e(inq.inquiry_id[:8])}</a></td></tr>'
            )

        body = (
            search_box
            + '<p><a href="/inquiry/new">+ Neue Anfrage erfassen</a></p>'
            "<table><tr><th>Datum</th><th>Ort</th>"
            "<th>CRM-Stufe</th><th>Verifizierung</th><th>Auftrag</th><th>ID</th></tr>"
            + "".join(rows or ['<tr><td colspan="6">keine</td></tr>'])
            + "</table>"
        )
        return _page("Anfragen", body)

    def render_auftraege(self, q: str = "") -> str:
        needle = q.strip().lower()

        def _matches(*fields: str) -> bool:
            if not needle:
                return True
            return any(needle in f.lower() for f in fields)

        search_box = (
            '<form method="get" action="/auftraege" class="searchbox">'
            f'<input type="text" name="q" value="{_e(q)}" placeholder="Suche: ID, Ort, Datum…">'
            "<button type=\"submit\">Suchen</button>"
            + (' <a href="/auftraege">Zurücksetzen</a>' if q else "")
            + "</form>"
        )

        rows = []
        for o in self._orders.list_orders():
            if not _matches(o.order_id, o.source_inquiry_id):
                continue
            if o.cancelled_at is not None:
                status = '<span class="cancelled">STORNIERT</span>'
                blocker = "–"
            else:
                ev = self.core.evaluate_ready_to_send(o.order_id)
                if ev.ready:
                    status = '<span class="ok">bereit</span>'
                    blocker = "–"
                else:
                    status = '<span class="blocked">blockiert</span>'
                    blocker = _e(_ready_to_send_blocker_label(ev.reasons[0])) if ev.reasons else "–"
            eff = "bestätigt" if o.effective_order_version_id else "noch nicht bestätigt"
            rows.append(
                f"<tr><td>{status}</td><td>{blocker}</td>"
                f"<td>{_e(o.source_inquiry_id[:8])}</td><td>{_e(eff)}</td>"
                f'<td><a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a></td></tr>'
            )

        body = (
            search_box
            + "<table><tr><th>Freigabe</th><th>Blocker</th>"
            "<th>Anfrage</th><th>Bestätigt</th><th>ID</th></tr>"
            + "".join(rows or ['<tr><td colspan="5">keine</td></tr>'])
            + "</table>"
        )
        return _page("Aufträge", body)

    # -- inquiries -------------------------------------------------------

    def render_inquiry_form(
        self,
        phone: str = "",
        event_date: str = "",
        guest_count_estimate: str = "",
        inquiry_source: str = "",
        intake_subject: str = "",
        intake_message: str = "",
        intake_summary: str = "",
        intake_external_ref: str = "",
    ) -> str:
        src_opts = "".join(
            f'<option value="{s}"{" selected" if s == inquiry_source else ""}>{s}</option>'
            for s in _OFFICE_SOURCES
        )
        # Rückruf -> Inquiry hint only (§11 addendum §14): Inquiry has no
        # phone/contact field at all (domain/inquiry.py), so this is never
        # written anywhere — it's page context for the office worker, shown
        # once, not a prefilled form field bound to any Inquiry attribute.
        phone_hint = f'<p class="subtitle">Anruf von: {_e(phone)}</p>' if phone else ""
        # event_date / guest_count_estimate / inquiry_source / intake_*:
        # optional prefill hints, from either the proposal preview's GET hint
        # (event_date/guest_count_estimate only, PROPOSAL_PREVIEW_MANUAL_
        # INQUIRY_PACK_V1 §4) or the POST prepare step (all seven,
        # PROPOSAL_PREVIEW_INTAKE_MAPPING_IMPLEMENTATION_PACK_V1 §5/§6).
        # Prefill only — every field stays editable and the submitted form
        # values are what create_inquiry sees; hints never override office
        # input and are never written anywhere by themselves.
        body = phone_hint + f"""<form method="post" action="/inquiry/new"><fieldset>
<p><label>Datum*</label><input type="date" name="event_date" value="{_e(event_date)}" required></p>
<p><label>Kanal</label><select name="inquiry_source">{src_opts}</select></p>
<p><label>Zeitfenster</label><input name="time_window_text"></p>
<p><label>Ort</label><input name="location_text"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" inputmode="numeric" value="{_e(guest_count_estimate)}"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(PLANNING_MODES[0])}</p>
<p><label>Rückruf-Verifizierung nötig</label><input type="checkbox" name="call_verification_required" value="1"></p>
<p class="subtitle">Intake-Kontext — keine Auftrags-/Küchenfreigabe.</p>
<p><label>Betreff</label><input name="intake_subject" value="{_e(intake_subject)}"></p>
<p><label>Nachricht</label><textarea name="intake_message" rows="4">{_e(intake_message)}</textarea></p>
<p><label>Zusammenfassung</label><textarea name="intake_summary" rows="3">{_e(intake_summary)}</textarea></p>
<p><label>Externe Referenz</label><input name="intake_external_ref" value="{_e(intake_external_ref)}"></p>
<p><button type="submit">Anfrage anlegen</button></p>
</fieldset></form>"""
        return _page("Neue Anfrage", body)

    def create_inquiry(self, form: dict[str, str]) -> Inquiry:
        required = form.get("call_verification_required") == "1"
        return self.inquiry_service.create_inquiry(
            event_date=date.fromisoformat(form["event_date"]),
            inquiry_source=form.get("inquiry_source", "manual"),
            crm_stage=CRM_PIPELINE[0],
            customer_linkage={},
            time_window_text=form.get("time_window_text", ""),
            location_text=form.get("location_text", ""),
            guest_count_estimate=_opt_int(form.get("guest_count_estimate", "")),
            planning_mode=form.get("planning_mode", PLANNING_MODES[0]),
            call_verification_required=required,
            call_verification_status="pending" if required else "not_required",
            intake_subject=form.get("intake_subject", ""),
            intake_message=form.get("intake_message", ""),
            intake_summary=form.get("intake_summary", ""),
            intake_external_ref=form.get("intake_external_ref", ""),
        )

    def render_inquiry(self, inquiry_id: str) -> str | None:
        inq = self._inquiries.get_by_id(inquiry_id)
        if inq is None:
            return None
        ev = self.progression.evaluate_inquiry_to_order_progression(inq)
        if ev.blocked:
            reasons = "".join(f"<li>{_e(_progression_blocker_label(r))}</li>" for r in ev.reasons)
            prog = f'<p class="blocked">Konvertierung blockiert:</p><ul>{reasons}</ul>'
        else:
            prog = '<p class="ok">Konvertierung möglich.</p>'
        verify_btn = ""
        if inq.call_verification_required and inq.call_verification_status != "verified":
            verify_btn = (
                f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/verify">'
                "<button>Telefonisch verifiziert</button></form> "
            )
        existing = [
            o for o in self._orders.list_orders() if o.source_inquiry_id == inquiry_id
        ]
        # Presentation only: only a non-cancelled order suppresses the convert
        # button — after Storno the office must be able to convert again.
        active = [o for o in existing if o.cancelled_at is None]
        convert = ""
        if existing:
            links = ", ".join(
                f'<a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a>'
                + (" (storniert)" if o.cancelled_at is not None else "")
                for o in existing
            )
            convert += f"<p>Auftrag vorhanden: {links}</p>"
        if not active:
            convert += (
                f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/convert">'
                "<button>In Auftrag umwandeln</button></form>"
            )
        guests = str(inq.guest_count_estimate) if inq.guest_count_estimate is not None else ""
        # Intake context: only shown as table rows when present, so an old
        # Inquiry from before this pack doesn't grow four "–" rows for
        # nothing (INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1 §6).
        intake_rows = "".join(
            f"<tr><th>{label}</th><td>{_e(value)}</td></tr>"
            for label, value in (
                ("Betreff", inq.intake_subject),
                ("Nachricht", inq.intake_message),
                ("Zusammenfassung", inq.intake_summary),
                ("Externe Referenz", inq.intake_external_ref),
            )
            if value
        )
        body = f"""<table>
<tr><th>Datum</th><td>{_e(inq.event_date.isoformat())}</td></tr>
<tr><th>Kanal</th><td>{_e(inq.inquiry_source)}</td></tr>
<tr><th>Zeitfenster</th><td>{_e(inq.time_window_text)}</td></tr>
<tr><th>Ort</th><td>{_e(inq.location_text)}</td></tr>
<tr><th>Gäste</th><td>{_e(guests or "–")}</td></tr>
<tr><th>CRM-Stufe</th><td>{_e(inq.crm_stage)}</td></tr>
<tr><th>Verifizierung</th><td>{_e(_verification_label(inq.call_verification_status))}</td></tr>
{intake_rows}</table>
<h2>Vorgangsprüfung (Progression)</h2>{prog}
<p>{verify_btn}{convert}</p>
<h2>Anfrage bearbeiten</h2>
<form method="post" action="/inquiry/{_e(inquiry_id)}/update"><fieldset>
<p><label>Datum</label><input type="date" name="event_date" value="{_e(inq.event_date.isoformat())}"></p>
<p><label>Zeitfenster</label><input name="time_window_text" value="{_e(inq.time_window_text)}"></p>
<p><label>Ort</label><input name="location_text" value="{_e(inq.location_text)}"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" value="{_e(guests)}"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(inq.planning_mode)}</p>
<p><label>CRM-Stufe</label>{_crm_stage_select(inq.crm_stage)}</p>
<p class="subtitle">Intake-Kontext — keine Auftrags-/Küchenfreigabe.</p>
<p><label>Betreff</label><input name="intake_subject" value="{_e(inq.intake_subject or "")}"></p>
<p><label>Nachricht</label><textarea name="intake_message" rows="4">{_e(inq.intake_message or "")}</textarea></p>
<p><label>Zusammenfassung</label><textarea name="intake_summary" rows="3">{_e(inq.intake_summary or "")}</textarea></p>
<p><label>Externe Referenz</label><input name="intake_external_ref" value="{_e(inq.intake_external_ref or "")}"></p>
<p><button type="submit">Speichern</button></p>
</fieldset></form>"""
        return _page(f"Anfrage {inq.inquiry_id[:8]}", body)

    def update_inquiry(self, inquiry_id: str, form: dict[str, str]) -> None:
        self.inquiry_service.update_inquiry(
            inquiry_id,
            event_date=date.fromisoformat(form["event_date"]),
            time_window_text=form.get("time_window_text", ""),
            location_text=form.get("location_text", ""),
            guest_count_estimate=_opt_int(form.get("guest_count_estimate", "")),
            planning_mode=form.get("planning_mode", PLANNING_MODES[0]),
            crm_stage=form.get("crm_stage", CRM_PIPELINE[0]),
            intake_subject=form.get("intake_subject", ""),
            intake_message=form.get("intake_message", ""),
            intake_summary=form.get("intake_summary", ""),
            intake_external_ref=form.get("intake_external_ref", ""),
        )

    # -- orders ----------------------------------------------------------

    def render_order(self, order_id: str) -> str | None:
        order = self._orders.get_order(order_id)
        if order is None:
            return None
        versions = self._orders.list_order_versions(order_id)
        cancelled = order.cancelled_at is not None
        rows = []
        for v in versions:
            printed = (
                v.kitchen_print_confirmed_at.isoformat()
                if v.kitchen_print_confirmed_at
                else "–"
            )
            marks = []
            if v.order_version_id == order.effective_order_version_id:
                marks.append("wirksam")
            if v.order_version_id == order.candidate_order_version_id:
                marks.append("Kandidat")
            actions = [
                f'<a href="/order/{_e(order_id)}/print?version={_e(v.order_version_id)}">Küchenzettel</a>'
            ]
            if not cancelled:
                if v.kitchen_print_confirmed_at is None:
                    actions.append(
                        f'<form class="inline" method="post" action="/order/{_e(order_id)}/print-confirm">'
                        f'<input type="hidden" name="order_version_id" value="{_e(v.order_version_id)}">'
                        "<button>Druck bestätigen</button></form>"
                    )
                if v.order_version_id != order.effective_order_version_id:
                    actions.append(
                        f'<form class="inline" method="post" action="/order/{_e(order_id)}/effective">'
                        f'<input type="hidden" name="order_version_id" value="{_e(v.order_version_id)}">'
                        "<button>Wirksam machen</button></form>"
                    )
            rows.append(
                f"<tr><td>v{v.version_number}</td><td>{_e(v.event_date.isoformat())}</td>"
                f"<td>{_e(v.time_window_text)}</td><td>{_e(v.location_text)}</td>"
                f"<td>{_e(str(v.guest_count_estimate) if v.guest_count_estimate is not None else '–')}</td>"
                f"<td>{_e(printed)}</td><td>{_e(', '.join(marks) or '–')}</td>"
                f"<td>{' '.join(actions)}</td></tr>"
            )
        ev = self.core.evaluate_ready_to_send(order_id)
        if ev.ready:
            release = '<p class="ok">READY_TO_SEND: bereit.</p>'
        else:
            reasons = "".join(f"<li>{_e(_ready_to_send_blocker_label(r))}</li>" for r in ev.reasons)
            release = f'<p class="blocked">Versandfreigabe blockiert:</p><ul>{reasons}</ul>'
        header = (
            '<p class="cancelled">STORNIERT</p>'
            if cancelled
            else ""
        )
        actions_block = ""
        if not cancelled:
            actions_block = f"""
<p>
<form class="inline" method="post" action="/order/{_e(order_id)}/ready"><button>Freigabe anfordern</button></form>
<form class="inline" method="post" action="/order/{_e(order_id)}/cancel"><button>Auftrag stornieren</button></form>
</p>
<h2>Neue Version</h2>
<form method="post" action="/order/{_e(order_id)}/version"><fieldset>
<p><label>Datum*</label><input type="date" name="event_date" required></p>
<p><label>Zeitfenster</label><input name="time_window_text"></p>
<p><label>Ort</label><input name="location_text"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" inputmode="numeric"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(PLANNING_MODES[0])}</p>
<p><button type="submit">Version anlegen</button></p>
</fieldset></form>"""
        body = f"""{header}
<p>Anfrage: <a href="/inquiry/{_e(order.source_inquiry_id)}">{_e(order.source_inquiry_id[:8])}</a></p>
<h2>Versionen</h2>
<table><tr><th>Nr</th><th>Datum</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th>
<th>Druck bestätigt</th><th>Status</th><th>Aktionen</th></tr>{''.join(rows)}</table>
<h2>Freigabe (READY_TO_SEND)</h2>{release}
{actions_block}"""
        return _page(f"Auftrag {order.order_id[:8]}", body)

    def create_version(self, order_id: str, form: dict[str, str]) -> None:
        order = self._orders.get_order(order_id)
        if order is None:
            raise ValueError(f"no order with id {order_id!r}")
        self.order_service.create_relevant_order_change_version(
            order,
            event_date=date.fromisoformat(form["event_date"]),
            time_window_text=form.get("time_window_text", ""),
            location_text=form.get("location_text", ""),
            guest_count_estimate=_opt_int(form.get("guest_count_estimate", "")),
            planning_mode=form.get("planning_mode", PLANNING_MODES[0]),
        )


def _opt_int(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    return int(raw)


def make_office_panel_handler(
    inquiry_repo: InquiryRepository,
    order_repo: OrderRepository,
    password: str,
    auerswald_url: str = "",
    auerswald_user: str = "",
    auerswald_password: str = "",
    kiosk_url: str = "",
) -> type[BaseHTTPRequestHandler]:
    panel = OfficePanel(inquiry_repo, order_repo, kiosk_url)
    expected = "Basic " + base64.b64encode(f"office:{password}".encode()).decode()

    class OfficePanelHandler(BaseHTTPRequestHandler):
        server_version = "OfficePanel/1.0"

        # -- plumbing --

        def _authorized(self) -> bool:
            return self.headers.get("Authorization") == expected

        def _deny(self) -> None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Office"')
            self.end_headers()

        def _html(self, page: str, status: int = 200) -> None:
            payload = page.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def _error_page(self, message: str, status: int = 400) -> None:
            global _sidebar_rueckruf_count
            _sidebar_rueckruf_count = fetch_rueckruf_count(
                auerswald_url, auerswald_user, auerswald_password
            )
            self._html(_page("Fehler", f'<p class="blocked">{_e(message)}</p>'), status)

        def _form(self) -> dict[str, str]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        # -- routing --

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorized():
                self._deny()
                return
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            global _sidebar_rueckruf_count
            if parts == ["rueckruf"]:
                # Reuse this one fetch for both the list and the sidebar
                # badge — no second request (owner requirement).
                items, error = fetch_missed_board(auerswald_url, auerswald_user, auerswald_password)
                _sidebar_rueckruf_count = len(items) if items else None
                self._html(render_rueckruf(items, error))
                return
            if not parts:
                # "/" also needs the actual rows (not just the count) for
                # the Rückruf-nötig queue (§11 addendum) — same one fetch
                # covers both the queue and the sidebar badge, still no
                # second auerswald-sync request per page.
                items, error = fetch_missed_board(auerswald_url, auerswald_user, auerswald_password)
                _sidebar_rueckruf_count = len(items) if items else None
                self._html(panel.render_queue(items))
                return
            _sidebar_rueckruf_count = fetch_rueckruf_count(
                auerswald_url, auerswald_user, auerswald_password
            )
            if parts == ["anfragen"]:
                q = parse_qs(parsed.query).get("q", [""])[0]
                self._html(panel.render_anfragen(q))
            elif parts == ["auftraege"]:
                q = parse_qs(parsed.query).get("q", [""])[0]
                self._html(panel.render_auftraege(q))
            elif parts == ["proposal-preview"]:
                self._html(render_proposal_preview_form())
            elif parts == ["inquiry", "new"]:
                q = parse_qs(parsed.query)
                self._html(
                    panel.render_inquiry_form(
                        phone=q.get("phone", [""])[0],
                        event_date=q.get("event_date", [""])[0],
                        guest_count_estimate=q.get("guest_count_estimate", [""])[0],
                    )
                )
            elif len(parts) == 2 and parts[0] == "inquiry":
                page = panel.render_inquiry(parts[1])
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] == "order":
                page = panel.render_order(parts[1])
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 3 and parts[0] == "order" and parts[2] == "print":
                self._print_sheet(parts[1], parsed.query)
            else:
                self.send_error(404)

        def _print_sheet(self, order_id: str, query: str) -> None:
            vid = parse_qs(query).get("version", [""])[0]
            order = order_repo.get_order(order_id)
            version = order_repo.get_order_version(vid) if vid else None
            if order is None or version is None or version.order_id != order_id:
                self.send_error(404)
                return
            self._html(render_print_sheet(order, version))

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                self._deny()
                return
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            try:
                self._route_post(parts)
            except (ValueError, KeyError) as exc:
                self._error_page(str(exc))

        def _route_post(self, parts: list[str]) -> None:
            if parts == ["inquiry", "new"]:
                inq = panel.create_inquiry(self._form())
                self._redirect(f"/inquiry/{inq.inquiry_id}")
            elif len(parts) == 3 and parts[0] == "inquiry":
                self._inquiry_action(parts[1], parts[2])
            elif len(parts) == 3 and parts[0] == "order":
                self._order_action(parts[1], parts[2])
            elif parts == ["proposal-preview"]:
                # Parse-and-render only (CONFIGURATOR_OFFICE_MANUAL_HANDOFF
                # pack): nothing is persisted and nothing is created, so
                # there is deliberately no redirect — the preview itself is
                # the whole result. Invalid payloads raise ValueError and
                # land in do_POST's existing 400 error page.
                payload = parse_proposal_payload(self._form().get("payload_json", ""))
                # This POST renders a full page directly (no redirect into
                # do_GET), so refresh the sidebar badge like do_GET does.
                global _sidebar_rueckruf_count
                _sidebar_rueckruf_count = fetch_rueckruf_count(
                    auerswald_url, auerswald_user, auerswald_password
                )
                self._html(render_proposal_preview(payload))
            elif parts == ["proposal-preview", "prepare"]:
                # PROPOSAL_PREVIEW_INTAKE_MAPPING_IMPLEMENTATION_PACK_V1 §6:
                # re-parses the same hidden payload with the exact same
                # validator as the preview above (single source of
                # validation) and renders the Inquiry form pre-filled —
                # still parse-and-render only, no repository write anywhere
                # in this branch, no redirect (nothing was written).
                payload = parse_proposal_payload(self._form().get("payload_json", ""))
                summary_lines = "\n".join(
                    f"{item['name']} × {item['quantity']}"
                    if item.get("quantity") is not None
                    else item["name"]
                    for item in payload["selected_items"]
                )
                self._html(
                    panel.render_inquiry_form(
                        event_date=payload["event_date"],
                        guest_count_estimate=str(payload["guest_count"]),
                        inquiry_source="configurator",
                        intake_subject=payload["title"],
                        intake_message=payload.get("notes") or "",
                        intake_summary=summary_lines,
                        intake_external_ref=payload.get("proposal_id") or "",
                    )
                )
            elif parts == ["rueckruf", "resolve"]:
                call_id = self._form()["call_id"]
                resolve_missed_call(auerswald_url, auerswald_user, auerswald_password, call_id)
                self._redirect("/rueckruf")
            else:
                self.send_error(404)

        def _inquiry_action(self, inquiry_id: str, action: str) -> None:
            if action == "update":
                panel.update_inquiry(inquiry_id, self._form())
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "verify":
                panel.inquiry_service.verify_customer_by_call(inquiry_id)
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "convert":
                inq = inquiry_repo.get_by_id(inquiry_id)
                if inq is None:
                    self.send_error(404)
                    return
                order, _v1 = panel.order_service.convert_inquiry_to_order(inq)
                self._redirect(f"/order/{order.order_id}")
            else:
                self.send_error(404)

        def _order_action(self, order_id: str, action: str) -> None:
            if action == "version":
                panel.create_version(order_id, self._form())
            elif action == "print-confirm":
                panel.core.confirm_kitchen_print(order_id, self._form()["order_version_id"])
            elif action == "effective":
                panel.core.make_order_version_effective(
                    order_id, self._form()["order_version_id"]
                )
            elif action == "ready":
                panel.core.request_ready_to_send(order_id)
            elif action == "cancel":
                panel.core.cancel_order(order_id)
            else:
                self.send_error(404)
                return
            self._redirect(f"/order/{order_id}")

    return OfficePanelHandler


def create_office_panel_server(
    inquiry_repo: InquiryRepository,
    order_repo: OrderRepository,
    password: str,
    host: str = "0.0.0.0",
    port: int = 8081,
    auerswald_url: str = "",
    auerswald_user: str = "",
    auerswald_password: str = "",
    kiosk_url: str = "",
) -> HTTPServer:
    # Single-threaded on purpose: the shared sqlite3 connections must stay on the
    # thread that serves requests (bring-up bug, WORKLOG Entry 048). This also
    # serializes writes — desirable on SQLite for a 1–2-person office.
    return HTTPServer(
        (host, port),
        make_office_panel_handler(
            inquiry_repo,
            order_repo,
            password,
            auerswald_url,
            auerswald_user,
            auerswald_password,
            kiosk_url,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Office panel (LAN-only write surface)")
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--password",
        default=os.environ.get("OFFICE_PANEL_PASSWORD", ""),
        help="Office password (or set OFFICE_PANEL_PASSWORD)",
    )
    parser.add_argument(
        "--auerswald-url",
        default=os.environ.get("AUERSWALD_SYNC_URL", ""),
        help="Base URL of the separate auerswald-sync call-log service "
        "(or set AUERSWALD_SYNC_URL) — read-only Rückrufe list, optional",
    )
    parser.add_argument(
        "--auerswald-user",
        default=os.environ.get("AUERSWALD_SYNC_USER", ""),
        help="Basic auth user for auerswald-sync (or set AUERSWALD_SYNC_USER)",
    )
    parser.add_argument(
        "--auerswald-password",
        default=os.environ.get("AUERSWALD_SYNC_PASSWORD", ""),
        help="Basic auth password for auerswald-sync (or set AUERSWALD_SYNC_PASSWORD)",
    )
    parser.add_argument(
        "--kiosk-url",
        default=os.environ.get("KIOSK_URL", ""),
        help="Base URL of the separate kitchen kiosk (or set KIOSK_URL) — "
        "single source of truth for the optional 'full week' deep link, optional",
    )
    args = parser.parse_args()
    if not args.password:
        raise SystemExit(
            "office panel refuses to start without a password "
            "(--password or OFFICE_PANEL_PASSWORD): it is a write surface (pack §7)"
        )

    from catering_system.repositories.sqlite_inquiry_repository import SQLiteInquiryRepository
    from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository

    server = create_office_panel_server(
        SQLiteInquiryRepository(args.db),
        SQLiteOrderRepository(args.db),
        args.password,
        args.host,
        args.port,
        args.auerswald_url,
        args.auerswald_user,
        args.auerswald_password,
        args.kiosk_url,
    )
    print(f"Office panel on http://{args.host}:{args.port}/ (user: office)")
    server.serve_forever()


if __name__ == "__main__":
    main()

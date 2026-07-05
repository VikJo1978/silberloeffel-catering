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
import os
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from catering_system.domain.inquiry import CRM_PIPELINE, Inquiry, PLANNING_MODES
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.progression_service import ProgressionService

_OFFICE_SOURCES = ("phone", "email", "manual")

_STYLE = """
body { font-family: sans-serif; margin: 2rem; max-width: 70rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }
th, td { border: 1px solid #999; padding: 0.4rem 0.8rem; text-align: left; }
th { background: #eee; }
h1 { font-size: 1.5rem; } h2 { font-size: 1.2rem; margin-top: 2rem; }
form.inline { display: inline; }
.blocked { color: #a00; } .ok { color: #070; } .cancelled { color: #a00; font-weight: bold; }
button { padding: 0.3rem 0.8rem; }
fieldset { margin-bottom: 1rem; }
label { display: inline-block; min-width: 12rem; }
"""


def _e(text: object) -> str:
    return html.escape(str(text))


def _page(title: str, body: str) -> str:
    return (
        f'<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
        f"<title>{_e(title)}</title><style>{_STYLE}</style></head>"
        f'<body><p><a href="/">&larr; Übersicht</a></p><h1>{_e(title)}</h1>{body}</body></html>'
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


class OfficePanel:
    """Route handling and rendering; kept separate from the HTTP handler for testability."""

    def __init__(self, inquiry_repo: InquiryRepository, order_repo: OrderRepository) -> None:
        self._inquiries = inquiry_repo
        self._orders = order_repo
        self.inquiry_service = InquiryService(inquiry_repo)
        self.order_service = OrderService(order_repo)
        self.core = OperationalCoreService(order_repo)
        self.progression = ProgressionService(order_repo)

    # -- queue -----------------------------------------------------------

    def render_queue(self) -> str:
        inquiry_rows = []
        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for o in orders:
            orders_by_inquiry.setdefault(o.source_inquiry_id, []).append(o)
        for inq in self._inquiries.list_all():
            has_order = "ja" if inq.inquiry_id in orders_by_inquiry else "–"
            inquiry_rows.append(
                f'<tr><td><a href="/inquiry/{_e(inq.inquiry_id)}">{_e(inq.inquiry_id[:8])}</a></td>'
                f"<td>{_e(inq.event_date.isoformat())}</td><td>{_e(inq.location_text)}</td>"
                f"<td>{_e(inq.crm_stage)}</td><td>{_e(inq.call_verification_status)}</td>"
                f"<td>{has_order}</td></tr>"
            )
        order_rows = []
        for o in orders:
            if o.cancelled_at is not None:
                status = '<span class="cancelled">STORNIERT</span>'
            else:
                ev = self.core.evaluate_ready_to_send(o.order_id)
                status = (
                    '<span class="ok">bereit</span>'
                    if ev.ready
                    else f'<span class="blocked">blockiert</span>'
                )
            eff = "ja" if o.effective_order_version_id else "–"
            order_rows.append(
                f'<tr><td><a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a></td>'
                f"<td>{_e(o.source_inquiry_id[:8])}</td><td>{eff}</td><td>{status}</td></tr>"
            )
        body = (
            '<p><a href="/inquiry/new">+ Neue Anfrage erfassen</a></p>'
            "<h2>Anfragen</h2><table><tr><th>ID</th><th>Datum</th><th>Ort</th>"
            "<th>CRM-Stufe</th><th>Verifizierung</th><th>Auftrag</th></tr>"
            + "".join(inquiry_rows or ['<tr><td colspan="6">keine</td></tr>'])
            + "</table><h2>Aufträge</h2><table><tr><th>ID</th><th>Anfrage</th>"
            "<th>Wirksam</th><th>Freigabe</th></tr>"
            + "".join(order_rows or ['<tr><td colspan="4">keine</td></tr>'])
            + "</table>"
        )
        return _page("Büro-Übersicht", body)

    # -- inquiries -------------------------------------------------------

    def render_inquiry_form(self) -> str:
        src_opts = "".join(f'<option value="{s}">{s}</option>' for s in _OFFICE_SOURCES)
        body = f"""<form method="post" action="/inquiry/new"><fieldset>
<p><label>Datum*</label><input type="date" name="event_date" required></p>
<p><label>Kanal</label><select name="inquiry_source">{src_opts}</select></p>
<p><label>Zeitfenster</label><input name="time_window_text"></p>
<p><label>Ort</label><input name="location_text"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" inputmode="numeric"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(PLANNING_MODES[0])}</p>
<p><label>Rückruf-Verifizierung nötig</label><input type="checkbox" name="call_verification_required" value="1"></p>
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
        )

    def render_inquiry(self, inquiry_id: str) -> str | None:
        inq = self._inquiries.get_by_id(inquiry_id)
        if inq is None:
            return None
        ev = self.progression.evaluate_inquiry_to_order_progression(inq)
        if ev.blocked:
            reasons = "".join(f"<li>{_e(r)}</li>" for r in ev.reasons)
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
        if existing:
            links = ", ".join(
                f'<a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a>' for o in existing
            )
            convert = f"<p>Auftrag vorhanden: {links}</p>"
        else:
            convert = (
                f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/convert">'
                "<button>In Auftrag umwandeln</button></form>"
            )
        guests = str(inq.guest_count_estimate) if inq.guest_count_estimate is not None else ""
        body = f"""<table>
<tr><th>Datum</th><td>{_e(inq.event_date.isoformat())}</td></tr>
<tr><th>Kanal</th><td>{_e(inq.inquiry_source)}</td></tr>
<tr><th>Zeitfenster</th><td>{_e(inq.time_window_text)}</td></tr>
<tr><th>Ort</th><td>{_e(inq.location_text)}</td></tr>
<tr><th>Gäste</th><td>{_e(guests or "–")}</td></tr>
<tr><th>CRM-Stufe</th><td>{_e(inq.crm_stage)}</td></tr>
<tr><th>Verifizierung</th><td>{_e(inq.call_verification_status)}</td></tr>
</table>
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
            reasons = "".join(f"<li>{_e(r)}</li>" for r in ev.reasons)
            release = f'<p class="blocked">READY_TO_SEND blockiert:</p><ul>{reasons}</ul>'
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
) -> type[BaseHTTPRequestHandler]:
    panel = OfficePanel(inquiry_repo, order_repo)
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
            if not parts:
                self._html(panel.render_queue())
            elif parts == ["inquiry", "new"]:
                self._html(panel.render_inquiry_form())
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
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host, port), make_office_panel_handler(inquiry_repo, order_repo, password)
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
    )
    print(f"Office panel on http://{args.host}:{args.port}/ (user: office)")
    server.serve_forever()


if __name__ == "__main__":
    main()

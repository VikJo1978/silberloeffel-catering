"""Kitchen kiosk — read-only Wochenübersicht display (KIOSK_EXECUTION_PACK_V1).

stdlib-only HTTP server. GET is the only allowed method; the kiosk writes
nothing, ever. All order-originating text is HTML-escaped before rendering.
"""

from __future__ import annotations

import argparse
import html
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from catering_system.domain.wochenuebersicht import Wochenuebersicht
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.wochenuebersicht_service import WochenuebersichtService

_WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def render_wochenuebersicht_html(view: Wochenuebersicht) -> str:
    """Pure renderer: Wochenübersicht read model → kitchen-display HTML."""
    rows: list[str] = []
    for e in view.entries:
        weekday = _WEEKDAYS_DE[e.event_date.weekday()]
        guests = str(e.guest_count_estimate) if e.guest_count_estimate is not None else "–"
        rows.append(
            "<tr>"
            f"<td>{weekday} {html.escape(e.event_date.isoformat())}</td>"
            f"<td>{html.escape(e.time_window_text)}</td>"
            f"<td>{html.escape(e.location_text)}</td>"
            f"<td>{html.escape(guests)}</td>"
            f"<td>v{e.version_number}</td>"
            "</tr>"
        )
    body = (
        "\n".join(rows)
        if rows
        else '<tr><td colspan="5">Keine Lieferungen in dieser Woche</td></tr>'
    )
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="60">
<title>Wochenübersicht KW {view.iso_week}/{view.iso_year}</title>
<style>
body {{ font-family: sans-serif; font-size: 1.4rem; margin: 2rem; }}
h1 {{ font-size: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #444; padding: 0.6rem 1rem; text-align: left; }}
th {{ background: #eee; }}
</style>
</head>
<body>
<h1>Wochenübersicht — KW {view.iso_week}/{view.iso_year}</h1>
<table>
<tr><th>Tag</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th><th>Version</th></tr>
{body}
</table>
</body>
</html>
"""


def _requested_week(query: str) -> tuple[int, int]:
    params = parse_qs(query)
    today = date.today().isocalendar()
    try:
        year = int(params["year"][0]) if "year" in params else today.year
        week = int(params["week"][0]) if "week" in params else today.week
    except (ValueError, IndexError):
        return today.year, today.week
    return year, week


def make_kiosk_handler(order_repository: OrderRepository) -> type[BaseHTTPRequestHandler]:
    service = WochenuebersichtService(order_repository)

    class KioskHandler(BaseHTTPRequestHandler):
        server_version = "KitchenKiosk/1.0"

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            parsed = urlparse(self.path)
            if parsed.path != "/":
                self.send_error(404)
                return
            year, week = _requested_week(parsed.query)
            page = render_wochenuebersicht_html(service.get_week_overview(year, week))
            payload = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _reject(self) -> None:
            self.send_error(405, "kiosk is read-only")

        do_POST = _reject
        do_PUT = _reject
        do_DELETE = _reject
        do_PATCH = _reject

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # kiosk display: no per-request stderr noise

    return KioskHandler


def create_kiosk_server(
    order_repository: OrderRepository, host: str = "0.0.0.0", port: int = 8080
) -> HTTPServer:
    # Single-threaded on purpose: the shared sqlite3 connection must stay on the
    # thread that serves requests (bring-up bug, WORKLOG Entry 048). A read-only
    # display with one client does not need request threading.
    return HTTPServer((host, port), make_kiosk_handler(order_repository))


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only kitchen kiosk display")
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository

    server = create_kiosk_server(SQLiteOrderRepository(args.db), args.host, args.port)
    print(f"Kitchen kiosk (read-only) on http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Kitchen kiosk — read-only Wochenübersicht display (KIOSK_EXECUTION_PACK_V1).

stdlib-only HTTP server. GET is the only allowed method; the kiosk writes
nothing, ever. All order-originating text is HTML-escaped before rendering.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from catering_system.domain.wochenuebersicht import (
    Wochenuebersicht,
    WochenuebersichtEntry,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.wochenuebersicht_service import WochenuebersichtService

_WEEKDAYS_DE = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)


def render_wochenuebersicht_html(view: Wochenuebersicht) -> str:
    """Pure renderer: Wochenübersicht read model → kitchen-display HTML."""
    rows: list[str] = []
    for e in view.entries:
        weekday = _WEEKDAYS_DE[e.event_date.weekday()]
        guests = (
            str(e.guest_count_estimate) if e.guest_count_estimate is not None else "–"
        )
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


_FEED_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_order_feed_date(query: str) -> date | None:
    """KIOSK_ORDER_FEED_PACK_V1 §3: exactly one parameter, `date`, exactly one
    strict YYYY-MM-DD value naming a real calendar date — anything else is None
    (→ 400). Unknown extra parameters are rejected, not ignored."""
    params = parse_qs(query, keep_blank_values=True)
    if set(params) != {"date"} or len(params["date"]) != 1:
        return None
    raw = params["date"][0]
    if not _FEED_DATE_RE.fullmatch(raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def render_order_feed_json(
    feed_date: date, entries: tuple[WochenuebersichtEntry, ...]
) -> bytes:
    """Pure renderer: per-date entries → courier order feed document (pack §3).

    Exactly the courier app's CoreOrderSummary slice; version numbers,
    planning mode, and direct customer identity and contact fields stay out.
    The event address itself remains sensitive operational data."""
    document = {
        "date": feed_date.isoformat(),
        "orders": [
            {
                "order_id": e.order_id,
                "event_date": e.event_date.isoformat(),
                "time_window_text": e.time_window_text,
                "location_text": e.location_text,
                "guest_count_estimate": e.guest_count_estimate,
            }
            for e in entries
        ],
    }
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def _requested_week(query: str) -> tuple[int, int]:
    params = parse_qs(query)
    today = date.today().isocalendar()
    try:
        year = int(params["year"][0]) if "year" in params else today.year
        week = int(params["week"][0]) if "week" in params else today.week
    except (ValueError, IndexError):
        return today.year, today.week
    return year, week


def make_kiosk_handler(
    order_repository: OrderRepository,
) -> type[BaseHTTPRequestHandler]:
    service = WochenuebersichtService(order_repository)

    class KioskHandler(BaseHTTPRequestHandler):
        server_version = "KitchenKiosk/1.0"

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "base-uri 'none'; frame-ancestors 'none'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            parsed = urlparse(self.path)
            if parsed.path == "/api/order-feed":
                feed_date = parse_order_feed_date(parsed.query)
                if feed_date is None:
                    self.send_error(400, "date must be one strict YYYY-MM-DD value")
                    return
                payload = render_order_feed_json(
                    feed_date, service.get_day_overview(feed_date)
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
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

    from catering_system.repositories.sqlite_order_repository import (
        SQLiteOrderRepository,
    )

    server = create_kiosk_server(SQLiteOrderRepository(args.db), args.host, args.port)
    print(f"Kitchen kiosk (read-only) on http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()

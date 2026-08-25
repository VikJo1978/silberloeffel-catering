"""Kitchen kiosk — read-only Wochenübersicht display (KIOSK_EXECUTION_PACK_V1).

stdlib-only HTTP server. GET is the only allowed method; the kiosk writes
nothing, ever. All order-originating text is HTML-escaped before rendering.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections.abc import Mapping
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from catering_system.domain.offer_charges import ReturnLogisticsDefinition
from catering_system.domain.wochenuebersicht import (
    Wochenuebersicht,
    WochenuebersichtEntry,
)
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.services.wochenuebersicht_service import WochenuebersichtService
from catering_system.ui.operational_pause_labels import pause_reason_label
from catering_system.ui.pickup_signal import (
    PickupSignalRefresher,
    render_pickup_signal_section,
)

_WEEKDAYS_DE = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)


def render_wochenuebersicht_html(
    view: Wochenuebersicht, pickup_section: str = ""
) -> str:
    """Pure renderer: Wochenübersicht read model → kitchen-display HTML.

    `pickup_section` is a pre-rendered, pre-escaped HTML fragment from
    pickup_signal.render_pickup_signal_section; empty when the signal
    feature is dormant. The insertion is fully conditional so the dormant
    page stays byte-identical to the pre-feature output (pinned by a golden
    test).
    """
    pickup_block = f"\n{pickup_section}" if pickup_section else ""
    rows: list[str] = []
    for e in view.entries:
        weekday = _WEEKDAYS_DE[e.event_date.weekday()]
        guests = (
            str(e.guest_count_estimate) if e.guest_count_estimate is not None else "–"
        )
        status = "–"
        if e.operational_pause_active:
            status_lines = ["<strong>PAUSIERT</strong>"]
            reason_label = pause_reason_label(e.operational_pause_reason_code)
            if reason_label:
                status_lines.append(f"Grund: {html.escape(reason_label)}")
            note = (e.operational_pause_note or "").strip()
            if note:
                status_lines.append(f"Hinweis: {html.escape(note)}")
            status = "<br>".join(status_lines)
        rows.append(
            "<tr>"
            f"<td>{weekday} {html.escape(e.event_date.isoformat())}</td>"
            f"<td>{html.escape(e.time_window_text)}</td>"
            f"<td>{html.escape(e.location_text)}</td>"
            f"<td>{html.escape(guests)}</td>"
            f"<td>v{e.version_number}</td>"
            f"<td>{status}</td>"
            "</tr>"
        )
    body = (
        "\n".join(rows)
        if rows
        else '<tr><td colspan="6">Keine Lieferungen in dieser Woche</td></tr>'
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
<tr><th>Tag</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th><th>Version</th><th>Status</th></tr>
{body}
</table>{pickup_block}
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


def next_return_working_day(event_date: date) -> date:
    """Return the next Monday-Friday date after ``event_date``.

    Issue #171 deliberately does not invent public-holiday knowledge: Core has
    no business-calendar source yet. Weekend skipping is deterministic and the
    only working-day rule this projection may truthfully derive today.
    """
    candidate = event_date + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _return_logistics_projection(
    event_date: date, definition: ReturnLogisticsDefinition | None
) -> dict[str, str | None] | None:
    if definition is None:
        return None
    return_date = (
        event_date
        if definition.mode == "SAME_DAY"
        else next_return_working_day(event_date)
    )
    return {
        "mode": definition.mode,
        "return_date": return_date.isoformat(),
        "pickup_window_text": definition.pickup_window_text,
    }


def render_order_feed_json(
    feed_date: date,
    entries: tuple[WochenuebersichtEntry, ...],
    return_logistics_by_order_id: Mapping[str, ReturnLogisticsDefinition | None]
    | None = None,
) -> bytes:
    """Pure renderer: per-date entries → courier order feed document (v2).

    Selection still comes exclusively from ``WochenuebersichtService``. The
    additive ``return_logistics`` planning fact is joined from the immutable
    accepted OrderCommercialSnapshot. Prices and courier execution state stay
    out of this payload.
    """
    return_logistics = return_logistics_by_order_id or {}
    document = {
        "date": feed_date.isoformat(),
        "orders": [
            {
                "order_id": e.order_id,
                "event_date": e.event_date.isoformat(),
                "time_window_text": e.time_window_text,
                "location_text": e.location_text,
                "guest_count_estimate": e.guest_count_estimate,
                "return_logistics": _return_logistics_projection(
                    e.event_date, return_logistics.get(e.order_id)
                ),
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
    pickup_signal: PickupSignalRefresher | None = None,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository | None = None,
) -> type[BaseHTTPRequestHandler]:
    service = WochenuebersichtService(
        order_repository, pause_repository=pause_repository
    )

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
                entries = service.get_day_overview(feed_date)
                return_logistics_by_order_id: dict[
                    str, ReturnLogisticsDefinition | None
                ] = {}
                if commercial_snapshot_repository is not None:
                    for entry in entries:
                        snapshot = commercial_snapshot_repository.get_by_order_id(
                            entry.order_id
                        )
                        return_logistics_by_order_id[entry.order_id] = (
                            snapshot.return_logistics if snapshot is not None else None
                        )
                payload = render_order_feed_json(
                    feed_date, entries, return_logistics_by_order_id
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
            pickup_section = (
                render_pickup_signal_section(pickup_signal.snapshot())
                if pickup_signal is not None
                else ""
            )
            page = render_wochenuebersicht_html(
                service.get_week_overview(year, week), pickup_section
            )
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
    order_repository: OrderRepository,
    host: str = "0.0.0.0",
    port: int = 8080,
    pickup_signal: PickupSignalRefresher | None = None,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository | None = None,
) -> HTTPServer:
    # Single-threaded on purpose: the shared sqlite3 connection must stay on the
    # thread that serves requests (bring-up bug, WORKLOG Entry 048). A read-only
    # display with one client does not need request threading. The pickup-signal
    # refresher is a separate thread but touches no SQLite.
    return HTTPServer(
        (host, port),
        make_kiosk_handler(
            order_repository,
            pickup_signal,
            pause_repository=pause_repository,
            commercial_snapshot_repository=commercial_snapshot_repository,
        ),
    )


def main() -> None:
    import os

    parser = argparse.ArgumentParser(description="Read-only kitchen kiosk display")
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--pickup-signal-url",
        default=os.environ.get("PICKUP_SIGNAL_URL", ""),
        help="Courier-app overdue-pickup feed URL (loopback in production). "
        "The bearer token comes ONLY from the PICKUP_SIGNAL_TOKEN environment "
        "variable — never from an argument (pack §5.1). Empty + empty token: "
        "the feature is dormant.",
    )
    args = parser.parse_args()

    signal_url = args.pickup_signal_url
    signal_token = os.environ.get("PICKUP_SIGNAL_TOKEN", "")
    if bool(signal_url) != bool(signal_token):
        raise SystemExit(
            "pickup signal needs PICKUP_SIGNAL_URL and PICKUP_SIGNAL_TOKEN "
            "together; refusing to start half-configured"
        )
    pickup_signal = (
        PickupSignalRefresher(signal_url, signal_token) if signal_url else None
    )

    from catering_system.repositories.sqlite_order_operational_pause_repository import (
        SQLiteOrderOperationalPauseRepository,
    )
    from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
        SQLiteOrderCommercialSnapshotRepository,
    )
    from catering_system.repositories.sqlite_order_repository import (
        SQLiteOrderRepository,
    )

    order_repo = SQLiteOrderRepository(args.db)
    pause_repo = SQLiteOrderOperationalPauseRepository(args.db)
    commercial_snapshot_repo = SQLiteOrderCommercialSnapshotRepository(args.db)
    server = create_kiosk_server(
        order_repo,
        args.host,
        args.port,
        pickup_signal,
        pause_repository=pause_repo,
        commercial_snapshot_repository=commercial_snapshot_repo,
    )
    if pickup_signal is not None:
        pickup_signal.start()
    print(f"Kitchen kiosk (read-only) on http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    finally:
        if pickup_signal is not None:
            pickup_signal.stop()


if __name__ == "__main__":
    main()

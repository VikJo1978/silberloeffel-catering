"""Kiosk-side pickup signal — parse, refresher lifecycle, rendering
(KIOSK_PICKUP_SIGNAL_PACK_V1 §8). HTTP cases run against a live local
fixture, same style as the order-feed tests in the courier repository."""

from __future__ import annotations

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from catering_system.ui.pickup_signal import (
    PickupSignalDocument,
    PickupSignalRefresher,
    fetch_pickup_signal,
    parse_pickup_signal,
    render_pickup_signal_section,
)

_DAY = date(2026, 7, 13)


def _document_bytes(
    pickups: list[dict],
    *,
    day: str = "2026-07-13",
    total_count: int | None = None,
    truncated: bool = False,
) -> bytes:
    return json.dumps(
        {
            "date": day,
            "total_count": total_count if total_count is not None else len(pickups),
            "truncated": truncated,
            "pickups": pickups,
        }
    ).encode("utf-8")


_GOOD_PICKUP = {
    "location_text": "Musterstraße 1, Hamburg",
    "event_date": "2026-07-10",
    "items": [
        {"name": "Chafing-Dish", "quantity": 2},
        {"name": "Platten", "quantity": None},
    ],
    "courier_name": "Max",
}


# --- parse -----------------------------------------------------------------


def test_parse_happy_path() -> None:
    document = parse_pickup_signal(_document_bytes([_GOOD_PICKUP]))
    assert document is not None
    assert document.date == _DAY
    assert document.total_count == 1 and document.truncated is False
    pickup = document.pickups[0]
    assert pickup.location_text == "Musterstraße 1, Hamburg"
    assert pickup.event_date == date(2026, 7, 10)
    assert [(i.name, i.quantity) for i in pickup.items] == [
        ("Chafing-Dish", 2),
        ("Platten", None),
    ]
    assert pickup.courier_name == "Max"


def test_parse_null_courier_name() -> None:
    document = parse_pickup_signal(
        _document_bytes([dict(_GOOD_PICKUP, courier_name=None)])
    )
    assert document is not None
    assert document.pickups[0].courier_name is None


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b'{"unexpected": "shape"}',
        _document_bytes([{"location_text": "x"}]),  # missing contract fields
        json.dumps(
            {
                "date": "2026-07-13",
                "total_count": 0,
                "truncated": False,
                "pickups": "nope",
            }
        ).encode(),
        b"x" * (256 * 1024 + 1),  # over the body limit
        _document_bytes(
            [dict(_GOOD_PICKUP, items=[{"name": "N", "quantity": 1}] * 21)]
        ),  # over the items-per-pickup limit
    ],
)
def test_parse_rejects_malformed_and_overlimit(raw: bytes) -> None:
    assert parse_pickup_signal(raw) is None


@pytest.mark.parametrize(
    "mutation",
    [
        {"location_text": "L" * 201},  # over-length is malformed, not clipped
        {"courier_name": "C" * 201},
        {"items": [{"name": "N" * 201, "quantity": 1}]},
        {"location_text": 7},  # exact JSON types, no coercion
        {"event_date": "2026-7-4"},
        {"event_date": 20260704},
        {"items": [{"name": "N", "quantity": 2.9}]},  # float must not truncate
        {"items": [{"name": "N", "quantity": True}]},  # bool is not a count
        {"items": [{"name": "N", "quantity": -1}]},
        {"courier_name": 5},
    ],
)
def test_parse_rejects_type_violations(mutation: dict) -> None:
    assert (
        parse_pickup_signal(_document_bytes([dict(_GOOD_PICKUP, **mutation)])) is None
    )


@pytest.mark.parametrize(
    ("total_count", "truncated"),
    [
        ("1", False),  # string count: '"false"-style' coercion must not pass
        (-1, False),
        (True, False),  # bool is an int subclass but not a count
        (2, False),  # untruncated must list everything it counts
        (0, True),  # truncated may under-report the list, never the count
        (1, "false"),  # string "false" is truthy, not a bool
    ],
)
def test_parse_rejects_inconsistent_envelope(total_count, truncated) -> None:
    raw = json.dumps(
        {
            "date": "2026-07-13",
            "total_count": total_count,
            "truncated": truncated,
            "pickups": [_GOOD_PICKUP],
        }
    ).encode("utf-8")
    assert parse_pickup_signal(raw) is None


def test_render_clips_oversized_values_defensively() -> None:
    """The parser rejects over-length values; the renderer keeps its own
    guard for any other document source. Each value is clipped on its own —
    a joined items line is never clipped as a whole."""
    from catering_system.ui.pickup_signal import (
        OverduePickup,
        PickupItem,
        PickupSignalDocument,
    )

    document = PickupSignalDocument(
        date=_DAY,
        total_count=1,
        truncated=False,
        pickups=(
            OverduePickup(
                location_text="L" * 500,
                event_date=date(2026, 7, 10),
                items=(PickupItem("N" * 500, 1), PickupItem("Zweites", None)),
                courier_name="C" * 500,
            ),
        ),
    )
    html = render_pickup_signal_section(document)
    assert "L" * 200 in html and "L" * 201 not in html
    assert "N" * 200 in html and "N" * 201 not in html
    assert "C" * 200 in html and "C" * 201 not in html
    assert "Zweites" in html  # later item survives per-value clipping


# --- fetch over live HTTP ----------------------------------------------------


def _serve(payload: bytes, status: int = 200) -> tuple[HTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        captured_auth: str | None = None

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            type(self).captured_auth = self.headers.get("Authorization")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/api/overdue-pickups"


def test_fetch_sends_bearer_and_parses() -> None:
    server, url = _serve(_document_bytes([_GOOD_PICKUP]))
    try:
        document = fetch_pickup_signal(url, "secret-token")
        assert document is not None and len(document.pickups) == 1
        assert server.RequestHandlerClass.captured_auth == "Bearer secret-token"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("status", [401, 400, 500])
def test_fetch_non_200_yields_none(status: int) -> None:
    server, url = _serve(b"denied", status)
    try:
        assert fetch_pickup_signal(url, "t") is None
    finally:
        server.shutdown()
        server.server_close()


def test_fetch_connection_refused_yields_none() -> None:
    probe = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    host, port = probe.server_address[:2]
    probe.server_close()
    assert fetch_pickup_signal(f"http://{host}:{port}/x", "t", 0.5) is None


# --- refresher lifecycle -----------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _refresher(
    fetch_results: list[PickupSignalDocument | None],
    clock: _Clock,
    today: date = _DAY,
    log_lines: list[str] | None = None,
) -> PickupSignalRefresher:
    results = iter(fetch_results)

    def fake_fetch(url: str, token: str, timeout: float):
        return next(results)

    return PickupSignalRefresher(
        "http://unused",
        "unused-token",
        fetch=fake_fetch,
        monotonic=clock,
        today=lambda: today,
        log=(log_lines.append if log_lines is not None else lambda line: None),
    )


def _doc(day: date = _DAY) -> PickupSignalDocument:
    return PickupSignalDocument(date=day, total_count=0, truncated=False, pickups=())


def test_snapshot_fresh_after_success_then_stale_after_five_minutes() -> None:
    clock = _Clock()
    refresher = _refresher([_doc()], clock)
    refresher.refresh_once()
    assert refresher.snapshot() is not None
    clock.now += 299.0
    assert refresher.snapshot() is not None
    clock.now += 2.0  # past the 5-minute monotonic boundary
    assert refresher.snapshot() is None


def test_failure_keeps_last_known_good_until_staleness() -> None:
    clock = _Clock()
    refresher = _refresher([_doc(), None], clock)
    refresher.refresh_once()
    clock.now += 60.0
    refresher.refresh_once()  # failed round: cache untouched
    assert refresher.snapshot() is not None


def test_yesterdays_payload_goes_stale_at_midnight_rollover() -> None:
    """Pack §5.2: at Berlin midnight the cached list for yesterday is stale
    immediately, even though its monotonic age is still under 5 minutes."""
    clock = _Clock()
    current_day = {"value": _DAY}
    refresher = PickupSignalRefresher(
        "http://unused",
        "unused",
        fetch=lambda *a: _doc(_DAY),
        monotonic=clock,
        today=lambda: current_day["value"],
        log=lambda line: None,
    )
    refresher.refresh_once()
    assert refresher.snapshot() is not None
    current_day["value"] = date(2026, 7, 14)  # midnight rollover
    assert refresher.snapshot() is None


def test_foreign_day_response_is_treated_as_malformed() -> None:
    clock = _Clock()
    refresher = _refresher([_doc(date(2026, 7, 12))], clock)  # yesterday's date
    refresher.refresh_once()
    assert refresher.snapshot() is None


def test_success_line_logged_on_first_success_and_recovery_only() -> None:
    lines: list[str] = []
    clock = _Clock()
    refresher = _refresher([_doc(), _doc(), None, _doc()], clock, log_lines=lines)
    for _ in range(4):
        refresher.refresh_once()
    assert lines == [
        "pickup signal refresh succeeded",  # first success
        "pickup signal refresh succeeded",  # recovery after the failed round
    ]


def test_thread_starts_fetches_immediately_and_joins_on_stop() -> None:
    fetched = threading.Event()

    def fake_fetch(url: str, token: str, timeout: float):
        fetched.set()
        return _doc()

    refresher = PickupSignalRefresher(
        "http://unused",
        "unused",
        interval_seconds=3600.0,  # only the immediate first fetch can fire
        fetch=fake_fetch,
        today=lambda: _DAY,
        log=lambda line: None,
    )
    refresher.start()
    assert fetched.wait(timeout=5.0), "first fetch must happen immediately"
    refresher.stop()  # must join promptly despite the huge interval
    assert refresher.snapshot() is not None


# --- rendering ---------------------------------------------------------------


def test_render_none_shows_muted_blind_line() -> None:
    html = render_pickup_signal_section(None)
    assert "Abholungen: Kurier-App nicht erreichbar" in html


def test_render_empty_fresh_list_renders_nothing() -> None:
    assert render_pickup_signal_section(_doc()) == ""


def test_render_rows_with_german_dates_and_escaping() -> None:
    document = parse_pickup_signal(
        _document_bytes(
            [
                dict(
                    _GOOD_PICKUP,
                    location_text='<script>alert("x")</script>',
                    courier_name="<b>Max</b>",
                    items=[{"name": "<i>Platten</i>", "quantity": 5}],
                )
            ]
        )
    )
    assert document is not None
    html = render_pickup_signal_section(document)
    assert "Abholungen — Geschirr steht noch beim Kunden" in html
    assert "10.07.2026" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>Max</b>" not in html and "&lt;b&gt;Max&lt;/b&gt;" in html
    assert "&lt;i&gt;Platten&lt;/i&gt; ×5" in html


def test_render_truncated_shows_prominent_warning() -> None:
    document = parse_pickup_signal(
        _document_bytes([_GOOD_PICKUP], total_count=77, truncated=True)
    )
    assert document is not None
    html = render_pickup_signal_section(document)
    assert "Abholliste unvollständig — 77 offene Rückläufe insgesamt" in html


def test_fetch_refuses_redirects_and_never_forwards_the_bearer() -> None:
    """urllib re-sends Authorization to redirect targets; a 302 must fail the
    round and the second server must never see a request at all."""
    target_hits: list[str | None] = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            target_hits.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    target = HTTPServer(("127.0.0.1", 0), Target)
    threading.Thread(target=target.serve_forever, daemon=True).start()
    t_host, t_port = target.server_address[:2]

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            self.send_response(302)
            self.send_header("Location", f"http://{t_host}:{t_port}/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    redirector = HTTPServer(("127.0.0.1", 0), Redirector)
    threading.Thread(target=redirector.serve_forever, daemon=True).start()
    r_host, r_port = redirector.server_address[:2]
    try:
        result = fetch_pickup_signal(f"http://{r_host}:{r_port}/api", "secret-token")
        assert result is None
        assert target_hits == []  # the bearer never traveled anywhere
    finally:
        redirector.shutdown()
        redirector.server_close()
        target.shutdown()
        target.server_close()


def test_refresher_survives_fetch_exception_and_logs_recovery() -> None:
    """An unexpected exception is one failed round, not a dead thread:
    exception → success must produce the recovery log line."""
    lines: list[str] = []
    clock = _Clock()
    calls = {"n": 0}

    def exploding_then_good(url: str, token: str, timeout: float):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return _doc()

    refresher = PickupSignalRefresher(
        "http://unused",
        "unused",
        fetch=exploding_then_good,
        monotonic=clock,
        today=lambda: _DAY,
        log=lines.append,
    )
    refresher.refresh_once()  # must not raise
    assert refresher.snapshot() is None
    refresher.refresh_once()
    assert refresher.snapshot() is not None
    assert lines == ["pickup signal refresh succeeded"]


@pytest.mark.parametrize("status", [201, 204])
def test_fetch_accepts_only_exactly_200(status: int) -> None:
    """Any other 2xx is not the contract's success and must fail the round."""
    server, url = _serve(_document_bytes([_GOOD_PICKUP]), status)
    try:
        assert fetch_pickup_signal(url, "t") is None
    finally:
        server.shutdown()
        server.server_close()

"""Pickup signal — kiosk-side client for the courier app's overdue-pickup
feed (KIOSK_PICKUP_SIGNAL_PACK_V1).

One background refresher thread polls the courier app and caches the parsed
result; the kiosk's serving thread only ever reads that cache and never
blocks on the network (pack §5.2 — both servers are single-threaded, and a
synchronous fetch could deadlock them against each other until timeout).
This module touches no SQLite and issues GET only.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")

_MAX_BODY_BYTES = 256 * 1024
_MAX_TEXT_CHARS = 200
_MAX_ITEMS_PER_PICKUP = 20
_FRESH_SECONDS = 300.0
_SUCCESS_LOG_LINE = "pickup signal refresh succeeded"  # pack §5.2: fixed text


def berlin_today() -> date:
    return datetime.now(BERLIN).date()


@dataclass(frozen=True)
class PickupItem:
    name: str
    quantity: int | None


@dataclass(frozen=True)
class OverduePickup:
    location_text: str
    event_date: date
    items: tuple[PickupItem, ...]
    courier_name: str | None


@dataclass(frozen=True)
class PickupSignalDocument:
    date: date
    total_count: int
    truncated: bool
    pickups: tuple[OverduePickup, ...]


class _Malformed(Exception):
    pass


_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _strict_date(value: object) -> date:
    if not isinstance(value, str) or not _ISO_DATE_RE.fullmatch(value):
        raise _Malformed
    return date.fromisoformat(value)


def _strict_text(value: object) -> str:
    """A JSON string within the contract cap. Over-length is malformed here,
    not clipped — clipping is the renderer's separate defensive guard."""
    if not isinstance(value, str) or len(value) > _MAX_TEXT_CHARS:
        raise _Malformed
    return value


def _strict_count(value: object) -> int:
    # bool is an int subclass in Python; "true" must not pass as a count.
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _Malformed
    return value


def parse_pickup_signal(raw: bytes) -> PickupSignalDocument | None:
    """Contract-strict parse (pack §3): exact JSON types, no coercion. None
    for anything malformed or over-limit — the caller treats that exactly
    like an unreachable feed."""
    if len(raw) > _MAX_BODY_BYTES:
        return None
    try:
        document = json.loads(raw.decode("utf-8"))
        truncated = document["truncated"]
        if not isinstance(truncated, bool):
            raise _Malformed
        raw_pickups = document["pickups"]
        if not isinstance(raw_pickups, list):
            raise _Malformed
        pickups = []
        for entry in raw_pickups:
            if not isinstance(entry, dict):
                raise _Malformed
            items = entry["items"]
            if not isinstance(items, list) or len(items) > _MAX_ITEMS_PER_PICKUP:
                raise _Malformed
            parsed_items = []
            for item in items:
                if not isinstance(item, dict):
                    raise _Malformed
                quantity = item["quantity"]
                parsed_items.append(
                    PickupItem(
                        name=_strict_text(item["name"]),
                        quantity=(
                            _strict_count(quantity) if quantity is not None else None
                        ),
                    )
                )
            courier_name = entry["courier_name"]
            pickups.append(
                OverduePickup(
                    location_text=_strict_text(entry["location_text"]),
                    event_date=_strict_date(entry["event_date"]),
                    items=tuple(parsed_items),
                    courier_name=(
                        _strict_text(courier_name) if courier_name is not None else None
                    ),
                )
            )
        total_count = _strict_count(document["total_count"])
        # Consistency: an untruncated document lists everything it counts;
        # a truncated one may only under-report the list, never the count.
        if not truncated and total_count != len(pickups):
            raise _Malformed
        if truncated and total_count < len(pickups):
            raise _Malformed
        return PickupSignalDocument(
            date=_strict_date(document["date"]),
            total_count=total_count,
            truncated=truncated,
            pickups=tuple(pickups),
        )
    except (_Malformed, KeyError, TypeError, ValueError, UnicodeDecodeError):
        return None


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """urllib re-sends the Authorization header to the redirect target; the
    bearer must never travel to a URL we did not configure. Any 3xx becomes
    an HTTPError and the round fails."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def fetch_pickup_signal(
    url: str, token: str, timeout_seconds: float = 1.0
) -> PickupSignalDocument | None:
    """One authenticated GET, redirects refused, exactly HTTP 200 accepted;
    never raises, never logs payloads or the token."""
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with _OPENER.open(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                return None
            raw = response.read(_MAX_BODY_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    return parse_pickup_signal(raw)


class PickupSignalRefresher:
    """Background poller with a last-known-good cache (pack §5.2).

    Lifecycle is normative: immediate first fetch, `stop_event.wait(60)`
    between rounds, monotonic staleness, stop()+join on shutdown. The fixed
    success line is logged on the first success and on each recovery after a
    failure — never on steady-state repeats.
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        interval_seconds: float = 60.0,
        timeout_seconds: float = 1.0,
        fetch: Callable[[str, str, float], PickupSignalDocument | None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = berlin_today,
        log: Callable[[str], None] = lambda line: print(line, flush=True),
    ) -> None:
        self._url = url
        self._token = token
        self._interval = interval_seconds
        self._timeout = timeout_seconds
        self._fetch = fetch if fetch is not None else fetch_pickup_signal
        self._monotonic = monotonic
        self._today = today
        self._log = log
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._document: PickupSignalDocument | None = None
        self._fetched_at: float | None = None
        self._last_round_succeeded = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        while True:  # first fetch happens immediately, not after one interval
            self.refresh_once()
            if self._stop_event.wait(self._interval):
                return

    def refresh_once(self) -> None:
        try:
            document = self._fetch(self._url, self._token, self._timeout)
        except Exception:  # noqa: BLE001 -- one bad round must never kill the
            document = None  # thread; the signal has to survive to retry
        if document is not None and document.date != self._today():
            document = None  # pack §5.2: foreign-day payload is malformed
        if document is None:
            self._last_round_succeeded = False
            return  # keep last known good; staleness will surface it
        with self._lock:
            self._document = document
            self._fetched_at = self._monotonic()
        if not self._last_round_succeeded:
            self._log(_SUCCESS_LOG_LINE)
        self._last_round_succeeded = True

    def snapshot(self) -> PickupSignalDocument | None:
        """Fresh document or None; None means 'signal is blind' (pack §5.3).

        Fresh = last success at most 5 monotonic minutes ago AND the payload
        is for the current Berlin day — at midnight yesterday's list goes
        stale instantly, not five minutes later.
        """
        with self._lock:
            document, fetched_at = self._document, self._fetched_at
        if document is None or fetched_at is None:
            return None
        if self._monotonic() - fetched_at > _FRESH_SECONDS:
            return None
        if document.date != self._today():
            return None
        return document


def _e(text: object) -> str:
    # Defensive display clip lives here (parser already rejects over-length
    # values; this guards the renderer against any other document source).
    return html.escape(_clip(str(text)))


def _clip(text: str) -> str:
    return text[:_MAX_TEXT_CHARS]


def _german_date(day: date) -> str:
    return f"{day.day:02d}.{day.month:02d}.{day.year}"


def render_pickup_signal_section(document: PickupSignalDocument | None) -> str:
    """Pure renderer for the section under the week table (pack §5.3).

    None → the muted 'signal is blind' line. Every courier-app-originating
    string is escaped here; dates and quantities are re-rendered from parsed
    types, never echoed.
    """
    if document is None:
        return (
            '<p class="signal-blind" style="color:#767676;font-size:1rem">'
            "Abholungen: Kurier-App nicht erreichbar</p>"
        )
    if not document.pickups and not document.truncated:
        return ""  # an empty reminder is noise on a kitchen display
    rows = []
    for pickup in document.pickups:
        # Escape-and-clip each value on its own; the joined line must not be
        # clipped as a whole or legitimate trailing items would vanish.
        items = ", ".join(
            f"{_e(item.name)} ×{item.quantity}"
            if item.quantity is not None
            else _e(item.name)
            for item in pickup.items
        )
        courier = pickup.courier_name if pickup.courier_name is not None else "–"
        rows.append(
            "<tr>"
            f"<td>{_e(_german_date(pickup.event_date))}</td>"
            f"<td>{_e(pickup.location_text)}</td>"
            f"<td>{items}</td>"
            f"<td>{_e(courier)}</td>"
            "</tr>"
        )
    warning = ""
    if document.truncated:
        warning = (
            '<p class="signal-warning" '
            'style="color:#b00020;font-size:1.6rem;font-weight:bold">'
            "Abholliste unvollständig — "
            f"{document.total_count} offene Rückläufe insgesamt</p>"
        )
    return (
        "<h2>Abholungen — Geschirr steht noch beim Kunden</h2>"
        f"{warning}"
        "<table>"
        "<tr><th>Geliefert am</th><th>Ort</th><th>Steht dort</th>"
        "<th>Fahrer/in</th></tr>"
        f"{''.join(rows)}"
        "</table>"
    )

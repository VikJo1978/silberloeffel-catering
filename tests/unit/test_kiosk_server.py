"""Unit tests — kitchen kiosk read-only server (KIOSK_EXECUTION_PACK_V1 §3)."""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.wochenuebersicht_service import WochenuebersichtService
from catering_system.ui.kiosk_server import (
    create_kiosk_server,
    render_wochenuebersicht_html,
)

_WEEK_YEAR = 2026
_WEEK = 40  # contains 2026-10-01


def _inquiry(event_date: date, location: str = "Hamburg") -> Inquiry:
    now = datetime.now(timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=event_date,
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        location_text=location,
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
    )


def _repo_with_effective_order(location: str = "Hamburg") -> InMemoryOrderRepository:
    repo = InMemoryOrderRepository()
    osvc = OrderService(repo)
    core = OperationalCoreService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_inquiry(date(2026, 10, 1), location))
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    return repo


def test_render_contains_entry_data() -> None:
    repo = _repo_with_effective_order()
    view = WochenuebersichtService(repo).get_week_overview(_WEEK_YEAR, _WEEK)
    page = render_wochenuebersicht_html(view)
    assert "Wochenübersicht — KW 40/2026" in page
    assert "Donnerstag 2026-10-01" in page
    assert "mittags" in page
    assert "Hamburg" in page
    assert "v1" in page


def test_render_empty_week_message() -> None:
    view = WochenuebersichtService(InMemoryOrderRepository()).get_week_overview(
        _WEEK_YEAR, _WEEK
    )
    page = render_wochenuebersicht_html(view)
    assert "Keine Lieferungen in dieser Woche" in page


def test_render_escapes_order_text() -> None:
    repo = _repo_with_effective_order(location='<script>alert("x")</script>')
    view = WochenuebersichtService(repo).get_week_overview(_WEEK_YEAR, _WEEK)
    page = render_wochenuebersicht_html(view)
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


@pytest.fixture()
def kiosk_url():
    repo = _repo_with_effective_order()
    server = create_kiosk_server(repo, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()


def test_get_week_over_http(kiosk_url: str) -> None:
    with urllib.request.urlopen(f"{kiosk_url}/?year={_WEEK_YEAR}&week={_WEEK}") as resp:
        assert resp.status == 200
        assert resp.headers["Cache-Control"] == "no-store"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        body = resp.read().decode("utf-8")
    assert "Hamburg" in body
    assert "KW 40/2026" in body


def test_post_rejected_read_only(kiosk_url: str) -> None:
    req = urllib.request.Request(f"{kiosk_url}/", data=b"x=1", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 405


def test_unknown_path_404(kiosk_url: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{kiosk_url}/admin")
    assert exc.value.code == 404


def test_malformed_week_params_fall_back_to_current_week(kiosk_url: str) -> None:
    with urllib.request.urlopen(f"{kiosk_url}/?year=abc&week=zz") as resp:
        assert resp.status == 200


def test_kiosk_serves_sqlite_like_on_lenovo(tmp_path) -> None:
    """Regression (bring-up bug): repo created in one thread, requests served by the
    server — must not hit sqlite3 cross-thread errors (single-threaded HTTPServer)."""
    import queue

    from catering_system.repositories.sqlite_order_repository import (
        SQLiteOrderRepository,
    )

    db = tmp_path / "core.db"
    seed = SQLiteOrderRepository(db)
    osvc = OrderService(seed)
    core = OperationalCoreService(seed)
    order, v1 = osvc.convert_inquiry_to_order(_inquiry(date(2026, 10, 1)))
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    seed.close()

    ready: queue.Queue = queue.Queue()

    def run() -> None:  # mirrors main(): repo + server built in the serving thread
        repo = SQLiteOrderRepository(db)
        server = create_kiosk_server(repo, host="127.0.0.1", port=0)
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/?year=2026&week=40") as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert "Hamburg" in body
    finally:
        server.shutdown()
        server.server_close()


# --- /api/order-feed (KIOSK_ORDER_FEED_PACK_V1) ---


def test_order_feed_happy_path_exact_shape(kiosk_url: str) -> None:
    import json

    with urllib.request.urlopen(f"{kiosk_url}/api/order-feed?date=2026-10-01") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "application/json; charset=utf-8"
        document = json.loads(resp.read().decode("utf-8"))
    assert set(document) == {"date", "orders"}
    assert document["date"] == "2026-10-01"
    assert len(document["orders"]) == 1
    order = document["orders"][0]
    assert set(order) == {
        "order_id",
        "event_date",
        "time_window_text",
        "location_text",
        "guest_count_estimate",
    }
    assert order["event_date"] == "2026-10-01"
    assert order["time_window_text"] == "mittags"
    assert order["location_text"] == "Hamburg"
    assert order["guest_count_estimate"] == 25


def test_order_feed_empty_date_returns_empty_orders(kiosk_url: str) -> None:
    import json

    with urllib.request.urlopen(f"{kiosk_url}/api/order-feed?date=2026-10-08") as resp:
        document = json.loads(resp.read().decode("utf-8"))
    assert document == {"date": "2026-10-08", "orders": []}


def test_order_feed_null_guest_count_passes_through() -> None:
    from catering_system.ui.kiosk_server import render_order_feed_json
    import json

    repo = _repo_with_effective_order()
    entries = WochenuebersichtService(repo).get_day_overview(date(2026, 10, 1))
    from dataclasses import replace

    entries = tuple(replace(e, guest_count_estimate=None) for e in entries)
    document = json.loads(render_order_feed_json(date(2026, 10, 1), entries))
    assert document["orders"][0]["guest_count_estimate"] is None


@pytest.mark.parametrize(
    "query",
    [
        "",  # missing date
        "date=",  # empty date
        "date=2026-10-01&date=2026-10-02",  # duplicated date
        "date=2026-10-01&foo=bar",  # unknown extra parameter
        "date=2026-7-4",  # not zero-padded
        "date=20261001",  # compact ISO rejected
        "date=2026-10-01T00:00",  # datetime shape
        "date=2026-10-01x",  # trailing junk
        "date=2026-02-30",  # impossible calendar date
    ],
)
def test_order_feed_strict_query_contract_rejects(kiosk_url: str, query: str) -> None:
    url = f"{kiosk_url}/api/order-feed"
    if query:
        url = f"{url}?{query}"
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(url)
    assert exc.value.code == 400


def test_order_feed_post_rejected_read_only(kiosk_url: str) -> None:
    req = urllib.request.Request(
        f"{kiosk_url}/api/order-feed?date=2026-10-01", data=b"x=1", method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 405


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
def test_order_feed_head_and_options_stay_unsupported(
    kiosk_url: str, method: str
) -> None:
    """Pack §3/§6: http.server has no do_HEAD/do_OPTIONS here — the existing
    501 is documented and deliberately unchanged; a future change must be a
    conscious one."""
    req = urllib.request.Request(
        f"{kiosk_url}/api/order-feed?date=2026-10-01", method=method
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 501


def test_order_feed_carries_kiosk_security_headers(kiosk_url: str) -> None:
    with urllib.request.urlopen(f"{kiosk_url}/api/order-feed?date=2026-10-01") as resp:
        assert resp.headers["Cache-Control"] == "no-store"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "no-referrer"


def test_html_route_unchanged_by_feed(kiosk_url: str) -> None:
    with urllib.request.urlopen(f"{kiosk_url}/?year={_WEEK_YEAR}&week={_WEEK}") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")


def test_kiosk_module_has_no_write_surface() -> None:
    """Pack §3: the kiosk never calls a repository write."""
    from pathlib import Path

    import catering_system.ui.kiosk_server as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "save_order",
        "update_order",
        "save_order_version",
        ".save(",
        ".update(",
    ):
        assert forbidden not in source

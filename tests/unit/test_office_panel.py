"""Unit tests — office panel (OFFICE_PANEL_EXECUTION_PACK_V1 §8). Live-socket, basic auth."""

from __future__ import annotations

import base64
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from catering_system.repositories.in_memory_inquiry_repository import InMemoryInquiryRepository
from catering_system.repositories.in_memory_order_repository import InMemoryOrderRepository
from catering_system.ui.office_panel import create_office_panel_server

_PASSWORD = "test-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()


@pytest.fixture()
def panel():
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(inquiry_repo, order_repo, _PASSWORD, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()


def _get(url: str, *, auth: bool = True) -> tuple[int, str]:
    req = urllib.request.Request(url)
    if auth:
        req.add_header("Authorization", _AUTH)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")


def _post(url: str, data: dict[str, str], *, auth: bool = True) -> tuple[int, str, str]:
    """Returns (status, final_url, body); urllib follows the 303 into a GET."""
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    if auth:
        req.add_header("Authorization", _AUTH)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.url, resp.read().decode("utf-8")


def _create_inquiry(base: str, **overrides: str) -> str:
    data = {
        "event_date": "2026-10-01",
        "inquiry_source": "phone",
        "time_window_text": "mittags",
        "location_text": "Hamburg",
        "guest_count_estimate": "25",
        "planning_mode": "caterer_suggestion",
    }
    data.update(overrides)
    _status, url, _body = _post(f"{base}/inquiry/new", data)
    return url.rsplit("/", 1)[-1]  # inquiry id from redirect target


def _convert(base: str, inquiry_id: str) -> str:
    _status, url, _body = _post(f"{base}/inquiry/{inquiry_id}/convert", {})
    return url.rsplit("/", 1)[-1]  # order id


# -- auth ---------------------------------------------------------------


def test_get_requires_auth(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{panel}/", auth=False)
    assert exc.value.code == 401


def test_post_requires_auth(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/inquiry/new", {"event_date": "2026-10-01"}, auth=False)
    assert exc.value.code == 401


def test_wrong_password_rejected(panel: str) -> None:
    req = urllib.request.Request(f"{panel}/")
    req.add_header("Authorization", "Basic " + base64.b64encode(b"office:wrong").decode())
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 401


# -- inquiries ----------------------------------------------------------


def test_queue_renders_empty(panel: str) -> None:
    status, body = _get(f"{panel}/")
    assert status == 200
    assert "Anfragen" in body and "Aufträge" in body


def test_create_inquiry_appears_in_queue(panel: str) -> None:
    iid = _create_inquiry(panel)
    _status, body = _get(f"{panel}/")
    assert iid[:8] in body
    assert "Hamburg" in body


def test_inquiry_detail_and_update(panel: str) -> None:
    iid = _create_inquiry(panel)
    _status, _url, body = _post(
        f"{panel}/inquiry/{iid}/update",
        {
            "event_date": "2026-10-02",
            "time_window_text": "abends",
            "location_text": "Kiel",
            "guest_count_estimate": "",
            "planning_mode": "self_select",
            "crm_stage": "In Prüfung",
        },
    )
    assert "Kiel" in body and "2026-10-02" in body and "In Prüfung" in body


def test_unverified_inquiry_shows_progression_block_and_convert_fails(panel: str) -> None:
    iid = _create_inquiry(panel, call_verification_required="1")
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Konvertierung blockiert" in body
    assert "inquiry_call_verification_unsatisfied" in body  # B7 vocabulary on inquiry view
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/inquiry/{iid}/convert", {})
    assert exc.value.code == 400


def test_verify_then_convert(panel: str) -> None:
    iid = _create_inquiry(panel, call_verification_required="1")
    _status, _url, body = _post(f"{panel}/inquiry/{iid}/verify", {})
    assert "verified" in body
    oid = _convert(panel, iid)
    status, body = _get(f"{panel}/order/{oid}")
    assert status == 200
    assert "v1" in body


def test_converted_inquiry_shows_order_link_instead_of_button(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Auftrag vorhanden" in body and oid[:8] in body
    assert "In Auftrag umwandeln" not in body


# -- orders -------------------------------------------------------------


def test_order_shows_operational_block_reasons(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    assert "READY_TO_SEND blockiert" in body
    assert "no_effective_version" in body  # operational vocabulary on order view
    assert "inquiry_call_verification_unsatisfied" not in body  # vocabularies not merged (§5)


def test_effective_before_print_rejected(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/order/{oid}/effective", {"order_version_id": vid})
    assert exc.value.code == 400
    assert "kitchen print not confirmed" in exc.value.read().decode("utf-8")


def test_full_release_flow(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})
    _status, _url, body = _post(f"{panel}/order/{oid}/effective", {"order_version_id": vid})
    assert "wirksam" in body
    _status, _url, body = _post(f"{panel}/order/{oid}/ready", {})
    assert "READY_TO_SEND: bereit" in body


def test_new_version_via_form(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, _url, body = _post(
        f"{panel}/order/{oid}/version",
        {
            "event_date": "2026-10-03",
            "time_window_text": "früh",
            "location_text": "Lübeck",
            "guest_count_estimate": "40",
            "planning_mode": "caterer_suggestion",
        },
    )
    assert "v2" in body and "Lübeck" in body


def test_print_sheet_renders(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split("print?version=")[1].split('"')[0]
    status, sheet = _get(f"{panel}/order/{oid}/print?version={vid}")
    assert status == 200
    assert "Küchenzettel" in sheet and "Hamburg" in sheet and "mittags" in sheet


def test_cancel_shows_storniert_and_hides_actions(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, _url, body = _post(f"{panel}/order/{oid}/cancel", {})
    assert "STORNIERT" in body
    assert "Auftrag stornieren" not in body  # actions hidden
    assert "order_cancelled" in body  # operational reason shown
    assert "Küchenzettel" in body  # history stays viewable


def test_cancelled_actions_rejected_serverside(panel: str) -> None:
    """Hiding buttons is presentation; the gate itself must still refuse (§1: no panel-side logic)."""
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    _post(f"{panel}/order/{oid}/cancel", {})
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})
    assert exc.value.code == 400


def test_xss_escaped_in_views(panel: str) -> None:
    iid = _create_inquiry(panel, location_text='<script>alert("x")</script>')
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body


def test_unknown_paths_404(panel: str) -> None:
    for path in ("/admin", "/inquiry/does-not-exist", "/order/does-not-exist"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"{panel}{path}")
        assert exc.value.code == 404

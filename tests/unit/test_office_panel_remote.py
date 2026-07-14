"""Office panel Phase 2 dual mode (PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §7):
RemoteCoreClient wired behind the real, unmodified panel rendering code,
against a real Core Office API server. Covers: read-parity with direct mode
(§3.10/§9 "dashboard parity"), full write flows through the frozen command
envelope, form-embedded idempotent retry, degradation on an unreachable API,
never opening core.db in remote mode, and half-config startup rejection.
"""

from __future__ import annotations

import base64
import os
import queue
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.ui.office_api import create_office_api_server
from catering_system.ui.office_panel_http import (
    create_office_panel_server,
    csrf_token_for_password,
)
from catering_system.ui.remote_core_client import RemoteCoreClient

_PASSWORD = "test-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()
_CSRF_TOKEN = csrf_token_for_password(_PASSWORD)
_API_TOKEN = "test-remote-api-token"

_HIDDEN_REMOTE_FIELD = re.compile(
    r'<input type="hidden" name="_(?:command_id|expect_[a-zA-Z_]+)" value="[^"]*">'
)


def _strip_remote_fields(html: str) -> str:
    return _HIDDEN_REMOTE_FIELD.sub("", html)


def _seed(db_path: Path) -> dict[str, str]:
    """Same fixture world as test_office_api.py's _seed: verify-pending,
    convertible, printed/effective, cancelled, and website_form inquiries —
    rich enough to exercise attention counts, search, next-action, and
    print-data on both a direct-mode and a remote-mode panel."""
    inquiries = SQLiteInquiryRepository(db_path)
    orders = SQLiteOrderRepository(db_path)
    inquiry_service = InquiryService(inquiries)
    order_service = OrderService(orders)
    core = OperationalCoreService(orders)

    def make_inquiry(**overrides):  # noqa: ANN202
        base = dict(
            event_date=date(2026, 10, 1),
            inquiry_source="manual",
            crm_stage="Neue Anfrage",
            customer_linkage={},
            time_window_text="mittags",
            location_text="Hamburg",
            guest_count_estimate=25,
            planning_mode="caterer_suggestion",
            call_verification_required=False,
            call_verification_status="not_required",
        )
        base.update(overrides)
        return inquiry_service.create_inquiry(**base)

    ids: dict[str, str] = {}
    needs_verify = make_inquiry(
        call_verification_required=True,
        call_verification_status="pending",
        location_text="Kiel",
    )
    ids["inquiry_verify"] = needs_verify.inquiry_id

    printed_src = make_inquiry(location_text="Bremen")
    order_printed, v1 = order_service.convert_inquiry_to_order(printed_src)
    core.confirm_kitchen_print(order_printed.order_id, v1.order_version_id)
    core.make_order_version_effective(order_printed.order_id, v1.order_version_id)
    ids["order_ready"] = order_printed.order_id
    ids["version_ready"] = v1.order_version_id

    unprinted_src = make_inquiry(location_text="Lübeck")
    order_unprinted, v1u = order_service.convert_inquiry_to_order(unprinted_src)
    ids["order_unprinted"] = order_unprinted.order_id
    ids["version_unprinted"] = v1u.order_version_id

    cancelled_src = make_inquiry(location_text="Flensburg")
    order_cancelled, _v1c = order_service.convert_inquiry_to_order(cancelled_src)
    core.cancel_order(order_cancelled.order_id)
    ids["order_cancelled"] = order_cancelled.order_id

    website = make_inquiry(
        inquiry_source="website_form",
        intake_external_ref="web-ref-001",
        intake_subject="Sommerfest",
    )
    ids["inquiry_website"] = website.inquiry_id

    inquiries.close()
    orders.close()
    return ids


def _run_server_in_thread(build_server) -> tuple[str, HTTPServer]:
    """Builds and serves an HTTPServer on the SAME thread throughout — a
    sqlite3 connection is thread-affine (WORKLOG Entry 048), so a repo/
    RemoteCoreClient wired to one must be constructed on the very thread
    that will later call serve_forever(), not handed in from the caller's
    thread. Mirrors test_office_api.py's `api` fixture."""
    ready: queue.Queue = queue.Queue()

    def run() -> None:
        server = build_server()
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _start_api_server(db: Path) -> tuple[str, HTTPServer]:
    return _run_server_in_thread(
        lambda: create_office_api_server(str(db), _API_TOKEN, "127.0.0.1", 0)
    )


def _start_direct_panel(db: Path) -> tuple[str, HTTPServer]:
    return _run_server_in_thread(
        lambda: create_office_panel_server(
            SQLiteInquiryRepository(db),
            SQLiteOrderRepository(db),
            _PASSWORD,
            host="127.0.0.1",
            port=0,
        )
    )


def _start_remote_panel(remote: RemoteCoreClient) -> tuple[str, HTTPServer]:
    """`remote` is constructed by the caller (no sqlite inside it, so no
    thread-affinity concern), but the panel/server objects that reference it
    are still built here on the serving thread, matching the same pattern."""
    return _run_server_in_thread(
        lambda: create_office_panel_server(
            remote, remote, _PASSWORD, host="127.0.0.1", port=0, remote=remote
        )
    )


def _get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", _AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _extract_hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    assert match, f"missing hidden field {name!r} in:\n{html}"
    return match.group(1)


def _post_form(url: str, fields: dict[str, str]) -> tuple[int, str]:
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", _AUTH)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


# --- read parity: same seeded core.db, direct-mode HTML vs remote-mode HTML -


@pytest.fixture()
def parity_world(tmp_path: Path):
    db = tmp_path / "core.db"
    ids = _seed(db)

    direct_url, direct_server = _start_direct_panel(db)

    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    remote_url, remote_server = _start_remote_panel(remote)

    yield direct_url, remote_url, ids

    for server in (direct_server, remote_server, api_server):
        server.shutdown()
        server.server_close()


def _assert_same_modulo_remote_fields(direct_html: str, remote_html: str) -> None:
    assert direct_html == _strip_remote_fields(remote_html)


def test_dashboard_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, _ids = parity_world
    d_status, d_html = _get(f"{direct_url}/")
    r_status, r_html = _get(f"{remote_url}/")
    assert d_status == r_status == 200
    _assert_same_modulo_remote_fields(d_html, r_html)
    # sanity: the remote page really does carry the extra hidden fields, so
    # the stripped-equality check above isn't vacuously comparing two empty
    # diffs
    assert "_command_id" in r_html
    assert "_command_id" not in d_html


def test_anfragen_search_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, _ids = parity_world
    for query in ("", "Bremen", "website_form"):
        q = urllib.parse.urlencode({"q": query})
        d_status, d_html = _get(f"{direct_url}/anfragen?{q}")
        r_status, r_html = _get(f"{remote_url}/anfragen?{q}")
        assert d_status == r_status == 200
        _assert_same_modulo_remote_fields(d_html, r_html)


def test_auftraege_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, _ids = parity_world
    d_status, d_html = _get(f"{direct_url}/auftraege")
    r_status, r_html = _get(f"{remote_url}/auftraege")
    assert d_status == r_status == 200
    _assert_same_modulo_remote_fields(d_html, r_html)


def test_order_detail_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    for key in ("order_ready", "order_unprinted", "order_cancelled"):
        order_id = ids[key]
        d_status, d_html = _get(f"{direct_url}/order/{order_id}")
        r_status, r_html = _get(f"{remote_url}/order/{order_id}")
        assert d_status == r_status == 200
        _assert_same_modulo_remote_fields(d_html, r_html)


def test_truncated_order_detail_warns_and_uses_true_latest_version(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    inquiries = SQLiteInquiryRepository(db)
    orders = SQLiteOrderRepository(db)
    inquiry = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 10, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    service = OrderService(orders)
    order, _version = service.convert_inquiry_to_order(inquiry)
    for number in range(2, 202):
        service.create_relevant_order_change_version(
            order,
            event_date=date(2026, 10, 1),
            time_window_text=f"Fenster {number}",
            location_text="Hamburg",
            guest_count_estimate=25,
            planning_mode="caterer_suggestion",
        )
    inquiries.close()
    orders.close()

    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    panel_url, panel_server = _start_remote_panel(remote)
    try:
        status, html = _get(f"{panel_url}/order/{order.order_id}")
        assert status == 200
        assert "Unvollständige Ansicht" in html
        assert "200 von 201 Versionen" in html
        assert _extract_hidden(html, "_expect_latest_version_number") == "201"
    finally:
        panel_server.shutdown()
        panel_server.server_close()
        api_server.shutdown()
        api_server.server_close()


def test_inquiry_detail_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    for key in ("inquiry_verify", "inquiry_website"):
        inquiry_id = ids[key]
        d_status, d_html = _get(f"{direct_url}/inquiry/{inquiry_id}")
        r_status, r_html = _get(f"{remote_url}/inquiry/{inquiry_id}")
        assert d_status == r_status == 200
        _assert_same_modulo_remote_fields(d_html, r_html)


def test_print_data_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    order_id, version_id = ids["order_ready"], ids["version_ready"]
    q = urllib.parse.urlencode({"version": version_id})
    d_status, d_html = _get(f"{direct_url}/order/{order_id}/print?{q}")
    r_status, r_html = _get(f"{remote_url}/order/{order_id}/print?{q}")
    assert d_status == r_status == 200
    assert d_html == r_html  # print sheet embeds no command form at all


def test_rueckruf_stays_local_not_routed_through_core(parity_world) -> None:
    """Rückruf/Auerswald stays outside Core.  On Proxmox, an unconfigured
    local integration must carry the frozen "only on premises" explanation
    rather than pretending that it is an ordinary missing URL."""
    direct_url, remote_url, _ids = parity_world
    d_status, d_html = _get(f"{direct_url}/rueckruf")
    r_status, r_html = _get(f"{remote_url}/rueckruf")
    assert d_status == r_status == 200
    assert "AUERSWALD_SYNC_URL nicht konfiguriert" in d_html
    assert "Rückruf-Liste: nur vor Ort verfügbar" in r_html


# --- full write flow through the frozen command envelope ---------------------


@pytest.fixture()
def remote_world(tmp_path: Path):
    db = tmp_path / "core.db"
    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    panel_url, panel_server = _start_remote_panel(remote)
    yield panel_url
    panel_server.shutdown()
    panel_server.server_close()
    api_server.shutdown()
    api_server.server_close()


def test_full_write_flow_through_remote_panel(remote_world) -> None:
    base = remote_world
    status, form_html = _get(f"{base}/inquiry/new")
    assert status == 200
    command_id = _extract_hidden(form_html, "_command_id")

    status, redirect_body = _post_form(
        f"{base}/inquiry/new",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": command_id,
            "event_date": "2026-11-11",
            "inquiry_source": "manual",
            "time_window_text": "abends",
            "location_text": "Rostock",
            "guest_count_estimate": "40",
            "planning_mode": "caterer_suggestion",
        },
    )
    assert status == 200
    inquiry_id_match = re.search(r"Anfrage ([0-9a-f]{8})", redirect_body)
    assert inquiry_id_match

    status, detail_html = _get(f"{base}/anfragen?q=Rostock")
    assert status == 200
    assert "Rostock" in detail_html
    inquiry_id = re.search(r'/inquiry/([0-9a-f-]{36})"', detail_html).group(1)

    status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert status == 200
    update_form = re.search(
        r'(<form method="post" action="/inquiry/[^"]*/update".*</form>)',
        detail_html,
        re.DOTALL,
    ).group(0)
    update_command_id = _extract_hidden(update_form, "_command_id")
    update_expect = _extract_hidden(update_form, "_expect_updated_at")
    status, _body = _post_form(
        f"{base}/inquiry/{inquiry_id}/update",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": update_command_id,
            "_expect_updated_at": update_expect,
            "event_date": "2026-11-11",
            "time_window_text": "abends",
            "location_text": "Rostock-Ost",
            "guest_count_estimate": "40",
            "planning_mode": "caterer_suggestion",
            "crm_stage": "Neue Anfrage",
        },
    )
    assert status == 200

    status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert status == 200
    assert "Rostock-Ost" in detail_html
    convert_command_id = _extract_hidden(
        re.search(r"(<form[^>]*convert[^\"]*\"[^>]*>.*?</form>)", detail_html).group(0),
        "_command_id",
    )
    status, _body = _post_form(
        f"{base}/inquiry/{inquiry_id}/convert",
        {"_csrf_token": _CSRF_TOKEN, "_command_id": convert_command_id},
    )
    assert status == 200

    status, order_list_html = _get(f"{base}/auftraege?q={inquiry_id[:8]}")
    assert status == 200
    order_id = re.search(r'/order/([0-9a-f-]{36})"', order_list_html).group(1)

    status, order_html = _get(f"{base}/order/{order_id}")
    assert status == 200
    version_id_match = re.search(r'name="order_version_id" value="([^"]+)"', order_html)
    assert version_id_match
    version_id = version_id_match.group(1)
    print_confirm_command_id = _extract_hidden(order_html, "_command_id")

    status, _body = _post_form(
        f"{base}/order/{order_id}/print-confirm",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": print_confirm_command_id,
            "order_version_id": version_id,
        },
    )
    assert status == 200

    status, order_html = _get(f"{base}/order/{order_id}")
    assert status == 200
    assert "Druck bestätigt" in order_html

    ready_command_id = _extract_hidden(
        re.search(
            r'(<form[^>]*action="/order/[^"]*/ready"[^>]*>.*?</form>)', order_html
        ).group(0),
        "_command_id",
    )
    status, _body = _post_form(
        f"{base}/order/{order_id}/ready",
        {"_csrf_token": _CSRF_TOKEN, "_command_id": ready_command_id},
    )
    assert status == 200  # not yet effective, but the command itself succeeds

    effective_command_id = _extract_hidden(
        re.search(
            r'(<form[^>]*action="/order/[^"]*/effective"[^>]*>.*?</form>)', order_html
        ).group(0),
        "_command_id",
    )
    effective_expect = _extract_hidden(order_html, "_expect_effective_version_id")
    status, _body = _post_form(
        f"{base}/order/{order_id}/effective",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": effective_command_id,
            "_expect_effective_version_id": effective_expect,
            "order_version_id": version_id,
        },
    )
    assert status == 200

    status, order_html = _get(f"{base}/order/{order_id}")
    assert status == 200
    assert "wirksam" in order_html
    assert "READY_TO_SEND: bereit." in order_html

    cancel_command_id = _extract_hidden(
        re.search(
            r'(<form[^>]*action="/order/[^"]*/cancel"[^>]*>.*?</form>)', order_html
        ).group(0),
        "_command_id",
    )
    cancel_expect = _extract_hidden(order_html, "_expect_updated_at")
    status, _body = _post_form(
        f"{base}/order/{order_id}/cancel",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": cancel_command_id,
            "_expect_updated_at": cancel_expect,
        },
    )
    assert status == 200
    status, order_html = _get(f"{base}/order/{order_id}")
    assert "STORNIERT" in order_html


def test_verify_flow_through_remote_panel(remote_world) -> None:
    """The main flow above never sets call_verification_required, so it never
    exercises verify_customer_by_call — cover it here."""
    base = remote_world
    _status, form_html = _get(f"{base}/inquiry/new")
    command_id = _extract_hidden(form_html, "_command_id")
    _status, _body = _post_form(
        f"{base}/inquiry/new",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": command_id,
            "event_date": "2026-11-13",
            "inquiry_source": "phone_by_office",
            "time_window_text": "mittags",
            "location_text": "Schwerin",
            "guest_count_estimate": "15",
            "planning_mode": "caterer_suggestion",
            "call_verification_required": "1",
        },
    )
    _status, list_html = _get(f"{base}/anfragen?q=Schwerin")
    inquiry_id = re.search(r'/inquiry/([0-9a-f-]{36})"', list_html).group(1)

    _status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert "Telefonisch verifiziert" in detail_html
    verify_form = re.search(
        r'(<form[^>]*action="/inquiry/[^"]*/verify"[^>]*>.*?</form>)', detail_html
    ).group(0)
    verify_command_id = _extract_hidden(verify_form, "_command_id")
    status, _body = _post_form(
        f"{base}/inquiry/{inquiry_id}/verify",
        {"_csrf_token": _CSRF_TOKEN, "_command_id": verify_command_id},
    )
    assert status == 200

    _status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert "Telefonisch verifiziert" not in detail_html  # button gone once verified
    assert "In Auftrag umwandeln" in detail_html  # convert now offered


def test_idempotent_retry_same_command_id_and_preconditions(remote_world) -> None:
    """§6.1/§6.3: after an indeterminate failure, retrying with the identical
    envelope must not double the effect — convert twice with the same
    command_id must produce exactly one order."""
    base = remote_world
    _status, form_html = _get(f"{base}/inquiry/new")
    command_id = _extract_hidden(form_html, "_command_id")
    fields = {
        "_csrf_token": _CSRF_TOKEN,
        "_command_id": command_id,
        "event_date": "2026-11-12",
        "inquiry_source": "manual",
        "time_window_text": "abends",
        "location_text": "Idempotenz-Stadt",
        "guest_count_estimate": "10",
        "planning_mode": "caterer_suggestion",
    }
    status1, _ = _post_form(f"{base}/inquiry/new", fields)
    status2, _ = _post_form(f"{base}/inquiry/new", fields)  # identical retry
    assert status1 == status2 == 200

    _status, list_html = _get(f"{base}/anfragen?q=Idempotenz-Stadt")
    # exactly one row, not two (the search box also echoes the query term
    # into its value= attribute, so count the table cell specifically)
    assert list_html.count("<td>Idempotenz-Stadt</td>") == 1

    inquiry_id = re.search(r'/inquiry/([0-9a-f-]{36})"', list_html).group(1)
    _status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    convert_form = re.search(
        r'(<form[^>]*action="/inquiry/[^"]*/convert"[^>]*>.*?</form>)', detail_html
    ).group(0)
    convert_command_id = _extract_hidden(convert_form, "_command_id")
    convert_fields = {"_csrf_token": _CSRF_TOKEN, "_command_id": convert_command_id}
    status1, _ = _post_form(f"{base}/inquiry/{inquiry_id}/convert", convert_fields)
    status2, _ = _post_form(f"{base}/inquiry/{inquiry_id}/convert", convert_fields)
    assert status1 == status2 == 200  # replay returns the recorded result

    _status, orders_html = _get(f"{base}/auftraege?q={inquiry_id[:8]}")
    # exactly one order row for this inquiry, not two — one header <tr> plus
    # one data <tr>
    assert orders_html.count("<tr>") == 2


# --- degradation: unreachable Core Office API --------------------------------


def test_unreachable_api_shows_german_message_never_empty_queue(tmp_path: Path) -> None:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
    remote = RemoteCoreClient(f"http://127.0.0.1:{dead_port}", _API_TOKEN)
    url, server = _start_remote_panel(remote)
    try:
        status, html = _get(f"{url}/")
        assert status == 503
        assert "Core nicht erreichbar" in html
        assert "nichts wurde gespeichert" in html
        # never an empty/broken dashboard rendered as if all-clear
        assert "Anfragen prüfen" not in html
    finally:
        server.shutdown()
        server.server_close()


# --- remote mode never opens core.db / half-config startup rejection --------


def test_remote_mode_never_constructs_sqlite_repos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("remote mode must never open core.db")

    monkeypatch.setattr(SQLiteInquiryRepository, "__init__", _boom)
    monkeypatch.setattr(SQLiteOrderRepository, "__init__", _boom)
    # constructing the remote client and the panel server must not touch
    # either SQLite repo class at all
    remote = RemoteCoreClient("http://127.0.0.1:8084", _API_TOKEN)
    _url, server = _start_remote_panel(remote)
    server.shutdown()
    server.server_close()


def test_half_config_url_only_rejects_before_startup(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env["CORE_OFFICE_API_URL"] = "http://127.0.0.1:8084"
    env.pop("CORE_OFFICE_API_TOKEN", None)
    env["OFFICE_PANEL_PASSWORD"] = "x"
    result = subprocess.run(
        [sys.executable, "-m", "catering_system.ui.office_panel", "--port", "0"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "CORE_OFFICE_API_URL" in result.stderr
    assert "CORE_OFFICE_API_TOKEN" in result.stderr


def test_half_config_token_only_rejects_before_startup(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env.pop("CORE_OFFICE_API_URL", None)
    env["CORE_OFFICE_API_TOKEN"] = "some-token"
    env["OFFICE_PANEL_PASSWORD"] = "x"
    result = subprocess.run(
        [sys.executable, "-m", "catering_system.ui.office_panel", "--port", "0"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "CORE_OFFICE_API_URL" in result.stderr


def test_remote_mode_starts_without_any_db_argument(tmp_path: Path) -> None:
    """Proves remote mode truly needs no --db: if it ever tried the direct
    path it would fail for lack of one. Started as a subprocess and killed
    once it prints its startup banner (it would otherwise serve forever)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    with __import__("socket").socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with __import__("socket").socket() as api_probe:
        api_probe.bind(("127.0.0.1", 0))
        api_port = api_probe.getsockname()[1]
    env["CORE_OFFICE_API_URL"] = f"http://127.0.0.1:{api_port}"
    env["CORE_OFFICE_API_TOKEN"] = "x"
    env["OFFICE_PANEL_PASSWORD"] = "x"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",  # unbuffered stdout, so readline() below sees it promptly
            "-m",
            "catering_system.ui.office_panel",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        import select

        ready, _, _ = select.select([proc.stdout], [], [], 10)
        assert ready, "office panel printed no startup banner within 10s"
        line = proc.stdout.readline()
        assert "remote mode" in line
        assert proc.poll() is None  # still running, didn't crash on startup
    finally:
        proc.terminate()
        proc.wait(timeout=10)

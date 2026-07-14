"""RemoteCoreClient unit tests (PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 Phase 2).

Covers the client in isolation against small HTTP-server doubles: redirect
refusal (bearer must never reach a second host), timeouts/unreachability,
malformed/oversized responses, and the write-forbidden tripwire. Behavioral
parity against the real Core Office API and the panel's dual-mode wiring live
in test_office_panel_remote.py.
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.order_service import OrderService
from catering_system.ui import remote_core_client as rcc
from catering_system.ui.remote_core_client import RemoteCoreClient, RemoteCoreError

_TOKEN = "test-remote-token"


def _serve(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[str, HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- redirect refusal: the single most safety-critical behavior -------------


def test_redirect_refused_and_second_host_never_contacted() -> None:
    captured: list[dict] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            captured.append(dict(self.headers))

        def log_message(self, *_args: object) -> None:
            pass

    target_url, target_server = _serve(TargetHandler)
    try:

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(302)
                self.send_header("Location", f"{target_url}/office/v1/queue")
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                pass

        redirect_url, redirect_server = _serve(RedirectHandler)
        try:
            client = RemoteCoreClient(redirect_url, _TOKEN)
            with pytest.raises(RemoteCoreError) as exc:
                client.get("/office/v1/queue")
            assert exc.value.unavailable
            assert exc.value.code == "redirect_refused"
            # The redirect target must never have been contacted at all — the
            # bearer only ever lives in the request to the CONFIGURED host.
            assert captured == []
        finally:
            redirect_server.shutdown()
            redirect_server.server_close()
    finally:
        target_server.shutdown()
        target_server.server_close()


def test_bearer_sent_only_to_configured_host_never_in_url() -> None:
    captured: list[dict] = []
    captured_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            captured.append(dict(self.headers))
            captured_paths.append(self.path)
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    url, server = _serve(Handler)
    try:
        client = RemoteCoreClient(url, _TOKEN)
        client.get("/office/v1/queue")
        assert captured[0]["Authorization"] == f"Bearer {_TOKEN}"
        assert _TOKEN not in captured_paths[0]
    finally:
        server.shutdown()
        server.server_close()


# --- timeouts / unreachable --------------------------------------------------


def test_unreachable_host_maps_to_unavailable() -> None:
    client = RemoteCoreClient(f"http://127.0.0.1:{_free_port()}", _TOKEN)
    with pytest.raises(RemoteCoreError) as exc:
        client.get("/office/v1/queue")
    assert exc.value.unavailable
    assert exc.value.code == "unreachable"


def test_read_timeout_maps_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    accepted = threading.Event()

    class HangingHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            accepted.set()
            time.sleep(2)  # longer than the patched timeout below
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            pass

    monkeypatch.setattr(rcc, "_READ_TIMEOUT_SECONDS", 0.2)
    url, server = _serve(HangingHandler)
    try:
        client = RemoteCoreClient(url, _TOKEN)
        with pytest.raises(RemoteCoreError) as exc:
            client.get("/office/v1/queue")
        assert exc.value.unavailable
        assert exc.value.code == "unreachable"
    finally:
        server.shutdown()
        server.server_close()


def test_timeout_constants_match_the_frozen_pack() -> None:
    """§6.5: 3 s reads / 5 s commands — locked in so a future edit can't
    silently drift from the frozen contract."""
    assert rcc._READ_TIMEOUT_SECONDS == 3
    assert rcc._COMMAND_TIMEOUT_SECONDS == 5


# --- malformed / oversized responses -----------------------------------------


def _json_server(status: int, content_type: str, body: bytes) -> tuple[str, HTTPServer]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    return _serve(Handler)


def test_malformed_json_body_is_invalid_response() -> None:
    url, server = _json_server(200, "application/json", b"not json")
    try:
        client = RemoteCoreClient(url, _TOKEN)
        with pytest.raises(RemoteCoreError) as exc:
            client.get("/office/v1/queue")
        assert exc.value.unavailable
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_non_object_json_body_is_invalid_response() -> None:
    url, server = _json_server(200, "application/json", b"[1, 2, 3]")
    try:
        client = RemoteCoreClient(url, _TOKEN)
        with pytest.raises(RemoteCoreError) as exc:
            client.get("/office/v1/queue")
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_wrong_content_type_is_invalid_response() -> None:
    url, server = _json_server(200, "text/plain", b'{"ok": true}')
    try:
        client = RemoteCoreClient(url, _TOKEN)
        with pytest.raises(RemoteCoreError) as exc:
            client.get("/office/v1/queue")
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_oversized_response_is_invalid_response() -> None:
    oversized = json.dumps({"pad": "x" * (600 * 1024)}).encode()
    url, server = _json_server(200, "application/json", oversized)
    try:
        client = RemoteCoreClient(url, _TOKEN)
        with pytest.raises(RemoteCoreError) as exc:
            client.get("/office/v1/queue")
        assert exc.value.unavailable
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_unexpected_status_is_unavailable() -> None:
    url, server = _json_server(200, "application/json", b'{"ok": true}')
    try:
        client = RemoteCoreClient(url, _TOKEN)
        # queue() only accepts 200; simulate a route expecting {201} seeing 200.
        with pytest.raises(RemoteCoreError) as exc:
            client._request("GET", "/office/v1/queue", expected={201})
        assert exc.value.unavailable
        assert exc.value.code == "unexpected_status"
    finally:
        server.shutdown()
        server.server_close()


# --- construction / config strictness ----------------------------------------


def test_rejects_empty_token() -> None:
    with pytest.raises(ValueError, match="CORE_OFFICE_API_TOKEN"):
        RemoteCoreClient("http://127.0.0.1:8084", "")


@pytest.mark.parametrize(
    "bad_url",
    [
        "not-a-url",
        "ftp://127.0.0.1:8084",
        "http://user:pass@127.0.0.1:8084",
        "http://127.0.0.1:8084?x=1",
        "http://127.0.0.1:8084#frag",
    ],
)
def test_rejects_malformed_base_url(bad_url: str) -> None:
    with pytest.raises(ValueError, match="CORE_OFFICE_API_URL"):
        RemoteCoreClient(bad_url, _TOKEN)


# --- command_id / write tripwire ----------------------------------------------


def test_new_page_command_id_is_uuid4() -> None:
    client = RemoteCoreClient("http://127.0.0.1:8084", _TOKEN)
    minted = client.new_page_command_id()
    parsed = uuid.UUID(minted)
    assert parsed.version == 4
    # a fresh render mints a different id each time
    assert client.new_page_command_id() != minted


def test_begin_request_resets_command_id_from_form() -> None:
    client = RemoteCoreClient("http://127.0.0.1:8084", _TOKEN)
    client.begin_request({"_command_id": "fixed-id", "other": "x"})
    assert client._id() == "fixed-id"
    assert client.form_value("other") == "x"
    client.begin_request(None)
    assert client._id() != "fixed-id"  # falls back to a fresh uuid4


@pytest.mark.parametrize(
    "method_name,args",
    [
        ("save", (object(),)),
        ("update", (object(),)),
        ("save_order_with_initial_version", (object(), object())),
        ("update_order", (object(),)),
        ("append_order_version", (object(), object())),
        ("update_order_version", (object(),)),
    ],
)
def test_write_methods_raise_runtime_error_not_type_error(
    method_name: str, args: tuple[object, ...]
) -> None:
    """The Codex draft bound these to a `self`-only stub, so calling them with
    the Protocol's real arguments raised a bare TypeError (arity mismatch)
    instead of the intended message — silently-wrong safety net. Each stub
    now has the exact Protocol signature."""
    client = RemoteCoreClient("http://127.0.0.1:8084", _TOKEN)
    with pytest.raises(RuntimeError, match="Core Office API commands"):
        getattr(client, method_name)(*args)


def test_find_by_source_and_external_ref_no_match_returns_none() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps(
                {"inquiries": [], "total_count": 0, "limit": 100, "offset": 0}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    url, server = _serve(Handler)
    try:
        client = RemoteCoreClient(url, _TOKEN)
        assert client.find_by_source_and_external_ref("website_form", "ref-1") is None
    finally:
        server.shutdown()
        server.server_close()


# --- regression: eager evaluation of next()'s default argument --------------
#
# next(generator, cast(T, _bad_response())) always raised, regardless of
# whether the generator had a match — Python evaluates every argument to
# next() (including the default) before next() itself runs, so the
# always-raising _bad_response() call fired unconditionally. This made every
# real create_relevant_order_change_version()/confirm_kitchen_print() call
# fail with "invalid_response" even though the underlying command succeeded.
# Only caught by exercising a full command -> re-read cycle against a real
# server, not by isolated client-level tests with canned responses.


def _run_office_api_in_thread(db_path):  # noqa: ANN001, ANN202
    from catering_system.ui.office_api import create_office_api_server

    ready: queue.Queue = queue.Queue()

    def run() -> None:
        server = create_office_api_server(str(db_path), _TOKEN, "127.0.0.1", 0)
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def test_confirm_kitchen_print_returns_the_version_not_bad_response(
    tmp_path,
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
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    order, version = OrderService(orders).convert_inquiry_to_order(inquiry)
    inquiries.close()
    orders.close()

    url, server = _run_office_api_in_thread(db)
    try:
        client = RemoteCoreClient(url, _TOKEN)
        client.begin_request({})
        result = client.core.confirm_kitchen_print(
            order.order_id, version.order_version_id
        )
        assert result.order_version_id == version.order_version_id
        assert result.kitchen_print_confirmed_at is not None
    finally:
        server.shutdown()
        server.server_close()


def test_create_relevant_order_change_version_returns_the_version_not_bad_response(
    tmp_path,
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
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    order, _v1 = OrderService(orders).convert_inquiry_to_order(inquiry)
    inquiries.close()
    orders.close()

    url, server = _run_office_api_in_thread(db)
    try:
        client = RemoteCoreClient(url, _TOKEN)
        client.begin_request({})
        result = client.order_service.create_relevant_order_change_version(
            order,
            event_date=date(2026, 10, 2),
            time_window_text="abends",
            location_text="Kiel",
            guest_count_estimate=20,
            planning_mode="caterer_suggestion",
        )
        assert result.version_number == 2
        assert result.location_text == "Kiel"
    finally:
        server.shutdown()
        server.server_close()

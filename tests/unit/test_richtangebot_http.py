from __future__ import annotations

import base64
import sqlite3
import threading
from dataclasses import replace
from datetime import UTC, datetime
from http.client import HTTPConnection
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from catering_system.domain.ai_telefon_call import AiTelefonCall
from catering_system.repositories.core_transaction import (
    CoreBusyError,
    CoreCommandExecutor,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_richtangebot_repository import (
    SQLiteRichtangebotRepository,
)
from catering_system.services.richtangebot_service import RichtangebotService
from catering_system.ui.office_panel_http import csrf_token_for_password
from catering_system.ui.office_panel_richtangebot_runtime import (
    create_richtangebot_enabled_office_panel_server,
)


@pytest.fixture(params=[False, True], ids=["default-transaction", "supplied-executor"])
def panel(tmp_path, request):
    connection = sqlite3.connect(
        tmp_path / "core.db", check_same_thread=False, isolation_level=None
    )
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    calls = SQLiteAiTelefonCallRepository.from_connection(connection)
    now = datetime(2026, 9, 11, tzinfo=UTC)
    call = AiTelefonCall(
        call_id=str(uuid4()),
        strato_id="strato-http",
        gmail_message_id="gmail-http",
        caller_phone="+49123",
        contact_name="Test Kunde",
        email="",
        subject="Taufe",
        summary="Taufe nächstes Jahr",
        raw_message="raw",
        event_type="Taufe",
        event_period="nächstes Jahr",
        event_time_text="zwischen 16 und 18 Uhr vereinbart",
        received_at=now,
        updated_at=now,
    )
    calls.save(call)
    executor = CoreCommandExecutor(connection) if request.param else None
    server = create_richtangebot_enabled_office_panel_server(
        inquiries,
        InMemoryOrderRepository(),
        "pw",
        host="127.0.0.1",
        port=0,
        command_executor=executor,
    )
    offers = SQLiteRichtangebotRepository.from_connection(connection)
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()

    def post(
        call_id=call.call_id, *, csrf=csrf_token_for_password("pw"), authenticated=True
    ):
        client = HTTPConnection(*server.server_address[:2], timeout=5)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if authenticated:
            headers["Authorization"] = (
                "Basic " + base64.b64encode(b"office:pw").decode()
            )
        try:
            client.request(
                "POST",
                f"/ki-telefonassistent/{call_id}/richtangebot",
                urlencode({"_csrf_token": csrf}),
                headers,
            )
            response = client.getresponse()
            return (
                response.status,
                response.getheader("Location"),
                response.read().decode(),
            )
        finally:
            client.close()

    yield SimpleNamespace(
        connection=connection,
        inquiries=inquiries,
        calls=calls,
        call=call,
        offers=offers,
        server=server,
        post=post,
    )
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()
    connection.close()


def assert_unchanged(panel):
    assert panel.calls.get(panel.call.call_id) == panel.call
    assert panel.offers.list_recent() == []
    assert panel.inquiries.list_all() == []
    assert not panel.connection.in_transaction


def test_post_creates_durable_richtangebot_and_repeat_redirects_to_same_document(panel):
    first = panel.post()
    second = panel.post()
    assert first[0] == second[0] == 303
    assert first[1] == second[1]
    stored = panel.calls.get(panel.call.call_id)
    assert stored.result_type == "RICHTANGEBOT"
    assert first[1] == f"/richtangebot/{stored.result_id}"
    values = panel.offers.list_recent()
    assert len(values) == 1
    assert values[0].event_start is None
    assert values[0].event_time_text == panel.call.event_time_text
    assert panel.inquiries.list_all() == []
    assert not panel.connection.in_transaction


def test_post_missing_call_returns_404(panel):
    assert panel.post(str(uuid4()))[0] == 404
    assert_unchanged(panel)


def test_post_insufficient_context_returns_422(panel):
    panel.call = replace(panel.call, event_type="", event_period="", event_time_text="")
    panel.calls.update(panel.call)
    status, location, body = panel.post()
    assert status == 422
    assert location is None
    assert "Kontakt- und Veranstaltungsangaben prüfen" in body
    assert_unchanged(panel)


@pytest.mark.parametrize("state", ["DONE", "INQUIRY", "TASK", "LINKED"])
def test_post_does_not_overwrite_previous_processing_result(panel, state):
    panel.call = replace(
        panel.call,
        status="DONE" if state == "DONE" else "PROCESSED",
        result_type=None if state == "DONE" else state,
        result_id=None if state == "DONE" else str(uuid4()),
        processed_at=None if state == "DONE" else panel.call.updated_at,
        linked_type="OFFER" if state == "LINKED" else None,
        linked_id=str(uuid4()) if state == "LINKED" else None,
    )
    panel.calls.update(panel.call)
    assert panel.post()[0] == 409
    assert_unchanged(panel)


@pytest.mark.parametrize(
    "csrf,authenticated,status",
    [("", True, 403), ("wrong", True, 403), ("", False, 401)],
)
def test_post_requires_authentication_and_csrf(panel, csrf, authenticated, status):
    assert panel.post(csrf=csrf, authenticated=authenticated)[0] == status
    assert_unchanged(panel)


def test_post_requires_offers_prepare_permission(panel, monkeypatch):
    def deny(handler, auth, permission, **kwargs):
        assert permission == "offers.prepare"
        handler._business_forbidden(active_section=kwargs["active_section"])
        return False

    monkeypatch.setattr(
        panel.server.RequestHandlerClass, "_require_business_permission_post", deny
    )
    assert panel.post()[0] == 403
    assert_unchanged(panel)


@pytest.mark.parametrize(
    "error,status",
    [
        (ValueError("private value"), 422),
        (TypeError("private type"), 422),
        (sqlite3.OperationalError("private database failure"), 503),
        (CoreBusyError("private lock details"), 503),
    ],
)
def test_post_write_failure_rolls_back_document_and_call_and_allows_retry(
    panel, monkeypatch, error, status
):
    original = SQLiteAiTelefonCallRepository.update

    def fail_after_update(repo, call):
        original(repo, call)
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteAiTelefonCallRepository, "update", fail_after_update)
        result = panel.post()
    assert result[0] == status
    assert result[1] is None
    assert "private" not in result[2]
    assert_unchanged(panel)
    assert panel.post()[0] == 303
    assert len(panel.offers.list_recent()) == 1


def test_post_handles_failure_before_document_is_written(panel, monkeypatch):
    def fail(*args):
        raise sqlite3.OperationalError("private storage error")

    monkeypatch.setattr(RichtangebotService, "create_from_call", fail)
    assert panel.post()[0] == 503
    assert_unchanged(panel)


def test_post_busy_database_returns_503_even_when_badge_query_would_fail(panel):
    db_path = panel.connection.execute("PRAGMA database_list").fetchone()[2]
    panel.connection.execute("PRAGMA busy_timeout=50")
    other = sqlite3.connect(db_path)
    try:
        other.execute("BEGIN EXCLUSIVE")
        status, location, body = panel.post()
        assert status == 503
        assert location is None
        assert "Datenbank ist gerade beschäftigt" in body
    finally:
        other.rollback()
        other.close()
    assert_unchanged(panel)
    assert panel.post()[0] == 303

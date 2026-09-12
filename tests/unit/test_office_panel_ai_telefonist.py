from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, time
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

from catering_system.domain.ai_telefon_call import AiTelefonCall
from catering_system.ui import office_panel, office_panel_http, office_panel_with_ai
from catering_system.ui.office_panel_ai_runtime import (
    _inject_ai_nav,
    _manual_task_service,
    create_ai_enabled_office_panel_server,
)
from catering_system.ui.office_panel_ai_telefonist import (
    render_ai_telefon_call_detail,
    render_ai_telefon_calls,
)
from catering_system.ui.office_panel_richtangebot_runtime import (
    create_richtangebot_enabled_office_panel_server,
)
from catering_system.ui.office_panel_views import OfficePageContext

_CALL_ID = "8e5d6ac1-1a43-49b0-8803-d76ac86a9666"
_RESULT_ID = "88d2656a-f17c-4686-9f91-b6b9bad20a7c"


def _call(
    *,
    status: str = "NEW",
    result_type: str | None = None,
    result_id: str | None = None,
    contact_name: str = "Viktor Merkel",
    caller_phone: str = "+4917642795029",
    event_date: date | None = date(2027, 1, 12),
) -> AiTelefonCall:
    return AiTelefonCall(
        call_id=_CALL_ID,
        strato_id="07a45b4c-68e4-424e-a670-372c3d50df92",
        gmail_message_id="1a08c74d9191a5be",
        caller_phone=caller_phone,
        contact_name=contact_name,
        email="vik@example.invalid",
        subject="Catering-Anfrage für Geburtstagsfeier",
        summary="100 Personen, 30 Euro pro Person, griechisches Buffet.",
        raw_message="Anrufer: +4917642795029\nZusammenfassung: Test",
        event_type="Geburtstag",
        event_date=event_date,
        event_period="Januar 2027",
        event_start=time(16, 45),
        guest_count=100,
        location="Brooks Heide 3, 22549 Hamburg",
        budget_per_person_cents=3000,
        fulfillment_mode="DELIVERY",
        customer_request="griechisches Buffet",
        callback_requested=True,
        callback_date=date(2026, 9, 11),
        callback_time=time(13, 20),
        status=status,  # type: ignore[arg-type]
        result_type=result_type,  # type: ignore[arg-type]
        result_id=result_id,
        received_at=datetime(2026, 9, 10, 18, 0, tzinfo=UTC),
        processed_at=(
            datetime(2026, 9, 10, 18, 5, tzinfo=UTC) if status == "PROCESSED" else None
        ),
        updated_at=datetime(2026, 9, 10, 18, 5, tzinfo=UTC),
    )


def test_render_empty_and_populated_call_list() -> None:
    empty = render_ai_telefon_calls([])
    assert "Noch keine Gespräche" in empty

    new_call = _call()
    done_call = _call(status="DONE", result_type="TASK", result_id=_RESULT_ID)
    html = render_ai_telefon_calls([new_call, done_call])

    assert "KI Telefonassistent" in html
    assert "1 neu" in html
    assert "Viktor Merkel" in html
    assert "Neu" in html
    assert "Erledigt · Aufgabe" in html
    assert "/ki-telefonassistent/" in html


def test_render_new_call_detail_with_all_actions_and_facts() -> None:
    context = OfficePageContext(
        csrf_token="csrf-token",
        employee_account_id="employee-1",
    )

    html = render_ai_telefon_call_detail(_call(), context=context)

    assert "Als Anfrage übernehmen" in html
    assert "Als Aufgabe übernehmen" in html
    assert "Erledigt" in html
    assert 'name="_csrf_token" value="csrf-token"' in html
    assert "12.01.2027" in html
    assert "16:45" in html
    assert "30,00 € / Person" in html
    assert "Lieferung" in html
    assert "Ja · 11.09.2026 · 13:20" in html
    assert "Technische Originaldaten" in html


def test_render_incomplete_call_explains_missing_fields() -> None:
    call = _call(contact_name="", caller_phone="", event_date=None)

    html = render_ai_telefon_call_detail(call, error_message="Testfehler")

    assert "Testfehler" in html
    assert "Anfrage noch nicht direkt übernehmbar" in html
    assert "Datum, Name, Telefon" in html
    assert "Als Anfrage übernehmen" not in html
    assert "Als Aufgabe übernehmen" not in html
    assert "Erledigt" in html


def test_render_processed_result_links() -> None:
    inquiry = render_ai_telefon_call_detail(
        _call(status="PROCESSED", result_type="INQUIRY", result_id=_RESULT_ID)
    )
    task = render_ai_telefon_call_detail(
        _call(status="PROCESSED", result_type="TASK", result_id=_RESULT_ID)
    )
    linked = render_ai_telefon_call_detail(
        _call(status="PROCESSED", result_type="LINKED", result_id=_RESULT_ID)
    )

    assert f"/inquiry/{_RESULT_ID}" in inquiry
    assert "Anfrage öffnen" in inquiry
    assert f"/aufgaben/{_RESULT_ID}" in task
    assert "Aufgabe öffnen" in task
    assert "öffnen" not in linked


def test_render_callback_and_fulfillment_fallbacks() -> None:
    call = _call()
    no_callback = AiTelefonCall(
        **{
            **call.__dict__,
            "callback_requested": False,
            "callback_date": None,
            "callback_time": None,
            "fulfillment_mode": "PICKUP",
            "budget_per_person_cents": None,
        }
    )
    unknown_callback = AiTelefonCall(
        **{
            **call.__dict__,
            "callback_requested": None,
            "fulfillment_mode": "UNKNOWN",
        }
    )

    html = render_ai_telefon_call_detail(no_callback)
    unknown_html = render_ai_telefon_call_detail(unknown_callback)

    assert "Abholung" in html
    assert "Nein" in html
    assert "Nicht angegeben" in unknown_html


class _DummyHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def test_runtime_builds_remote_and_local_servers(monkeypatch) -> None:
    monkeypatch.setattr(
        office_panel_http,
        "make_office_panel_handler",
        lambda *args, **kwargs: _DummyHandler,
    )

    remote_server = create_ai_enabled_office_panel_server(
        object(),
        object(),
        "pw",
        host="127.0.0.1",
        port=0,
        remote=object(),
    )
    try:
        assert remote_server.RequestHandlerClass is _DummyHandler
    finally:
        remote_server.server_close()

    connection = sqlite3.connect(":memory:")
    inquiry_repo = SimpleNamespace(_conn=connection)
    local_server = create_ai_enabled_office_panel_server(
        inquiry_repo,
        object(),
        "pw",
        host="127.0.0.1",
        port=0,
    )
    try:
        assert (
            local_server.RequestHandlerClass.__name__ == "AiEnabledOfficePanelHandler"
        )
    finally:
        local_server.server_close()
        connection.close()


def test_manual_task_service_wiring_branches() -> None:
    connection = sqlite3.connect(":memory:")
    other_connection = sqlite3.connect(":memory:")
    try:
        assert _manual_task_service(connection, None) is None
        assert _manual_task_service(connection, SimpleNamespace()) is None

        separate_auth_repo = SimpleNamespace(
            _conn=other_connection,
            get_account_by_id=lambda employee_id: SimpleNamespace(is_active=True),
        )
        separate_auth = SimpleNamespace(repository=separate_auth_repo)
        assert _manual_task_service(connection, separate_auth) is not None

        auth_repo = SimpleNamespace(
            _conn=connection,
            get_account_by_id=lambda employee_id: SimpleNamespace(is_active=True),
        )
        auth_service = SimpleNamespace(repository=auth_repo)
        assert _manual_task_service(connection, auth_service) is not None
    finally:
        other_connection.close()
        connection.close()


def test_ai_nav_injection_and_guard_branches() -> None:
    page = (
        '<html><nav><a class="office-nav-link" href="/inquiries">Anfragen</a>'
        '<a class="office-nav-link" href="/offers">Angebote</a>'
        '<a class="office-nav-link" href="/aufgaben">Aufgaben</a></nav></html>'
    )
    allowed_auth = SimpleNamespace(
        kind="basic",
        legacy_shared_access=True,
        employee=None,
    )
    handler = SimpleNamespace(
        path="/ki-telefonassistent",
        _request_auth=allowed_auth,
    )
    service = SimpleNamespace(count_new=lambda: 3)

    injected = _inject_ai_nav(page, handler, service)
    assert "KI Telefonassistent" in injected
    assert '<span class="badge">3</span>' in injected
    assert 'aria-current="page"' in injected
    assert injected.index("Angebote") < injected.index("KI Telefonassistent")
    assert injected.index("KI Telefonassistent") < injected.index("Aufgaben")

    assert _inject_ai_nav("<html></html>", handler, service) == "<html></html>"
    assert _inject_ai_nav(injected, handler, service) == injected

    no_auth_handler = SimpleNamespace(path="/", _request_auth=None)
    assert _inject_ai_nav(page, no_auth_handler, service) == page

    no_badge = _inject_ai_nav(
        page,
        SimpleNamespace(path="/", _request_auth=allowed_auth),
        SimpleNamespace(count_new=lambda: 0),
    )
    assert "KI Telefonassistent" in no_badge
    assert "badge" not in no_badge


def test_office_panel_with_ai_entrypoint_swaps_server_factory(monkeypatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(office_panel, "main", lambda: called.append(True))

    office_panel_with_ai.main()

    assert called == [True]
    assert (
        office_panel.create_office_panel_server
        is create_richtangebot_enabled_office_panel_server
    )

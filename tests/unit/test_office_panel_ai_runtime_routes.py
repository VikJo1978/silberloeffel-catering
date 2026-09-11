from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

from catering_system.domain.ai_telefon_call import AiTelefonCall
from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)
from catering_system.ui import office_panel_http
from catering_system.ui.office_panel_ai_runtime import (
    create_ai_enabled_office_panel_server,
)
from catering_system.ui.office_panel_views import OfficePageContext

_CALL_ID = "8e5d6ac1-1a43-49b0-8803-d76ac86a9666"
_INQUIRY_ID = "88d2656a-f17c-4686-9f91-b6b9bad20a7c"


def _call() -> AiTelefonCall:
    received = datetime(2026, 9, 10, 18, 0, tzinfo=UTC)
    return AiTelefonCall(
        call_id=_CALL_ID,
        strato_id="9b03db78-d1bb-4866-b15e-2f92d99a4917",
        gmail_message_id="1a08c90969d6e2e2",
        caller_phone="+4917642795029",
        contact_name="Viktor Schmidt",
        email="",
        subject="Änderung eines bestehenden Angebots",
        summary="Bitte Gästezahl von 60 auf 70 ändern und zurückrufen.",
        raw_message="Zusammenfassung: Test",
        status="NEW",
        received_at=received,
        updated_at=received,
    )


class _RuntimeBaseHandler:
    def _require_business_permission_get(self, *args, **kwargs) -> bool:
        return True

    def _require_business_permission_post(self, *args, **kwargs) -> bool:
        return True

    def _page_context(self) -> OfficePageContext:
        return OfficePageContext(csrf_token="csrf-token")

    def _html(
        self,
        page: str,
        status: int = 200,
        *,
        cookie_headers: tuple[str, ...] = (),
    ) -> None:
        self.rendered_page = page
        self.rendered_status = status
        self.cookie_headers = cookie_headers

    def _redirect(self, location: str) -> None:
        self.redirect_location = location

    def _form(self) -> dict[str, str]:
        return self.form_data

    def _business_forbidden(self, *, active_section: str = "home") -> None:
        self.forbidden_section = active_section

    def _route_get(self) -> None:
        self.fell_through_get = True

    def _route_post(self, parts: list[str]) -> None:
        self.fell_through_post = parts

    def send_error(self, status: int) -> None:
        self.error_status = status


def _handler_fixture(monkeypatch):
    monkeypatch.setattr(
        office_panel_http,
        "make_office_panel_handler",
        lambda *args, **kwargs: _RuntimeBaseHandler,
    )
    connection = sqlite3.connect(":memory:")
    inquiry_repo = SimpleNamespace(
        _conn=connection,
        list_all=lambda: [],
        get_by_id=lambda value: object() if value == _INQUIRY_ID else None,
    )
    order_repo = SimpleNamespace(
        list_orders=lambda: [],
        list_order_versions=lambda order_id: [],
        get_order=lambda order_id: None,
    )
    repository = SQLiteAiTelefonCallRepository.from_connection(connection)
    repository.save(_call())
    server = create_ai_enabled_office_panel_server(
        inquiry_repo,
        order_repo,
        "pw",
        host="127.0.0.1",
        port=0,
    )
    auth = SimpleNamespace(kind="basic", legacy_shared_access=True, employee=None)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    handler._request_auth = auth
    handler.form_data = {}
    return connection, repository, server, handler


def test_runtime_routes_render_list_and_detail(monkeypatch) -> None:
    connection, repository, server, handler = _handler_fixture(monkeypatch)
    try:
        handler.path = "/ki-telefonassistent"
        handler._route_get()
        assert "KI Telefonassistent" in handler.rendered_page
        assert "Viktor Schmidt" in handler.rendered_page

        handler.path = f"/ki-telefonassistent/{_CALL_ID}"
        handler._route_get()
        assert "Änderung eines bestehenden Angebots" in handler.rendered_page
        assert "Mit bestehendem Vorgang verknüpfen" in handler.rendered_page
    finally:
        server.server_close()
        connection.close()


def test_runtime_route_links_existing_inquiry(monkeypatch) -> None:
    connection, repository, server, handler = _handler_fixture(monkeypatch)
    try:
        handler.path = f"/ki-telefonassistent/{_CALL_ID}"
        handler.form_data = {
            "linked_type": "INQUIRY",
            "linked_id": _INQUIRY_ID,
        }
        handler._route_post(["ki-telefonassistent", _CALL_ID, "verknuepfen"])

        assert handler.redirect_location == f"/ki-telefonassistent/{_CALL_ID}"
        stored = repository.get(_CALL_ID)
        assert stored is not None
        assert stored.status == "PROCESSED"
        assert stored.result_type == "LINKED"
        assert stored.linked_type == "INQUIRY"
        assert stored.linked_id == _INQUIRY_ID
    finally:
        server.server_close()
        connection.close()

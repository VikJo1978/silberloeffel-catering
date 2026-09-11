"""Richtangebot extension layered on top of the KI Telefonassistent runtime."""

from __future__ import annotations

import sqlite3
from typing import Any, cast
from urllib.parse import quote, unquote, urlparse

from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)
from catering_system.repositories.sqlite_richtangebot_repository import (
    SQLiteRichtangebotRepository,
)
from catering_system.services.ai_telefon_call_service import AiTelefonCallService
from catering_system.services.richtangebot_service import RichtangebotService
from catering_system.ui.office_panel_ai_runtime import (
    create_ai_enabled_office_panel_server,
)
from catering_system.ui.office_panel_richtangebot import (
    render_richtangebot_detail,
    render_richtangebote_section,
)
from catering_system.ui.office_panel_shell import OfficeSection

_OFFERS_SECTION: OfficeSection = "offers"
_AI_SECTION = cast(OfficeSection, "ai_phone")


def create_richtangebot_enabled_office_panel_server(
    inquiry_repo: Any,
    order_repo: Any,
    password: str,
    *args: Any,
    **kwargs: Any,
):
    """Return the AI-enabled server plus preliminary Richtangebot routes."""

    server = create_ai_enabled_office_panel_server(
        inquiry_repo,
        order_repo,
        password,
        *args,
        **kwargs,
    )
    connection = getattr(inquiry_repo, "_conn", None)
    if kwargs.get("remote") is not None or not isinstance(
        connection, sqlite3.Connection
    ):
        return server

    richt_repo = SQLiteRichtangebotRepository.from_connection(connection)
    richt_service = RichtangebotService(richt_repo)
    call_repo = SQLiteAiTelefonCallRepository.from_connection(connection)
    call_service = AiTelefonCallService(call_repo, richtangebot_service=richt_service)
    command_executor = kwargs.get("command_executor")
    base_handler: Any = server.RequestHandlerClass

    class RichtangebotEnabledHandler(base_handler):
        def _run_richtangebot_write(self, work):
            if command_executor is not None:
                return command_executor.run(work)
            return work()

        def _route_get(self) -> None:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 2 and parts[0] == "richtangebot":
                auth = self._request_auth
                if not self._require_business_permission_get(
                    auth, "offers.view", active_section=_OFFERS_SECTION
                ):
                    return
                value = richt_service.get(unquote(parts[1]))
                if value is None:
                    self.send_error(404)
                    return
                self._html(
                    render_richtangebot_detail(value, context=self._page_context())
                )
                return
            super()._route_get()

        def _route_post(self, parts: list[str]) -> None:
            if (
                len(parts) == 3
                and parts[0] == "ki-telefonassistent"
                and parts[2] == "richtangebot"
            ):
                auth = self._request_auth
                if not self._require_business_permission_post(
                    auth, "offers.prepare", active_section=_AI_SECTION
                ):
                    return
                call_id = unquote(parts[1])
                updated = self._run_richtangebot_write(
                    lambda: call_service.convert_to_richtangebot(call_id)
                )
                assert updated.result_id is not None
                self._redirect(f"/richtangebot/{quote(updated.result_id, safe='')}")
                return
            super()._route_post(parts)

        def _html(
            self,
            page: str,
            status: int = 200,
            *,
            cookie_headers: tuple[str, ...] = (),
        ) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/angebote" and status == 200:
                section = render_richtangebote_section(richt_service.list_recent())
                if section:
                    marker = '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
                    if marker in page:
                        page = page.replace(marker, section + marker, 1)
                    elif "</main>" in page:
                        page = page.replace("</main>", section + "</main>", 1)
            super()._html(page, status, cookie_headers=cookie_headers)

    server.RequestHandlerClass = RichtangebotEnabledHandler
    return server

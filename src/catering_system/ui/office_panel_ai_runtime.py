"""Runtime integration for the KI Telefonassistent inbox.

This module deliberately wraps the existing Office Panel handler instead of
copying its large routing module. The base handler keeps authentication, CSRF,
security headers and all existing routes. The wrapper adds only the AI phone
inbox routes and injects one sidebar entry.

For the current Lenovo deployment this integration is available in direct
SQLite mode. Remote Office Panel mode remains unchanged until the frozen Core
Office API gets an explicit AI-call contract.
"""

from __future__ import annotations

import sqlite3
from http.server import HTTPServer
from typing import Any, cast
from urllib.parse import quote, unquote, urlparse

from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)
from catering_system.repositories.sqlite_manual_task_repository import (
    SQLiteManualTaskRepository,
)
from catering_system.services.ai_telefon_call_service import AiTelefonCallService
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.manual_task_service import ManualTaskService
from catering_system.ui.office_panel_ai_telefonist import (
    render_ai_telefon_call_detail,
    render_ai_telefon_calls,
)
from catering_system.ui.office_panel_authz import can_access
from catering_system.ui.office_panel_shell import OfficeSection


def create_ai_enabled_office_panel_server(
    inquiry_repo: Any,
    order_repo: Any,
    password: str,
    host: str = "0.0.0.0",
    port: int = 8081,
    auerswald_url: str = "",
    auerswald_user: str = "",
    auerswald_password: str = "",
    kiosk_url: str = "",
    configurator_url: str = "",
    *,
    remote: Any | None = None,
    command_executor: Any | None = None,
    payment_reminder_repo: Any | None = None,
    confirmation_document_repo: Any | None = None,
    confirmation_outbound_repo: Any | None = None,
    pause_repository: Any | None = None,
    contact_note_repo: Any | None = None,
    contact_profile_repo: Any | None = None,
    offer_repo: Any | None = None,
    catalog_repo: Any | None = None,
    commercial_snapshot_repo: Any | None = None,
    offer_document_repo: Any | None = None,
    offer_pdf_static_content: Any | None = None,
    kitchen_print_job_repo: Any | None = None,
    ui_version: str = "legacy",
    auth_mode: str = "basic",
    auth_service: Any | None = None,
    secure_cookie: bool = True,
) -> HTTPServer:
    """Return the normal Office Panel server plus the local AI call inbox.

    Remote mode is intentionally delegated unchanged. The inbox is a Core fact
    and must not create a second, panel-local database beside a remote Core.
    """

    from catering_system.ui.office_panel_http import make_office_panel_handler

    base_handler: Any = make_office_panel_handler(
        inquiry_repo,
        order_repo,
        password,
        auerswald_url,
        auerswald_user,
        auerswald_password,
        kiosk_url,
        configurator_url,
        remote=remote,
        command_executor=command_executor,
        payment_reminder_repo=payment_reminder_repo,
        confirmation_document_repo=confirmation_document_repo,
        confirmation_outbound_repo=confirmation_outbound_repo,
        pause_repository=pause_repository,
        contact_note_repo=contact_note_repo,
        contact_profile_repo=contact_profile_repo,
        offer_repo=offer_repo,
        catalog_repo=catalog_repo,
        commercial_snapshot_repo=commercial_snapshot_repo,
        offer_document_repo=offer_document_repo,
        offer_pdf_static_content=offer_pdf_static_content,
        kitchen_print_job_repo=kitchen_print_job_repo,
        ui_version=ui_version,
        auth_mode=auth_mode,  # type: ignore[arg-type]
        auth_service=auth_service,
        secure_cookie=secure_cookie,
    )

    connection = getattr(inquiry_repo, "_conn", None)
    if remote is not None or not isinstance(connection, sqlite3.Connection):
        return HTTPServer((host, port), base_handler)

    call_repository = SQLiteAiTelefonCallRepository.from_connection(connection)
    manual_task_service = _manual_task_service(connection, auth_service)
    call_service = AiTelefonCallService(
        call_repository,
        inquiry_repository=inquiry_repo,
        inquiry_service=InquiryService(inquiry_repo),
        manual_task_service=manual_task_service,
    )

    class AiEnabledOfficePanelHandler(base_handler):
        def _ai_active_section(self) -> OfficeSection:
            return cast(OfficeSection, "ai_phone")

        def _run_ai_write(self, work):
            if command_executor is not None:
                return command_executor.run(work)
            return work()

        def _route_get(self) -> None:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            if parts == ["ki-telefonassistent"]:
                auth = self._request_auth
                if not self._require_business_permission_get(
                    auth, "queue.view", active_section=self._ai_active_section()
                ):
                    return
                self._html(
                    render_ai_telefon_calls(
                        call_service.list_recent(), context=self._page_context()
                    )
                )
                return
            if len(parts) == 2 and parts[0] == "ki-telefonassistent":
                auth = self._request_auth
                if not self._require_business_permission_get(
                    auth, "queue.view", active_section=self._ai_active_section()
                ):
                    return
                call = call_service.get(unquote(parts[1]))
                if call is None:
                    self.send_error(404)
                    return
                self._html(
                    render_ai_telefon_call_detail(call, context=self._page_context())
                )
                return
            super()._route_get()

        def _route_post(self, parts: list[str]) -> None:
            if len(parts) == 3 and parts[0] == "ki-telefonassistent":
                call_id = unquote(parts[1])
                action = parts[2]
                auth = self._request_auth

                if action == "anfrage":
                    if not self._require_business_permission_post(
                        auth,
                        "inquiries.create",
                        active_section=self._ai_active_section(),
                    ):
                        return
                    updated = self._run_ai_write(
                        lambda: call_service.convert_to_inquiry(call_id)
                    )
                    assert updated.result_id is not None
                    self._redirect(f"/inquiry/{quote(updated.result_id, safe='')}")
                    return

                if action == "aufgabe":
                    if not self._require_business_permission_post(
                        auth,
                        "tasks.create",
                        active_section=self._ai_active_section(),
                    ):
                        return
                    if (
                        auth is None
                        or auth.kind != "employee"
                        or auth.employee is None
                        or auth.legacy_shared_access
                    ):
                        self._business_forbidden(
                            active_section=self._ai_active_section()
                        )
                        return
                    employee_id = auth.employee.account.id
                    updated = self._run_ai_write(
                        lambda: call_service.convert_to_task(
                            call_id, created_by_employee_id=employee_id
                        )
                    )
                    assert updated.result_id is not None
                    self._redirect(f"/aufgaben/{quote(updated.result_id, safe='')}")
                    return

                if action == "erledigt":
                    if not self._require_business_permission_post(
                        auth,
                        "queue.resolve",
                        active_section=self._ai_active_section(),
                    ):
                        return
                    self._run_ai_write(lambda: call_service.mark_done(call_id))
                    self._redirect("/ki-telefonassistent")
                    return

            super()._route_post(parts)

        def _html(
            self,
            page: str,
            status: int = 200,
            *,
            cookie_headers: tuple[str, ...] = (),
        ) -> None:
            super()._html(
                _inject_ai_nav(page, self, call_service),
                status,
                cookie_headers=cookie_headers,
            )

    return HTTPServer((host, port), AiEnabledOfficePanelHandler)


def _manual_task_service(
    connection: sqlite3.Connection, auth_service: Any | None
) -> ManualTaskService | None:
    if auth_service is None:
        return None
    auth_repository = getattr(auth_service, "repository", None)
    if auth_repository is None:
        return None

    # Keep the task write on the same Core connection as the AiTelefonCall
    # update so CoreCommandExecutor can commit both facts atomically. The auth
    # repository may legitimately use another connection to the same DB.
    repository = SQLiteManualTaskRepository.from_connection(connection)

    def employee_exists(employee_id: str) -> bool:
        account = auth_repository.get_account_by_id(employee_id)
        return account is not None and account.is_active

    return ManualTaskService(repository, employee_exists=employee_exists)


def _inject_ai_nav(page: str, handler: Any, call_service: AiTelefonCallService) -> str:
    """Add one sidebar entry without modifying the large shared page renderer."""

    nav_end = "</nav>"
    if nav_end not in page or "/ki-telefonassistent" in page.split(nav_end, 1)[0]:
        return page
    auth = getattr(handler, "_request_auth", None)
    if auth is None or not can_access(auth, "queue.view"):
        return page
    current = (
        ' aria-current="page"'
        if handler.path.startswith("/ki-telefonassistent")
        else ""
    )
    count = call_service.count_new()
    badge = f'<span class="badge">{count}</span>' if count else ""
    link = (
        f'<a class="office-nav-link" href="/ki-telefonassistent"{current}>'
        '<svg aria-hidden="true"><use href="#office-i-phone"></use></svg>'
        f"<span>KI Telefonassistent</span>{badge}</a>"
    )

    # Place it beside the other Vertrieb work queues when Aufgaben is visible;
    # otherwise append it to the nav as a safe fallback.
    tasks_link = '<a class="office-nav-link" href="/aufgaben"'
    if tasks_link in page:
        return page.replace(tasks_link, link + tasks_link, 1)
    return page.replace(nav_end, link + nav_end, 1)

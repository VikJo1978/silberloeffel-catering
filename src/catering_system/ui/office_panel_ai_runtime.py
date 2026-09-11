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
from urllib.parse import parse_qs, quote, unquote, urlparse

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
    AiTelefonLinkCandidate,
    render_ai_telefon_call_detail,
    render_ai_telefon_calls,
)
from catering_system.ui.office_panel_authz import can_access
from catering_system.ui.office_panel_shell import OfficeSection

_LINK_VIEW_PERMISSIONS = {
    "INQUIRY": "inquiries.view",
    "OFFER": "offers.view",
    "ORDER": "orders.view",
}


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

        def _ai_link_candidates(
            self, query: str, auth: Any
        ) -> tuple[AiTelefonLinkCandidate, ...]:
            allowed_types = frozenset(
                linked_type
                for linked_type, permission in _LINK_VIEW_PERMISSIONS.items()
                if can_access(auth, permission)
                and (linked_type != "OFFER" or offer_repo is not None)
            )
            return _link_candidates(
                query,
                inquiry_repo,
                order_repo,
                offer_repo,
                allowed_types=allowed_types,
            )

        def _render_ai_detail(self, call: Any, *, error_message: str = "") -> None:
            parsed = urlparse(self.path)
            query = (
                parse_qs(parsed.query, keep_blank_values=True).get("q", [""])[0].strip()
            )
            self._html(
                render_ai_telefon_call_detail(
                    call,
                    context=self._page_context(),
                    error_message=error_message,
                    link_query=query,
                    link_candidates=self._ai_link_candidates(query, self._request_auth),
                )
            )

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
                self._render_ai_detail(call)
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

                if action == "verknuepfen":
                    if not self._require_business_permission_post(
                        auth,
                        "queue.resolve",
                        active_section=self._ai_active_section(),
                    ):
                        return
                    call = call_service.get(call_id)
                    if call is None:
                        self.send_error(404)
                        return
                    form = self._form()
                    linked_type = form.get("linked_type", "").strip().upper()
                    linked_id = form.get("linked_id", "").strip()
                    permission = _LINK_VIEW_PERMISSIONS.get(linked_type)
                    if permission is None or not can_access(auth, permission):
                        self._business_forbidden(
                            active_section=self._ai_active_section()
                        )
                        return
                    if not _linked_target_exists(
                        linked_type,
                        linked_id,
                        inquiry_repo,
                        order_repo,
                        offer_repo,
                    ):
                        self._render_ai_detail(
                            call,
                            error_message=(
                                "Der ausgewählte Vorgang existiert nicht mehr. "
                                "Bitte erneut suchen."
                            ),
                        )
                        return
                    try:
                        self._run_ai_write(
                            lambda: call_service.link_existing(
                                call_id,
                                linked_type=linked_type,
                                linked_id=linked_id,
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        self._render_ai_detail(
                            call,
                            error_message=(
                                "Die Verknüpfung konnte nicht gespeichert werden. "
                                "Bitte den Vorgang erneut auswählen."
                            ),
                        )
                        return
                    self._redirect(f"/ki-telefonassistent/{quote(call_id, safe='')}")
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


def _link_candidates(
    query: str,
    inquiry_repo: Any,
    order_repo: Any,
    offer_repo: Any | None,
    *,
    allowed_types: frozenset[str],
    limit: int = 20,
) -> tuple[AiTelefonLinkCandidate, ...]:
    needle = query.strip().casefold()
    if len(needle) < 2 or not allowed_types or limit < 1:
        return ()

    inquiries = list(inquiry_repo.list_all())
    inquiry_by_id = {inquiry.inquiry_id: inquiry for inquiry in inquiries}
    candidates: list[AiTelefonLinkCandidate] = []

    def append(candidate: AiTelefonLinkCandidate) -> bool:
        candidates.append(candidate)
        return len(candidates) >= limit

    if "INQUIRY" in allowed_types:
        for inquiry in inquiries:
            if _matches_link_query(needle, inquiry):
                title, details = _inquiry_candidate_text(inquiry)
                if append(
                    AiTelefonLinkCandidate(
                        linked_type="INQUIRY",
                        linked_id=inquiry.inquiry_id,
                        title=title,
                        details=details,
                    )
                ):
                    return tuple(candidates)

    if "OFFER" in allowed_types and offer_repo is not None:
        for offer in offer_repo.list_all():
            inquiry = inquiry_by_id.get(offer.source_inquiry_id)
            if not _matches_link_query(needle, offer, inquiry):
                continue
            latest = max(offer.versions, key=lambda version: version.version_number)
            source_title, _ = _inquiry_candidate_text(inquiry)
            details = _candidate_details(
                latest.event_date,
                latest.location_text,
                offer.offer_id,
            )
            if append(
                AiTelefonLinkCandidate(
                    linked_type="OFFER",
                    linked_id=offer.offer_id,
                    title=f"Angebot · {source_title}",
                    details=details,
                )
            ):
                return tuple(candidates)

    if "ORDER" in allowed_types:
        for order in order_repo.list_orders():
            inquiry = inquiry_by_id.get(order.source_inquiry_id)
            versions = order_repo.list_order_versions(order.order_id)
            latest = (
                max(versions, key=lambda version: version.version_number)
                if versions
                else None
            )
            if not _matches_link_query(needle, order, inquiry, latest):
                continue
            source_title, _ = _inquiry_candidate_text(inquiry)
            details = _candidate_details(
                getattr(latest, "event_date", None),
                getattr(latest, "location_text", ""),
                order.order_id,
            )
            if append(
                AiTelefonLinkCandidate(
                    linked_type="ORDER",
                    linked_id=order.order_id,
                    title=f"Auftrag · {source_title}",
                    details=details,
                )
            ):
                return tuple(candidates)

    return tuple(candidates)


def _linked_target_exists(
    linked_type: str,
    linked_id: str,
    inquiry_repo: Any,
    order_repo: Any,
    offer_repo: Any | None,
) -> bool:
    if not linked_id:
        return False
    if linked_type == "INQUIRY":
        return inquiry_repo.get_by_id(linked_id) is not None
    if linked_type == "OFFER":
        return offer_repo is not None and offer_repo.get(linked_id) is not None
    if linked_type == "ORDER":
        return order_repo.get_order(linked_id) is not None
    return False


def _matches_link_query(needle: str, *objects: Any) -> bool:
    return any(obj is not None and needle in repr(obj).casefold() for obj in objects)


def _inquiry_candidate_text(inquiry: Any | None) -> tuple[str, str]:
    if inquiry is None:
        return "Vorgang ohne Anfragekontext", ""
    snapshot = getattr(inquiry, "customer_snapshot", None)
    contact_name = getattr(snapshot, "contact_name", "") if snapshot is not None else ""
    title = contact_name or getattr(inquiry, "intake_subject", None) or "Anfrage"
    details = _candidate_details(
        getattr(inquiry, "event_date", None),
        getattr(inquiry, "location_text", ""),
        inquiry.inquiry_id,
    )
    return str(title), details


def _candidate_details(event_date: Any, location: Any, identifier: str) -> str:
    bits: list[str] = []
    if event_date is not None:
        formatter = getattr(event_date, "strftime", None)
        bits.append(formatter("%d.%m.%Y") if callable(formatter) else str(event_date))
    if location:
        bits.append(str(location))
    bits.append(identifier)
    return " · ".join(bits)


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

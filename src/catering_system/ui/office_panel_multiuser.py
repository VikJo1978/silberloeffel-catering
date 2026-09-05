"""Multi-user edit coordination wrapper for the existing Office Panel handler.

The wrapper does not replace any business command, RBAC check, CSRF check or
optimistic concurrency precondition.  It only adds a short-lived employee
lease so colleagues can see when somebody else is already editing the same
Inquiry, Offer or Order.
"""

from __future__ import annotations

import html
import sqlite3
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from catering_system.repositories.sqlite_office_edit_lease_repository import (
    OfficeEditLeaseClaim,
    SQLiteOfficeEditLeaseRepository,
)
from catering_system.ui.office_panel_http import make_office_panel_handler

_BERLIN = ZoneInfo("Europe/Berlin")

_RECORD_WRITE_PERMISSIONS: dict[str, frozenset[str]] = {
    "inquiry": frozenset(
        {
            "inquiries.edit",
            "inquiries.verify",
            "customers.edit",
            "offers.prepare",
            "offers.version.create",
            "orders.version.create",
        }
    ),
    "offer": frozenset(
        {
            "offers.prepare",
            "offers.version.create",
            "offers.pdf.generate",
            "offers.send",
            "offers.status.change",
            "offers.timing.acknowledge",
            "orders.version.create",
        }
    ),
    "order": frozenset(
        {
            "orders.version.create",
            "orders.print.confirm",
            "orders.effective.set",
            "orders.ready.release",
            "orders.pause",
            "orders.cancel",
            "orders.delete",
            "orders.payment.reminder",
            "documents.prepare",
            "documents.send",
        }
    ),
}

_LIST_PATHS = {
    "inquiry": "/anfragen",
    "offer": "/angebote",
    "order": "/orders",
}

_ACTIVE_SECTIONS = {
    "inquiry": "inquiries",
    "offer": "offers",
    "order": "orders",
}


def _detail_record(path: str) -> tuple[str, str] | None:
    parts = [part for part in urlparse(path).path.split("/") if part]
    if len(parts) == 2 and parts[0] in _RECORD_WRITE_PERMISSIONS:
        return parts[0], parts[1]
    return None


def _post_record(parts: list[str]) -> tuple[str, str] | None:
    if len(parts) == 3 and parts[0] in _RECORD_WRITE_PERMISSIONS:
        return parts[0], parts[1]
    if (
        len(parts) == 4
        and parts[0] == "order"
        and parts[2] == "confirmation-document"
        and parts[3] == "send"
    ):
        return "order", parts[1]
    return None


def _lease_route(parts: list[str]) -> tuple[str, str, str] | None:
    if (
        len(parts) == 4
        and parts[0] == "work-lease"
        and parts[1] in _RECORD_WRITE_PERMISSIONS
        and parts[3] in {"takeover", "release"}
    ):
        return parts[1], parts[2], parts[3]
    return None


def _employee_actor(auth: Any) -> tuple[str, str, frozenset[str]] | None:
    if (
        auth is None
        or getattr(auth, "kind", None) != "employee"
        or getattr(auth, "employee", None) is None
        or getattr(auth, "legacy_shared_access", False)
    ):
        return None
    employee = auth.employee
    return (
        employee.account.id,
        employee.account.display_name,
        employee.effective_permissions,
    )


def _can_coordinate(auth: Any, entity_type: str) -> bool:
    actor = _employee_actor(auth)
    if actor is None:
        return False
    return bool(actor[2].intersection(_RECORD_WRITE_PERMISSIONS[entity_type]))


def _lease_repository(auth_service: Any) -> SQLiteOfficeEditLeaseRepository | None:
    if auth_service is None:
        return None
    connection = getattr(getattr(auth_service, "repository", None), "_conn", None)
    if not isinstance(connection, sqlite3.Connection):
        return None
    return SQLiteOfficeEditLeaseRepository.from_connection(connection)


def _record_url(entity_type: str, entity_id: str) -> str:
    return f"/{entity_type}/{quote(entity_id, safe='')}"


def _lease_banner(
    claim: OfficeEditLeaseClaim,
    *,
    csrf_token: str,
) -> str:
    lease = claim.lease
    entity_type = lease.entity_type
    entity_id = lease.entity_id
    expires = lease.expires_at.astimezone(_BERLIN).strftime("%H:%M")
    csrf = html.escape(csrf_token, quote=True)
    action_base = (
        f"/work-lease/{html.escape(entity_type, quote=True)}/"
        f"{html.escape(entity_id, quote=True)}"
    )
    if claim.owned_by_requester:
        return (
            '<div class="office-global-banner">'
            "<strong>In Bearbeitung durch Sie.</strong> "
            f"Reserviert bis {html.escape(expires)}. "
            '<form class="inline" method="post" '
            f'action="{action_base}/release">'
            f'<input type="hidden" name="_csrf_token" value="{csrf}">'
            '<button type="submit">Bearbeitung beenden</button>'
            "</form></div>"
        )
    holder = html.escape(lease.holder_display_name)
    return (
        '<div class="office-global-banner blocked">'
        f"<strong>Wird bearbeitet von {holder}.</strong> "
        "Änderungen sind gesperrt, damit der Vorgang nicht doppelt bearbeitet wird. "
        f"Lease bis {html.escape(expires)}. "
        '<form class="inline" method="post" '
        f'action="{action_base}/takeover" '
        "onsubmit=\"return confirm('Bearbeitung wirklich übernehmen?');\">"
        f'<input type="hidden" name="_csrf_token" value="{csrf}">'
        '<button type="submit">Bearbeitung übernehmen</button>'
        "</form></div>"
    )


def add_edit_lease_coordination(
    base_handler: type[BaseHTTPRequestHandler],
    repository: SQLiteOfficeEditLeaseRepository | None,
) -> type[BaseHTTPRequestHandler]:
    """Decorate the existing handler class in place with soft edit leases."""
    if repository is None:
        return base_handler

    handler = cast(Any, base_handler)
    original_route_get = handler._route_get
    original_route_post = handler._route_post
    original_page_context = handler._page_context
    original_html = handler._html

    def _route_get(self: Any) -> None:
        self._office_edit_lease_claim = None
        record = _detail_record(self.path)
        auth = getattr(self, "_request_auth", None)
        if record is not None and _can_coordinate(auth, record[0]):
            actor = _employee_actor(auth)
            assert actor is not None
            self._office_edit_lease_claim = repository.claim_or_observe(
                record[0],
                record[1],
                holder_account_id=actor[0],
                holder_display_name=actor[1],
            )
        original_route_get(self)

    def _page_context(self: Any, *args: Any, **kwargs: Any) -> Any:
        context = original_page_context(self, *args, **kwargs)
        claim = getattr(self, "_office_edit_lease_claim", None)
        if claim is None or claim.owned_by_requester:
            return context
        blocked = _RECORD_WRITE_PERMISSIONS[claim.lease.entity_type]
        return replace(
            context,
            employee_effective_permissions=(
                context.employee_effective_permissions.difference(blocked)
            ),
        )

    def _html(self: Any, page: str, status: int = 200, **kwargs: Any) -> None:
        claim = getattr(self, "_office_edit_lease_claim", None)
        if claim is not None:
            auth = getattr(self, "_request_auth", None)
            csrf_token = getattr(auth, "csrf_token", "") if auth is not None else ""
            marker = '<div class="office-content">'
            banner = _lease_banner(claim, csrf_token=csrf_token)
            page = page.replace(marker, marker + banner, 1)
        original_html(self, page, status, **kwargs)

    def _route_post(self: Any, parts: list[str]) -> None:
        lease_action = _lease_route(parts)
        auth = getattr(self, "_request_auth", None)
        if lease_action is not None:
            entity_type, entity_id, action = lease_action
            if not _can_coordinate(auth, entity_type):
                self._business_forbidden(active_section=_ACTIVE_SECTIONS[entity_type])
                return
            actor = _employee_actor(auth)
            assert actor is not None
            if action == "takeover":
                lease = repository.takeover(
                    entity_type,
                    entity_id,
                    holder_account_id=actor[0],
                    holder_display_name=actor[1],
                )
                self._office_edit_lease_claim = OfficeEditLeaseClaim(
                    lease=lease,
                    owned_by_requester=True,
                )
                self._redirect(_record_url(entity_type, entity_id))
                return
            repository.release(
                entity_type,
                entity_id,
                holder_account_id=actor[0],
            )
            self._redirect(_LIST_PATHS[entity_type])
            return

        record = _post_record(parts)
        if record is not None and _can_coordinate(auth, record[0]):
            actor = _employee_actor(auth)
            assert actor is not None
            claim = repository.claim_or_observe(
                record[0],
                record[1],
                holder_account_id=actor[0],
                holder_display_name=actor[1],
            )
            self._office_edit_lease_claim = claim
            if not claim.owned_by_requester:
                self._error_page(
                    f"Dieser Vorgang wird bereits von {claim.lease.holder_display_name} "
                    "bearbeitet. Es wurde nichts gespeichert.",
                    status=409,
                )
                return
        original_route_post(self, parts)

    handler._route_get = _route_get
    handler._route_post = _route_post
    handler._page_context = _page_context
    handler._html = _html
    return base_handler


def create_office_panel_server(
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
    **kwargs: Any,
) -> HTTPServer:
    """Create the normal server with the narrow lease coordination decorator."""
    base_handler = make_office_panel_handler(
        inquiry_repo,
        order_repo,
        password,
        auerswald_url,
        auerswald_user,
        auerswald_password,
        kiosk_url,
        configurator_url,
        **kwargs,
    )
    repository = _lease_repository(kwargs.get("auth_service"))
    handler = add_edit_lease_coordination(base_handler, repository)
    return HTTPServer((host, port), handler)


def main() -> None:
    """Run the existing Office Panel main with the coordinated server factory."""
    from catering_system.ui import office_panel

    office_panel_runtime = cast(Any, office_panel)
    office_panel_runtime.create_office_panel_server = create_office_panel_server
    office_panel.main()


if __name__ == "__main__":
    main()

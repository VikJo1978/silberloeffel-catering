from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from catering_system.repositories.sqlite_office_edit_lease_repository import (
    SQLiteOfficeEditLeaseRepository,
)
from catering_system.ui.office_panel_multiuser import add_edit_lease_coordination
from catering_system.ui.office_panel_views import OfficePageContext


def _repository() -> SQLiteOfficeEditLeaseRepository:
    return SQLiteOfficeEditLeaseRepository.from_connection(sqlite3.connect(":memory:"))


def _auth(account_id: str, display_name: str, *permissions: str) -> Any:
    account = SimpleNamespace(id=account_id, display_name=display_name)
    employee = SimpleNamespace(
        account=account,
        effective_permissions=frozenset(permissions),
    )
    return SimpleNamespace(
        kind="employee",
        employee=employee,
        legacy_shared_access=False,
        csrf_token="csrf-test",
    )


def test_lease_claim_renew_conflict_expiry_takeover_and_release() -> None:
    repo = _repository()
    start = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)

    first = repo.claim_or_observe(
        "inquiry",
        "inq-1",
        holder_account_id="anna",
        holder_display_name="Anna Bromm",
        now=start,
        ttl=timedelta(minutes=30),
    )
    assert first.owned_by_requester is True
    assert first.lease.holder_account_id == "anna"

    renewed = repo.claim_or_observe(
        "inquiry",
        "inq-1",
        holder_account_id="anna",
        holder_display_name="Anna Bromm",
        now=start + timedelta(minutes=5),
        ttl=timedelta(minutes=30),
    )
    assert renewed.owned_by_requester is True
    assert renewed.lease.acquired_at == start
    assert renewed.lease.expires_at == start + timedelta(minutes=35)

    blocked = repo.claim_or_observe(
        "inquiry",
        "inq-1",
        holder_account_id="viktor",
        holder_display_name="Viktor Johanson",
        now=start + timedelta(minutes=10),
    )
    assert blocked.owned_by_requester is False
    assert blocked.lease.holder_display_name == "Anna Bromm"

    taken = repo.takeover(
        "inquiry",
        "inq-1",
        holder_account_id="viktor",
        holder_display_name="Viktor Johanson",
        now=start + timedelta(minutes=11),
    )
    assert taken.holder_account_id == "viktor"
    assert repo.release("inquiry", "inq-1", holder_account_id="anna") is False
    assert repo.release("inquiry", "inq-1", holder_account_id="viktor") is True
    assert repo.get_active("inquiry", "inq-1", now=start + timedelta(minutes=12)) is None

    repo.claim_or_observe(
        "order",
        "order-1",
        holder_account_id="anna",
        holder_display_name="Anna Bromm",
        now=start,
        ttl=timedelta(minutes=1),
    )
    after_expiry = repo.claim_or_observe(
        "order",
        "order-1",
        holder_account_id="viktor",
        holder_display_name="Viktor Johanson",
        now=start + timedelta(minutes=2),
    )
    assert after_expiry.owned_by_requester is True
    assert after_expiry.lease.holder_account_id == "viktor"


def test_foreign_lease_removes_write_permissions_and_blocks_post() -> None:
    repo = _repository()

    class FakeHandler:
        def _route_get(self) -> None:
            self.base_get_called = True

        def _route_post(self, parts: list[str]) -> None:
            self.base_post_parts = parts

        def _page_context(self, *args: Any, **kwargs: Any) -> OfficePageContext:
            del args, kwargs
            return OfficePageContext(
                csrf_token="csrf-test",
                current_user_name=self._request_auth.employee.account.display_name,
                employee_account_id=self._request_auth.employee.account.id,
                employee_effective_permissions=(
                    self._request_auth.employee.effective_permissions
                ),
            )

        def _html(self, page: str, status: int = 200, **kwargs: Any) -> None:
            del kwargs
            self.rendered_page = page
            self.rendered_status = status

        def _error_page(self, message: str, status: int = 400) -> None:
            self.error = (message, status)

        def _business_forbidden(self, *, active_section: str = "home") -> None:
            self.forbidden_section = active_section

        def _redirect(self, location: str) -> None:
            self.redirect_location = location

    coordinated = add_edit_lease_coordination(FakeHandler, repo)  # type: ignore[arg-type]

    anna = coordinated()
    anna.path = "/inquiry/inq-1"
    anna._request_auth = _auth(  # type: ignore[attr-defined]
        "anna",
        "Anna Bromm",
        "inquiries.view",
        "inquiries.edit",
    )
    anna._route_get()  # type: ignore[attr-defined]

    viktor = coordinated()
    viktor.path = "/inquiry/inq-1"
    viktor._request_auth = _auth(  # type: ignore[attr-defined]
        "viktor",
        "Viktor Johanson",
        "inquiries.view",
        "inquiries.edit",
        "inquiries.verify",
    )
    viktor._route_get()  # type: ignore[attr-defined]
    context = viktor._page_context()  # type: ignore[attr-defined]
    assert "inquiries.view" in context.employee_effective_permissions
    assert "inquiries.edit" not in context.employee_effective_permissions
    assert "inquiries.verify" not in context.employee_effective_permissions

    viktor._html(  # type: ignore[attr-defined]
        '<html><div class="office-content"><p>Detail</p></div></html>'
    )
    assert "Wird bearbeitet von Anna Bromm" in viktor.rendered_page
    assert "Bearbeitung übernehmen" in viktor.rendered_page

    viktor._route_post(["inquiry", "inq-1", "update"])  # type: ignore[attr-defined]
    assert viktor.error[1] == 409
    assert "Anna Bromm" in viktor.error[0]
    assert not hasattr(viktor, "base_post_parts")


def test_takeover_switches_owner_and_release_returns_to_list() -> None:
    repo = _repository()
    repo.claim_or_observe(
        "offer",
        "offer-1",
        holder_account_id="anna",
        holder_display_name="Anna Bromm",
    )

    class FakeHandler:
        def _route_get(self) -> None:
            pass

        def _route_post(self, parts: list[str]) -> None:
            self.base_post_parts = parts

        def _page_context(self, *args: Any, **kwargs: Any) -> OfficePageContext:
            del args, kwargs
            return OfficePageContext()

        def _html(self, page: str, status: int = 200, **kwargs: Any) -> None:
            del page, status, kwargs

        def _business_forbidden(self, *, active_section: str = "home") -> None:
            self.forbidden_section = active_section

        def _redirect(self, location: str) -> None:
            self.redirect_location = location

    coordinated = add_edit_lease_coordination(FakeHandler, repo)  # type: ignore[arg-type]
    handler = coordinated()
    handler._request_auth = _auth(  # type: ignore[attr-defined]
        "viktor",
        "Viktor Johanson",
        "offers.view",
        "offers.status.change",
    )

    handler._route_post(  # type: ignore[attr-defined]
        ["work-lease", "offer", "offer-1", "takeover"]
    )
    assert handler.redirect_location == "/offer/offer-1"
    active = repo.get_active("offer", "offer-1")
    assert active is not None
    assert active.holder_account_id == "viktor"

    handler._route_post(  # type: ignore[attr-defined]
        ["work-lease", "offer", "offer-1", "release"]
    )
    assert handler.redirect_location == "/angebote"
    assert repo.get_active("offer", "offer-1") is None

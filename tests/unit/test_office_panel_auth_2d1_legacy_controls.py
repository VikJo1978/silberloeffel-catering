from __future__ import annotations

from datetime import date

from catering_system.domain.inquiry import PLANNING_MODES
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.ui.office_panel import OfficePanel
from catering_system.ui.office_panel_views import OfficePageContext
from tests.helpers.office_panel_context import legacy_office_context
from tests.helpers.order_seed import seed_order


def _legacy_panel_with_order() -> tuple[OfficePanel, str]:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    panel = OfficePanel(inquiry_repo, order_repo, ui_version="legacy")
    inquiry = panel.inquiry_service.create_inquiry(
        event_date=date(2026, 10, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    order, _version = seed_order(order_repo, inquiry)
    return panel, order.order_id


def _employee_context(*permissions: str) -> OfficePageContext:
    return OfficePageContext(
        legacy_shared_access=False,
        employee_effective_permissions=frozenset(permissions),
    )


def test_legacy_order_hides_mutation_controls_for_viewer() -> None:
    panel, order_id = _legacy_panel_with_order()
    page = panel.render_order(
        order_id,
        context=_employee_context("orders.view"),
    )
    assert page is not None
    assert "Druck bestätigen" not in page
    assert "Wirksam machen" not in page
    assert "Freigabe anfordern" not in page
    assert "Auftrag stornieren" not in page
    assert "Version anlegen" not in page


def test_legacy_order_shows_print_confirm_with_permission() -> None:
    panel, order_id = _legacy_panel_with_order()
    page = panel.render_order(
        order_id,
        context=_employee_context("orders.view", "orders.print.confirm"),
    )
    assert page is not None
    assert "Druck bestätigen" in page


def test_legacy_order_shows_version_form_with_permission() -> None:
    panel, order_id = _legacy_panel_with_order()
    page = panel.render_order(
        order_id,
        context=_employee_context("orders.view", "orders.version.create"),
    )
    assert page is not None
    assert "Version anlegen" in page
    assert "Freigabe anfordern" not in page


def test_legacy_order_shows_ready_and_cancel_with_permissions() -> None:
    panel, order_id = _legacy_panel_with_order()
    page = panel.render_order(
        order_id,
        context=_employee_context(
            "orders.view",
            "orders.ready.release",
            "orders.cancel",
        ),
    )
    assert page is not None
    assert "Freigabe anfordern" in page
    assert "Auftrag stornieren" in page
    assert "Version anlegen" not in page


def test_legacy_order_basic_fallback_retains_controls() -> None:
    panel, order_id = _legacy_panel_with_order()
    page = panel.render_order(order_id, context=legacy_office_context())
    assert page is not None
    assert "Druck bestätigen" in page
    assert "Freigabe anfordern" in page
    assert "Auftrag stornieren" in page
    assert "Version anlegen" in page

"""Office API read models — dashboard parity with the live panel
(PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §3.10, §9 'dashboard parity')."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.ui import office_api_views as views

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    email="kunde@example.com", phone="+49301234567"
)

_NOW = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)


def _inquiry(inquiry_id: str = "11111111-1111-1111-1111-111111111111") -> Inquiry:
    return Inquiry(
        inquiry_id=inquiry_id,
        event_date=date(2026, 10, 1),
        created_at=_NOW,
        updated_at=_NOW,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
        customer_snapshot=_CONTACT_COMPLETE_SNAPSHOT,
    )


def _panel_action(order: Order, repo: InMemoryOrderRepository) -> dict | None:
    """Extract (action, version) from the real panel's `_next_step_action`
    HTML so the API resolution is provably identical."""
    from catering_system.ui.office_panel import OfficePanel

    panel = OfficePanel.__new__(OfficePanel)
    panel._orders = repo
    panel._remote = None
    html = panel._next_step_action(order)
    if not html:
        return None
    action = re.search(r"/order/[^/]+/([a-z-]+)\"", html)
    version = re.search(r'name="order_version_id" value="([^"]+)"', html)
    assert action and version
    return {"action": action.group(1), "order_version_id": version.group(1)}


def _order_states() -> list[tuple[InMemoryOrderRepository, Order]]:
    """A matrix of order states covering every `_next_step_action` branch."""
    states = []

    def build(configure) -> None:  # noqa: ANN001
        repo = InMemoryOrderRepository()
        osvc = OrderService(repo)
        core = OperationalCoreService(repo)
        order, v1 = osvc.convert_inquiry_to_order(_inquiry())
        configure(repo, osvc, core, order, v1)
        refreshed = repo.get_order(order.order_id)
        assert refreshed is not None
        states.append((repo, refreshed))

    build(lambda repo, osvc, core, order, v1: None)  # unprinted v1
    build(
        lambda repo, osvc, core, order, v1: core.confirm_kitchen_print(
            order.order_id, v1.order_version_id
        )
    )  # printed, not effective

    def printed_effective(repo, osvc, core, order, v1):  # noqa: ANN001, ANN202
        core.confirm_kitchen_print(order.order_id, v1.order_version_id)
        core.make_order_version_effective(order.order_id, v1.order_version_id)

    build(printed_effective)  # nothing to do

    def with_candidate(repo, osvc, core, order, v1):  # noqa: ANN001, ANN202
        core.confirm_kitchen_print(order.order_id, v1.order_version_id)
        core.make_order_version_effective(order.order_id, v1.order_version_id)
        v2 = osvc.create_relevant_order_change_version(
            order,
            event_date=date(2026, 10, 2),
            time_window_text="abends",
            location_text="Kiel",
            guest_count_estimate=30,
            planning_mode=PLANNING_MODES[0],
        )
        osvc.set_candidate_order_version(order.order_id, v2.order_version_id)

    build(with_candidate)  # candidate v2 unprinted → print-confirm on v2

    def highest_fallback(repo, osvc, core, order, v1):  # noqa: ANN001, ANN202
        core.confirm_kitchen_print(order.order_id, v1.order_version_id)
        core.make_order_version_effective(order.order_id, v1.order_version_id)
        osvc.create_relevant_order_change_version(
            order,
            event_date=date(2026, 10, 2),
            time_window_text="abends",
            location_text="Kiel",
            guest_count_estimate=30,
            planning_mode=PLANNING_MODES[0],
        )  # no candidate set → fallback to highest version

    build(highest_fallback)

    def cancelled(repo, osvc, core, order, v1):  # noqa: ANN001, ANN202
        core.cancel_order(order.order_id)

    build(cancelled)
    return states


def test_next_action_resolution_matches_the_live_panel_exactly() -> None:
    for repo, order in _order_states():
        versions = repo.list_order_versions(order.order_id)
        api_action = views.resolve_next_action(order, versions)
        panel_action = _panel_action(order, repo)
        if order.cancelled_at is not None:
            # The panel hides the whole row for cancelled orders elsewhere;
            # its private helper still offers an action, but the frozen
            # contract fixes next_action = null for cancelled orders (§4.1).
            assert api_action is None
        else:
            assert api_action == panel_action


def test_week_uses_berlin_calendar() -> None:
    assert views.BERLIN.key == "Europe/Berlin"
    today = views.berlin_today()
    assert today == datetime.now(views.BERLIN).date()


def test_detail_caps_and_truncation_flags() -> None:
    repo = InMemoryOrderRepository()
    osvc = OrderService(repo)
    order, _v1 = osvc.convert_inquiry_to_order(_inquiry())
    fresh = repo.get_order(order.order_id)
    assert fresh is not None
    many_orders = [
        Order(
            order_id=f"o-{i:03d}",
            source_inquiry_id="i",
            created_at=_NOW,
            updated_at=_NOW,
            cancelled_at=_NOW,
        )
        for i in range(60)
    ]
    detail = views.inquiry_detail(_inquiry(), many_orders)
    assert len(detail["orders"]) == views.DETAIL_ORDERS_CAP
    assert detail["orders_truncated"] is True
    assert detail["orders_total_count"] == 60
    assert detail["linked_order_id"] is None  # all cancelled → no active link

    versions = [
        OrderVersion(
            order_version_id=f"v-{i:03d}",
            order_id=fresh.order_id,
            version_number=i + 1,
            created_at=_NOW,
            event_date=date(2026, 10, 1),
            time_window_text="t",
            location_text="l",
            guest_count_estimate=None,
            planning_mode=PLANNING_MODES[0],
        )
        for i in range(views.DETAIL_VERSIONS_CAP + 10)
    ]
    from catering_system.domain.ready_to_send import ReadyToSendEvaluation

    order_detail = views.order_detail(
        fresh,
        versions,
        ReadyToSendEvaluation(order_id=fresh.order_id, ready=False, reasons=()),
    )
    assert len(order_detail["versions"]) == views.DETAIL_VERSIONS_CAP
    assert order_detail["versions_truncated"] is True
    assert order_detail["versions_total_count"] == views.DETAIL_VERSIONS_CAP + 10


def test_search_semantics_match_the_panel() -> None:
    inquiry = _inquiry()
    assert views.inquiry_matches(inquiry, "hamburg")  # location
    assert views.inquiry_matches(inquiry, "2026-10-01")  # event date
    assert views.inquiry_matches(inquiry, inquiry.inquiry_id[:8].lower())  # id
    assert views.inquiry_matches(inquiry, inquiry.crm_stage[:4].lower())  # stage
    assert views.inquiry_matches(inquiry, "manual")  # source
    assert not views.inquiry_matches(inquiry, "mittags")  # time window is NOT searched
    order = Order(
        order_id="ORDER-abc",
        source_inquiry_id="INQ-xyz",
        created_at=_NOW,
        updated_at=_NOW,
    )
    assert views.order_matches(order, "order-abc")
    assert views.order_matches(order, "inq-xyz")
    assert not views.order_matches(order, "hamburg")

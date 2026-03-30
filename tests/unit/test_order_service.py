"""Unit tests — Slice B1/B2 Order, OrderVersion, conversion, version history."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.repositories.in_memory_order_repository import InMemoryOrderRepository
from catering_system.services.order_service import OrderService


def _module_source_lower(module: object) -> str:
    return Path(module.__file__).read_text(encoding="utf-8").lower()


def _sample_inquiry() -> Inquiry:
    now = datetime.now(timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
    )


def test_convert_inquiry_to_order_creates_order_and_initial_version() -> None:
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    inquiry = _sample_inquiry()
    order, ver = svc.convert_inquiry_to_order(inquiry)
    assert order.source_inquiry_id == inquiry.inquiry_id
    assert ver.order_id == order.order_id
    assert ver.version_number == 1
    assert ver.event_date == inquiry.event_date
    assert ver.time_window_text == inquiry.time_window_text
    assert ver.location_text == inquiry.location_text
    assert ver.guest_count_estimate == inquiry.guest_count_estimate
    assert ver.planning_mode == inquiry.planning_mode
    loaded = repo.get_order(order.order_id)
    assert loaded is not None
    assert loaded.order_id == order.order_id
    stored = repo.get_order_version(ver.order_version_id)
    assert stored is not None
    assert stored.version_number == 1


def test_create_relevant_order_change_version_second_preserves_first() -> None:
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = svc.convert_inquiry_to_order(_sample_inquiry())
    v2 = svc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 11, 2),
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[1],
    )
    assert v2.version_number == 2
    assert v2.order_id == order.order_id
    hist = repo.list_order_versions(order.order_id)
    assert len(hist) == 2
    assert hist[0].order_version_id == v1.order_version_id
    assert hist[0].version_number == 1
    assert hist[1].order_version_id == v2.order_version_id
    assert hist[1].time_window_text == "abends"
    reloaded = repo.get_order_version(v1.order_version_id)
    assert reloaded is not None
    assert reloaded.event_date == v1.event_date
    updated_order = repo.get_order(order.order_id)
    assert updated_order is not None
    assert updated_order.updated_at >= order.updated_at


def test_order_domain_has_no_kitchen_or_release_surface() -> None:
    """B1/B2 gate: no print / READY_TO_SEND / operational-switch fields on Order types."""
    import catering_system.domain.order as order_mod

    lowered = _module_source_lower(order_mod)
    assert "ready_to_send" not in lowered
    assert "kitchen" not in lowered
    assert "wochen" not in lowered
    assert "kiosk" not in lowered
    assert "effective" not in lowered


def test_order_service_has_no_kitchen_or_release_surface() -> None:
    import catering_system.services.order_service as os_mod

    lowered = _module_source_lower(os_mod)
    assert "ready_to_send" not in lowered
    assert "kitchen" not in lowered
    assert "print" not in lowered

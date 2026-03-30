"""Unit tests — Slice B1/B2/B3/B5/B6 Order, OrderVersion, conversion, history, candidate reads."""

from __future__ import annotations

import sys
from dataclasses import fields, replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.in_memory_order_repository import InMemoryOrderRepository
from catering_system.services.order_service import OrderService

_B3_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "is_active",
        "is_effective",
        "active_version_id",
        "effective_version_id",
        "selected_version_id",
        "release_ready",
        "ready_to_send",
    }
)


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


def test_convert_inquiry_to_order_blocked_when_verification_required_not_verified() -> None:
    svc = OrderService(InMemoryOrderRepository())
    for status in ("pending", "failed", "blocked"):
        inquiry = replace(
            _sample_inquiry(),
            call_verification_required=True,
            call_verification_status=status,  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="inquiry_to_order conversion blocked"):
            svc.convert_inquiry_to_order(inquiry)


def test_convert_inquiry_to_order_blocked_when_required_but_not_verified_status() -> None:
    """required=True with not_required status is inconsistent — still blocked (not verified)."""
    svc = OrderService(InMemoryOrderRepository())
    inquiry = replace(
        _sample_inquiry(),
        call_verification_required=True,
        call_verification_status="not_required",
    )
    with pytest.raises(ValueError, match="inquiry_to_order conversion blocked"):
        svc.convert_inquiry_to_order(inquiry)


def test_convert_inquiry_to_order_allowed_when_verification_required_and_verified() -> None:
    svc = OrderService(InMemoryOrderRepository())
    inquiry = replace(
        _sample_inquiry(),
        call_verification_required=True,
        call_verification_status="verified",
    )
    order, ver = svc.convert_inquiry_to_order(inquiry)
    assert order.source_inquiry_id == inquiry.inquiry_id
    assert ver.version_number == 1


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


def test_list_order_versions_and_get_latest_match_history_not_activation() -> None:
    """Full history via service; latest is max(version_number); history not collapsed to one active row."""
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = svc.convert_inquiry_to_order(_sample_inquiry())
    v2 = svc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 12, 3),
        time_window_text="spät",
        location_text="München",
        guest_count_estimate=50,
        planning_mode=PLANNING_MODES[0],
    )
    from_repo = repo.list_order_versions(order.order_id)
    full = svc.list_order_versions(order.order_id)
    assert full == from_repo
    assert len(full) == 2
    assert full[0].version_number == 1
    assert full[1].version_number == 2
    nums = [v.version_number for v in full]
    assert nums == sorted(nums)
    latest = svc.get_latest_order_version(order.order_id)
    assert latest is not None
    assert latest.order_version_id == v2.order_version_id
    assert latest.version_number == max(nums)
    assert latest.version_number == max(v1.version_number, v2.version_number)


def test_get_latest_order_version_returns_none_when_no_versions() -> None:
    """Explicit None when no versions; no synthetic active/effective version."""
    svc = OrderService(InMemoryOrderRepository())
    missing_id = "00000000-0000-0000-0000-000000000000"
    assert svc.get_latest_order_version(missing_id) is None
    assert svc.list_order_versions(missing_id) == []


def test_set_and_get_candidate_order_version_office_side_only() -> None:
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = svc.convert_inquiry_to_order(_sample_inquiry())
    assert repo.get_order(order.order_id) is not None
    assert repo.get_order(order.order_id).candidate_order_version_id is None
    assert svc.get_candidate_order_version(order.order_id) is None
    updated = svc.set_candidate_order_version(order.order_id, v1.order_version_id)
    assert updated.candidate_order_version_id == v1.order_version_id
    cand = svc.get_candidate_order_version(order.order_id)
    assert cand is not None
    assert cand.order_version_id == v1.order_version_id


def test_changing_candidate_preserves_full_version_history() -> None:
    svc = OrderService(InMemoryOrderRepository())
    order, v1 = svc.convert_inquiry_to_order(_sample_inquiry())
    v2 = svc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 11, 2),
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[1],
    )
    svc.set_candidate_order_version(order.order_id, v1.order_version_id)
    svc.set_candidate_order_version(order.order_id, v2.order_version_id)
    hist = svc.list_order_versions(order.order_id)
    assert len(hist) == 2
    assert {hist[0].order_version_id, hist[1].order_version_id} == {
        v1.order_version_id,
        v2.order_version_id,
    }
    assert svc.get_candidate_order_version(order.order_id).order_version_id == v2.order_version_id


def test_candidate_can_differ_from_latest_historical_version() -> None:
    """B6: candidate is not latest-in-history; not effective operational selection."""
    svc = OrderService(InMemoryOrderRepository())
    order, v1 = svc.convert_inquiry_to_order(_sample_inquiry())
    v2 = svc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 11, 2),
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[1],
    )
    svc.set_candidate_order_version(order.order_id, v1.order_version_id)
    latest = svc.get_latest_order_version(order.order_id)
    cand = svc.get_candidate_order_version(order.order_id)
    assert latest is not None and cand is not None
    assert latest.order_version_id == v2.order_version_id
    assert cand.order_version_id == v1.order_version_id
    assert latest.version_number > cand.version_number


def test_set_candidate_rejects_foreign_version_id() -> None:
    svc = OrderService(InMemoryOrderRepository())
    order, _ = svc.convert_inquiry_to_order(_sample_inquiry())
    with pytest.raises(ValueError, match="not a version of order"):
        svc.set_candidate_order_version(order.order_id, "00000000-0000-0000-0000-000000000001")


def _assert_dataclasses_have_no_b3_forbidden_fields() -> None:
    for cls in (Order, OrderVersion):
        names = {f.name for f in fields(cls)}
        assert names.isdisjoint(_B3_FORBIDDEN_FIELD_NAMES)


def test_order_domain_has_no_kitchen_or_release_surface() -> None:
    """B1/B2/B3/B6: no print / release-kitchen surface / forbidden activation fields on Order types."""
    import catering_system.domain.order as order_mod

    lowered = _module_source_lower(order_mod)
    assert "ready_to_send" not in lowered
    assert "kitchen" not in lowered
    assert "wochen" not in lowered
    assert "kiosk" not in lowered
    _assert_dataclasses_have_no_b3_forbidden_fields()


def test_order_service_has_no_kitchen_or_release_surface() -> None:
    import catering_system.services.order_service as os_mod

    lowered = _module_source_lower(os_mod)
    assert "ready_to_send" not in lowered
    assert "kitchen" not in lowered
    assert "print" not in lowered
    for name in _B3_FORBIDDEN_FIELD_NAMES:
        assert not hasattr(OrderService, name)
    _assert_dataclasses_have_no_b3_forbidden_fields()

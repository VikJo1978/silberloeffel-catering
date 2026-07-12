"""Unit tests — Wochenübersicht derived weekly overview (WOCHENUEBERSICHT_EXECUTION_PACK_V1 §4)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.wochenuebersicht_service import WochenuebersichtService

# date(2026, 10, 1) is Thursday of ISO week 2026-W40
_WEEK_YEAR = 2026
_WEEK = 40


def _inquiry(event_date: date) -> Inquiry:
    now = datetime.now(timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=event_date,
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


def _setup() -> tuple[
    InMemoryOrderRepository,
    OrderService,
    OperationalCoreService,
    WochenuebersichtService,
]:
    repo = InMemoryOrderRepository()
    return (
        repo,
        OrderService(repo),
        OperationalCoreService(repo),
        WochenuebersichtService(repo),
    )


def _make_effective_order(
    osvc: OrderService, core: OperationalCoreService, event_date: date
) -> str:
    order, v1 = osvc.convert_inquiry_to_order(_inquiry(event_date))
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    return order.order_id


def test_empty_week_returns_empty_overview() -> None:
    _repo, _osvc, _core, week = _setup()
    view = week.get_week_overview(_WEEK_YEAR, _WEEK)
    assert view.iso_year == _WEEK_YEAR and view.iso_week == _WEEK
    assert view.entries == ()


def test_order_without_effective_version_never_appears() -> None:
    _repo, osvc, _core, week = _setup()
    osvc.convert_inquiry_to_order(_inquiry(date(2026, 10, 1)))  # no confirm, no switch
    assert week.get_week_overview(_WEEK_YEAR, _WEEK).entries == ()


def test_effective_order_in_week_appears_with_effective_data() -> None:
    _repo, osvc, core, week = _setup()
    oid = _make_effective_order(osvc, core, date(2026, 10, 1))
    view = week.get_week_overview(_WEEK_YEAR, _WEEK)
    assert len(view.entries) == 1
    e = view.entries[0]
    assert e.order_id == oid
    assert e.event_date == date(2026, 10, 1)
    assert e.version_number == 1
    assert e.time_window_text == "mittags"


def test_effective_order_outside_week_excluded() -> None:
    _repo, osvc, core, week = _setup()
    _make_effective_order(osvc, core, date(2026, 10, 12))  # W42
    assert week.get_week_overview(_WEEK_YEAR, _WEEK).entries == ()
    assert len(week.get_week_overview(_WEEK_YEAR, 42).entries) == 1


def test_overview_shows_effective_not_latest_version() -> None:
    """A newer historical version must not leak in — effective is the only kitchen truth."""
    repo, osvc, core, week = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_inquiry(date(2026, 10, 1)))
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    osvc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Kiel",
        guest_count_estimate=99,
        planning_mode=PLANNING_MODES[0],
    )  # v2 exists in history but is not effective
    view = week.get_week_overview(_WEEK_YEAR, _WEEK)
    assert len(view.entries) == 1
    e = view.entries[0]
    assert e.effective_order_version_id == v1.order_version_id
    assert e.event_date == date(2026, 10, 1)
    assert e.location_text == "Hamburg"


def test_ordering_is_deterministic_by_date_window_then_id() -> None:
    _repo, osvc, core, week = _setup()
    _make_effective_order(osvc, core, date(2026, 10, 2))
    _make_effective_order(osvc, core, date(2026, 10, 1))
    _make_effective_order(osvc, core, date(2026, 10, 1))
    view = week.get_week_overview(_WEEK_YEAR, _WEEK)
    dates = [e.event_date for e in view.entries]
    assert dates == sorted(dates)
    same_day = [e for e in view.entries if e.event_date == date(2026, 10, 1)]
    assert [e.order_id for e in same_day] == sorted(e.order_id for e in same_day)


def test_overview_read_is_pure() -> None:
    repo, osvc, core, week = _setup()
    oid = _make_effective_order(osvc, core, date(2026, 10, 1))
    before = repo.get_order(oid)
    week.get_week_overview(_WEEK_YEAR, _WEEK)
    assert repo.get_order(oid) == before


# --- get_day_overview (KIOSK_ORDER_FEED_PACK_V1 §4) ---


def test_day_overview_includes_only_the_requested_date() -> None:
    _repo, osvc, core, week = _setup()
    match = _make_effective_order(osvc, core, date(2026, 10, 1))
    _make_effective_order(osvc, core, date(2026, 10, 2))  # same ISO week
    entries = week.get_day_overview(date(2026, 10, 1))
    assert [e.order_id for e in entries] == [match]


def test_day_overview_excludes_cancelled_and_unreleased_orders() -> None:
    _repo, osvc, core, week = _setup()
    cancelled = _make_effective_order(osvc, core, date(2026, 10, 1))
    core.cancel_order(cancelled)
    osvc.convert_inquiry_to_order(_inquiry(date(2026, 10, 1)))  # no effective version
    assert week.get_day_overview(date(2026, 10, 1)) == ()


def test_day_overview_is_the_date_filtered_subset_of_the_week() -> None:
    _repo, osvc, core, week = _setup()
    for day in (1, 1, 2):
        _make_effective_order(osvc, core, date(2026, 10, day))
    whole_week = week.get_week_overview(_WEEK_YEAR, _WEEK).entries
    for day in (date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)):
        expected = tuple(e for e in whole_week if e.event_date == day)
        assert week.get_day_overview(day) == expected


def test_day_overview_ordering_is_deterministic() -> None:
    _repo, osvc, core, week = _setup()
    _make_effective_order(osvc, core, date(2026, 10, 1))
    _make_effective_order(osvc, core, date(2026, 10, 1))
    entries = week.get_day_overview(date(2026, 10, 1))
    keys = [(e.time_window_text, e.order_id) for e in entries]
    assert keys == sorted(keys)


def test_day_overview_read_is_pure() -> None:
    repo, osvc, core, week = _setup()
    oid = _make_effective_order(osvc, core, date(2026, 10, 1))
    before = repo.get_order(oid)
    week.get_day_overview(date(2026, 10, 1))
    assert repo.get_order(oid) == before

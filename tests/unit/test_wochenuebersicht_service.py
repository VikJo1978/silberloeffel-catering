"""Unit tests — Wochenübersicht derived weekly overview (WOCHENUEBERSICHT_EXECUTION_PACK_V1 §4)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.in_memory_order_operational_pause_repository import (
    InMemoryOrderOperationalPauseRepository,
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
    pauses = InMemoryOrderOperationalPauseRepository()
    return (
        repo,
        OrderService(repo),
        OperationalCoreService(repo, pause_repository=pauses),
        WochenuebersichtService(repo, pause_repository=pauses),
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


def test_candidate_change_reaches_week_and_day_only_after_effective_switch() -> None:
    _repo, osvc, core, week = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_inquiry(date(2026, 10, 1)))
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    v2 = osvc.propose_order_version_change(
        order.order_id,
        event_date=date(2026, 10, 8),  # W41
        time_window_text="abends",
        location_text="Kiel",
        guest_count_estimate=40,
        planning_mode=PLANNING_MODES[0],
        actor_reference="office-panel",
        change_reason="Termin verschoben",
    )

    assert [
        entry.effective_order_version_id
        for entry in week.get_day_overview(v1.event_date)
    ] == [v1.order_version_id]
    assert week.get_day_overview(v2.event_date) == ()
    assert len(week.get_week_overview(2026, 40).entries) == 1
    assert week.get_week_overview(2026, 41).entries == ()

    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)
    assert week.get_day_overview(v1.event_date) == ()
    assert [
        entry.effective_order_version_id
        for entry in week.get_day_overview(v2.event_date)
    ] == [v2.order_version_id]


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


def test_pause_projection_follows_effective_v2_and_disappears_after_resume() -> None:
    _repo, osvc, core, week = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_inquiry(date(2026, 10, 1)))
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    v2 = osvc.propose_order_version_change(
        order.order_id,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Kiel",
        guest_count_estimate=40,
        planning_mode=PLANNING_MODES[0],
        actor_reference="office-panel",
        change_reason="Termin verschoben",
    )
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)
    pause = core.pause_order(
        order.order_id,
        reason_code="customer_request",
        note="Gästezahl noch offen",
        actor_reference="office-panel",
        command_id=str(uuid4()),
        expected_latest_pause_event_id=None,
    )

    weekly = week.get_week_overview(_WEEK_YEAR, _WEEK)
    daily = week.get_day_overview(v2.event_date)
    assert len(weekly.entries) == 1
    entry = weekly.entries[0]
    assert daily == (entry,)
    assert entry.effective_order_version_id == v2.order_version_id
    assert entry.event_date == date(2026, 10, 2)
    assert entry.location_text == "Kiel"
    assert entry.operational_pause_active is True
    assert entry.operational_pause_reason_code == "customer_request"
    assert entry.operational_pause_note == "Gästezahl noch offen"

    core.resume_order(
        order.order_id,
        reason_code="operator_cleared",
        note=None,
        actor_reference="office-panel",
        command_id=str(uuid4()),
        expected_current_pause_event_id=pause.pause_event_id,
        expected_latest_pause_event_id=pause.pause_event_id,
    )
    resumed = week.get_week_overview(_WEEK_YEAR, _WEEK)
    assert len(resumed.entries) == 1
    assert resumed.entries[0].effective_order_version_id == v2.order_version_id
    assert resumed.entries[0].operational_pause_active is False
    assert resumed.entries[0].operational_pause_reason_code is None
    assert resumed.entries[0].operational_pause_note is None


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


def test_day_overview_excludes_foreign_effective_version() -> None:
    """Defensive ownership gate: an order whose effective reference names
    another order's version must not appear. The repository rejects such a
    reference through its API, so the corruption is planted directly in the
    store to prove the service-side check stands on its own."""
    from dataclasses import replace

    repo, osvc, core, week = _setup()
    victim = _make_effective_order(osvc, core, date(2026, 10, 1))
    donor = _make_effective_order(osvc, core, date(2026, 10, 1))
    donor_order = repo.get_order(donor)
    assert donor_order is not None and donor_order.effective_order_version_id
    tampered = replace(
        repo.get_order(victim),
        effective_order_version_id=donor_order.effective_order_version_id,
    )
    repo._orders[victim] = tampered  # bypass validation: simulate corrupted store
    entries = week.get_day_overview(date(2026, 10, 1))
    assert [e.order_id for e in entries] == [donor]


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

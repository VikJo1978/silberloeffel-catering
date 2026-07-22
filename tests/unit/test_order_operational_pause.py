"""Slice A1 — order-level operational PAUSE (domain, persistence, read paths)."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

import sqlite3
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.operational_core_events import (
    OrderOperationalPaused,
    OrderOperationalResumed,
)
from catering_system.domain.ready_to_send import (
    READY_REASON_OPERATIONAL_PAUSE,
    READY_REASON_PENDING_ORDER_VERSION_CHANGE,
)
from catering_system.domain.order_operational_pause import (
    OrderOperationalPauseEvent,
    derive_active_pause,
    derive_operational_pause_projection,
    validate_pause_reason_code,
    validate_resume_reason_code,
)
from catering_system.repositories.in_memory_order_operational_pause_repository import (
    InMemoryOrderOperationalPauseRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_order_operational_pause_repository import (
    SQLiteOrderOperationalPauseRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.wochenuebersicht_service import WochenuebersichtService
from catering_system.ui.kiosk_server import (
    render_order_feed_json,
    render_wochenuebersicht_html,
)

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    email="kunde@example.com", phone="+49301234567"
)


_WEEK_YEAR = 2026
_WEEK = 40


def _utc_now() -> datetime:
    return datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)


def _sample_inquiry() -> Inquiry:
    now = _utc_now()
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
        customer_snapshot=_CONTACT_COMPLETE_SNAPSHOT,
    )


def _paused_event(
    *,
    order_id: str = "22222222-2222-4222-8222-222222222222",
    pause_event_id: str | None = None,
    command_id: str | None = None,
    occurred_at: datetime | None = None,
) -> OrderOperationalPauseEvent:
    return OrderOperationalPauseEvent(
        pause_event_id=pause_event_id or str(uuid4()),
        order_id=order_id,
        action="paused",
        reason_code="manual_hold",
        note="hold",
        actor_reference="office-panel",
        occurred_at=occurred_at or _utc_now(),
        command_id=command_id or str(uuid4()),
    )


def _resumed_event(
    active: OrderOperationalPauseEvent,
    *,
    command_id: str | None = None,
    occurred_at: datetime | None = None,
) -> OrderOperationalPauseEvent:
    return OrderOperationalPauseEvent(
        pause_event_id=str(uuid4()),
        order_id=active.order_id,
        action="resumed",
        reason_code="operator_cleared",
        note=None,
        actor_reference="office-panel",
        occurred_at=occurred_at or active.occurred_at,
        command_id=command_id or str(uuid4()),
        resumes_pause_event_id=active.pause_event_id,
    )


def _setup() -> tuple[
    InMemoryOrderRepository,
    InMemoryOrderOperationalPauseRepository,
    OrderService,
    OperationalCoreService,
    list[object],
]:
    orders = InMemoryOrderRepository()
    pauses = InMemoryOrderOperationalPauseRepository()
    events: list[object] = []
    return (
        orders,
        pauses,
        OrderService(orders),
        OperationalCoreService(
            orders, pause_repository=pauses, event_sink=events.append
        ),
        events,
    )


def _pause(core: OperationalCoreService, order_id: str, **kwargs: object):
    projection = core.get_operational_pause_projection(order_id)
    return core.pause_order(
        order_id,
        expected_latest_pause_event_id=projection.get("latest_pause_event_id"),
        **kwargs,
    )


def _resume(core: OperationalCoreService, order_id: str, **kwargs: object):
    projection = core.get_operational_pause_projection(order_id)
    return core.resume_order(
        order_id,
        expected_current_pause_event_id=str(projection["current_pause_event_id"]),
        expected_latest_pause_event_id=str(projection["latest_pause_event_id"]),
        **kwargs,
    )


def test_derive_active_pause_from_history() -> None:
    first = _paused_event(
        pause_event_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        occurred_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
    )
    second = _paused_event(
        pause_event_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        occurred_at=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
    )
    resume_first = _resumed_event(
        first,
        occurred_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    )
    assert derive_active_pause((first, resume_first, second)) == second
    assert derive_active_pause((first, resume_first)) is None


def test_reason_code_validation() -> None:
    assert validate_pause_reason_code("manual_hold") == "manual_hold"
    assert validate_resume_reason_code("operator_cleared") == "operator_cleared"
    with pytest.raises(ValueError, match="invalid pause reason_code"):
        validate_pause_reason_code("unknown")
    with pytest.raises(ValueError, match="invalid resume reason_code"):
        validate_resume_reason_code("unknown")


def test_pause_active_order_success() -> None:
    repo, _pauses, osvc, core, events = _setup()
    order, _v1 = seed_order(repo, _sample_inquiry())
    event = _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note="review",
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    assert event.action == "paused"
    assert core.get_active_operational_pause(order.order_id) == event
    assert events == [
        OrderOperationalPaused(
            order_id=order.order_id, pause_event_id=event.pause_event_id
        )
    ]


def test_pause_without_effective_version_succeeds() -> None:
    _repo, _pauses, osvc, core, _events = _setup()
    order, _v1 = seed_order(_repo, _sample_inquiry())
    assert core.get_active_operational_pause(order.order_id) is None
    _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    assert core.get_active_operational_pause(order.order_id) is not None


def test_repeat_pause_with_new_command_rejected() -> None:
    _repo, _pauses, osvc, core, events = _setup()
    order, _v1 = seed_order(_repo, _sample_inquiry())
    _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    with pytest.raises(ValueError, match="already paused"):
        _pause(
            core,
            order.order_id,
            reason_code="manual_hold",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
        )
    assert len(events) == 1


def test_resume_active_pause_and_history_preserved() -> None:
    repo, pauses, osvc, core, events = _setup()
    order, _v1 = seed_order(repo, _sample_inquiry())
    paused = _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note="hold",
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    resumed = _resume(
        core,
        order.order_id,
        reason_code="operator_cleared",
        note="cleared",
        actor_reference="operator-2",
        command_id=str(uuid4()),
    )
    assert core.get_active_operational_pause(order.order_id) is None
    history = pauses.list_events(order.order_id)
    assert history == (paused, resumed)
    assert events[-1] == OrderOperationalResumed(
        order_id=order.order_id,
        pause_event_id=resumed.pause_event_id,
        resumed_pause_event_id=paused.pause_event_id,
    )


def test_resume_not_paused_order_rejected() -> None:
    _repo, _pauses, osvc, core, _events = _setup()
    order, _v1 = seed_order(_repo, _sample_inquiry())
    with pytest.raises(ValueError, match="not paused"):
        core.resume_order(
            order.order_id,
            reason_code="operator_cleared",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
            expected_current_pause_event_id=str(uuid4()),
            expected_latest_pause_event_id=str(uuid4()),
        )


def test_pause_resume_do_not_change_order_version_or_effective() -> None:
    repo, _pauses, osvc, core, _events = _setup()
    order, v1 = seed_order(repo, _sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    before = repo.get_order(order.order_id)
    assert before is not None
    before_version = repo.get_order_version(v1.order_version_id)
    assert before_version is not None
    _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    _resume(
        core,
        order.order_id,
        reason_code="operator_cleared",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    after = repo.get_order(order.order_id)
    assert after == before
    after_version = repo.get_order_version(v1.order_version_id)
    assert after_version == before_version


def test_pause_unknown_order_not_found() -> None:
    _repo, _pauses, _osvc, core, _events = _setup()
    with pytest.raises(ValueError, match="no order with id"):
        core.pause_order(
            str(uuid4()),
            reason_code="manual_hold",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
            expected_latest_pause_event_id=None,
        )


def test_pause_missing_reason_or_actor_validation() -> None:
    _repo, _pauses, osvc, core, _events = _setup()
    order, _v1 = seed_order(_repo, _sample_inquiry())
    with pytest.raises(ValueError, match="invalid pause reason_code"):
        _pause(
            core,
            order.order_id,
            reason_code="bad",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
        )
    with pytest.raises(ValueError, match="actor_reference is required"):
        OrderOperationalPauseEvent(
            pause_event_id=str(uuid4()),
            order_id=order.order_id,
            action="paused",
            reason_code="manual_hold",
            note=None,
            actor_reference="",
            occurred_at=_utc_now(),
            command_id=str(uuid4()),
        )


def test_in_memory_pause_events_round_trip_and_ordering() -> None:
    repo = InMemoryOrderOperationalPauseRepository()
    first = _paused_event(
        pause_event_id="11111111-1111-4111-8111-111111111111",
        occurred_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
    )
    second = _paused_event(
        pause_event_id="22222222-2222-4222-8222-222222222222",
        occurred_at=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
    )
    repo.append_event(second)
    repo.append_event(first)
    assert repo.list_events(first.order_id) == (first, second)
    assert repo.get_active_pause(first.order_id) == second


def test_in_memory_duplicate_event_or_command_id_rejected() -> None:
    repo = InMemoryOrderOperationalPauseRepository()
    event = _paused_event(command_id="33333333-3333-4333-8333-333333333333")
    repo.append_event(event)
    with pytest.raises(KeyError):
        repo.append_event(
            OrderOperationalPauseEvent(
                pause_event_id=event.pause_event_id,
                order_id=event.order_id,
                action="paused",
                reason_code="manual_hold",
                note=None,
                actor_reference="office-panel",
                occurred_at=_utc_now(),
                command_id=str(uuid4()),
            )
        )
    with pytest.raises(ValueError, match="command_id"):
        repo.append_event(
            OrderOperationalPauseEvent(
                pause_event_id=str(uuid4()),
                order_id=event.order_id,
                action="paused",
                reason_code="manual_hold",
                note=None,
                actor_reference="office-panel",
                occurred_at=_utc_now(),
                command_id=event.command_id,
            )
        )


def test_sqlite_pause_events_round_trip_and_migration(tmp_path) -> None:
    db = tmp_path / "core.db"
    orders = SQLiteOrderRepository(db)
    order, _v1 = seed_order(orders, _sample_inquiry())
    orders.close()
    pauses = SQLiteOrderOperationalPauseRepository(db)
    event = _paused_event(order_id=order.order_id)
    pauses.append_event(event)
    loaded = pauses.list_events(order.order_id)
    assert loaded == (event,)
    assert pauses.get_active_pause(order.order_id) == event
    pauses.close()


def test_sqlite_pause_migration_on_existing_database(tmp_path) -> None:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            source_inquiry_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            candidate_order_version_id TEXT,
            effective_order_version_id TEXT,
            cancelled_at TEXT
        );
        """
    )
    conn.close()
    pauses = SQLiteOrderOperationalPauseRepository(db)
    row = pauses._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='order_operational_pause_events'"
    ).fetchone()
    assert row is not None
    pauses.close()


def test_paused_effective_order_still_in_wochenuebersicht_and_kiosk_feed() -> None:
    orders = InMemoryOrderRepository()
    pauses = InMemoryOrderOperationalPauseRepository()
    core = OperationalCoreService(orders, pause_repository=pauses)
    week = WochenuebersichtService(orders, pause_repository=pauses)
    order, v1 = seed_order(orders, _sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    view = week.get_week_overview(_WEEK_YEAR, _WEEK)
    entry = next(e for e in view.entries if e.order_id == order.order_id)
    assert entry.operational_pause_active is True
    assert any(entry.order_id == order.order_id for entry in view.entries)
    html = render_wochenuebersicht_html(view)
    assert "PAUSIERT" in html
    feed = render_order_feed_json(
        date(2026, 10, 1),
        tuple(e for e in view.entries if e.event_date == date(2026, 10, 1)),
    )
    payload = feed.decode()
    assert order.order_id in payload


def test_pause_blocks_ready_to_send_and_resume_clears_only_pause_blocker() -> None:
    _repo, _pauses, osvc, core, _events = _setup()
    order, v1 = seed_order(_repo, _sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    assert core.evaluate_ready_to_send(order.order_id).ready is True
    _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    blocked = core.evaluate_ready_to_send(order.order_id)
    assert blocked.ready is False
    assert blocked.reasons == (READY_REASON_OPERATIONAL_PAUSE,)
    _resume(
        core,
        order.order_id,
        reason_code="operator_cleared",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    assert core.evaluate_ready_to_send(order.order_id).ready is True


def test_pause_with_pending_candidate_reports_both_blockers() -> None:
    repo, _pauses, osvc, core, _events = _setup()
    order, v1 = seed_order(repo, _sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    osvc.propose_order_version_change(
        order.order_id,
        event_date=date(2026, 10, 2),
        time_window_text=v1.time_window_text,
        location_text=v1.location_text,
        guest_count_estimate=v1.guest_count_estimate,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Termin verschoben",
    )
    reasons = core.evaluate_ready_to_send(order.order_id).reasons
    assert reasons == (
        READY_REASON_OPERATIONAL_PAUSE,
        READY_REASON_PENDING_ORDER_VERSION_CHANGE,
    )


def test_storniert_order_cannot_be_paused_or_resumed() -> None:
    _repo, _pauses, osvc, core, _events = _setup()
    order, _v1 = seed_order(_repo, _sample_inquiry())
    core.cancel_order(order.order_id)
    with pytest.raises(ValueError, match="cancelled"):
        _pause(
            core,
            order.order_id,
            reason_code="manual_hold",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
        )
    with pytest.raises(ValueError, match="cancelled"):
        core.resume_order(
            order.order_id,
            reason_code="operator_cleared",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
            expected_current_pause_event_id=str(uuid4()),
            expected_latest_pause_event_id=str(uuid4()),
        )


def test_derive_operational_pause_projection_inactive_and_active() -> None:
    assert derive_operational_pause_projection(()) == {
        "active": False,
        "latest_pause_event_id": None,
    }
    paused = _paused_event(
        pause_event_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    projection = derive_operational_pause_projection((paused,))
    assert projection["active"] is True
    assert projection["current_pause_event_id"] == paused.pause_event_id
    assert projection["latest_pause_event_id"] == paused.pause_event_id


def test_stale_pause_after_resume_cycle_rejected() -> None:
    _repo, _pauses, osvc, core, _events = _setup()
    order, _v1 = seed_order(_repo, _sample_inquiry())
    _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    _resume(
        core,
        order.order_id,
        reason_code="operator_cleared",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    with pytest.raises(ValueError, match="stale operational pause state"):
        core.pause_order(
            order.order_id,
            reason_code="manual_hold",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
            expected_latest_pause_event_id=None,
        )


def test_stale_resume_for_previous_pause_event_rejected() -> None:
    _repo, _pauses, osvc, core, _events = _setup()
    order, _v1 = seed_order(_repo, _sample_inquiry())
    pause_a = _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    _resume(
        core,
        order.order_id,
        reason_code="operator_cleared",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    pause_b = _pause(
        core,
        order.order_id,
        reason_code="customer_request",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    projection = core.get_operational_pause_projection(order.order_id)
    with pytest.raises(ValueError, match="stale operational pause state"):
        core.resume_order(
            order.order_id,
            reason_code="operator_cleared",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
            expected_current_pause_event_id=pause_a.pause_event_id,
            expected_latest_pause_event_id=projection["latest_pause_event_id"],
        )
    assert core.get_active_operational_pause(order.order_id) == pause_b


def test_sqlite_pause_update_and_delete_triggers_reject(tmp_path) -> None:
    from catering_system.repositories.core_transaction import open_core_connection

    db = tmp_path / "pause-triggers.db"
    conn = open_core_connection(db)
    orders = SQLiteOrderRepository.from_connection(conn)
    pauses = SQLiteOrderOperationalPauseRepository.from_connection(conn)
    order, _v1 = seed_order(orders, _sample_inquiry())
    event = _paused_event(order_id=order.order_id)
    pauses.append_event(event)
    with pytest.raises(sqlite3.IntegrityError):
        pauses._conn.execute(
            "UPDATE order_operational_pause_events SET note='changed' "
            "WHERE pause_event_id=?",
            (event.pause_event_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        pauses._conn.execute(
            "DELETE FROM order_operational_pause_events WHERE pause_event_id=?",
            (event.pause_event_id,),
        )
    pauses.close()
    orders.close()


def test_resume_on_other_order_with_foreign_pause_id_rejected() -> None:
    _repo, _pauses, osvc, core, _events = _setup()
    order_a, _v1 = seed_order(_repo, _sample_inquiry())
    inquiry_b = Inquiry(
        inquiry_id="33333333-3333-4333-8333-333333333333",
        event_date=date(2026, 10, 2),
        created_at=_utc_now(),
        updated_at=_utc_now(),
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=10,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
        customer_snapshot=_CONTACT_COMPLETE_SNAPSHOT,
    )
    order_b, _v2 = seed_order(_repo, inquiry_b)
    paused = _pause(
        core,
        order_a.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    with pytest.raises(ValueError, match="not paused"):
        core.resume_order(
            order_b.order_id,
            reason_code="operator_cleared",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
            expected_current_pause_event_id=paused.pause_event_id,
            expected_latest_pause_event_id=paused.pause_event_id,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("action", "broken", "invalid pause action"),
        ("pause_event_id", "", "pause_event_id is required"),
        ("order_id", "", "order_id is required"),
        ("reason_code", "", "reason_code is required"),
        ("reason_code", "r" * 101, "reason_code exceeds length limit"),
        ("actor_reference", "", "actor_reference is required"),
        ("actor_reference", "a" * 201, "actor_reference exceeds length limit"),
        ("note", "n" * 2001, "note exceeds length limit"),
        ("command_id", "", "command_id is required"),
        (
            "resumes_pause_event_id",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "paused event must not resume another pause",
        ),
    ],
)
def test_pause_event_rejects_invalid_domain_facts(
    field: str, value: object, message: str
) -> None:
    values: dict[str, object] = {
        "pause_event_id": str(uuid4()),
        "order_id": "22222222-2222-4222-8222-222222222222",
        "action": "paused",
        "reason_code": "manual_hold",
        "note": None,
        "actor_reference": "office-panel",
        "occurred_at": _utc_now(),
        "command_id": str(uuid4()),
        "resumes_pause_event_id": None,
    }
    values[field] = value
    with pytest.raises(ValueError, match=message):
        OrderOperationalPauseEvent(**values)


def test_resume_event_requires_pause_linkage() -> None:
    with pytest.raises(ValueError, match="resumed event must reference"):
        OrderOperationalPauseEvent(
            pause_event_id=str(uuid4()),
            order_id="22222222-2222-4222-8222-222222222222",
            action="resumed",
            reason_code="operator_cleared",
            note=None,
            actor_reference="office-panel",
            occurred_at=_utc_now(),
            command_id=str(uuid4()),
        )


def test_projection_tolerates_duplicate_resume_fact_and_keeps_latest_id() -> None:
    paused = _paused_event(
        pause_event_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        occurred_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
    )
    first_resume = _resumed_event(
        paused,
        occurred_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    )
    duplicate_resume = _resumed_event(
        paused,
        occurred_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
    )
    projection = derive_operational_pause_projection(
        (duplicate_resume, paused, first_resume)
    )
    assert projection == {
        "active": False,
        "latest_pause_event_id": duplicate_resume.pause_event_id,
    }


def test_pause_history_and_remaining_stale_service_branches() -> None:
    _repo, pauses, osvc, core, _events = _setup()
    order, _version = seed_order(_repo, _sample_inquiry())
    paused = _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="operator-1",
        command_id=str(uuid4()),
    )
    assert core.list_operational_pause_history(order.order_id) == (paused,)
    with pytest.raises(ValueError, match="stale operational pause state"):
        core.resume_order(
            order.order_id,
            reason_code="operator_cleared",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
            expected_current_pause_event_id=paused.pause_event_id,
            expected_latest_pause_event_id=str(uuid4()),
        )
    with pytest.raises(ValueError, match="no order with id"):
        core.resume_order(
            str(uuid4()),
            reason_code="operator_cleared",
            note=None,
            actor_reference="operator-1",
            command_id=str(uuid4()),
            expected_current_pause_event_id=str(uuid4()),
            expected_latest_pause_event_id=str(uuid4()),
        )
    assert pauses.list_events(order.order_id) == (paused,)


def test_sqlite_owner_trigger_malformed_row_and_idempotent_migration(tmp_path) -> None:
    db = tmp_path / "pause-integrity.db"
    orders = SQLiteOrderRepository(db)
    order, _version = seed_order(orders, _sample_inquiry())
    orders.close()
    pauses = SQLiteOrderOperationalPauseRepository(db)
    with pytest.raises(sqlite3.IntegrityError, match="owner does not exist"):
        pauses.append_event(_paused_event(order_id=str(uuid4())))
    pauses._conn.execute(
        """
        INSERT INTO order_operational_pause_events (
            pause_event_id, order_id, action, reason_code, note,
            actor_reference, occurred_at, command_id, resumes_pause_event_id
        ) VALUES (?, ?, 'paused', 'manual_hold', NULL, 'office-panel', ?, ?, NULL)
        """,
        (str(uuid4()), order.order_id, "not-a-datetime", str(uuid4())),
    )
    with pytest.raises(ValueError, match="Invalid isoformat"):
        pauses.list_events(order.order_id)
    pauses.close()
    reopened = SQLiteOrderOperationalPauseRepository(db)
    migrations = reopened._conn.execute(
        "SELECT COUNT(*) FROM schema_migrations "
        "WHERE component='order_operational_pause'"
    ).fetchone()[0]
    assert migrations == 1
    reopened.close()


def test_sqlite_pause_append_rolls_back_with_failed_command_bundle(tmp_path) -> None:
    from catering_system.repositories.core_transaction import (
        CoreCommandExecutor,
        open_core_connection,
    )

    connection = open_core_connection(tmp_path / "pause-rollback.db")
    orders = SQLiteOrderRepository.from_connection(connection)
    pauses = SQLiteOrderOperationalPauseRepository.from_connection(connection)
    order, _version = seed_order(orders, _sample_inquiry())
    event = _paused_event(order_id=order.order_id)

    def fail_after_append() -> None:
        pauses.append_event(event)
        raise RuntimeError("second bundle write failed")

    with pytest.raises(RuntimeError, match="second bundle write failed"):
        CoreCommandExecutor(connection).run(fail_after_append)
    assert pauses.list_events(order.order_id) == ()
    connection.close()

"""SQLite migration and atomicity for Phase 3 / Slice 3A print jobs."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.kitchen_print_job import KitchenPrintPolicy
from catering_system.repositories.sqlite_kitchen_print_job_repository import (
    SQLiteKitchenPrintJobRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.kitchen_print_service import KitchenPrintService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    email="kunde@example.com", phone="+49301234567"
)

JOB_1 = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
JOB_2 = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def _inquiry() -> Inquiry:
    now = datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)
    return Inquiry(
        inquiry_id="22222222-2222-4222-8222-222222222222",
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


def _sqlite_world(
    db: Path,
) -> tuple[
    SQLiteOrderRepository,
    SQLiteKitchenPrintJobRepository,
    KitchenPrintService,
    str,
    str,
]:
    orders = SQLiteOrderRepository(db)
    order, version = seed_order(orders, _inquiry())
    jobs = SQLiteKitchenPrintJobRepository(db)
    clock = MutableClock()
    service = KitchenPrintService(
        orders,
        jobs,
        policy=KitchenPrintPolicy(
            acceptance_timeout=timedelta(seconds=20),
            acknowledgment_timeout=timedelta(minutes=3),
        ),
        clock=clock,
    )
    return orders, jobs, service, order.order_id, version.order_version_id


def test_migration_is_additive_and_does_not_backfill_manual_confirmation(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    orders = SQLiteOrderRepository(db)
    order, version = seed_order(orders, _inquiry())
    manually_confirmed = OperationalCoreService(orders).confirm_kitchen_print(
        order.order_id, version.order_version_id
    )
    orders.close()

    jobs = SQLiteKitchenPrintJobRepository(db)
    assert jobs.list_for_version(version.order_version_id) == []
    jobs.close()

    reopened = SQLiteOrderRepository(db)
    assert reopened.get_order_version(version.order_version_id) == manually_confirmed
    reopened.close()
    connection = sqlite3.connect(db)
    assert connection.execute(
        "SELECT version, name FROM schema_migrations WHERE component = 'kitchen_print'"
    ).fetchall() == [(1, "create_kitchen_print_jobs")]
    assert {
        row[1] for row in connection.execute("PRAGMA index_list(kitchen_print_jobs)")
    } >= {
        "uq_kitchen_print_attempt",
        "uq_kitchen_print_live_job",
        "idx_kitchen_print_version_requested",
        "idx_kitchen_print_open_deadlines",
    }
    connection.close()


def test_sqlite_jobs_roundtrip_and_ack_confirmation_survive_reconnect(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    orders, jobs, service, order_id, version_id = _sqlite_world(db)
    first = service.request_print(order_id, version_id, print_job_id=JOB_1)
    service.accept_print_job(JOB_1)
    acknowledged, confirmed = service.acknowledge_print_job(JOB_1)
    reprint = service.reprint(JOB_1, new_print_job_id=JOB_2)
    orders.close()
    jobs.close()

    reopened_jobs = SQLiteKitchenPrintJobRepository(db)
    rows = reopened_jobs.list_for_version(version_id)
    assert rows == [acknowledged, reprint]
    assert rows[0].requested_at == first.requested_at
    reopened_jobs.close()
    reopened_orders = SQLiteOrderRepository(db)
    assert reopened_orders.get_order_version(version_id) == confirmed
    order = reopened_orders.get_order(order_id)
    assert order is not None
    assert order.effective_order_version_id == version_id
    assert order.candidate_order_version_id is None
    reopened_orders.close()


def test_atomic_ack_rolls_back_version_if_job_fact_write_fails(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    orders, jobs, service, order_id, version_id = _sqlite_world(db)
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    accepted = service.accept_print_job(JOB_1)

    connection = sqlite3.connect(db)
    connection.execute(
        """
        CREATE TRIGGER fail_print_job_ack
        BEFORE UPDATE OF acknowledged_at ON kitchen_print_jobs
        WHEN NEW.acknowledged_at IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'simulated job ACK failure'); END
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="simulated job ACK failure"):
        service.acknowledge_print_job(JOB_1)

    stored_version = orders.get_order_version(version_id)
    stored_order = orders.get_order(order_id)
    assert stored_version is not None
    assert stored_version.kitchen_print_confirmed_at is None
    assert stored_order is not None
    assert stored_order.effective_order_version_id is None
    assert jobs.get(JOB_1) == accepted
    jobs.close()
    orders.close()


def test_activation_guard_miss_preserves_print_confirmation(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    orders, jobs, service, order_id, _version_id = _sqlite_world(db)
    order_service = OrderService(orders)
    order = orders.get_order(order_id)
    assert order is not None
    v2 = order_service.create_relevant_order_change_version(
        order,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Kiel",
        guest_count_estimate=30,
        planning_mode="caterer_suggestion",
    )
    order_service.set_candidate_order_version(order_id, v2.order_version_id)
    order = orders.get_order(order_id)
    assert order is not None
    v3 = order_service.create_relevant_order_change_version(
        order,
        event_date=date(2026, 10, 3),
        time_window_text="mittags",
        location_text="Lübeck",
        guest_count_estimate=40,
        planning_mode="self_select",
    )
    service.request_print(order_id, v2.order_version_id, print_job_id=JOB_1)
    accepted = service.accept_print_job(JOB_1)

    connection = sqlite3.connect(db)
    connection.execute(
        """
        CREATE TRIGGER simulate_candidate_race
        BEFORE UPDATE OF kitchen_print_confirmed_at ON order_versions
        WHEN NEW.order_version_id = '33333333-3333-4333-8333-333333333333'
        BEGIN
            UPDATE orders
            SET candidate_order_version_id = '44444444-4444-4444-8444-444444444444'
            WHERE order_id = '11111111-1111-4111-8111-111111111111';
        END
        """.replace("33333333-3333-4333-8333-333333333333", v2.order_version_id)
        .replace("44444444-4444-4444-8444-444444444444", v3.order_version_id)
        .replace("11111111-1111-4111-8111-111111111111", order_id)
    )
    connection.commit()
    connection.close()

    acknowledged, confirmed = service.acknowledge_print_job(JOB_1)

    stored_order = orders.get_order(order_id)
    stored_v2 = orders.get_order_version(v2.order_version_id)
    assert acknowledged.acknowledged_at is not None
    assert confirmed.kitchen_print_confirmed_at is not None
    assert jobs.get(JOB_1).acknowledged_at == acknowledged.acknowledged_at
    assert stored_v2 is not None
    assert stored_v2.kitchen_print_confirmed_at == confirmed.kitchen_print_confirmed_at
    assert stored_order is not None
    assert stored_order.effective_order_version_id is None
    assert stored_order.candidate_order_version_id == v3.order_version_id
    assert jobs.get(JOB_1) != accepted
    jobs.close()
    orders.close()


def test_sqlite_guards_prevent_rewriting_or_deleting_print_history(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    orders, jobs, service, order_id, version_id = _sqlite_world(db)
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    service.accept_print_job(JOB_1)
    jobs.close()
    orders.close()

    connection = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError, match="immutable once recorded"):
        connection.execute(
            "UPDATE kitchen_print_jobs SET accepted_at = NULL, "
            "ack_deadline_at = NULL WHERE print_job_id = ?",
            (JOB_1,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        connection.execute(
            "DELETE FROM kitchen_print_jobs WHERE print_job_id = ?", (JOB_1,)
        )
    connection.close()

"""Repository boundary tests for Phase 3B atomic kitchen print claim."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.kitchen_print_job import KitchenPrintJob, KitchenPrintPolicy
from catering_system.repositories.sqlite_kitchen_print_job_repository import (
    SQLiteKitchenPrintJobRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.kitchen_print_service import KitchenPrintService
from tests.helpers.order_seed import seed_order

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_NOW = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
_POLICY = KitchenPrintPolicy(
    acceptance_timeout=timedelta(seconds=30),
    acknowledgment_timeout=timedelta(minutes=5),
)

_JOB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_JOB_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_JOB_EXPIRED = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_JOB_ELIGIBLE = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def _inquiry(*, location: str = "Hamburg") -> Inquiry:
    now = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    return Inquiry(
        inquiry_id=str(uuid.uuid4()),
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        location_text=location,
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
        customer_snapshot=_CCSnapshot(email="kunde@example.com", phone="+49301234567"),
    )


def _sqlite_claim_world(
    db: Path,
) -> tuple[SQLiteOrderRepository, SQLiteKitchenPrintJobRepository, KitchenPrintService]:
    orders = SQLiteOrderRepository(db)
    jobs = SQLiteKitchenPrintJobRepository(db)
    service = KitchenPrintService(
        orders,
        jobs,
        policy=_POLICY,
        clock=lambda: _NOW,
    )
    return orders, jobs, service


def _save_open_job(
    jobs: SQLiteKitchenPrintJobRepository,
    *,
    order_id: str,
    order_version_id: str,
    print_job_id: str,
    requested_at: datetime,
    accept_deadline_at: datetime,
) -> KitchenPrintJob:
    job = KitchenPrintJob(
        print_job_id=print_job_id,
        order_id=order_id,
        order_version_id=order_version_id,
        attempt_number=1,
        requested_at=requested_at,
        accept_deadline_at=accept_deadline_at,
    )
    jobs.save(job)
    return job


def test_sqlite_claim_skips_expired_accept_deadline(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    orders, jobs, _service = _sqlite_claim_world(db)
    expired_order, expired_version = seed_order(orders, _inquiry(location="expired"))
    eligible_order, eligible_version = seed_order(orders, _inquiry(location="eligible"))

    _save_open_job(
        jobs,
        order_id=expired_order.order_id,
        order_version_id=expired_version.order_version_id,
        print_job_id=_JOB_EXPIRED,
        requested_at=_NOW - timedelta(minutes=5),
        accept_deadline_at=_NOW - timedelta(seconds=1),
    )
    _save_open_job(
        jobs,
        order_id=eligible_order.order_id,
        order_version_id=eligible_version.order_version_id,
        print_job_id=_JOB_ELIGIBLE,
        requested_at=_NOW - timedelta(minutes=1),
        accept_deadline_at=_NOW + timedelta(seconds=10),
    )

    claimed = jobs.claim_next_eligible(_NOW, _POLICY)

    assert claimed is not None
    assert claimed.print_job_id == _JOB_ELIGIBLE
    jobs.close()
    orders.close()


def test_sqlite_claim_orders_by_deadline_then_requested_at(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    orders, jobs, _service = _sqlite_claim_world(db)
    order_a, version_a = seed_order(orders, _inquiry(location="A"))
    order_b, version_b = seed_order(orders, _inquiry(location="B"))
    order_c, version_c = seed_order(orders, _inquiry(location="C"))

    base_requested = datetime(2026, 8, 8, 9, 50, tzinfo=UTC)
    _save_open_job(
        jobs,
        order_id=order_a.order_id,
        order_version_id=version_a.order_version_id,
        print_job_id=_JOB_A,
        requested_at=base_requested,
        accept_deadline_at=_NOW + timedelta(seconds=30),
    )
    _save_open_job(
        jobs,
        order_id=order_b.order_id,
        order_version_id=version_b.order_version_id,
        print_job_id=_JOB_B,
        requested_at=base_requested + timedelta(minutes=1),
        accept_deadline_at=_NOW + timedelta(seconds=30),
    )
    _save_open_job(
        jobs,
        order_id=order_c.order_id,
        order_version_id=version_c.order_version_id,
        print_job_id=_JOB_C,
        requested_at=base_requested + timedelta(minutes=5),
        accept_deadline_at=_NOW + timedelta(seconds=20),
    )

    first = jobs.claim_next_eligible(_NOW, _POLICY)
    second = jobs.claim_next_eligible(_NOW, _POLICY)
    third = jobs.claim_next_eligible(_NOW, _POLICY)

    assert [row.print_job_id if row is not None else None for row in (first, second, third)] == [
        _JOB_C,
        _JOB_A,
        _JOB_B,
    ]
    jobs.close()
    orders.close()


def test_sqlite_claim_sets_acceptance_facts_without_domain_confirmation(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    orders, jobs, _service = _sqlite_claim_world(db)
    order, version = seed_order(orders, _inquiry())

    _save_open_job(
        jobs,
        order_id=order.order_id,
        order_version_id=version.order_version_id,
        print_job_id=_JOB_A,
        requested_at=_NOW - timedelta(minutes=1),
        accept_deadline_at=_NOW + timedelta(seconds=30),
    )

    claimed = jobs.claim_next_eligible(_NOW, _POLICY)
    stored_version = orders.get_order_version(version.order_version_id)

    assert claimed is not None
    assert claimed.accepted_at == _NOW
    assert claimed.ack_deadline_at == _NOW + _POLICY.acknowledgment_timeout
    assert stored_version is not None
    assert stored_version.kitchen_print_confirmed_at is None
    jobs.close()
    orders.close()


def test_accept_print_job_after_claim_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    orders, jobs, service = _sqlite_claim_world(db)
    order, version = seed_order(orders, _inquiry())

    service.request_print(order.order_id, version.order_version_id, print_job_id=_JOB_A)
    claimed = jobs.claim_next_eligible(_NOW, _POLICY)
    assert claimed is not None

    accepted_again = service.accept_print_job(_JOB_A)
    stored = jobs.get(_JOB_A)

    assert accepted_again.accepted_at == claimed.accepted_at
    assert accepted_again.ack_deadline_at == claimed.ack_deadline_at
    assert stored == accepted_again
    jobs.close()
    orders.close()


def test_sqlite_repository_claim_does_not_filter_cancelled_order(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    orders, jobs, service = _sqlite_claim_world(db)
    order, version = seed_order(orders, _inquiry())

    service.request_print(order.order_id, version.order_version_id, print_job_id=_JOB_A)
    cancelled = orders.get_order(order.order_id)
    assert cancelled is not None
    orders.update_order(
        replace(cancelled, cancelled_at=_NOW, updated_at=_NOW)
    )

    claimed = jobs.claim_next_eligible(_NOW, _POLICY)

    assert claimed is not None
    assert claimed.print_job_id == _JOB_A
    assert claimed.accepted_at == _NOW
    assert claimed.rejected_at is None
    jobs.close()
    orders.close()

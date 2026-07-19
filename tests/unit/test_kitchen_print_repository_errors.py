"""Kitchen print repository guardrail coverage (in-memory + sqlite)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.kitchen_print_job import KitchenPrintJob
from catering_system.repositories.in_memory_kitchen_print_job_repository import (
    InMemoryKitchenPrintJobRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_kitchen_print_job_repository import (
    SQLiteKitchenPrintJobRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.order_service import OrderService

JOB_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
JOB_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_NOW = datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc)


def _inquiry() -> Inquiry:
    created = datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-4111-8111-111111111111",
        event_date=date(2026, 10, 1),
        created_at=created,
        updated_at=created,
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


def _memory_world() -> tuple[
    InMemoryOrderRepository, InMemoryKitchenPrintJobRepository, str, str
]:
    orders = InMemoryOrderRepository()
    order, version = OrderService(orders).convert_inquiry_to_order(_inquiry())
    jobs = InMemoryKitchenPrintJobRepository(orders)
    return orders, jobs, order.order_id, version.order_version_id


def _sqlite_world(
    tmp_path: Path,
) -> tuple[SQLiteOrderRepository, SQLiteKitchenPrintJobRepository, str, str]:
    db = tmp_path / "core.db"
    orders = SQLiteOrderRepository(db)
    order, version = OrderService(orders).convert_inquiry_to_order(_inquiry())
    jobs = SQLiteKitchenPrintJobRepository(db)
    return orders, jobs, order.order_id, version.order_version_id


def _job(order_id: str, version_id: str, *, job_id: str = JOB_1) -> KitchenPrintJob:
    return KitchenPrintJob(
        print_job_id=job_id,
        order_id=order_id,
        order_version_id=version_id,
        attempt_number=1,
        requested_at=_NOW,
        accept_deadline_at=_NOW + timedelta(seconds=30),
    )


def test_in_memory_update_unknown_job_raises_key_error() -> None:
    _, jobs, order_id, version_id = _memory_world()
    with pytest.raises(KeyError):
        jobs.update(_job(order_id, version_id))


def test_in_memory_save_reprint_rejects_stale_previous() -> None:
    _, jobs, order_id, version_id = _memory_world()
    previous = _job(order_id, version_id)
    jobs.save(previous)
    stale = replace(
        previous,
        accepted_at=_NOW + timedelta(seconds=1),
        ack_deadline_at=_NOW + timedelta(minutes=1),
    )
    new_job = replace(
        _job(order_id, version_id, job_id=JOB_2),
        attempt_number=2,
        supersedes_print_job_id=JOB_1,
    )
    with pytest.raises(ValueError, match="stale previous print job"):
        jobs.save_reprint(
            stale, replace(previous, superseded_at=_NOW + timedelta(seconds=2)), new_job
        )


def test_in_memory_acknowledge_rejects_version_mismatch() -> None:
    orders, jobs, order_id, version_id = _memory_world()
    job = _job(order_id, version_id)
    jobs.save(job)
    accepted = replace(
        job,
        accepted_at=_NOW + timedelta(seconds=1),
        ack_deadline_at=_NOW + timedelta(minutes=1),
    )
    jobs.update(accepted)
    acknowledged = replace(accepted, acknowledged_at=_NOW + timedelta(seconds=2))
    wrong_version = orders.get_order_version(version_id)
    assert wrong_version is not None
    mismatched = replace(wrong_version, order_id="00000000-0000-4000-8000-000000000000")
    with pytest.raises(ValueError, match="does not belong to print job"):
        jobs.acknowledge_and_confirm(acknowledged, mismatched)


def test_in_memory_validate_new_job_rejects_duplicate_attempt_number() -> None:
    _, jobs, order_id, version_id = _memory_world()
    jobs.save(_job(order_id, version_id))
    duplicate = replace(_job(order_id, version_id, job_id=JOB_2), attempt_number=1)
    with pytest.raises(ValueError, match="attempt_number already exists"):
        jobs.save(duplicate)


def test_sqlite_save_reprint_rejects_wrong_supersedes_reference(tmp_path: Path) -> None:
    _, jobs, order_id, version_id = _sqlite_world(tmp_path)
    previous = _job(order_id, version_id)
    jobs.save(previous)
    new_job = replace(
        _job(order_id, version_id, job_id=JOB_2),
        attempt_number=2,
        supersedes_print_job_id=JOB_2,
    )
    with pytest.raises(
        ValueError, match="reprint must reference the previous print job"
    ):
        jobs.save_reprint(previous, None, new_job)
    jobs.close()


def test_sqlite_acknowledge_rejects_missing_acknowledged_at(tmp_path: Path) -> None:
    orders, jobs, order_id, version_id = _sqlite_world(tmp_path)
    job = _job(order_id, version_id)
    jobs.save(job)
    accepted = replace(
        job,
        accepted_at=_NOW + timedelta(seconds=1),
        ack_deadline_at=_NOW + timedelta(minutes=1),
    )
    jobs.update(accepted)
    version = orders.get_order_version(version_id)
    assert version is not None
    with pytest.raises(
        ValueError, match="atomic confirmation requires acknowledged_at"
    ):
        jobs.acknowledge_and_confirm(accepted, version)
    jobs.close()
    orders.close()


def test_sqlite_update_unknown_job_raises_key_error(tmp_path: Path) -> None:
    _, jobs, order_id, version_id = _sqlite_world(tmp_path)
    with pytest.raises(KeyError):
        jobs.update(_job(order_id, version_id))
    jobs.close()


def test_in_memory_save_reprint_rejects_wrong_supersedes_reference() -> None:
    _, jobs, order_id, version_id = _memory_world()
    previous = _job(order_id, version_id)
    jobs.save(previous)
    new_job = replace(
        _job(order_id, version_id, job_id=JOB_2),
        attempt_number=2,
        supersedes_print_job_id=JOB_2,
    )
    with pytest.raises(ValueError, match="reprint attempt chain is invalid"):
        jobs.save_reprint(previous, None, new_job)


def test_in_memory_acknowledge_rejects_missing_acknowledged_at() -> None:
    orders, jobs, order_id, version_id = _memory_world()
    job = _job(order_id, version_id)
    jobs.save(job)
    accepted = replace(
        job,
        accepted_at=_NOW + timedelta(seconds=1),
        ack_deadline_at=_NOW + timedelta(minutes=1),
    )
    jobs.update(accepted)
    version = orders.get_order_version(version_id)
    assert version is not None
    with pytest.raises(
        ValueError, match="atomic confirmation requires acknowledged_at"
    ):
        jobs.acknowledge_and_confirm(accepted, version)


def test_sqlite_acknowledge_rejects_mismatched_confirmation_timestamp(
    tmp_path: Path,
) -> None:
    orders, jobs, order_id, version_id = _sqlite_world(tmp_path)
    job = _job(order_id, version_id)
    jobs.save(job)
    accepted = replace(
        job,
        accepted_at=_NOW + timedelta(seconds=1),
        ack_deadline_at=_NOW + timedelta(minutes=1),
    )
    jobs.update(accepted)
    acknowledged = replace(accepted, acknowledged_at=_NOW + timedelta(seconds=2))
    version = orders.get_order_version(version_id)
    assert version is not None
    wrong_confirmation = replace(
        version, kitchen_print_confirmed_at=_NOW + timedelta(hours=1)
    )
    with pytest.raises(ValueError, match="confirmation facts must share one timestamp"):
        jobs.acknowledge_and_confirm(acknowledged, wrong_confirmation)
    jobs.close()
    orders.close()

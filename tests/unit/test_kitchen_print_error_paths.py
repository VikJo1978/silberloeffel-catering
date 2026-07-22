"""Kitchen print service and repository failure-path coverage."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

from datetime import date, datetime, timedelta, timezone
from dataclasses import replace

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.kitchen_print_job import KitchenPrintJob, KitchenPrintPolicy
from catering_system.repositories.in_memory_kitchen_print_job_repository import (
    InMemoryKitchenPrintJobRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.kitchen_print_service import KitchenPrintService

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    email="kunde@example.com", phone="+49301234567"
)

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
        customer_snapshot=_CONTACT_COMPLETE_SNAPSHOT,
    )


def _service() -> tuple[InMemoryOrderRepository, KitchenPrintService, str, str]:
    orders = InMemoryOrderRepository()
    order, version = seed_order(orders, _inquiry())
    jobs = InMemoryKitchenPrintJobRepository(orders)
    service = KitchenPrintService(orders, jobs, clock=lambda: _NOW)
    return orders, service, order.order_id, version.order_version_id


def test_request_print_rejects_unknown_order() -> None:
    _, service, _, version_id = _service()
    with pytest.raises(ValueError, match="no order with id"):
        service.request_print("00000000-0000-4000-8000-000000000000", version_id)


def test_request_print_rejects_foreign_version() -> None:
    _, service, order_id, _ = _service()
    with pytest.raises(ValueError, match="is not a version of order"):
        service.request_print(order_id, "00000000-0000-4000-8000-000000000000")


def test_request_print_rejects_conflicting_existing_job_id() -> None:
    orders, service, order_id, version_id = _service()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    other_order, other_version = seed_order(
        orders, replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    )
    with pytest.raises(
        ValueError, match="print_job_id already exists with different facts"
    ):
        service.request_print(
            other_order.order_id, other_version.order_version_id, print_job_id=JOB_1
        )


def test_accept_print_job_rejects_missing_job() -> None:
    _, service, _, _ = _service()
    with pytest.raises(ValueError, match="no print job with id"):
        service.accept_print_job(JOB_1)


def test_accept_print_job_rejects_after_deadline() -> None:
    clock = [_NOW]

    def tick() -> datetime:
        return clock[0]

    orders = InMemoryOrderRepository()
    order, version = seed_order(orders, _inquiry())
    jobs = InMemoryKitchenPrintJobRepository(orders)
    service = KitchenPrintService(orders, jobs, clock=tick)
    service.request_print(order.order_id, version.order_version_id, print_job_id=JOB_1)
    clock[0] = _NOW + timedelta(minutes=1)
    with pytest.raises(ValueError, match="acceptance deadline has passed"):
        service.accept_print_job(JOB_1)


def test_reject_print_job_rejects_unknown_code() -> None:
    _, service, order_id, version_id = _service()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    with pytest.raises(ValueError, match="unsupported rejection_code"):
        service.reject_print_job(JOB_1, "unknown_reason")


def test_acknowledge_requires_technical_acceptance() -> None:
    _, service, order_id, version_id = _service()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    with pytest.raises(ValueError, match="must be technically accepted"):
        service.acknowledge_print_job(JOB_1)


def test_reprint_requires_latest_attempt() -> None:
    _, service, order_id, version_id = _service()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    service.accept_print_job(JOB_1)
    latest = service.reprint(JOB_1, new_print_job_id=JOB_2)
    with pytest.raises(ValueError, match="reprint must name the latest print attempt"):
        service.reprint(JOB_1)
    assert latest.print_job_id == JOB_2


def test_kitchen_print_policy_rejects_non_positive_timeouts() -> None:
    with pytest.raises(ValueError, match="acceptance_timeout must be positive"):
        KitchenPrintPolicy(acceptance_timeout=timedelta(0))


def test_in_memory_repo_rejects_invalid_ownership() -> None:
    orders = InMemoryOrderRepository()
    jobs = InMemoryKitchenPrintJobRepository(orders)
    job = KitchenPrintJob(
        print_job_id=JOB_1,
        order_id="00000000-0000-4000-8000-000000000000",
        order_version_id="00000000-0000-4000-8000-000000000001",
        attempt_number=1,
        requested_at=_NOW,
        accept_deadline_at=_NOW + timedelta(seconds=30),
    )
    with pytest.raises(ValueError, match="ownership is invalid"):
        jobs.save(job)

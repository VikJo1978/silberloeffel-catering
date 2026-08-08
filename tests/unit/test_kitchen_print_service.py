"""Phase 3 / Slice 3A print-job facts, derivation, and service rules."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

from dataclasses import fields
from datetime import date, datetime, timedelta, timezone

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.kitchen_print_job import (
    KitchenPrintJob,
    KitchenPrintPolicy,
    derive_kitchen_print_job_state,
)
from catering_system.domain.operational_core_events import KitchenPrintConfirmed
from catering_system.repositories.in_memory_kitchen_print_job_repository import (
    InMemoryKitchenPrintJobRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.kitchen_print_service import KitchenPrintService
from catering_system.services.operational_core_service import OperationalCoreService

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    email="kunde@example.com", phone="+49301234567"
)

JOB_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
JOB_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
JOB_3 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def _inquiry() -> Inquiry:
    now = datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-4111-8111-111111111111",
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


def _setup() -> tuple[
    InMemoryOrderRepository,
    KitchenPrintService,
    OperationalCoreService,
    MutableClock,
    str,
    str,
    list[object],
]:
    orders = InMemoryOrderRepository()
    order, version = seed_order(orders, _inquiry())
    jobs = InMemoryKitchenPrintJobRepository(orders)
    clock = MutableClock(datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc))
    events: list[object] = []
    service = KitchenPrintService(
        orders,
        jobs,
        policy=KitchenPrintPolicy(
            acceptance_timeout=timedelta(seconds=12),
            acknowledgment_timeout=timedelta(minutes=2),
        ),
        clock=clock,
        event_sink=events.append,
    )
    return (
        orders,
        service,
        OperationalCoreService(orders),
        clock,
        order.order_id,
        version.order_version_id,
        events,
    )


def test_first_attempt_is_append_only_facts_without_stored_status() -> None:
    _orders, service, _core, clock, order_id, version_id, _events = _setup()
    job = service.request_print(order_id, version_id, print_job_id=JOB_1)

    assert job.attempt_number == 1
    assert job.requested_at == clock.now
    assert job.accept_deadline_at == clock.now + timedelta(seconds=12)
    assert job.accepted_at is None
    assert job.ack_deadline_at is None
    assert derive_kitchen_print_job_state(job, now=clock.now) == "awaiting_acceptance"
    assert "status" not in {field.name for field in fields(KitchenPrintJob)}


def test_first_attempt_retry_with_same_job_id_is_idempotent() -> None:
    _orders, service, _core, clock, order_id, version_id, _events = _setup()
    first = service.request_print(order_id, version_id, print_job_id=JOB_1)
    clock.advance(timedelta(seconds=3))

    retry = service.request_print(order_id, version_id, print_job_id=JOB_1)

    assert retry == first
    assert retry.requested_at != clock.now
    assert service.list_print_jobs_for_version(version_id) == [first]


def test_technical_acceptance_sets_ack_deadline_and_derives_awaiting_ack() -> None:
    _orders, service, _core, clock, order_id, version_id, _events = _setup()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    clock.advance(timedelta(seconds=2))
    accepted = service.accept_print_job(JOB_1)

    assert accepted.accepted_at == clock.now
    assert accepted.ack_deadline_at == clock.now + timedelta(minutes=2)
    assert derive_kitchen_print_job_state(accepted, now=clock.now) == "awaiting_ack"


def test_technical_rejection_is_distinct_and_idempotent() -> None:
    _orders, service, _core, clock, order_id, version_id, _events = _setup()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    rejected = service.reject_print_job(JOB_1, "printer_unavailable")

    assert rejected.rejected_at == clock.now
    assert rejected.rejection_code == "printer_unavailable"
    assert derive_kitchen_print_job_state(rejected, now=clock.now) == "rejected"
    assert service.reject_print_job(JOB_1, "printer_unavailable") == rejected
    with pytest.raises(ValueError, match="different rejection"):
        service.reject_print_job(JOB_1, "spool_rejected")


def test_ack_before_deadline_atomically_confirms_version() -> None:
    orders, service, core, clock, order_id, version_id, events = _setup()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    service.accept_print_job(JOB_1)
    clock.advance(timedelta(seconds=30))

    acknowledged, version = service.acknowledge_print_job(JOB_1)

    assert acknowledged.acknowledged_at == clock.now
    assert version.kitchen_print_confirmed_at == clock.now
    assert orders.get_order_version(version_id) == version
    assert derive_kitchen_print_job_state(acknowledged, now=clock.now) == "confirmed"
    assert events == [
        KitchenPrintConfirmed(order_id=order_id, order_version_id=version_id)
    ]
    assert core.evaluate_ready_to_send(order_id).ready is False  # still not effective


def test_ack_after_deadline_is_late_but_still_valid() -> None:
    _orders, service, _core, clock, order_id, version_id, _events = _setup()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    accepted = service.accept_print_job(JOB_1)
    clock.advance(timedelta(minutes=3))

    assert derive_kitchen_print_job_state(accepted, now=clock.now) == "ack_overdue"
    acknowledged, version = service.acknowledge_print_job(JOB_1)
    assert acknowledged.acknowledged_at == clock.now
    assert version.kitchen_print_confirmed_at == clock.now
    assert derive_kitchen_print_job_state(acknowledged, now=clock.now) == "confirmed"


def test_repeated_ack_keeps_original_facts_and_emits_once() -> None:
    _orders, service, _core, clock, order_id, version_id, events = _setup()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    service.accept_print_job(JOB_1)
    first_job, first_version = service.acknowledge_print_job(JOB_1)
    clock.advance(timedelta(minutes=1))
    second_job, second_version = service.acknowledge_print_job(JOB_1)

    assert second_job == first_job
    assert second_version == first_version
    assert second_job.acknowledged_at != clock.now
    assert len(events) == 1


def test_reprint_creates_new_job_and_supersedes_live_attempt() -> None:
    _orders, service, _core, clock, order_id, version_id, _events = _setup()
    first = service.request_print(order_id, version_id, print_job_id=JOB_1)
    clock.advance(timedelta(seconds=3))
    second = service.reprint(JOB_1, new_print_job_id=JOB_2)

    assert second.print_job_id != first.print_job_id
    assert second.attempt_number == 2
    assert second.supersedes_print_job_id == first.print_job_id
    stored_first = service.get_print_job(JOB_1)
    assert stored_first is not None and stored_first.superseded_at == clock.now
    assert derive_kitchen_print_job_state(stored_first, now=clock.now) == "superseded"


def test_reprint_retry_with_same_new_job_id_is_idempotent() -> None:
    _orders, service, _core, clock, order_id, version_id, _events = _setup()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    first_result = service.reprint(JOB_1, new_print_job_id=JOB_2)
    clock.advance(timedelta(seconds=3))

    retry = service.reprint(JOB_1, new_print_job_id=JOB_2)

    assert retry == first_result
    assert retry.requested_at != clock.now
    assert service.list_print_jobs_for_version(version_id) == [
        service.get_print_job(JOB_1),
        first_result,
    ]


def test_multiple_jobs_for_same_version_preserve_attempt_history() -> None:
    _orders, service, _core, _clock, order_id, version_id, _events = _setup()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    service.reject_print_job(JOB_1, "spool_rejected")
    service.reprint(JOB_1, new_print_job_id=JOB_2)
    service.reject_print_job(JOB_2, "printer_unavailable")
    third = service.reprint(JOB_2, new_print_job_id=JOB_3)

    rows = service.list_print_jobs_for_version(version_id)
    assert [job.print_job_id for job in rows] == [JOB_1, JOB_2, JOB_3]
    assert [job.attempt_number for job in rows] == [1, 2, 3]
    assert third.supersedes_print_job_id == JOB_2
    assert rows[0].rejection_code == "spool_rejected"
    assert rows[1].rejection_code == "printer_unavailable"


def test_effective_switch_stays_blocked_until_job_ack_then_succeeds() -> None:
    _orders, service, core, _clock, order_id, version_id, _events = _setup()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    service.accept_print_job(JOB_1)

    with pytest.raises(ValueError, match="kitchen print not confirmed"):
        core.make_order_version_effective(order_id, version_id)

    service.acknowledge_print_job(JOB_1)
    updated = core.make_order_version_effective(order_id, version_id)
    assert updated.effective_order_version_id == version_id


def test_existing_manual_confirmation_flow_is_unchanged() -> None:
    orders, _service, core, _clock, order_id, version_id, _events = _setup()
    first = core.confirm_kitchen_print(order_id, version_id)
    second = core.confirm_kitchen_print(order_id, version_id)
    effective = core.make_order_version_effective(order_id, version_id)

    assert second == first
    assert first.kitchen_print_confirmed_at is not None
    assert orders.get_order_version(version_id) == first
    assert effective.effective_order_version_id == version_id


def test_acceptance_deadline_and_cancelled_state_are_pure_derivations() -> None:
    _orders, service, _core, clock, order_id, version_id, _events = _setup()
    job = service.request_print(order_id, version_id, print_job_id=JOB_1)
    clock.advance(timedelta(seconds=12))

    assert derive_kitchen_print_job_state(job, now=clock.now) == "acceptance_overdue"
    assert (
        derive_kitchen_print_job_state(job, now=clock.now, order_cancelled=True)
        == "cancelled"
    )
    with pytest.raises(ValueError, match="deadline has passed"):
        service.accept_print_job(JOB_1)


def test_claim_next_eligible_records_order_cancelled_after_atomic_accept() -> None:
    orders, service, core, _clock, order_id, version_id, _events = _setup()
    service.request_print(order_id, version_id, print_job_id=JOB_1)
    core.cancel_order(order_id)

    claimed = service.claim_next_eligible()
    stored = service.get_print_job(JOB_1)
    version = orders.get_order_version(version_id)

    assert claimed is None
    assert stored is not None
    assert stored.accepted_at is not None
    assert stored.rejected_at is not None
    assert stored.rejection_code == "order_cancelled"
    assert version is not None
    assert version.kitchen_print_confirmed_at is None

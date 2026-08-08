"""Slice 3B contract tests — Kitchen Print Agent boundary (PR: PHASE-3B-PRINT-CONTRACT-TESTS).

Proves claim eligibility, atomicity, technical-vs-domain separation, kitchen_job
intent, document immutability, ledger replay, reject path, and human-only ACK.
No production Slice 3B implementation required — tests encode ADR invariants via
tests.helpers.kitchen_print_agent_contract reference boundary.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, date, datetime, timedelta

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
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from tests.helpers.kitchen_print_agent_contract import (
    InMemoryAgentCommandLedger,
    InMemoryDocumentStore,
    claim_next_eligible,
    claim_with_document,
    execute_claim_command,
    is_eligible_for_claim,
    load_document_by_ref,
    resolve_kitchen_job_projection,
)
from tests.helpers.order_seed import seed_order
from tests.unit.test_offer_service import _accepted_offer_state

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_NOW = datetime(2026, 8, 8, 11, 0, tzinfo=UTC)
_POLICY = KitchenPrintPolicy(
    acceptance_timeout=timedelta(seconds=30),
    acknowledgment_timeout=timedelta(minutes=5),
)

_JOB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_JOB_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_JOB_D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


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


def _print_service(
    orders: InMemoryOrderRepository,
    jobs: InMemoryKitchenPrintJobRepository,
) -> KitchenPrintService:
    return KitchenPrintService(
        orders,
        jobs,
        policy=_POLICY,
        clock=lambda: _NOW,
    )


def _requested_job(
    service: KitchenPrintService,
    order_id: str,
    version_id: str,
    print_job_id: str,
) -> KitchenPrintJob:
    return service.request_print(order_id, version_id, print_job_id=print_job_id)


def _eligible_job_setup() -> tuple[
    InMemoryOrderRepository,
    InMemoryKitchenPrintJobRepository,
    KitchenPrintService,
    KitchenPrintJob,
]:
    orders = InMemoryOrderRepository()
    order_a, version_a = seed_order(orders, _inquiry(location="A"))
    order_b, version_b = seed_order(orders, _inquiry(location="B"))
    order_c, version_c = seed_order(orders, _inquiry(location="C"))
    order_d, version_d = seed_order(orders, _inquiry(location="D"))
    jobs = InMemoryKitchenPrintJobRepository(orders)
    service = _print_service(orders, jobs)

    job_a = _requested_job(
        service, order_a.order_id, version_a.order_version_id, _JOB_A
    )
    job_b = _requested_job(
        service, order_b.order_id, version_b.order_version_id, _JOB_B
    )
    job_c = _requested_job(
        service, order_c.order_id, version_c.order_version_id, _JOB_C
    )
    _requested_job(service, order_d.order_id, version_d.order_version_id, _JOB_D)

    service.accept_print_job(_JOB_B)
    service.reject_print_job(_JOB_C, "printer_unavailable")
    service.accept_print_job(_JOB_D)
    service.reprint(_JOB_D, new_print_job_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")

    assert is_eligible_for_claim(
        job_a, now=_NOW, order=orders.get_order(order_a.order_id)
    )
    assert not is_eligible_for_claim(
        jobs.get(_JOB_B) or job_b, now=_NOW, order=orders.get_order(order_b.order_id)
    )
    assert not is_eligible_for_claim(
        jobs.get(_JOB_C) or job_c, now=_NOW, order=orders.get_order(order_c.order_id)
    )
    superseded = jobs.get(_JOB_D)
    assert superseded is not None and superseded.superseded_at is not None

    return orders, jobs, service, job_a


def test_claim_next_eligible_returns_only_awaiting_acceptance_job() -> None:
    orders, jobs, _service, job_a = _eligible_job_setup()

    claimed = claim_next_eligible(orders, jobs, now=_NOW, policy=_POLICY)

    assert claimed is not None
    assert claimed.print_job_id == job_a.print_job_id
    assert claimed.order_version_id == job_a.order_version_id
    assert claimed.accepted_at == _NOW
    assert claimed.ack_deadline_at == _NOW + _POLICY.acknowledgment_timeout


def test_claim_next_eligible_is_atomic_under_concurrency() -> None:
    orders = InMemoryOrderRepository()
    first_order, first_version = seed_order(orders, _inquiry(location="first"))
    second_order, second_version = seed_order(orders, _inquiry(location="second"))
    jobs = InMemoryKitchenPrintJobRepository(orders)
    service = _print_service(orders, jobs)
    _requested_job(
        service, first_order.order_id, first_version.order_version_id, _JOB_A
    )
    _requested_job(
        service, second_order.order_id, second_version.order_version_id, _JOB_B
    )

    barrier = threading.Barrier(2)
    results: list[KitchenPrintJob | None] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            results.append(claim_next_eligible(orders, jobs, now=_NOW, policy=_POLICY))
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(results) == 2
    claimed_ids = {job.print_job_id for job in results if job is not None}
    assert len(claimed_ids) == 2
    assert claimed_ids == {_JOB_A, _JOB_B}


def test_claim_does_not_set_kitchen_print_confirmed_at() -> None:
    orders, jobs, _service, job_a = _eligible_job_setup()

    claimed = claim_next_eligible(orders, jobs, now=_NOW, policy=_POLICY)
    assert claimed is not None
    assert claimed.accepted_at == _NOW

    version = orders.get_order_version(job_a.order_version_id)
    assert version is not None
    assert version.kitchen_print_confirmed_at is None


def test_kitchen_job_intent_resolves_requested_version_not_effective() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, v1 = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    order_service = OrderService(orders)
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)

    v2 = order_service.create_relevant_order_change_version(
        order,
        event_date=date(2026, 9, 1),
        time_window_text="abends",
        location_text="Lübeck",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
    )
    order_service.set_candidate_order_version(order.order_id, v2.order_version_id)

    projection = resolve_kitchen_job_projection(
        orders,
        offer_service._commercial_snapshots,
        order_id=order.order_id,
        order_version_id=v2.order_version_id,
    )

    assert projection.event.order_version_id == v2.order_version_id
    assert projection.event.version_number == 2
    assert projection.event.location_text == "Lübeck"
    assert projection.flags.intent == "kitchen_job"
    assert projection.flags.watermark is None
    assert projection.flags.is_preview is False


def test_kitchen_print_document_is_immutable_after_order_mutations() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    jobs = InMemoryKitchenPrintJobRepository(orders)
    service = _print_service(orders, jobs)
    service.request_print(
        order.order_id,
        order_version.order_version_id,
        print_job_id=_JOB_A,
    )
    store = InMemoryDocumentStore()

    result = claim_with_document(
        orders,
        jobs,
        offer_service._commercial_snapshots,
        store,
        now=_NOW,
        policy=_POLICY,
    )
    assert result is not None
    first_ref = result.document.document_ref
    first_bytes = result.document.body

    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)

    stored = load_document_by_ref(store, first_ref)
    assert stored.document_ref == first_ref
    assert stored.body == first_bytes


def test_claim_command_replay_returns_byte_identical_response() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    jobs = InMemoryKitchenPrintJobRepository(orders)
    service = _print_service(orders, jobs)
    service.request_print(
        order.order_id,
        order_version.order_version_id,
        print_job_id=_JOB_A,
    )
    store = InMemoryDocumentStore()
    ledger = InMemoryAgentCommandLedger()
    command_id = "11111111-1111-4111-8111-111111111111"

    first_status, first_body = execute_claim_command(
        command_id=command_id,
        order_repository=orders,
        job_repository=jobs,
        commercial_snapshot_repository=offer_service._commercial_snapshots,
        document_store=store,
        ledger=ledger,
        now=_NOW,
        policy=_POLICY,
    )
    second_status, second_body = execute_claim_command(
        command_id=command_id,
        order_repository=orders,
        job_repository=jobs,
        commercial_snapshot_repository=offer_service._commercial_snapshots,
        document_store=store,
        ledger=ledger,
        now=_NOW,
        policy=_POLICY,
    )

    assert first_status == 200
    assert second_status == first_status
    assert second_body == first_body


def test_agent_reject_after_claim_leaves_domain_confirmation_unset() -> None:
    orders, jobs, service, _job_a = _eligible_job_setup()

    claimed = claim_next_eligible(orders, jobs, now=_NOW, policy=_POLICY)
    assert claimed is not None

    rejected = service.reject_print_job(claimed.print_job_id, "printer_unavailable")
    version = orders.get_order_version(claimed.order_version_id)
    assert version is not None

    assert rejected.rejected_at == _NOW
    assert rejected.rejection_code == "printer_unavailable"
    assert rejected.acknowledged_at is None
    assert version.kitchen_print_confirmed_at is None


def test_only_acknowledge_print_job_sets_kitchen_print_confirmed_at() -> None:
    orders, jobs, service, job_a = _eligible_job_setup()

    claimed = claim_next_eligible(orders, jobs, now=_NOW, policy=_POLICY)
    assert claimed is not None
    version_before_ack = orders.get_order_version(job_a.order_version_id)
    assert version_before_ack is not None
    assert version_before_ack.kitchen_print_confirmed_at is None

    acknowledged, confirmed_version = service.acknowledge_print_job(job_a.print_job_id)

    assert acknowledged.acknowledged_at == _NOW
    assert confirmed_version.kitchen_print_confirmed_at == _NOW
    assert orders.get_order_version(job_a.order_version_id) == confirmed_version


def test_kitchen_print_agent_contract_must_not_import_offer_or_catalog() -> None:
    from pathlib import Path

    helper = (
        Path(__file__).resolve().parents[1]
        / "helpers"
        / "kitchen_print_agent_contract.py"
    )
    text = helper.read_text(encoding="utf-8")
    assert "OfferRepository" not in text
    assert "CatalogRepository" not in text

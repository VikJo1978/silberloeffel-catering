"""Transaction coordination for the Core Office API
(PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §6.1, §6.2, §6.4)."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from catering_system.domain.inquiry import (
    ACTIVE_ORDER_CRM_STAGE,
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.repositories.core_transaction import (
    CoreBusyError,
    CoreCommandExecutor,
    DeferredEventSink,
    open_core_connection,
)
from catering_system.repositories.office_api_ledger import (
    OfficeCommandLedger,
    command_fingerprint,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
)
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.repositories.sqlite_payment_reminder_repository import (
    SQLitePaymentReminderRepository,
)
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.offer_service import OfferService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.payment_reminder_service import PaymentReminderService

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    email="kunde@example.com", phone="+49301234567"
)

_PREPARE_CMD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SNAPSHOT_ID = "77777777-7777-4777-8777-777777777771"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"


def _inquiry(inquiry_id: str = "11111111-1111-1111-1111-111111111111") -> Inquiry:
    now = datetime.now(timezone.utc)
    return Inquiry(
        inquiry_id=inquiry_id,
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        delivery_date_local="2026-10-01",
        delivery_window_start_local="11:30",
        delivery_window_end_local="12:00",
        event_start_local="13:00",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
        customer_snapshot=_CONTACT_COMPLETE_SNAPSHOT,
    )


@pytest.fixture()
def shared(tmp_path: Path):
    connection = open_core_connection(tmp_path / "core.db")
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    orders = SQLiteOrderRepository.from_connection(connection)
    ledger = OfficeCommandLedger(connection)
    yield connection, inquiries, orders, ledger
    connection.close()


def test_business_write_and_ledger_row_commit_atomically(shared) -> None:
    connection, inquiries, orders, ledger = shared
    executor = CoreCommandExecutor(connection)
    inquiries_service_input = _inquiry()

    def work() -> str:
        inquiries.save(inquiries_service_input)
        order, _v1 = seed_order(orders, inquiries_service_input)
        ledger.record("cmd-1", "fp-1", 201, '{"order_id": "x"}')
        return order.order_id

    order_id = executor.run(work)
    assert orders.get_order(order_id) is not None
    assert ledger.get("cmd-1") is not None


def test_failure_rolls_back_business_write_and_ledger_together(shared) -> None:
    connection, inquiries, orders, ledger = shared
    executor = CoreCommandExecutor(connection)
    saved = _inquiry()

    def work() -> None:
        inquiries.save(saved)
        seed_order(orders, saved)
        ledger.record("cmd-2", "fp", 201, "{}")
        raise RuntimeError("crash between service write and response")

    with pytest.raises(RuntimeError):
        executor.run(work)
    assert inquiries.get_by_id(saved.inquiry_id) is None
    assert orders.list_orders() == []
    assert ledger.get("cmd-2") is None


def test_events_flush_only_after_commit_and_never_on_rollback(shared) -> None:
    connection, inquiries, orders, _ledger = shared
    delivered: list[object] = []
    events = DeferredEventSink(delivered.append)
    executor = CoreCommandExecutor(connection, events)
    core = OperationalCoreService(orders, event_sink=events)
    inq = _inquiry()

    def create() -> str:
        inquiries.save(inq)
        order, v1 = seed_order(orders, inq)
        core.confirm_kitchen_print(order.order_id, v1.order_version_id)
        assert delivered == []  # nothing may leave before COMMIT
        return order.order_id

    order_id = executor.run(create)
    assert len(delivered) == 1  # KitchenPrintConfirmed, post-commit only

    def cancel_then_crash() -> None:
        core.cancel_order(order_id)
        raise RuntimeError("rollback")

    with pytest.raises(RuntimeError):
        executor.run(cancel_then_crash)
    assert len(delivered) == 1  # the cancelled event was discarded
    stored = orders.get_order(order_id)
    assert stored is not None and stored.cancelled_at is None


def test_lock_contention_maps_to_core_busy_and_writes_nothing(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    connection = open_core_connection(db)
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    ledger = OfficeCommandLedger(connection)
    executor = CoreCommandExecutor(connection)

    holder = sqlite3.connect(db)  # a second writer holds the write lock
    holder.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("PRAGMA busy_timeout = 50")  # keep the test fast
        with pytest.raises(CoreBusyError):
            executor.run(lambda: inquiries.save(_inquiry("busy-1")))
    finally:
        holder.rollback()
        holder.close()
    assert inquiries.get_by_id("busy-1") is None
    assert ledger.get("anything") is None
    # the connection is reusable after the busy rollback:
    executor.run(lambda: inquiries.save(_inquiry("busy-2")))
    assert inquiries.get_by_id("busy-2") is not None
    connection.close()


def test_busy_timeout_pragma_is_set_to_two_seconds(tmp_path: Path) -> None:
    connection = open_core_connection(tmp_path / "core.db")
    value = connection.execute("PRAGMA busy_timeout").fetchone()[0]
    connection.close()
    assert value == 2000  # pack §6.4: below the panel's 5 s command timeout


def test_standalone_repositories_keep_autocommit_behavior(tmp_path: Path) -> None:
    """The refactor must be behavior-preserving for existing callers."""
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    repo.save(_inquiry())
    repo.close()
    reopened = SQLiteInquiryRepository(tmp_path / "core.db")
    assert reopened.get_by_id("11111111-1111-1111-1111-111111111111") is not None
    reopened.close()


def test_fingerprint_distinguishes_every_command_dimension() -> None:
    base = command_fingerprint(
        "/office/v1/orders/{id}/cancel",
        {"id": "o-1"},
        {},
        {"updated_at": "2026-07-13T09:00:00+00:00"},
        "office-panel",
    )
    variants = [
        command_fingerprint(
            "/office/v1/orders/{id}/ready",
            {"id": "o-1"},
            {},
            {"updated_at": "2026-07-13T09:00:00+00:00"},
            "office-panel",
        ),
        command_fingerprint(
            "/office/v1/orders/{id}/cancel",
            {"id": "o-2"},
            {},
            {"updated_at": "2026-07-13T09:00:00+00:00"},
            "office-panel",
        ),
        command_fingerprint(
            "/office/v1/orders/{id}/cancel",
            {"id": "o-1"},
            {"x": 1},
            {"updated_at": "2026-07-13T09:00:00+00:00"},
            "office-panel",
        ),
        command_fingerprint(
            "/office/v1/orders/{id}/cancel",
            {"id": "o-1"},
            {},
            {"updated_at": "2026-07-13T09:00:01+00:00"},
            "office-panel",
        ),
        command_fingerprint(
            "/office/v1/orders/{id}/cancel",
            {"id": "o-1"},
            {},
            {"updated_at": "2026-07-13T09:00:00+00:00"},
            "promotion-client",
        ),
    ]
    assert len({base, *variants}) == 6  # all six differ


# --- orders migration 6: partial unique active-order index (pack §6.2) ---


def test_second_convert_lookup_is_idempotent_for_same_inquiry(shared) -> None:
    connection, inquiries, orders, _ledger = shared
    executor = CoreCommandExecutor(connection)
    inq = _inquiry()
    executor.run(lambda: inquiries.save(inq))
    first = executor.run(lambda: seed_order(orders, inq))
    second = executor.run(lambda: OrderService(orders).convert_inquiry_to_order(inq))
    assert second[0].order_id == first[0].order_id
    assert len([o for o in orders.list_orders() if o.cancelled_at is None]) == 1


def test_convert_after_storno_returns_existing_order(shared) -> None:
    connection, inquiries, orders, _ledger = shared
    executor = CoreCommandExecutor(connection)
    core = OperationalCoreService(orders)
    inq = _inquiry()
    executor.run(lambda: inquiries.save(inq))
    first = executor.run(lambda: seed_order(orders, inq))
    executor.run(lambda: core.cancel_order(first[0].order_id))
    second = executor.run(lambda: OrderService(orders).convert_inquiry_to_order(inq))
    assert second[0].order_id == first[0].order_id
    assert len(orders.list_orders()) == 1


def test_migration_6_aborts_on_existing_active_duplicates(tmp_path: Path) -> None:
    """Fail-closed pre-check: a database that already violates the invariant
    must refuse the migration for manual resolution."""
    db = tmp_path / "dup.db"
    conn = sqlite3.connect(db)
    from catering_system.repositories.sqlite_migrations import apply_migrations
    from catering_system.repositories.sqlite_order_repository import _MIGRATIONS

    apply_migrations(conn, "orders", _MIGRATIONS[:5])
    now = datetime.now(timezone.utc).isoformat()
    for order_id in ("o-1", "o-2"):
        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, NULL, NULL, NULL)",
            (order_id, "same-inquiry", now, now),
        )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="more than one non-cancelled order"):
        SQLiteOrderRepository(db)


def test_ledger_records_and_replays_minimal_results(shared) -> None:
    connection, _inquiries, _orders, ledger = shared
    executor = CoreCommandExecutor(connection)
    executor.run(lambda: ledger.record("cmd-9", "fp-9", 200, '{"order_id":"o"}'))
    recorded = ledger.get("cmd-9")
    assert recorded is not None
    assert recorded.result_status == 200
    assert recorded.fingerprint == "fp-9"
    assert ledger.get("missing") is None


def _valid_offer_snapshot(*, inquiry_id: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "offer_snapshot_v1",
        "source": "fingerfood-configurator-backend",
        "inquiry_id": inquiry_id,
        "snapshot_id": _SNAPSHOT_ID,
        "snapshot_created_at": "2026-07-15T08:30:00+00:00",
        "valid_until": "2026-07-29",
        "currency": "EUR",
        "recipient": {
            "company_name": "Example company",
            "contact_name": "Example contact",
            "email": "customer@example.invalid",
            "postal_address": "Customer-visible recipient address",
        },
        "event": {
            "event_date": "2026-08-20",
            "time_window_text": "18:00–22:00",
            "delivery_date_local": "2026-08-20",
            "delivery_window_start_local": "17:30",
            "delivery_window_end_local": "18:00",
            "event_start_local": "18:30",
            "location_text": "Hamburg",
            "guest_count": 80,
            "planning_mode": "caterer_suggestion",
        },
        "customer_text": {
            "title": "Sommerfest",
            "introduction": "Customer-visible introduction",
            "notes": "Customer-visible conditions and notes",
        },
        "payment_terms": {
            "method": "RECHNUNG",
            "customer_visible_text": "Zahlung per Rechnung",
        },
        "calculator": {
            "name": "fingerfood-backend",
            "calculator_revision": "future-revision",
            "catalog_revision": "future-revision",
            "tax_revision": "future-revision",
        },
        "variants": [
            {
                "variant_id": _VARIANT_ID,
                "label": "Variante A",
                "description": "Customer-visible alternative",
                "positions": [
                    {
                        "position_id": _POSITION_ID,
                        "kind": "catalog",
                        "name": "Fingerfood Paket",
                        "quantity_mode": "total",
                        "quantity": "80",
                        "unit_label": "Stück",
                        "unit_net_cents": 290,
                        "net_total_cents": 23200,
                        "vat_rate_percent": 7,
                        "vat_amount_cents": 1624,
                        "gross_total_cents": 24824,
                        "related_position_id": None,
                    }
                ],
                "totals": {
                    "net_cents": 23200,
                    "vat_7_base_cents": 23200,
                    "vat_7_amount_cents": 1624,
                    "vat_19_base_cents": 0,
                    "vat_19_amount_cents": 0,
                    "gross_cents": 24824,
                },
            }
        ],
    }
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def test_prepare_offer_write_and_ledger_commit_atomically(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        today=lambda: date(2026, 7, 15),
    )
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id)

    def work() -> str:
        offer = service.prepare_offer_version(inquiry.inquiry_id, snapshot)
        ledger.record(_PREPARE_CMD, "fp-prepare", 201, '{"offer_id":"x"}')
        return offer.offer_id

    offer_id = executor.run(work)
    assert offers.get(offer_id) is not None
    assert ledger.get(_PREPARE_CMD) is not None


def test_prepare_offer_save_failure_leaves_no_ledger(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        today=lambda: date(2026, 7, 15),
    )
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id)

    def failing_save(offer):  # noqa: ANN001
        raise sqlite3.IntegrityError("simulated offer save failure")

    offers.save = failing_save  # type: ignore[method-assign]

    def work() -> None:
        service.prepare_offer_version(inquiry.inquiry_id, snapshot)
        ledger.record(_PREPARE_CMD, "fp-prepare", 201, "{}")

    with pytest.raises(sqlite3.IntegrityError):
        executor.run(work)
    assert ledger.get(_PREPARE_CMD) is None
    assert offers.get_by_source_inquiry_id(inquiry.inquiry_id) is None


def test_prepare_offer_ledger_failure_rolls_back_offer(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        today=lambda: date(2026, 7, 15),
    )
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id)

    def work() -> None:
        service.prepare_offer_version(inquiry.inquiry_id, snapshot)
        raise RuntimeError("ledger path aborted before record")

    with pytest.raises(RuntimeError):
        executor.run(work)
    assert offers.get_by_source_inquiry_id(inquiry.inquiry_id) is None
    assert ledger.get(_PREPARE_CMD) is None


def test_record_sent_evidence_and_ledger_commit_atomically(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        today=lambda: date(2026, 7, 15),
    )
    offer = executor.run(
        lambda: service.prepare_offer_version(
            inquiry.inquiry_id,
            _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id),
        )
    )
    version_id = offer.versions[0].offer_version_id
    sent_cmd = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    def work() -> str:
        service.record_sent_evidence(
            offer.offer_id,
            version_id,
            sent_at=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
            channel="email",
            recipient_reference="customer@example.invalid",
            evidence_reference="mail-123",
            recorded_by="office-panel",
        )
        ledger.record(sent_cmd, "fp-sent", 200, '{"offer_id":"x"}')
        return version_id

    executor.run(work)
    stored = offers.get(offer.offer_id)
    assert stored is not None
    assert len(stored.sent_evidence) == 1
    assert ledger.get(sent_cmd) is not None


def test_record_sent_evidence_append_failure_leaves_no_ledger(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        today=lambda: date(2026, 7, 15),
    )
    offer = executor.run(
        lambda: service.prepare_offer_version(
            inquiry.inquiry_id,
            _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id),
        )
    )
    version_id = offer.versions[0].offer_version_id
    sent_cmd = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

    def failing_append(evidence):  # noqa: ANN001
        raise sqlite3.IntegrityError("simulated append failure")

    offers.append_sent_evidence = failing_append  # type: ignore[method-assign]

    def work() -> None:
        service.record_sent_evidence(
            offer.offer_id,
            version_id,
            sent_at=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
            channel="email",
            recipient_reference="customer@example.invalid",
            evidence_reference="mail-123",
            recorded_by="office-panel",
        )
        ledger.record(sent_cmd, "fp-sent", 200, "{}")

    with pytest.raises(sqlite3.IntegrityError):
        executor.run(work)
    assert ledger.get(sent_cmd) is None
    stored = offers.get(offer.offer_id)
    assert stored is not None
    assert stored.sent_evidence == ()


def test_record_acceptance_evidence_and_ledger_commit_atomically(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        today=lambda: date(2026, 7, 15),
    )
    offer = executor.run(
        lambda: service.prepare_offer_version(
            inquiry.inquiry_id,
            _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id),
        )
    )
    version_id = offer.versions[0].offer_version_id
    variant_id = offer.versions[0].variants[0].variant_id
    executor.run(
        lambda: service.record_sent_evidence(
            offer.offer_id,
            version_id,
            sent_at=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
            channel="email",
            recipient_reference="customer@example.invalid",
            evidence_reference="mail-123",
            recorded_by="office-panel",
        )
    )
    acceptance_cmd = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

    def work() -> str:
        service.record_acceptance_evidence(
            offer.offer_id,
            version_id,
            variant_id,
            accepted_at=datetime(2026, 7, 15, 11, 0, tzinfo=timezone.utc),
            channel="email",
            evidence_reference="reply-1",
            recorded_by="office-panel",
        )
        ledger.record(acceptance_cmd, "fp-accept", 200, '{"acceptance_id":"x"}')
        return version_id

    executor.run(work)
    stored = offers.get(offer.offer_id)
    assert stored is not None
    assert stored.acceptance_evidence is not None
    assert ledger.get(acceptance_cmd) is not None


def test_record_acceptance_evidence_append_failure_leaves_no_ledger(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        today=lambda: date(2026, 7, 15),
    )
    offer = executor.run(
        lambda: service.prepare_offer_version(
            inquiry.inquiry_id,
            _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id),
        )
    )
    version_id = offer.versions[0].offer_version_id
    variant_id = offer.versions[0].variants[0].variant_id
    executor.run(
        lambda: service.record_sent_evidence(
            offer.offer_id,
            version_id,
            sent_at=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
            channel="email",
            recipient_reference="customer@example.invalid",
            evidence_reference="mail-123",
            recorded_by="office-panel",
        )
    )
    acceptance_cmd = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

    def failing_append(evidence):  # noqa: ANN001
        raise sqlite3.IntegrityError("simulated append failure")

    offers.append_acceptance_evidence = failing_append  # type: ignore[method-assign]

    def work() -> None:
        service.record_acceptance_evidence(
            offer.offer_id,
            version_id,
            variant_id,
            accepted_at=datetime(2026, 7, 15, 11, 0, tzinfo=timezone.utc),
            channel="email",
            evidence_reference="reply-1",
            recorded_by="office-panel",
        )
        ledger.record(acceptance_cmd, "fp-accept", 200, "{}")

    with pytest.raises(sqlite3.IntegrityError):
        executor.run(work)
    assert ledger.get(acceptance_cmd) is None
    stored = offers.get(offer.offer_id)
    assert stored is not None
    assert stored.acceptance_evidence is None


def test_convert_accepted_offer_and_ledger_commit_atomically(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    snapshots = SQLiteOrderCommercialSnapshotRepository.from_connection(connection)
    reminders = SQLitePaymentReminderRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        snapshots,
        today=lambda: date(2026, 7, 15),
    )
    offer = executor.run(
        lambda: service.prepare_offer_version(
            inquiry.inquiry_id,
            _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id),
        )
    )
    version_id = offer.versions[0].offer_version_id
    variant_id = offer.versions[0].variants[0].variant_id
    executor.run(
        lambda: service.record_sent_evidence(
            offer.offer_id,
            version_id,
            sent_at=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
            channel="email",
            recipient_reference="customer@example.invalid",
            evidence_reference="mail-123",
            recorded_by="office-panel",
        )
    )
    acceptance_id = executor.run(
        lambda: (
            service.record_acceptance_evidence(
                offer.offer_id,
                version_id,
                variant_id,
                accepted_at=datetime(2026, 7, 15, 11, 0, tzinfo=timezone.utc),
                channel="email",
                evidence_reference="reply-1",
                recorded_by="office-panel",
            ).acceptance_evidence.acceptance_id
        )  # type: ignore[union-attr]
    )
    convert_cmd = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    payment_service = PaymentReminderService(reminders, orders)
    inquiry_service = InquiryService(inquiries)

    def work() -> str:
        converted, order, order_version = service.convert_accepted_offer(
            offer.offer_id,
            version_id,
            variant_id,
            acceptance_id,
        )
        commercial_version = next(
            item for item in converted.versions if item.offer_version_id == version_id
        )
        payment_service.seed_from_conversion(
            order.order_id, commercial_version.payment_method
        )
        inquiry_service.update_inquiry(
            inquiry.inquiry_id,
            crm_stage=ACTIVE_ORDER_CRM_STAGE,
        )
        ledger.record(
            convert_cmd,
            "fp-convert",
            201,
            json.dumps({"order_id": order.order_id}),
        )
        return order_version.order_version_id

    executor.run(work)
    stored = offers.get(offer.offer_id)
    assert stored is not None
    assert stored.conversion_link is not None
    assert ledger.get(convert_cmd) is not None
    assert reminders.get(stored.conversion_link.order_id) is not None
    assert inquiries.get_by_id(inquiry.inquiry_id).crm_stage == ACTIVE_ORDER_CRM_STAGE
    snapshot = snapshots.get_by_order_id(stored.conversion_link.order_id)
    assert snapshot is not None
    assert snapshot.source_offer_version_id == version_id
    assert snapshot.positions[0].name == "Fingerfood Paket"


def test_convert_accepted_offer_append_failure_leaves_no_ledger(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    snapshots = SQLiteOrderCommercialSnapshotRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        snapshots,
        today=lambda: date(2026, 7, 15),
    )
    offer = executor.run(
        lambda: service.prepare_offer_version(
            inquiry.inquiry_id,
            _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id),
        )
    )
    version_id = offer.versions[0].offer_version_id
    variant_id = offer.versions[0].variants[0].variant_id
    executor.run(
        lambda: service.record_sent_evidence(
            offer.offer_id,
            version_id,
            sent_at=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
            channel="email",
            recipient_reference="customer@example.invalid",
            evidence_reference="mail-123",
            recorded_by="office-panel",
        )
    )
    acceptance_id = executor.run(
        lambda: (
            service.record_acceptance_evidence(
                offer.offer_id,
                version_id,
                variant_id,
                accepted_at=datetime(2026, 7, 15, 11, 0, tzinfo=timezone.utc),
                channel="email",
                evidence_reference="reply-1",
                recorded_by="office-panel",
            ).acceptance_evidence.acceptance_id
        )  # type: ignore[union-attr]
    )
    convert_cmd = "10101010-1010-4101-8101-010101010101"

    def failing_append(link):  # noqa: ANN001
        raise sqlite3.IntegrityError("simulated append failure")

    offers.append_conversion_link = failing_append  # type: ignore[method-assign]

    def work() -> None:
        service.convert_accepted_offer(
            offer.offer_id,
            version_id,
            variant_id,
            acceptance_id,
        )
        ledger.record(convert_cmd, "fp-convert", 201, "{}")

    with pytest.raises(sqlite3.IntegrityError):
        executor.run(work)
    assert ledger.get(convert_cmd) is None
    stored = offers.get(offer.offer_id)
    assert stored is not None
    assert stored.conversion_link is None
    assert len(orders.list_orders()) == 0
    assert snapshots.get_by_order_id("any") is None
    rows = connection.execute(
        "SELECT COUNT(*) FROM order_commercial_snapshots"
    ).fetchone()
    assert rows is not None and rows[0] == 0


def test_convert_accepted_offer_crm_failure_rolls_back(shared) -> None:
    connection, inquiries, orders, ledger = shared
    offers = SQLiteOfferRepository.from_connection(connection)
    snapshots = SQLiteOrderCommercialSnapshotRepository.from_connection(connection)
    executor = CoreCommandExecutor(connection)
    inquiry = replace(_inquiry(), inquiry_id="22222222-2222-4222-8222-222222222222")
    executor.run(lambda: inquiries.save(inquiry))
    service = OfferService(
        offers,
        inquiries,
        orders,
        snapshots,
        today=lambda: date(2026, 7, 15),
    )
    offer = executor.run(
        lambda: service.prepare_offer_version(
            inquiry.inquiry_id,
            _valid_offer_snapshot(inquiry_id=inquiry.inquiry_id),
        )
    )
    version_id = offer.versions[0].offer_version_id
    variant_id = offer.versions[0].variants[0].variant_id
    executor.run(
        lambda: service.record_sent_evidence(
            offer.offer_id,
            version_id,
            sent_at=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
            channel="email",
            recipient_reference="customer@example.invalid",
            evidence_reference="mail-123",
            recorded_by="office-panel",
        )
    )
    acceptance_id = executor.run(
        lambda: (
            service.record_acceptance_evidence(
                offer.offer_id,
                version_id,
                variant_id,
                accepted_at=datetime(2026, 7, 15, 11, 0, tzinfo=timezone.utc),
                channel="email",
                evidence_reference="reply-1",
                recorded_by="office-panel",
            ).acceptance_evidence.acceptance_id
        )  # type: ignore[union-attr]
    )
    convert_cmd = "20202020-2020-4202-8202-020202020202"
    reminders = SQLitePaymentReminderRepository.from_connection(connection)
    payment_service = PaymentReminderService(reminders, orders)
    inquiry_service = InquiryService(inquiries)

    def failing_update(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("simulated CRM failure")

    inquiry_service.update_inquiry = failing_update  # type: ignore[method-assign]

    def work() -> None:
        converted, order, _ov = service.convert_accepted_offer(
            offer.offer_id,
            version_id,
            variant_id,
            acceptance_id,
        )
        commercial_version = next(
            item for item in converted.versions if item.offer_version_id == version_id
        )
        payment_service.seed_from_conversion(
            order.order_id, commercial_version.payment_method
        )
        inquiry_service.update_inquiry(
            inquiry.inquiry_id,
            crm_stage=ACTIVE_ORDER_CRM_STAGE,
        )
        ledger.record(convert_cmd, "fp-convert", 201, "{}")

    with pytest.raises(RuntimeError, match="simulated CRM failure"):
        executor.run(work)
    assert ledger.get(convert_cmd) is None
    stored = offers.get(offer.offer_id)
    assert stored is not None
    assert stored.conversion_link is None
    assert len(orders.list_orders()) == 0
    rows = connection.execute(
        "SELECT COUNT(*) FROM order_commercial_snapshots"
    ).fetchone()
    assert rows is not None and rows[0] == 0

"""Transaction coordination for the Core Office API
(PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §6.1, §6.2, §6.4)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from catering_system.domain.inquiry import (
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
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService


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
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
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
        order, _v1 = OrderService(orders).convert_inquiry_to_order(
            inquiries_service_input
        )
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
        OrderService(orders).convert_inquiry_to_order(saved)
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
        order, v1 = OrderService(orders).convert_inquiry_to_order(inq)
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


def test_second_active_order_for_same_inquiry_hits_the_index(shared) -> None:
    connection, inquiries, orders, _ledger = shared
    executor = CoreCommandExecutor(connection)
    inq = _inquiry()
    executor.run(lambda: inquiries.save(inq))
    executor.run(lambda: OrderService(orders).convert_inquiry_to_order(inq))
    with pytest.raises(sqlite3.IntegrityError):
        executor.run(lambda: OrderService(orders).convert_inquiry_to_order(inq))
    assert len([o for o in orders.list_orders() if o.cancelled_at is None]) == 1


def test_reconvert_after_storno_still_works(shared) -> None:
    connection, inquiries, orders, _ledger = shared
    executor = CoreCommandExecutor(connection)
    core = OperationalCoreService(orders)
    inq = _inquiry()
    executor.run(lambda: inquiries.save(inq))
    first = executor.run(lambda: OrderService(orders).convert_inquiry_to_order(inq))
    executor.run(lambda: core.cancel_order(first[0].order_id))
    second = executor.run(lambda: OrderService(orders).convert_inquiry_to_order(inq))
    assert second[0].order_id != first[0].order_id
    active = [o for o in orders.list_orders() if o.cancelled_at is None]
    assert [o.order_id for o in active] == [second[0].order_id]


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

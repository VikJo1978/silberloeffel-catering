"""Unit tests — SQLite repositories behind the existing Protocols (persistence adapter only)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    PLANNING_MODES,
    Inquiry,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)
from catering_system.domain.order_confirmation_document import (
    SCHEMA_VERSION_V3,
    OrderConfirmationDocumentSnapshot,
)
from catering_system.domain.order_operational_context import (
    OrderVersionOperationalContextSnapshot,
)
from catering_system.repositories.inquiry_repository import (
    DuplicateExternalReferenceError,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_migrations import apply_migrations
from catering_system.repositories.sqlite_order_confirmation_document_repository import (
    SQLiteOrderConfirmationDocumentRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.progression_service import ProgressionService
from tests.helpers.order_seed import seed_order

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    company_name="Müller GmbH",
    contact_name="Anna Müller",
    email="kunde@example.com",
    phone="+49301234567",
    invoice_address=CustomerAddress(
        street="Alter Wall 22",
        postal_code="20457",
        city="Hamburg",
        country="Deutschland",
    ),
    delivery_address_mode="SAME_AS_INVOICE",
)


def _sample_inquiry() -> Inquiry:
    now = datetime.now(UTC)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={"customer_id": "cust-1"},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
        intake_subject="Betreff",
        intake_message="Nachricht",
        intake_summary="Zusammenfassung",
        intake_external_ref="ref-1",
        customer_snapshot=_CONTACT_COMPLETE_SNAPSHOT,
    )


def _confirmation_snapshot(
    order_id: str,
    order_version_id: str,
    *,
    created_at: datetime,
) -> OrderConfirmationDocumentSnapshot:
    address = CustomerAddress(
        street="Backfill Straße 1",
        postal_code="20457",
        city="Hamburg",
        country="Deutschland",
    )
    return OrderConfirmationDocumentSnapshot(
        document_snapshot_id=f"doc-{order_version_id}",
        order_id=order_id,
        order_version_id=order_version_id,
        offer_id="offer-1",
        offer_version_id="offer-version-1",
        document_reference="AB-TEST-V1",
        created_at=created_at,
        created_by="office",
        recipient_name="Backfill Anna",
        recipient_email="backfill@example.invalid",
        recipient_company="Backfill GmbH",
        recipient_phone="+4940999",
        recipient_status="ready",
        event_date=date(2026, 10, 1),
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        positions=(),
        vat_buckets=(),
        net_total_cents=1000,
        vat_total_cents=190,
        gross_total_cents=1190,
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        document_hash="sha256:" + ("0" * 64),
        schema_version=SCHEMA_VERSION_V3,
        invoice_address=address,
        delivery_address=address,
        delivery_address_differs=False,
        fulfillment_mode="DELIVERY",
    )


def test_inquiry_roundtrip_preserves_all_fields(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    inquiry = _sample_inquiry()
    repo.save(inquiry)
    loaded = repo.get_by_id(inquiry.inquiry_id)
    assert loaded == inquiry  # incl. tz-aware datetimes, linkage dict, intake fields


def test_sqlite_inquiry_migration_from_pre_intake_context_schema(
    tmp_path: Path,
) -> None:
    """INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1 §4/§9 — same
    shape as test_storno.py::test_sqlite_roundtrip_and_pre_storno_migration:
    a pre-this-pack (13-column) inquiries table gets the four intake columns
    added in place, old rows load with None, and a fresh save/reopen
    round-trips the new fields correctly."""
    import json
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)  # simulate a pre-intake-context database
    conn.executescript(
        """
        CREATE TABLE inquiries (
            inquiry_id TEXT PRIMARY KEY, event_date TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            inquiry_source TEXT NOT NULL, crm_stage TEXT NOT NULL,
            customer_linkage TEXT NOT NULL, time_window_text TEXT NOT NULL,
            location_text TEXT NOT NULL, guest_count_estimate INTEGER,
            planning_mode TEXT NOT NULL, call_verification_required INTEGER NOT NULL,
            call_verification_status TEXT NOT NULL
        );
        """
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO inquiries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "pre-intake-id",
            "2026-10-01",
            now,
            now,
            "manual",
            CRM_PIPELINE[0],
            json.dumps({}),
            "mittags",
            "Hamburg",
            25,
            PLANNING_MODES[0],
            0,
            CALL_VERIFICATION_STATUSES[0],
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteInquiryRepository(db)  # migration runs here
    legacy = repo.get_by_id("pre-intake-id")
    assert legacy is not None
    assert legacy.intake_subject is None
    assert legacy.intake_message is None
    assert legacy.intake_summary is None
    assert legacy.intake_external_ref is None

    updated = replace(legacy, intake_subject="Nachträglich gesetzt")
    repo.update(updated)
    repo.close()

    repo2 = SQLiteInquiryRepository(db)
    reloaded = repo2.get_by_id("pre-intake-id")
    assert reloaded is not None
    assert reloaded.intake_subject == "Nachträglich gesetzt"


def test_inquiry_update_missing_raises(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    with pytest.raises(KeyError):
        repo.update(_sample_inquiry())


def test_inquiry_get_unknown_returns_none(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    assert repo.get_by_id("missing") is None


# -- find_by_source_and_external_ref (WEBSITE_FORM_INTAKE_IDEMPOTENCY_PACK_V1) --


def test_find_by_source_and_external_ref_matches(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    inquiry = replace(
        _sample_inquiry(), inquiry_source="website_form", intake_external_ref="web-42"
    )
    repo.save(inquiry)
    found = repo.find_by_source_and_external_ref("website_form", "web-42")
    assert found is not None
    assert found.inquiry_id == inquiry.inquiry_id


def test_find_by_source_and_external_ref_returns_none_when_source_differs(
    tmp_path: Path,
) -> None:
    """Same intake_external_ref value, different source — must not match
    (configurator's proposal_id and website_form's submission_id can
    coincidentally share a value; source-scoping prevents a false match)."""
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    inquiry = replace(
        _sample_inquiry(), inquiry_source="configurator", intake_external_ref="42"
    )
    repo.save(inquiry)
    assert repo.find_by_source_and_external_ref("website_form", "42") is None


def test_find_by_source_and_external_ref_returns_none_when_ref_differs(
    tmp_path: Path,
) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    inquiry = replace(
        _sample_inquiry(), inquiry_source="website_form", intake_external_ref="web-42"
    )
    repo.save(inquiry)
    assert (
        repo.find_by_source_and_external_ref("website_form", "does-not-exist") is None
    )


def test_find_by_source_and_external_ref_returns_none_when_ref_missing(
    tmp_path: Path,
) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    inquiry = replace(
        _sample_inquiry(), inquiry_source="website_form", intake_external_ref=None
    )
    repo.save(inquiry)
    assert repo.find_by_source_and_external_ref("website_form", "web-42") is None


def test_duplicate_website_external_ref_is_rejected_atomically(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    first = replace(
        _sample_inquiry(), inquiry_source="website_form", intake_external_ref="web-42"
    )
    duplicate = replace(first, inquiry_id="different-inquiry-id")
    repo.save(first)

    with pytest.raises(DuplicateExternalReferenceError):
        repo.save(duplicate)

    assert repo.list_all() == [first]


def test_same_configurator_external_ref_remains_allowed(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    first = replace(
        _sample_inquiry(),
        inquiry_source="configurator",
        intake_external_ref="proposal-1",
    )
    second = replace(first, inquiry_id="second-inquiry-id")
    repo.save(first)
    repo.save(second)
    assert len(repo.list_all()) == 2


def test_inquiry_save_does_not_overwrite_existing_id(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    first = _sample_inquiry()
    repo.save(first)

    with pytest.raises(sqlite3.IntegrityError):
        repo.save(replace(first, location_text="silently overwritten"))

    assert repo.get_by_id(first.inquiry_id) == first


def test_order_roundtrip_and_version_ordering(tmp_path: Path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    osvc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    v2 = osvc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Hamburg",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[0],
    )
    loaded_order = repo.get_order(order.order_id)
    assert loaded_order is not None
    assert loaded_order.order_id == order.order_id
    assert loaded_order.source_inquiry_id == order.source_inquiry_id
    rows = repo.list_order_versions(order.order_id)
    assert [v.version_number for v in rows] == [1, 2]
    assert rows[0] == v1
    assert rows[1] == v2


def test_order_operational_context_backfill_from_exact_confirmation_snapshot(
    tmp_path: Path,
) -> None:
    db = tmp_path / "test.db"
    orders = SQLiteOrderRepository(db)
    order, version = seed_order(orders, _sample_inquiry())
    confirmations = SQLiteOrderConfirmationDocumentRepository(db)
    confirmations.insert(
        _confirmation_snapshot(
            order.order_id,
            version.order_version_id,
            created_at=datetime.now(UTC),
        )
    )

    reopened = SQLiteOrderRepository(db)
    context = reopened.get_operational_context(version.order_version_id)
    assert context is not None
    assert context.recipient_company == "Backfill GmbH"
    assert context.recipient_name == "Backfill Anna"
    assert context.recipient_phone == "+4940999"
    assert context.delivery_address is not None
    assert context.delivery_address.street == "Backfill Straße 1"
    assert context.source == "confirmation_snapshot_backfill"

    reopened_again = SQLiteOrderRepository(db)
    assert reopened_again.get_operational_context(version.order_version_id) == context


def test_order_operational_context_backfill_requires_exact_version(
    tmp_path: Path,
) -> None:
    db = tmp_path / "test.db"
    orders = SQLiteOrderRepository(db)
    order, v1 = seed_order(orders, _sample_inquiry())
    v2 = OrderService(orders).create_relevant_order_change_version(
        order,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Hamburg",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[0],
    )
    confirmations = SQLiteOrderConfirmationDocumentRepository(db)
    confirmations.insert(
        _confirmation_snapshot(
            order.order_id,
            v1.order_version_id,
            created_at=datetime.now(UTC),
        )
    )

    reopened = SQLiteOrderRepository(db)
    assert reopened.get_operational_context(v1.order_version_id) is not None
    assert reopened.get_operational_context(v2.order_version_id) is None


def test_order_operational_context_snapshot_is_immutable(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    orders = SQLiteOrderRepository(db)
    order, version = seed_order(orders, _sample_inquiry())
    confirmations = SQLiteOrderConfirmationDocumentRepository(db)
    confirmations.insert(
        _confirmation_snapshot(
            order.order_id,
            version.order_version_id,
            created_at=datetime.now(UTC),
        )
    )
    orders.close()

    reopened = SQLiteOrderRepository(db)
    assert reopened.get_operational_context(version.order_version_id) is not None
    with pytest.raises(sqlite3.DatabaseError, match="operational context is immutable"):
        reopened._conn.execute(
            """
            UPDATE order_version_operational_context_snapshots
            SET recipient_name = ?
            WHERE order_version_id = ?
            """,
            ("Mutation", version.order_version_id),
        )
    with pytest.raises(sqlite3.DatabaseError, match="operational context is immutable"):
        reopened._conn.execute(
            """
            DELETE FROM order_version_operational_context_snapshots
            WHERE order_version_id = ?
            """,
            (version.order_version_id,),
        )


def test_initial_order_and_version_creation_rolls_back_together(tmp_path: Path) -> None:
    """A failed v1 insert must not leave an order without its initial version."""
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    existing_order, existing_v1 = seed_order(repo, _sample_inquiry())
    new_order = replace(
        existing_order,
        order_id="new-order",
        source_inquiry_id="22222222-2222-2222-2222-222222222222",
        candidate_order_version_id=None,
        effective_order_version_id=None,
    )
    colliding_v1 = replace(existing_v1, order_id=new_order.order_id)

    with pytest.raises(sqlite3.IntegrityError):
        repo.save_order_with_initial_version(new_order, colliding_v1)

    assert repo.get_order(new_order.order_id) is None
    assert repo.get_order_version(existing_v1.order_version_id) == existing_v1


def test_initial_operational_context_failure_rolls_back_order_version(
    tmp_path: Path,
) -> None:
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    existing_order, existing_v1 = seed_order(repo, _sample_inquiry())
    new_order = replace(
        existing_order,
        order_id="new-order",
        source_inquiry_id="33333333-3333-3333-3333-333333333333",
        candidate_order_version_id=None,
        effective_order_version_id=None,
    )
    new_v1 = replace(
        existing_v1,
        order_id=new_order.order_id,
        order_version_id="new-version",
    )
    bad_context = OrderVersionOperationalContextSnapshot(
        order_version_id=existing_v1.order_version_id,
        order_id=existing_order.order_id,
        recipient_company="Bad GmbH",
        recipient_name="Bad",
        recipient_phone="+490",
        delivery_address=None,
        created_at=datetime.now(UTC),
        source="explicit_change",
    )

    with pytest.raises(ValueError, match="operational context owner is invalid"):
        repo.save_order_with_initial_version(new_order, new_v1, bad_context)

    assert repo.get_order(new_order.order_id) is None
    assert repo.get_order_version(new_v1.order_version_id) is None
    assert repo.get_operational_context(new_v1.order_version_id) is None


def test_append_operational_context_failure_rolls_back_version_order_and_context(
    tmp_path: Path,
) -> None:
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    order, v1 = seed_order(repo, _sample_inquiry())
    updated_order = replace(
        order,
        updated_at=order.updated_at + timedelta(minutes=1),
        candidate_order_version_id="new-version",
    )
    new_v2 = replace(
        v1,
        order_version_id="new-version",
        version_number=2,
        parent_order_version_id=v1.order_version_id,
    )
    bad_context = OrderVersionOperationalContextSnapshot(
        order_version_id=v1.order_version_id,
        order_id=order.order_id,
        recipient_company="Bad GmbH",
        recipient_name="Bad",
        recipient_phone="+490",
        delivery_address=None,
        created_at=datetime.now(UTC),
        source="explicit_change",
    )

    with pytest.raises(ValueError, match="operational context owner is invalid"):
        repo.append_order_version(updated_order, new_v2, bad_context)

    assert repo.get_order(order.order_id) == order
    assert repo.get_order_version(new_v2.order_version_id) is None
    assert repo.get_operational_context(new_v2.order_version_id) is None


def test_initial_version_must_belong_to_order_and_be_v1(tmp_path: Path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    order, v1 = seed_order(repo, _sample_inquiry())
    invalid_order = replace(order, order_id="new-order")

    with pytest.raises(ValueError, match="must be v1 of the supplied order"):
        repo.save_order_with_initial_version(invalid_order, v1)

    assert repo.get_order(invalid_order.order_id) is None


def test_append_version_conflict_rolls_back_order_update(tmp_path: Path) -> None:
    """A duplicate version number must not leave updated aggregate metadata."""
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    order, v1 = seed_order(repo, _sample_inquiry())
    updated_order = replace(order, updated_at=order.updated_at + timedelta(minutes=1))
    duplicate_number = replace(v1, order_version_id="different-version-id")

    with pytest.raises(sqlite3.IntegrityError):
        repo.append_order_version(updated_order, duplicate_number)

    assert repo.get_order(order.order_id) == order
    assert repo.list_order_versions(order.order_id) == [v1]


def test_update_unknown_order_version_does_not_insert(tmp_path: Path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    _order, v1 = seed_order(repo, _sample_inquiry())
    missing = replace(v1, order_version_id="missing-version")

    with pytest.raises(KeyError):
        repo.update_order_version(missing)

    assert repo.get_order_version(missing.order_version_id) is None


def test_order_version_snapshot_fields_cannot_be_updated(tmp_path: Path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    order, v1 = seed_order(repo, _sample_inquiry())

    with pytest.raises(ValueError, match="snapshot is immutable"):
        repo.update_order_version(replace(v1, location_text="Andere Adresse"))

    stored = repo.get_order_version(v1.order_version_id)
    assert stored == v1
    confirmed = OperationalCoreService(repo).confirm_kitchen_print(
        order.order_id, v1.order_version_id
    )
    assert confirmed.kitchen_print_confirmed_at is not None
    with pytest.raises(ValueError, match="confirmation is immutable"):
        repo.update_order_version(replace(confirmed, kitchen_print_confirmed_at=None))


def test_order_update_missing_raises(tmp_path: Path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    OrderService(repo)
    order, _v1 = seed_order(repo, _sample_inquiry())
    ghost = order.__class__(
        order_id="missing",
        source_inquiry_id=order.source_inquiry_id,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )
    with pytest.raises(KeyError):
        repo.update_order(ghost)


def test_operational_core_flow_survives_reconnect(tmp_path: Path) -> None:
    """Kitchen print confirmation and effective switch persist across process restarts."""
    db = tmp_path / "test.db"
    repo = SQLiteOrderRepository(db)
    OrderService(repo)
    core = OperationalCoreService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    repo.close()

    repo2 = SQLiteOrderRepository(db)  # simulated restart
    core2 = OperationalCoreService(repo2)
    stored = repo2.get_order(order.order_id)
    assert stored is not None
    assert stored.effective_order_version_id == v1.order_version_id
    ver = repo2.get_order_version(v1.order_version_id)
    assert ver is not None and ver.kitchen_print_confirmed_at is not None
    ev = core2.evaluate_ready_to_send(order.order_id)
    assert ev.ready is True


def test_progression_chain_works_over_sqlite(tmp_path: Path) -> None:
    """B7–B27 derived reads run unchanged over the SQLite adapter (same Protocol)."""
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    osvc = OrderService(repo)
    prog = ProgressionService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    cp = prog.get_order_progression_checkpoint(order.order_id)
    assert cp is not None
    assert cp.blocked is False
    assert cp.candidate_order_version_id == v1.order_version_id


def test_component_migrations_are_recorded_once(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    SQLiteInquiryRepository(db).close()
    SQLiteOrderRepository(db).close()
    SQLiteInquiryRepository(db).close()
    SQLiteOrderRepository(db).close()

    connection = sqlite3.connect(db)
    rows = connection.execute(
        "SELECT component, version FROM schema_migrations ORDER BY component, version"
    ).fetchall()
    connection.close()
    assert rows == [
        ("inquiries", 1),
        ("inquiries", 2),
        ("inquiries", 3),
        ("inquiries", 4),
        ("inquiries", 5),  # CUSTOMER_ADDRESS_SOURCE_V1-A
        ("inquiries", 6),  # FULFILLMENT_SOURCE_V1: fulfillment_mode
        ("orders", 1),
        ("orders", 2),
        ("orders", 3),
        ("orders", 4),
        ("orders", 5),
        ("orders", 6),  # PROXMOX pack §6.2: unique active source inquiry
        ("orders", 7),  # immutable change provenance + snapshot guard
        ("orders", 8),  # frozen operational context per order version
        ("orders", 9),  # frozen fulfillment mode in operational context
    ]


def test_sqlite_rejects_orphan_order_version(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    repo = SQLiteOrderRepository(db)
    seed_order(repo, _sample_inquiry())
    repo.close()
    connection = sqlite3.connect(db)

    with pytest.raises(sqlite3.IntegrityError, match="owner does not exist"):
        connection.execute(
            "INSERT INTO order_versions "
            "(order_version_id, order_id, version_number, created_at, event_date, "
            "time_window_text, location_text, guest_count_estimate, planning_mode, "
            "kitchen_print_confirmed_at) "
            "SELECT 'orphan-version', 'missing-order', 2, created_at, event_date, "
            "time_window_text, location_text, guest_count_estimate, planning_mode, NULL "
            "FROM order_versions LIMIT 1"
        )
    connection.close()


def test_sqlite_rejects_unowned_order_reference(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    repo = SQLiteOrderRepository(db)
    order, _v1 = seed_order(repo, _sample_inquiry())
    repo.close()
    connection = sqlite3.connect(db)

    with pytest.raises(sqlite3.IntegrityError, match="reference is not owned"):
        connection.execute(
            "UPDATE orders SET candidate_order_version_id = ? WHERE order_id = ?",
            ("missing-version", order.order_id),
        )
    connection.close()


def test_sqlite_rejects_deleting_order_that_owns_versions(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    repo = SQLiteOrderRepository(db)
    order, _v1 = seed_order(repo, _sample_inquiry())
    repo.close()
    connection = sqlite3.connect(db)

    with pytest.raises(sqlite3.IntegrityError, match="still owns versions"):
        connection.execute("DELETE FROM orders WHERE order_id = ?", (order.order_id,))
    connection.close()


def test_sqlite_rejects_moving_referenced_version(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    repo = SQLiteOrderRepository(db)
    service = OrderService(repo)
    order, version = seed_order(repo, _sample_inquiry())
    service.set_candidate_order_version(order.order_id, version.order_version_id)
    other_order, _other_version = seed_order(
        repo, replace(_sample_inquiry(), inquiry_id="other-inquiry")
    )
    repo.close()
    connection = sqlite3.connect(db)

    with pytest.raises(sqlite3.IntegrityError, match="snapshot is immutable"):
        connection.execute(
            "UPDATE order_versions SET order_id = ? WHERE order_version_id = ?",
            (other_order.order_id, version.order_version_id),
        )
    connection.close()


def test_migration_failure_rolls_back_schema_and_history() -> None:
    connection = sqlite3.connect(":memory:")

    def fail_after_schema_change(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE must_rollback (id INTEGER)")
        raise RuntimeError("migration failed")

    with pytest.raises(RuntimeError, match="migration failed"):
        apply_migrations(
            connection, "test", ((1, "failure", fail_after_schema_change),)
        )

    assert connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE component = 'test'"
    ).fetchone() == (0,)
    assert (
        connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'must_rollback'"
        ).fetchone()
        is None
    )
    connection.close()


def test_migration_runner_rejects_incomplete_history() -> None:
    connection = sqlite3.connect(":memory:")
    migrations = (
        (1, "one", lambda conn: conn.execute("CREATE TABLE one (id INTEGER)")),
        (2, "two", lambda conn: conn.execute("CREATE TABLE two (id INTEGER)")),
    )
    apply_migrations(connection, "test", migrations)
    connection.execute(
        "DELETE FROM schema_migrations WHERE component = 'test' AND version = 1"
    )
    connection.commit()

    with pytest.raises(RuntimeError, match="incomplete.*history"):
        apply_migrations(connection, "test", migrations)
    connection.close()


def test_migration_runner_rejects_changed_migration_name() -> None:
    connection = sqlite3.connect(":memory:")
    migration = ((1, "original", lambda _conn: None),)
    apply_migrations(connection, "test", migration)
    connection.execute(
        "UPDATE schema_migrations SET name = 'tampered' WHERE component = 'test'"
    )
    connection.commit()

    with pytest.raises(RuntimeError, match="name mismatch"):
        apply_migrations(connection, "test", migration)
    connection.close()

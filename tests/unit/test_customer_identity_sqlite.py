"""SQLite tests for customer identity foundation."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from catering_system.domain.customer_identity import CustomerIdentity, PhoneContactPoint
from catering_system.repositories.sqlite_customer_identity_repository import (
    SQLiteCustomerIdentityRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.repositories.sqlite_phone_contact_point_repository import (
    SQLitePhoneContactPointRepository,
)

PHONE_A = "+491700000099"


def _now() -> datetime:
    return datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _customer(customer_id: str, *, status: str = "active") -> CustomerIdentity:
    return CustomerIdentity(
        customer_id=customer_id,
        display_name="Synthetic Customer",
        company_name=None,
        status=status,  # type: ignore[arg-type]
        created_at=_now(),
        updated_at=_now(),
    )


def _phone(
    phone_id: str, customer_id: str, *, status: str = "active"
) -> PhoneContactPoint:
    return PhoneContactPoint(
        phone_contact_point_id=phone_id,
        customer_id=customer_id,
        normalized_phone=PHONE_A,
        display_phone="0170/0000099",
        status=status,  # type: ignore[arg-type]
        created_at=_now(),
        updated_at=_now(),
    )


def _open_repos(
    tmp_path: Path,
) -> tuple[
    SQLiteCustomerIdentityRepository,
    SQLitePhoneContactPointRepository,
]:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    return customers, phones


def test_schema_created_on_new_db(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    customers.close()
    phones.close()
    connection = sqlite3.connect(db)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "customer_identities" in tables
    assert "phone_contact_points" in tables
    connection.close()


def test_schema_initialization_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    first = SQLiteCustomerIdentityRepository(db)
    second = SQLitePhoneContactPointRepository(db)
    first.close()
    second.close()
    SQLiteCustomerIdentityRepository(db).close()
    SQLitePhoneContactPointRepository(db).close()


def test_customer_identity_round_trip(tmp_path: Path) -> None:
    customers, _phones = _open_repos(tmp_path)
    identity = _customer("cust-1")
    customers.add(identity)
    loaded = customers.get_by_id("cust-1")
    assert loaded == identity
    customers.close()


def test_phone_contact_point_round_trip(tmp_path: Path) -> None:
    customers, phones = _open_repos(tmp_path)
    identity = _customer("cust-1")
    customers.add(identity)
    point = _phone("phone-1", identity.customer_id)
    phones.add(point)
    assert phones.get_by_id("phone-1") == point
    assert phones.list_by_customer_id("cust-1") == [point]
    customers.close()
    phones.close()


def test_exact_lookup_and_inactive_excluded(tmp_path: Path) -> None:
    customers, phones = _open_repos(tmp_path)
    identity = _customer("cust-1")
    customers.add(identity)
    phones.add(_phone("phone-active", identity.customer_id))
    phones.add(_phone("phone-inactive", identity.customer_id, status="inactive"))
    assert len(phones.find_active_by_normalized_phone(PHONE_A)) == 1
    customers.close()
    phones.close()


def test_ambiguous_candidates_preserved(tmp_path: Path) -> None:
    customers, phones = _open_repos(tmp_path)
    first = _customer("cust-1")
    second = _customer("cust-2")
    customers.add(first)
    customers.add(second)
    phones.add(_phone("phone-1", first.customer_id))
    phones.add(_phone("phone-2", second.customer_id))
    matches = phones.find_active_by_normalized_phone(PHONE_A)
    assert {point.phone_contact_point_id for point in matches} == {"phone-1", "phone-2"}
    customers.close()
    phones.close()


def test_merged_customer_excluded_from_active_lookup(tmp_path: Path) -> None:
    customers, phones = _open_repos(tmp_path)
    identity = _customer("cust-1", status="merged")
    customers.add(identity)
    phones.add(_phone("phone-1", identity.customer_id))
    assert phones.find_active_by_normalized_phone(PHONE_A) == []
    customers.close()
    phones.close()


def test_fk_enforcement_and_immutable_customer_id(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    with pytest.raises(sqlite3.IntegrityError, match="owner does not exist"):
        phones.add(_phone("phone-1", "missing-customer"))
    identity = _customer("cust-1")
    customers.add(identity)
    phones.add(_phone("phone-1", identity.customer_id))
    customers.close()
    phones.close()
    connection = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError, match="customer_id is immutable"):
        connection.execute(
            "UPDATE phone_contact_points SET customer_id = ? WHERE phone_contact_point_id = ?",
            ("other-customer", "phone-1"),
        )
    connection.close()


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    customers, phones = _open_repos(tmp_path)
    identity = _customer("cust-1")
    customers.add(identity)
    with pytest.raises(sqlite3.IntegrityError):
        customers.add(replace(identity, display_name="Duplicate"))
    phones.add(_phone("phone-1", identity.customer_id))
    with pytest.raises(sqlite3.IntegrityError):
        phones.add(replace(_phone("phone-1", identity.customer_id), display_phone="x"))
    customers.close()
    phones.close()


def test_persistence_after_reopen(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    identity = _customer("cust-1")
    customers.add(identity)
    phones.add(_phone("phone-1", identity.customer_id))
    customers.close()
    phones.close()

    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    assert customers.get_by_id("cust-1") == identity
    assert (
        phones.find_active_by_normalized_phone(PHONE_A)[0].phone_contact_point_id
        == "phone-1"
    )
    customers.close()
    phones.close()


def test_existing_inquiry_and_order_repositories_still_work(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    inquiries = SQLiteInquiryRepository(db)
    orders = SQLiteOrderRepository(db)
    assert inquiries.list_all() == []
    assert orders.list_orders() == []
    customers.close()
    phones.close()
    inquiries.close()
    orders.close()


def test_sqlite_update_missing_customer_raises(tmp_path: Path) -> None:
    customers, _phones = _open_repos(tmp_path)
    with pytest.raises(KeyError):
        customers.update(_customer("missing"))
    customers.close()


def test_sqlite_customer_update_preserves_created_at(tmp_path: Path) -> None:
    customers, _phones = _open_repos(tmp_path)
    created = _now()
    identity = replace(_customer("cust-1"), created_at=created, updated_at=created)
    customers.add(identity)
    later = created.replace(hour=created.hour + 2)
    customers.update(replace(identity, display_name="Updated", updated_at=later))
    loaded = customers.get_by_id("cust-1")
    assert loaded is not None
    assert loaded.created_at == created
    assert loaded.updated_at == later
    customers.close()

"""Schema bootstrap and SQLite contract tests for customer identity foundation."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from catering_system.domain.customer_identity import CustomerIdentity, PhoneContactPoint
from catering_system.repositories.bootstrap_customer_identity_schema import (
    bootstrap_customer_identity_schema,
)
from catering_system.repositories.sqlite_customer_identity_repository import (
    SQLiteCustomerIdentityRepository,
)
from catering_system.repositories.sqlite_phone_contact_point_repository import (
    SQLitePhoneContactPointRepository,
)

PHONE = "+491700000099"


def _now() -> datetime:
    return datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _customer(
    customer_id: str = "cust-1", *, status: str = "active"
) -> CustomerIdentity:
    return CustomerIdentity(
        customer_id=customer_id,
        display_name="Synthetic Customer",
        company_name=None,
        status=status,  # type: ignore[arg-type]
        created_at=_now(),
        updated_at=_now(),
    )


def _phone(
    phone_id: str = "phone-1",
    customer_id: str = "cust-1",
    *,
    status: str = "active",
) -> PhoneContactPoint:
    return PhoneContactPoint(
        phone_contact_point_id=phone_id,
        customer_id=customer_id,
        normalized_phone=PHONE,
        display_phone=None,
        status=status,  # type: ignore[arg-type]
        created_at=_now(),
        updated_at=_now(),
    )


def test_bootstrap_helper_applies_both_components(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    connection = sqlite3.connect(db)
    bootstrap_customer_identity_schema(connection)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"customer_identities", "phone_contact_points"}.issubset(tables)
    connection.close()


def test_repeated_bootstrap_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    connection = sqlite3.connect(db)
    bootstrap_customer_identity_schema(connection)
    bootstrap_customer_identity_schema(connection)
    connection.close()


def test_concurrent_bootstrap_leaves_complete_schema(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            connection = sqlite3.connect(db, timeout=30.0)
            bootstrap_customer_identity_schema(connection)
            connection.close()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    connection = sqlite3.connect(db)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    connection.close()
    assert {"customer_identities", "phone_contact_points"}.issubset(tables)
    assert errors == []


def test_foreign_keys_enabled_and_enforced_after_reopen(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    with pytest.raises(sqlite3.IntegrityError, match="owner does not exist"):
        phones.add(_phone())
    customers.close()
    phones.close()

    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    customers.add(_customer())
    phones.add(_phone())
    customers.close()
    phones.close()


def test_update_preserves_created_at_and_changes_updated_at(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    created = _now()
    updated_at = created
    identity = CustomerIdentity(
        customer_id="cust-1",
        display_name="Before",
        company_name=None,
        status="active",
        created_at=created,
        updated_at=updated_at,
    )
    customers.add(identity)
    later = created.replace(hour=created.hour + 1)
    customers.update(
        replace(identity, display_name="After", updated_at=later, created_at=later)
    )
    loaded = customers.get_by_id("cust-1")
    assert loaded is not None
    assert loaded.created_at == created
    assert loaded.updated_at == later
    assert loaded.display_name == "After"
    customers.close()


def test_invalid_status_rejected_on_load(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    customers.add(_customer())
    customers.close()
    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE customer_identities SET status = ? WHERE customer_id = ?",
        ("not-a-status", "cust-1"),
    )
    connection.commit()
    connection.close()
    customers = SQLiteCustomerIdentityRepository(db)
    with pytest.raises(ValueError, match="customer identity status"):
        customers.get_by_id("cust-1")
    customers.close()


def test_inactive_customer_excluded_from_active_lookup(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    customers.add(_customer(status="inactive"))
    phones.add(_phone())
    assert phones.find_active_by_normalized_phone(PHONE) == []
    customers.close()
    phones.close()


def test_ambiguous_matches_have_deterministic_order(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    customers = SQLiteCustomerIdentityRepository(db)
    phones = SQLitePhoneContactPointRepository(db)
    earlier = _now().replace(hour=10)
    later = _now().replace(hour=11)
    customers.add(_customer("cust-1"))
    customers.add(replace(_customer("cust-2"), display_name="Second"))
    phones.add(
        replace(
            _phone("phone-late", "cust-2"),
            created_at=later,
            updated_at=later,
        )
    )
    phones.add(
        replace(
            _phone("phone-early", "cust-1"),
            created_at=earlier,
            updated_at=earlier,
        )
    )
    ordered = phones.find_active_by_normalized_phone(PHONE)
    assert [point.phone_contact_point_id for point in ordered] == [
        "phone-early",
        "phone-late",
    ]
    customers.close()
    phones.close()


def test_office_api_bootstrap_applies_foundation_schema(tmp_path: Path) -> None:
    from catering_system.domain.offer_pdf import OfferPdfStaticContent
    from catering_system.repositories.core_transaction import open_core_connection
    from catering_system.ui.office_api import OfficeApi

    db = tmp_path / "core.db"
    OfficeApi(
        open_core_connection(db),
        offer_pdf_static_content=OfferPdfStaticContent(
            company_legal_name="TEST GmbH [PLATZHALTER]",
            company_address_lines=("Teststraße 1", "20095 Hamburg"),
            acceptance_statement="[TEST PLACEHOLDER — NOT APPROVED CUSTOMER WORDING]",
        ),
    )
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

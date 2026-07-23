"""CUSTOMER_ADDRESS_SOURCE_V1-A — snapshot addresses + CDP mode wiring."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerAddress,
    customer_addresses_equal,
)
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot,
    customer_snapshot_from_mapping,
    customer_snapshot_to_mapping,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_migrations import apply_migrations
from catering_system.services.customer_document_projection import (
    build_customer_document_recipient,
)

_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
_INVOICE = CustomerAddress(
    street="Bürostraße 1",
    postal_code="20095",
    city="Hamburg",
    country="DE",
)
_DELIVERY = CustomerAddress(
    street="Eventplatz 9",
    postal_code="20457",
    city="Hamburg",
    country="DE",
)


def _inquiry(snapshot: InquiryCustomerSnapshot | None) -> Inquiry:
    return Inquiry(
        inquiry_id="99999999-9999-4999-8999-999999999999",
        event_date=date(2026, 8, 20),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        created_at=_NOW,
        updated_at=_NOW,
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        customer_snapshot=snapshot,
    )


def test_same_as_invoice_rejects_stored_delivery() -> None:
    with pytest.raises(ValueError, match="delivery_address must be None"):
        InquiryCustomerSnapshot(
            contact_name="Anna",
            invoice_address=_INVOICE,
            delivery_address=_DELIVERY,
            delivery_address_mode="SAME_AS_INVOICE",
        )


def test_separate_requires_delivery() -> None:
    with pytest.raises(ValueError, match="SEPARATE mode requires delivery_address"):
        InquiryCustomerSnapshot(
            contact_name="Anna",
            invoice_address=_INVOICE,
            delivery_address_mode="SEPARATE",
        )


def test_mapping_round_trip_with_addresses() -> None:
    snapshot = InquiryCustomerSnapshot(
        contact_name="Anna",
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    mapped = customer_snapshot_to_mapping(snapshot)
    assert mapped is not None
    assert mapped["delivery_address_mode"] == "SEPARATE"
    assert customer_snapshot_from_mapping(mapped) == snapshot


def test_direct_and_remote_mapping_shape_parity() -> None:
    """Office API mapping and RemoteCoreClient share customer_snapshot_from_mapping."""
    snapshot = InquiryCustomerSnapshot(
        company_name="ACME",
        contact_name="Anna",
        email="anna@example.invalid",
        phone="+49301234567",
        invoice_address=_INVOICE,
        delivery_address=None,
        delivery_address_mode="SAME_AS_INVOICE",
    )
    direct = customer_snapshot_to_mapping(snapshot)
    assert direct is not None
    assert set(direct) == {
        "company_name",
        "contact_name",
        "email",
        "phone",
        "invoice_address",
        "delivery_address",
        "delivery_address_mode",
    }
    assert direct["delivery_address"] is None
    assert direct["delivery_address_mode"] == "SAME_AS_INVOICE"
    remote_parsed = customer_snapshot_from_mapping(direct)
    assert remote_parsed == snapshot
    assert customer_snapshot_to_mapping(remote_parsed) == direct


def test_recipient_unknown_does_not_copy_invoice() -> None:
    recipient = build_customer_document_recipient(
        _inquiry(
            InquiryCustomerSnapshot(
                contact_name="Anna",
                invoice_address=_INVOICE,
                delivery_address_mode="UNKNOWN",
            )
        )
    )
    assert recipient.invoice_address == _INVOICE
    assert recipient.delivery_address is None
    assert recipient.warnings == ()


def test_recipient_same_as_invoice_uses_effective_delivery() -> None:
    recipient = build_customer_document_recipient(
        _inquiry(
            InquiryCustomerSnapshot(
                contact_name="Anna",
                invoice_address=_INVOICE,
                delivery_address_mode="SAME_AS_INVOICE",
            )
        )
    )
    assert recipient.invoice_address == _INVOICE
    assert recipient.delivery_address == _INVOICE
    assert recipient.delivery_address_differs is False
    assert recipient.warnings == ()


def test_recipient_separate_equal_normalized_no_warning() -> None:
    noisy = CustomerAddress(
        street="  Bürostraße   1 ",
        postal_code="20095",
        city="hamburg",
        country="de",
    )
    assert customer_addresses_equal(_INVOICE, noisy)
    recipient = build_customer_document_recipient(
        _inquiry(
            InquiryCustomerSnapshot(
                contact_name="Anna",
                invoice_address=_INVOICE,
                delivery_address=noisy,
                delivery_address_mode="SEPARATE",
            )
        )
    )
    assert recipient.delivery_address_differs is False
    assert recipient.warnings == ()


def test_recipient_separate_differing_emits_warning() -> None:
    recipient = build_customer_document_recipient(
        _inquiry(
            InquiryCustomerSnapshot(
                contact_name="Anna",
                invoice_address=_INVOICE,
                delivery_address=_DELIVERY,
                delivery_address_mode="SEPARATE",
            )
        )
    )
    assert recipient.delivery_address_differs is True
    assert WARNING_DELIVERY_ADDRESS_DIFFERS in recipient.warnings


def test_sqlite_legacy_row_loads_unknown_mode(tmp_path) -> None:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    # Apply only migrations 1–4, insert contact snapshot, then run migration 5.
    from catering_system.repositories import sqlite_inquiry_repository as repo_mod

    apply_migrations(conn, "inquiries", repo_mod._MIGRATIONS[:4])
    conn.execute(
        "INSERT INTO inquiries ("
        "inquiry_id, event_date, created_at, updated_at, inquiry_source, crm_stage, "
        "customer_linkage, time_window_text, location_text, guest_count_estimate, "
        "planning_mode, call_verification_required, call_verification_status, "
        "intake_subject, intake_message, intake_summary, intake_external_ref, "
        "customer_id, snapshot_company_name, snapshot_contact_name, snapshot_email, "
        "snapshot_phone"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "99999999-9999-4999-8999-999999999999",
            "2026-08-20",
            _NOW.isoformat(),
            _NOW.isoformat(),
            "manual",
            "Neue Anfrage",
            "{}",
            "mittags",
            "Hamburg",
            25,
            "caterer_suggestion",
            0,
            "not_required",
            None,
            None,
            None,
            None,
            None,
            "Example GmbH",
            "Example Contact",
            "kunde@example.com",
            "+49301234567",
        ),
    )
    conn.commit()
    apply_migrations(conn, "inquiries", repo_mod._MIGRATIONS)
    conn.close()

    inquiries = SQLiteInquiryRepository(db)
    loaded = inquiries.get_by_id("99999999-9999-4999-8999-999999999999")
    assert loaded is not None
    assert loaded.customer_snapshot is not None
    assert loaded.customer_snapshot.delivery_address_mode == "UNKNOWN"
    assert loaded.customer_snapshot.invoice_address is None
    assert loaded.customer_snapshot.delivery_address is None
    inquiries.close()


def test_sqlite_round_trip_addresses(tmp_path) -> None:
    db = tmp_path / "core.db"
    inquiries = SQLiteInquiryRepository(db)
    snapshot = InquiryCustomerSnapshot(
        company_name="ACME",
        contact_name="Anna",
        email="anna@example.invalid",
        phone="+49301234567",
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    inquiry = _inquiry(snapshot)
    inquiries.save(inquiry)
    loaded = inquiries.get_by_id(inquiry.inquiry_id)
    assert loaded is not None
    assert loaded.customer_snapshot == snapshot
    mapped = customer_snapshot_to_mapping(loaded.customer_snapshot)
    assert mapped is not None
    assert (
        json.loads(json.dumps(mapped["invoice_address"]))
        == customer_snapshot_to_mapping(snapshot)["invoice_address"]
    )
    inquiries.close()

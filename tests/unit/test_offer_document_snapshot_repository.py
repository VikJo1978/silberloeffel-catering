"""OFFER_DOCUMENT_SNAPSHOT_V1 — SQLite repository, owner trigger, immutability.

Uses two SQLiteOfferRepository/SQLiteOfferDocumentSnapshotRepository
instances against the same file so the owner trigger's EXISTS check against
the real ``offer_variants`` table is exercised, not a fake.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_offer_document_snapshot_repository import (
    _MIGRATIONS,
    SQLiteOfferDocumentSnapshotRepository,
)
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from catering_system.services.offer_document_snapshot_service import (
    OfferDocumentSnapshotService,
)
from catering_system.services.offer_service import OfferService
from tests.unit.test_offer_service import _INQUIRY_ID, _sample_inquiry, _valid_snapshot

_INVOICE = CustomerAddress(
    street="Bürostraße 1", postal_code="20095", city="Hamburg", country="DE"
)


def _prepared_offer(db: Path):
    """Real SQLite-backed Offer with one Prepared version + variant, plus a
    complete DELIVERY-eligible Inquiry — shared setup for the tests below."""
    offers = SQLiteOfferRepository(db)
    inquiries_repo = InMemoryInquiryRepository()  # Inquiry stays in-memory;
    # only Offer/OfferVersion/OfferVariant need to be real SQLite rows for
    # the owner trigger to validate against.
    snapshot = InquiryCustomerSnapshot(
        company_name="ACME GmbH",
        contact_name="Anna",
        email="anna@example.invalid",
        phone="+49301234567",
        invoice_address=_INVOICE,
        delivery_address=None,
        delivery_address_mode="SAME_AS_INVOICE",
    )
    inquiry = replace(
        _sample_inquiry(), customer_snapshot=snapshot, fulfillment_mode="DELIVERY"
    )
    inquiries_repo.save(inquiry)
    offer_service = OfferService(offers, inquiries_repo, InMemoryOrderRepository())
    offer = offer_service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    offers.close()
    return offer, inquiries_repo


def test_prepare_offer_document_persists_and_reloads(tmp_path: Path) -> None:
    db = tmp_path / "offer.db"
    offer, inquiries_repo = _prepared_offer(db)
    version = offer.versions[0]

    documents = SQLiteOfferDocumentSnapshotRepository(db)
    offers = SQLiteOfferRepository(db)
    doc_service = OfferDocumentSnapshotService(offers, inquiries_repo, documents)
    snap = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    documents.close()
    offers.close()

    documents2 = SQLiteOfferDocumentSnapshotRepository(db)
    reloaded = documents2.get_by_offer_version_id(version.offer_version_id)
    assert reloaded is not None
    assert reloaded.offer_document_snapshot_id == snap.offer_document_snapshot_id
    assert reloaded.document_hash == snap.document_hash
    documents2.close()


def test_owner_trigger_rejects_row_with_no_matching_offer_variant(
    tmp_path: Path,
) -> None:
    db = tmp_path / "offer.db"
    _prepared_offer(db)  # ensures the offers schema exists in this file
    documents = SQLiteOfferDocumentSnapshotRepository(db)
    conn = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError, match="owner is invalid"):
        conn.execute(
            "INSERT INTO offer_document_snapshots ("
            "offer_document_snapshot_id, offer_id, offer_version_id, "
            "offer_variant_id, document_reference, schema_version, "
            "canonical_snapshot_json, document_hash, created_at, created_by"
            ") VALUES ('s1','no-such-offer','no-such-version','no-such-variant',"
            "'ANG-DEADBEEF-V1',1,'{}','sha256:"
            + "0" * 64
            + "','2026-01-01T00:00:00+00:00','office')"
        )
        conn.commit()
    conn.close()
    documents.close()


def test_immutable_update_and_delete_are_rejected(tmp_path: Path) -> None:
    db = tmp_path / "offer.db"
    offer, inquiries_repo = _prepared_offer(db)
    version = offer.versions[0]
    offers = SQLiteOfferRepository(db)
    documents = SQLiteOfferDocumentSnapshotRepository(db)
    doc_service = OfferDocumentSnapshotService(offers, inquiries_repo, documents)
    snap = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        documents._conn.execute(  # noqa: SLF001
            "UPDATE offer_document_snapshots SET created_by = 'someone-else' "
            "WHERE offer_document_snapshot_id = ?",
            (snap.offer_document_snapshot_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        documents._conn.execute(  # noqa: SLF001
            "DELETE FROM offer_document_snapshots WHERE offer_document_snapshot_id = ?",
            (snap.offer_document_snapshot_id,),
        )
    offers.close()
    documents.close()


def test_unique_offer_version_id_enforced_at_db_layer(tmp_path: Path) -> None:
    db = tmp_path / "offer.db"
    offer, inquiries_repo = _prepared_offer(db)
    version = offer.versions[0]
    offers = SQLiteOfferRepository(db)
    documents = SQLiteOfferDocumentSnapshotRepository(db)
    doc_service = OfferDocumentSnapshotService(offers, inquiries_repo, documents)
    doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    # Bypass the service's idempotency check to prove the DB itself refuses
    # a second row for the same offer_version_id.
    from catering_system.services.offer_document_snapshot_serialization import (
        snapshot_to_canonical_json,
    )

    existing = documents.get_by_offer_version_id(version.offer_version_id)
    duplicate = replace(existing, offer_document_snapshot_id="a-different-id")
    with pytest.raises(sqlite3.IntegrityError):
        documents._conn.execute(  # noqa: SLF001
            "INSERT INTO offer_document_snapshots ("
            "offer_document_snapshot_id, offer_id, offer_version_id, "
            "offer_variant_id, document_reference, schema_version, "
            "canonical_snapshot_json, document_hash, created_at, created_by"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                duplicate.offer_document_snapshot_id,
                duplicate.offer_id,
                duplicate.offer_version_id,
                duplicate.offer_variant_id,
                duplicate.document_reference,
                duplicate.schema_version,
                snapshot_to_canonical_json(duplicate),
                duplicate.document_hash,
                duplicate.created_at.isoformat(),
                duplicate.created_by,
            ),
        )
    offers.close()
    documents.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    from catering_system.repositories.sqlite_migrations import apply_migrations

    db = tmp_path / "offer_documents.db"
    conn = sqlite3.connect(db)
    apply_migrations(conn, "offer_document_snapshots", _MIGRATIONS)
    apply_migrations(conn, "offer_document_snapshots", _MIGRATIONS)
    rows = conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE component = "
        "'offer_document_snapshots'"
    ).fetchone()
    assert rows == (1,)
    conn.close()


def test_unrelated_offer_data_and_hashes_unchanged_after_snapshot_table_exists(
    tmp_path: Path,
) -> None:
    db = tmp_path / "offer.db"
    offer, inquiries_repo = _prepared_offer(db)
    original_version = offer.versions[0]
    # Creating the sibling table/migration must not touch existing Offer rows.
    SQLiteOfferDocumentSnapshotRepository(db).close()
    offers = SQLiteOfferRepository(db)
    reloaded_offer = offers.get(offer.offer_id)
    offers.close()
    assert reloaded_offer.versions[0].snapshot_hash == original_version.snapshot_hash
    assert reloaded_offer.versions[0].customer_title == original_version.customer_title

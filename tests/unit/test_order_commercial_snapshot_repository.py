"""Persistence tests — OrderCommercialSnapshot repositories (PR A)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from catering_system.domain.inquiry import Inquiry
from catering_system.domain.offer import (
    AcceptanceEvidence,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    SentEvidence,
)
from catering_system.domain.order_commercial_snapshot import (
    build_order_commercial_snapshot,
)
from catering_system.repositories.core_transaction import open_core_connection
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from tests.helpers.order_seed import seed_order

_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_INQUIRY_ID = "22222222-2222-4222-8222-222222222222"
_VERSION_ID = "33333333-3333-4333-8333-333333333331"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "55555555-5555-4555-8555-555555555551"
_ACCEPTANCE_ID = "66666666-6666-4666-8666-666666666661"
_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _inquiry() -> Inquiry:
    return Inquiry(
        inquiry_id=_INQUIRY_ID,
        event_date=date(2026, 8, 20),
        created_at=_NOW,
        updated_at=_NOW,
        inquiry_source="manual",
        crm_stage="Angebot gesendet / Rückmeldung offen",
        customer_linkage={},
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )


def _snapshot(
    *,
    order_id: str,
    snapshot_id: str = "99999999-9999-4999-8999-999999999991",
    name: str = "Fingerfood Paket",
):
    position = OfferPosition(
        position_id=_POSITION_ID,
        kind="catalog",
        name=name,
        unit_net_cents=290,
        net_total_cents=23200,
        vat_rate_percent=7,
        vat_amount_cents=1624,
        gross_total_cents=24824,
        description="Frozen description",
        composition="Frozen composition",
        notes="Frozen notes",
        quantity=Decimal("80"),
        quantity_mode="total",
        unit_label="Stück",
        catalog_item_id="catalog-1",
        allergens=("A", "C"),
    )
    variant = OfferVariant(
        variant_id=_VARIANT_ID,
        offer_version_id=_VERSION_ID,
        label="Variante A",
        description="Customer-visible alternative",
        positions=(position,),
    )
    version = OfferVersion(
        offer_version_id=_VERSION_ID,
        offer_id=_OFFER_ID,
        version_number=1,
        created_at=_NOW,
        valid_until=date(2026, 7, 29),
        snapshot_id="77777777-7777-4777-8777-777777777771",
        snapshot_hash="sha256:" + ("a" * 64),
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count=80,
        planning_mode="caterer_suggestion",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        variants=(variant,),
    )
    acceptance = AcceptanceEvidence(
        acceptance_id=_ACCEPTANCE_ID,
        offer_id=_OFFER_ID,
        accepted_offer_version_id=_VERSION_ID,
        accepted_variant_id=_VARIANT_ID,
        accepted_at=_NOW,
        recorded_at=_NOW,
        channel="email",
        evidence_reference="reply-1",
        recorded_by="office-panel",
    )
    sent = SentEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_VERSION_ID,
        sent_at=_NOW,
        recorded_at=_NOW,
        channel="email",
        recipient_reference="kunde@example.invalid",
        evidence_reference="mail-1",
        recorded_by="office-panel",
    )
    offer = Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        versions=(version,),
        sent_evidence=(sent,),
        acceptance_evidence=acceptance,
    )
    return build_order_commercial_snapshot(
        order_id=order_id,
        offer=offer,
        offer_version=version,
        variant=variant,
        acceptance=acceptance,
        created_at=_NOW,
        snapshot_id=snapshot_id,
    )


def test_in_memory_create_and_get_by_order_id() -> None:
    repo = InMemoryOrderCommercialSnapshotRepository()
    snapshot = _snapshot(order_id="order-1")
    repo.create(snapshot)
    loaded = repo.get_by_order_id("order-1")
    assert loaded == snapshot
    assert repo.get_by_id(snapshot.snapshot_id) == snapshot


def test_in_memory_rejects_duplicate_order_id() -> None:
    repo = InMemoryOrderCommercialSnapshotRepository()
    repo.create(_snapshot(order_id="order-1"))
    with pytest.raises(ValueError, match="already exists"):
        repo.create(
            _snapshot(
                order_id="order-1",
                snapshot_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            )
        )


def test_sqlite_roundtrip_and_immutable(tmp_path: Path) -> None:
    connection = open_core_connection(tmp_path / "core.db")
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    orders = SQLiteOrderRepository.from_connection(connection)
    snapshots = SQLiteOrderCommercialSnapshotRepository.from_connection(connection)
    inquiry = _inquiry()
    inquiries.save(inquiry)
    order, _version = seed_order(orders, inquiry)
    connection.commit()

    snapshot = _snapshot(order_id=order.order_id)
    snapshots.create(snapshot)
    connection.commit()

    loaded = snapshots.get_by_order_id(order.order_id)
    assert loaded is not None
    assert loaded.positions[0].name == "Fingerfood Paket"
    assert loaded.positions[0].allergens == ("A", "C")
    assert loaded.positions[0].quantity == Decimal("80")
    assert loaded.payment_method == "RECHNUNG"

    with pytest.raises(sqlite3.Error, match="immutable"):
        connection.execute(
            "UPDATE order_commercial_snapshots SET variant_label = ? "
            "WHERE snapshot_id = ?",
            ("mutated", snapshot.snapshot_id),
        )
    with pytest.raises(sqlite3.Error, match="immutable"):
        connection.execute(
            "DELETE FROM order_commercial_snapshots WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        )
    with pytest.raises(ValueError, match="already exists"):
        snapshots.create(
            _snapshot(
                order_id=order.order_id,
                snapshot_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                name="Other",
            )
        )
    connection.close()


def test_sqlite_owner_trigger_rejects_orphan_order_id(tmp_path: Path) -> None:
    connection = open_core_connection(tmp_path / "core.db")
    SQLiteOrderRepository.from_connection(connection)
    snapshots = SQLiteOrderCommercialSnapshotRepository.from_connection(connection)
    with pytest.raises(sqlite3.Error, match="owner is invalid"):
        snapshots.create(_snapshot(order_id="missing-order"))
    connection.close()

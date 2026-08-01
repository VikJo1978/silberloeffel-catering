from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from catering_system.domain.inquiry_timing import evaluate_timing
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.offer_service import (
    OfferService,
    OfferTimingReviewRequiredError,
)
from catering_system.services.offer_snapshot_validation import validate_offer_snapshot
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _sample_inquiry,
    _valid_snapshot,
)


def test_previous_day_delivery_does_not_trigger_short_gap_warning() -> None:
    evaluation = evaluate_timing(
        event_date=date(2026, 8, 20),
        delivery_date_local="2026-08-19",
        delivery_window_start_local="23:00",
        delivery_window_end_local="23:30",
        event_start_local="00:10",
        legacy_time_window_text=None,
    )
    assert evaluation.findings == ()


def test_gap_29_minutes_is_warning_but_30_minutes_is_not() -> None:
    narrow = evaluate_timing(
        event_date=date(2026, 8, 20),
        delivery_date_local="2026-08-20",
        delivery_window_start_local="17:00",
        delivery_window_end_local="18:01",
        event_start_local="18:30",
        legacy_time_window_text=None,
    )
    exact = evaluate_timing(
        event_date=date(2026, 8, 20),
        delivery_date_local="2026-08-20",
        delivery_window_start_local="17:00",
        delivery_window_end_local="18:00",
        event_start_local="18:30",
        legacy_time_window_text=None,
    )
    assert "DELIVERY_GAP_TOO_SHORT" in narrow.findings
    assert "DELIVERY_GAP_TOO_SHORT" not in exact.findings


def test_snapshot_validation_accepts_canonical_timing_fields() -> None:
    payload = _valid_snapshot()
    payload["event"]["legacy_time_window_text"] = "Alttext"
    payload["event"]["time_review_acknowledged_at"] = "2026-07-15T08:40:00+00:00"
    payload["event"]["time_review_acknowledged_by"] = "office"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    snapshot = validate_offer_snapshot(payload)
    assert snapshot.event.delivery_date_local == "2026-08-20"
    assert snapshot.event.time_review_acknowledged_by == "office"
    assert snapshot.event.legacy_time_window_text == "Alttext"


def test_snapshot_validation_rejects_malformed_delivery_date() -> None:
    payload = _valid_snapshot()
    payload["event"]["delivery_date_local"] = "2026-13-20"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(ValueError, match="delivery_date_local"):
        validate_offer_snapshot(payload)


def test_inquiry_service_mirrors_legacy_time_window_text_and_clears_ack() -> None:
    repo = InMemoryInquiryRepository()
    service = InquiryService(repo)
    inquiry = service.create_inquiry(
        inquiry_source="manual",
        event_date=date(2026, 8, 20),
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        time_review_acknowledged_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
        time_review_acknowledged_by="office",
    )
    assert inquiry.legacy_time_window_text == "18:00–22:00"
    assert inquiry.time_review_acknowledged_at is not None

    updated = service.update_inquiry(
        inquiry.inquiry_id,
        event_date=date(2026, 8, 20),
        crm_stage="Neue Anfrage",
        time_window_text="19:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode="caterer_suggestion",
    )
    assert updated.legacy_time_window_text == "19:00–22:00"
    assert updated.time_review_acknowledged_at is None
    assert updated.time_review_acknowledged_by is None


def test_inquiry_service_canonical_write_does_not_synthesize_legacy() -> None:
    repo = InMemoryInquiryRepository()
    service = InquiryService(repo)
    inquiry = service.create_inquiry(
        inquiry_source="manual",
        event_date=date(2026, 8, 20),
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        delivery_date_local="2026-08-20",
        delivery_window_start_local="17:30",
        delivery_window_end_local="18:00",
        event_start_local="18:45",
        legacy_time_window_text=None,
    )
    assert inquiry.legacy_time_window_text is None


def test_prepare_offer_legacy_snapshot_uses_inquiry_fallback_and_persists_timing() -> (
    None
):
    inquiry = _sample_inquiry()
    offers = InMemoryOfferRepository()
    service = OfferService(
        offers,
        InMemoryInquiryRepository(),
        InMemoryOrderRepository(),
    )
    service._inquiry_repository.save(inquiry)  # type: ignore[attr-defined]
    payload = _valid_snapshot()
    payload["event"].pop("delivery_date_local")
    payload["event"].pop("delivery_window_start_local")
    payload["event"].pop("delivery_window_end_local")
    payload["event"].pop("event_start_local")
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    offer = service.prepare_offer_version(_INQUIRY_ID, payload)
    version = offer.versions[0]
    assert version.delivery_date_local == inquiry.delivery_date_local
    assert version.delivery_window_end_local == inquiry.delivery_window_end_local
    assert version.legacy_time_window_text is None


def test_prepare_offer_blocks_when_time_review_required() -> None:
    inquiry = _sample_inquiry()
    offers = InMemoryOfferRepository()
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    service = OfferService(offers, inquiries, InMemoryOrderRepository())
    payload = _valid_snapshot()
    payload["event"].pop("delivery_date_local")
    payload["event"].pop("delivery_window_start_local")
    payload["event"].pop("delivery_window_end_local")
    payload["event"].pop("event_start_local")
    inquiry.delivery_date_local = None
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(OfferTimingReviewRequiredError) as excinfo:
        service.prepare_offer_version(_INQUIRY_ID, payload)
    assert "DELIVERY_DATE_MISSING" in excinfo.value.findings


def test_invalid_delivery_window_cannot_be_acknowledged_through() -> None:
    inquiry = _sample_inquiry()
    inquiry.delivery_window_start_local = "19:00"
    inquiry.delivery_window_end_local = "18:00"
    inquiry.time_review_acknowledged_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    inquiry.time_review_acknowledged_by = "office"
    offers = InMemoryOfferRepository()
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    service = OfferService(offers, inquiries, InMemoryOrderRepository())
    payload = _valid_snapshot()
    payload["event"].pop("delivery_date_local")
    payload["event"].pop("delivery_window_start_local")
    payload["event"].pop("delivery_window_end_local")
    payload["event"].pop("event_start_local")
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(OfferTimingReviewRequiredError) as excinfo:
        service.prepare_offer_version(_INQUIRY_ID, payload)
    assert excinfo.value.invalid_window is True


def test_sqlite_inquiry_migration_backfills_legacy_time_window_text(
    tmp_path: Path,
) -> None:
    db = tmp_path / "legacy-inquiry.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE inquiries (
            inquiry_id TEXT PRIMARY KEY,
            event_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            inquiry_source TEXT NOT NULL,
            crm_stage TEXT NOT NULL,
            customer_linkage TEXT NOT NULL,
            time_window_text TEXT NOT NULL,
            location_text TEXT NOT NULL,
            guest_count_estimate INTEGER,
            planning_mode TEXT NOT NULL,
            call_verification_required INTEGER NOT NULL,
            call_verification_status TEXT NOT NULL
        );
        """
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO inquiries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "inquiry-1",
            "2026-08-20",
            now,
            now,
            "manual",
            "Neue Anfrage",
            json.dumps({}),
            "18:00–22:00",
            "Hamburg",
            80,
            "caterer_suggestion",
            0,
            "not_required",
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteInquiryRepository(db)
    loaded = repo.get_by_id("inquiry-1")
    repo.close()
    assert loaded is not None
    assert loaded.legacy_time_window_text == "18:00–22:00"


def test_sqlite_offer_migration_backfills_legacy_time_window_text(
    tmp_path: Path,
) -> None:
    db = tmp_path / "legacy-offer.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE offers (
            offer_id TEXT PRIMARY KEY,
            source_inquiry_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE offer_versions (
            offer_version_id TEXT PRIMARY KEY,
            offer_id TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            valid_until TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            event_date TEXT,
            time_window_text TEXT,
            location_text TEXT,
            guest_count INTEGER,
            planning_mode TEXT,
            payment_method TEXT,
            payment_customer_visible_text TEXT
        );
        CREATE TABLE offer_variants (
            variant_id TEXT PRIMARY KEY,
            offer_version_id TEXT NOT NULL,
            offer_id TEXT NOT NULL,
            label TEXT NOT NULL,
            sort_order INTEGER NOT NULL
        );
        CREATE TABLE offer_positions (
            position_id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL,
            offer_version_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            unit_net_cents INTEGER NOT NULL,
            net_total_cents INTEGER NOT NULL,
            vat_rate_percent INTEGER NOT NULL,
            vat_amount_cents INTEGER NOT NULL,
            gross_total_cents INTEGER NOT NULL,
            related_position_id TEXT,
            sort_order INTEGER NOT NULL
        );
        """
    )
    now = datetime.now(UTC).isoformat()
    conn.execute("INSERT INTO offers VALUES (?, ?, ?)", ("offer-1", _INQUIRY_ID, now))
    conn.execute(
        """
        INSERT INTO offer_versions (
            offer_version_id, offer_id, version_number, created_at, valid_until,
            snapshot_id, snapshot_hash, event_date, time_window_text, location_text,
            guest_count, planning_mode, payment_method, payment_customer_visible_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "version-1",
            "offer-1",
            1,
            now,
            "2026-08-25",
            "77777777-7777-4777-8777-777777777771",
            "sha256:" + ("a" * 64),
            "2026-08-20",
            "18:00–22:00",
            "Hamburg",
            80,
            "caterer_suggestion",
            "RECHNUNG",
            "Zahlung per Rechnung",
        ),
    )
    conn.execute(
        "INSERT INTO offer_variants VALUES (?, ?, ?, ?, ?)",
        ("variant-1", "version-1", "offer-1", "Variante A", 0),
    )
    conn.execute(
        """
        INSERT INTO offer_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "position-1",
            "variant-1",
            "version-1",
            "catalog",
            "Fingerfood",
            100,
            100,
            7,
            7,
            107,
            None,
            0,
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteOfferRepository(db)
    loaded = repo.get("offer-1")
    repo.close()
    assert loaded is not None
    assert loaded.versions[0].legacy_time_window_text == "18:00–22:00"

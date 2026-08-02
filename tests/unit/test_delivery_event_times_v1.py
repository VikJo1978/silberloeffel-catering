from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from catering_system.domain.inquiry_timing import (
    TimingEvaluation,
    evaluate_timing,
    normalize_legacy_time_window_text,
    timing_acknowledgement_is_valid,
    validate_local_date_text,
    validate_local_time_text,
    validate_optional_acknowledged_by,
    validate_optional_local_date_text,
    validate_optional_local_time_text,
)
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
    OfferPreparationBlockedError,
    OfferService,
    OfferTimingReviewRequiredError,
)
from catering_system.services.offer_snapshot_validation import validate_offer_snapshot
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _sample_inquiry,
    _valid_snapshot,
)


@pytest.mark.parametrize(
    ("validator", "value", "message"),
    [
        (validate_local_date_text, None, "YYYY-MM-DD string"),
        (validate_local_date_text, "20-08-2026", "YYYY-MM-DD string"),
        (validate_local_date_text, "2026-02-30", "real YYYY-MM-DD date"),
        (validate_optional_local_date_text, True, "must not be a boolean"),
        (validate_local_time_text, None, "HH:MM string"),
        (validate_local_time_text, "9:00", "HH:MM string"),
        (validate_local_time_text, "25:00", "real HH:MM time"),
        (validate_optional_local_time_text, False, "must not be a boolean"),
    ],
)
def test_timing_text_validators_reject_invalid_values(
    validator: Callable[[object, str], object],
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validator(value, "event_field")


def test_optional_timing_metadata_normalizes_and_rejects_invalid_values() -> None:
    assert validate_optional_local_date_text(None, "delivery_date") is None
    assert validate_optional_local_time_text(None, "event_start") is None
    assert validate_optional_acknowledged_by(None, "acknowledged_by") is None
    assert (
        validate_optional_acknowledged_by("  office  ", "acknowledged_by") == "office"
    )
    assert validate_optional_acknowledged_by("   ", "acknowledged_by") is None
    assert normalize_legacy_time_window_text("  18:00–22:00  ", "legacy") == (
        "18:00–22:00"
    )
    assert normalize_legacy_time_window_text("   ", "legacy") is None

    with pytest.raises(ValueError, match="must be a string"):
        validate_optional_acknowledged_by(1, "acknowledged_by")
    with pytest.raises(ValueError, match="exceeds length limit"):
        validate_optional_acknowledged_by("x" * 201, "acknowledged_by")
    with pytest.raises(ValueError, match="must be a string"):
        normalize_legacy_time_window_text(1, "legacy")
    with pytest.raises(ValueError, match="exceeds length limit"):
        normalize_legacy_time_window_text("x" * 501, "legacy")


def test_timing_evaluation_reports_missing_legacy_and_after_event_findings() -> None:
    incomplete = evaluate_timing(
        event_date=date(2026, 8, 20),
        delivery_date_local=None,
        delivery_window_start_local=None,
        delivery_window_end_local=None,
        event_start_local=None,
        legacy_time_window_text="18:00–22:00",
    )
    assert incomplete.findings == (
        "DELIVERY_DATE_MISSING",
        "DELIVERY_WINDOW_START_MISSING",
        "DELIVERY_WINDOW_END_MISSING",
        "EVENT_START_MISSING",
        "LEGACY_TIME_UNRESOLVED",
    )

    after_event = evaluate_timing(
        event_date=date(2026, 8, 20),
        delivery_date_local="2026-08-20",
        delivery_window_start_local="18:00",
        delivery_window_end_local="19:00",
        event_start_local="18:30",
        legacy_time_window_text=None,
    )
    assert after_event.findings == ("DELIVERY_AFTER_EVENT_START",)


def test_timing_acknowledgement_validity_depends_on_finding_kind() -> None:
    acknowledged_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    assert not timing_acknowledgement_is_valid(
        TimingEvaluation(("DELIVERY_WINDOW_INVALID",)),
        acknowledged_at=acknowledged_at,
        acknowledged_by="office",
    )
    assert timing_acknowledgement_is_valid(
        TimingEvaluation(()),
        acknowledged_at=None,
        acknowledged_by=None,
    )
    assert not timing_acknowledgement_is_valid(
        TimingEvaluation(("DELIVERY_DATE_MISSING",)),
        acknowledged_at=None,
        acknowledged_by=None,
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


def _snapshot_without_det_timing() -> dict[str, object]:
    payload = _valid_snapshot()
    for key in (
        "delivery_date_local",
        "delivery_window_start_local",
        "delivery_window_end_local",
        "event_start_local",
    ):
        payload["event"].pop(key, None)
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def _offer_service_with_inquiry(
    inquiry=_sample_inquiry(),  # noqa: ANN001
) -> tuple[InMemoryOfferRepository, InMemoryInquiryRepository, OfferService]:
    offers = InMemoryOfferRepository()
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    service = OfferService(offers, inquiries, InMemoryOrderRepository())
    return offers, inquiries, service


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


def test_prepare_offer_rejects_snapshot_without_det_even_when_inquiry_has_timing() -> (
    None
):
    inquiry = _sample_inquiry()
    inquiry.delivery_date_local = "2026-09-01"
    inquiry.delivery_window_end_local = "12:00"
    _offers, _inquiries, service = _offer_service_with_inquiry(inquiry)
    payload = _snapshot_without_det_timing()
    with pytest.raises(OfferTimingReviewRequiredError) as excinfo:
        service.prepare_offer_version(_INQUIRY_ID, payload)
    assert "DELIVERY_DATE_MISSING" in excinfo.value.findings


def test_prepare_offer_rejects_snapshot_missing_required_canonical_timing() -> None:
    _offers, _inquiries, service = _offer_service_with_inquiry()
    payload = _snapshot_without_det_timing()
    with pytest.raises(OfferTimingReviewRequiredError) as excinfo:
        service.prepare_offer_version(_INQUIRY_ID, payload)
    assert "DELIVERY_DATE_MISSING" in excinfo.value.findings


def test_prepare_offer_creates_version_from_full_canonical_timing() -> None:
    inquiry = _sample_inquiry()
    _offers, _inquiries, service = _offer_service_with_inquiry(inquiry)
    payload = _valid_snapshot()
    offer = service.prepare_offer_version(_INQUIRY_ID, payload)
    version = offer.versions[0]
    assert version.delivery_date_local == payload["event"]["delivery_date_local"]
    assert (
        version.delivery_window_start_local
        == payload["event"]["delivery_window_start_local"]
    )
    assert (
        version.delivery_window_end_local
        == payload["event"]["delivery_window_end_local"]
    )
    assert version.event_start_local == payload["event"]["event_start_local"]
    assert version.time_review_acknowledged_at is None
    assert version.time_review_acknowledged_by is None


def test_inquiry_timing_change_after_offer_does_not_mutate_saved_version() -> None:
    inquiry = _sample_inquiry()
    _offers, inquiries, service = _offer_service_with_inquiry(inquiry)
    payload = _valid_snapshot()
    offer = service.prepare_offer_version(_INQUIRY_ID, payload)
    version_before = offer.versions[0]
    inquiries.update(
        replace(
            inquiry,
            delivery_date_local="2026-09-01",
            delivery_window_start_local="10:00",
            delivery_window_end_local="11:00",
            event_start_local="12:00",
            time_review_acknowledged_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
            time_review_acknowledged_by="forged",
        )
    )
    stored = _offers.get(offer.offer_id)
    assert stored is not None
    version_after = stored.versions[0]
    assert version_after.delivery_date_local == version_before.delivery_date_local
    assert (
        version_after.delivery_window_end_local
        == version_before.delivery_window_end_local
    )
    assert version_after.event_start_local == version_before.event_start_local
    assert version_after.snapshot_hash == version_before.snapshot_hash
    assert version_after.time_review_acknowledged_at is None
    assert version_after.time_review_acknowledged_by is None


def test_persisted_offer_version_timing_matches_validated_snapshot() -> None:
    _offers, _inquiries, service = _offer_service_with_inquiry()
    payload = _valid_snapshot()
    validated = validate_offer_snapshot(payload)
    offer = service.prepare_offer_version(_INQUIRY_ID, payload)
    version = offer.versions[0]
    assert version.delivery_date_local == validated.event.delivery_date_local
    assert (
        version.delivery_window_start_local
        == validated.event.delivery_window_start_local
    )
    assert (
        version.delivery_window_end_local == validated.event.delivery_window_end_local
    )
    assert version.event_start_local == validated.event.event_start_local
    assert version.legacy_time_window_text == validated.event.legacy_time_window_text


def test_trusted_internal_acknowledgement_allows_overrideable_finding() -> None:
    _offers, _inquiries, service = _offer_service_with_inquiry()
    payload = _valid_snapshot()
    payload["event"]["delivery_window_end_local"] = "18:16"
    payload["event"]["time_review_acknowledged_at"] = "2026-07-15T08:40:00+00:00"
    payload["event"]["time_review_acknowledged_by"] = "employee:trusted-internal"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    offer = service.prepare_offer_version(_INQUIRY_ID, payload)
    version = offer.versions[0]
    assert version.delivery_window_end_local == "18:16"
    assert version.time_review_acknowledged_by == "employee:trusted-internal"
    assert version.time_review_acknowledged_at is not None


def test_direct_offer_service_without_acknowledgement_fails_on_overrideable_finding() -> (
    None
):
    _offers, _inquiries, service = _offer_service_with_inquiry()
    payload = _valid_snapshot()
    payload["event"]["delivery_window_end_local"] = "18:16"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(OfferTimingReviewRequiredError) as excinfo:
        service.prepare_offer_version(_INQUIRY_ID, payload)
    assert "DELIVERY_GAP_TOO_SHORT" in excinfo.value.findings
    assert excinfo.value.invalid_window is False


def test_prepare_offer_blocks_when_time_review_required() -> None:
    _offers, _inquiries, service = _offer_service_with_inquiry()
    payload = _snapshot_without_det_timing()
    with pytest.raises(OfferTimingReviewRequiredError) as excinfo:
        service.prepare_offer_version(_INQUIRY_ID, payload)
    assert "DELIVERY_DATE_MISSING" in excinfo.value.findings


def test_invalid_delivery_window_cannot_be_acknowledged_through() -> None:
    _offers, _inquiries, service = _offer_service_with_inquiry()
    payload = _valid_snapshot()
    payload["event"]["delivery_window_start_local"] = "19:00"
    payload["event"]["delivery_window_end_local"] = "18:00"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(OfferTimingReviewRequiredError) as excinfo:
        service.prepare_offer_version(_INQUIRY_ID, payload)
    assert excinfo.value.invalid_window is True


def test_invalid_delivery_window_blocked_even_with_trusted_acknowledgement() -> None:
    _offers, _inquiries, service = _offer_service_with_inquiry()
    payload = _valid_snapshot()
    payload["event"]["delivery_window_start_local"] = "19:00"
    payload["event"]["delivery_window_end_local"] = "18:00"
    payload["event"]["time_review_acknowledged_at"] = "2026-07-15T08:40:00+00:00"
    payload["event"]["time_review_acknowledged_by"] = "employee:trusted-internal"
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    with pytest.raises(OfferTimingReviewRequiredError) as excinfo:
        service.prepare_offer_version(_INQUIRY_ID, payload)
    assert excinfo.value.invalid_window is True


def test_identical_canonical_snapshot_preserves_idempotency_semantics() -> None:
    _offers, _inquiries, service = _offer_service_with_inquiry()
    payload = _valid_snapshot()
    first = service.prepare_offer_version(_INQUIRY_ID, payload)
    with pytest.raises(OfferPreparationBlockedError, match="offer already exists"):
        service.prepare_offer_version(_INQUIRY_ID, payload)
    stored = _offers.get(first.offer_id)
    assert stored == first


def test_different_canonical_timing_facts_produce_different_snapshot_hash() -> None:
    first = _valid_snapshot()
    second = _valid_snapshot()
    second["event"]["delivery_window_end_local"] = "18:15"
    second["snapshot_hash"] = compute_snapshot_hash(second)
    assert first["snapshot_hash"] != second["snapshot_hash"]


def test_prepare_next_offer_version_does_not_read_timing_from_inquiry() -> None:
    inquiry = _sample_inquiry()
    _offers, inquiries, service = _offer_service_with_inquiry(inquiry)
    offer = service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    version_id = offer.versions[0].offer_version_id
    service.record_sent_evidence(
        offer.offer_id,
        version_id,
        sent_at=datetime(2026, 7, 15, 10, 0, tzinfo=UTC),
        channel="email",
        recipient_reference="customer@example.invalid",
        evidence_reference="msg-1",
        recorded_by="office-panel",
    )
    inquiries.update(
        replace(
            inquiry,
            delivery_date_local="2026-09-01",
            delivery_window_start_local="10:00",
            delivery_window_end_local="11:00",
            event_start_local="12:00",
        )
    )
    revision = _valid_snapshot()
    revision["snapshot_id"] = "88888888-8888-4888-8888-888888888882"
    revision["source_draft_id"] = "draft-2"
    revision["snapshot_created_at"] = "2026-07-16T08:30:00+00:00"
    revision["valid_until"] = "2026-08-05"
    for key in (
        "delivery_date_local",
        "delivery_window_start_local",
        "delivery_window_end_local",
        "event_start_local",
    ):
        revision["event"].pop(key, None)
    revision["snapshot_hash"] = compute_snapshot_hash(revision)
    with pytest.raises(OfferTimingReviewRequiredError) as excinfo:
        service.prepare_next_offer_version(
            offer.offer_id,
            revision,
            expected_latest_version_number=1,
        )
    assert "DELIVERY_DATE_MISSING" in excinfo.value.findings


def test_sqlite_offer_version_immutability_triggers_remain_effective(
    tmp_path: Path,
) -> None:
    inquiry = _sample_inquiry()
    db = tmp_path / "immutable-offer.db"
    inquiries = SQLiteInquiryRepository(db)
    inquiries.save(inquiry)
    offers = SQLiteOfferRepository(db)
    service = OfferService(
        offers,
        inquiries,
        InMemoryOrderRepository(),
    )
    offer = service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    version_id = offer.versions[0].offer_version_id
    with pytest.raises(sqlite3.IntegrityError, match="offer_versions is immutable"):
        offers._conn.execute(
            "UPDATE offer_versions SET delivery_date_local = ? WHERE offer_version_id = ?",
            ("2026-09-01", version_id),
        )
    offers.close()
    inquiries.close()


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

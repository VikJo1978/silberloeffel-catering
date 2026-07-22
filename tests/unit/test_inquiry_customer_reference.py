"""INQUIRY_CUSTOMER_REFERENCE_AND_SNAPSHOT_V1 — domain, persistence, intake."""

from __future__ import annotations

import sqlite3
import sys
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from catering_system.domain.contact_projection import derive_contact_identity
from catering_system.domain.customer_identity import CustomerIdentity
from catering_system.domain.inquiry import (
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
    apply_inquiry_customer_reference,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot,
    snapshot_from_intake_message,
)
from catering_system.intake.email_adapter import intake_from_email
from catering_system.intake.manual_adapter import intake_from_manual
from catering_system.intake.phone_adapter import intake_from_phone
from catering_system.intake.website_form_adapter import intake_from_website_form
from catering_system.repositories.bootstrap_customer_identity_schema import (
    bootstrap_customer_identity_schema,
)
from catering_system.repositories.in_memory_customer_identity_repository import (
    InMemoryCustomerIdentityRepository,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_migrations import apply_migrations
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui import office_api_views as views

UTC = timezone.utc


def _base_kwargs() -> dict:
    return {
        "event_date": date(2026, 8, 1),
        "crm_stage": CRM_PIPELINE[0],
        "customer_linkage": {},
        "time_window_text": "abends",
        "location_text": "Berlin",
        "guest_count_estimate": 40,
        "planning_mode": PLANNING_MODES[0],
        "call_verification_required": False,
        "call_verification_status": "not_required",
    }


def _snapshot(**kwargs: str | None) -> InquiryCustomerSnapshot:
    return InquiryCustomerSnapshot(**kwargs)


def test_inquiry_without_customer_reference() -> None:
    svc = InquiryService(InMemoryInquiryRepository())
    inquiry = svc.create_inquiry(inquiry_source="manual", **_base_kwargs())
    assert inquiry.customer_id is None
    assert inquiry.customer_snapshot is None


def test_inquiry_with_snapshot_without_customer_id() -> None:
    svc = InquiryService(InMemoryInquiryRepository())
    inquiry = svc.create_inquiry(
        inquiry_source="manual",
        intake_message="Firma: ACME\nName: Alex\nE-Mail: a@example.com",
        **_base_kwargs(),
    )
    assert inquiry.customer_id is None
    assert inquiry.customer_snapshot == _snapshot(
        company_name="ACME",
        contact_name="Alex",
        email="a@example.com",
        phone=None,
    )


def test_assign_customer_id_with_snapshot() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    inquiry = svc.create_inquiry(
        inquiry_source="manual",
        intake_message="Name: Alex\nE-Mail: a@example.com",
        **_base_kwargs(),
    )
    snap = inquiry.customer_snapshot
    assert snap is not None
    updated = svc.assign_customer_reference(
        inquiry.inquiry_id,
        customer_id="cust-1",
        snapshot=snap,
    )
    assert updated.customer_id == "cust-1"
    assert updated.customer_snapshot == snap


def test_assign_customer_id_without_snapshot_rejected() -> None:
    inquiry = Inquiry(
        inquiry_id="q-1",
        event_date=date(2026, 8, 1),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="",
        location_text="",
        guest_count_estimate=None,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
    )
    with pytest.raises(ValueError, match="snapshot is required"):
        apply_inquiry_customer_reference(
            inquiry,
            customer_id="cust-1",
            snapshot=_snapshot(),
        )


def test_snapshot_immutable_on_replace() -> None:
    inquiry = replace(
        Inquiry(
            inquiry_id="q-1",
            event_date=date(2026, 8, 1),
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
            updated_at=datetime(2026, 8, 1, tzinfo=UTC),
            inquiry_source="manual",
            crm_stage=CRM_PIPELINE[0],
            customer_linkage={},
            time_window_text="",
            location_text="",
            guest_count_estimate=None,
            planning_mode=PLANNING_MODES[0],
            call_verification_required=False,
            call_verification_status="not_required",
        ),
        customer_snapshot=_snapshot(contact_name="Alex"),
    )
    with pytest.raises(ValueError, match="immutable"):
        apply_inquiry_customer_reference(
            inquiry,
            customer_id="cust-1",
            snapshot=_snapshot(contact_name="Bob"),
        )


def test_identical_assign_is_idempotent() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    inquiry = svc.create_inquiry(
        inquiry_source="manual",
        intake_message="Name: Alex",
        **_base_kwargs(),
    )
    snap = inquiry.customer_snapshot
    assert snap is not None
    first = svc.assign_customer_reference(
        inquiry.inquiry_id, customer_id="cust-1", snapshot=snap
    )
    second = svc.assign_customer_reference(
        inquiry.inquiry_id, customer_id="cust-1", snapshot=snap
    )
    assert first.customer_id == second.customer_id == "cust-1"
    assert repo.get_by_id(inquiry.inquiry_id) == first


def test_sqlite_round_trip_preserves_customer_reference(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    inquiry = Inquiry(
        inquiry_id=str(uuid.uuid4()),
        event_date=date(2026, 8, 1),
        created_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=10,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
        customer_id="cust-42",
        customer_snapshot=_snapshot(
            company_name="ACME",
            contact_name="Alex",
            email="a@example.com",
            phone="+4930123456",
        ),
    )
    repo.save(inquiry)
    loaded = repo.get_by_id(inquiry.inquiry_id)
    assert loaded == inquiry


def test_legacy_sqlite_row_loads_null_customer_reference(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE inquiries (
            inquiry_id TEXT PRIMARY KEY, event_date TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            inquiry_source TEXT NOT NULL, crm_stage TEXT NOT NULL,
            customer_linkage TEXT NOT NULL, time_window_text TEXT NOT NULL,
            location_text TEXT NOT NULL, guest_count_estimate INTEGER,
            planning_mode TEXT NOT NULL, call_verification_required INTEGER NOT NULL,
            call_verification_status TEXT NOT NULL,
            intake_subject TEXT, intake_message TEXT, intake_summary TEXT,
            intake_external_ref TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO inquiries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "11111111-1111-1111-1111-111111111111",
            "2026-08-01",
            "2026-08-01T12:00:00+00:00",
            "2026-08-01T12:00:00+00:00",
            "manual",
            CRM_PIPELINE[0],
            "{}",
            "abends",
            "Berlin",
            10,
            PLANNING_MODES[0],
            0,
            "not_required",
            None,
            None,
            None,
            None,
        ),
    )
    conn.commit()
    conn.close()
    repo = SQLiteInquiryRepository(db)
    loaded = repo.get_by_id("11111111-1111-1111-1111-111111111111")
    assert loaded is not None
    assert loaded.customer_id is None
    assert loaded.customer_snapshot is None


def test_migration_adds_only_customer_reference_columns(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (component, version)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE inquiries (
            inquiry_id TEXT PRIMARY KEY, event_date TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            inquiry_source TEXT NOT NULL, crm_stage TEXT NOT NULL,
            customer_linkage TEXT NOT NULL, time_window_text TEXT NOT NULL,
            location_text TEXT NOT NULL, guest_count_estimate INTEGER,
            planning_mode TEXT NOT NULL, call_verification_required INTEGER NOT NULL,
            call_verification_status TEXT NOT NULL,
            intake_subject TEXT, intake_message TEXT, intake_summary TEXT,
            intake_external_ref TEXT
        )
        """
    )
    conn.commit()
    from catering_system.repositories import sqlite_inquiry_repository as sir

    apply_migrations(conn, "inquiries", sir._MIGRATIONS)
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(inquiries)").fetchall()
    }
    assert {
        "customer_id",
        "snapshot_company_name",
        "snapshot_contact_name",
        "snapshot_email",
        "snapshot_phone",
    } <= columns


def test_website_form_duplicate_does_not_change_snapshot(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    svc = InquiryService(repo)
    raw = {
        "event_date": date(2026, 8, 1),
        "company": "ACME",
        "name": "Alex",
        "email": "a@example.com",
        "phone": "030 4455",
        "submission_id": "sub-1",
    }
    first = intake_from_website_form(svc, raw)
    existing = repo.find_by_source_and_external_ref("website_form", "sub-1")
    assert existing is not None
    assert existing.customer_snapshot == first.customer_snapshot
    assert existing.inquiry_id == first.inquiry_id


def test_intake_channels_capture_snapshot_from_contact_fields() -> None:
    svc = InquiryService(InMemoryInquiryRepository())
    email = intake_from_email(
        svc,
        {
            "event_date": date(2026, 8, 1),
            "from": "a@example.com",
            "subject": "Anfrage",
            "body_text": "Hallo",
        },
    )
    assert email.customer_snapshot is not None
    assert email.customer_snapshot.email == "a@example.com"

    phone = intake_from_phone(
        svc,
        {"event_date": date(2026, 8, 1), "call_notes": "Rückruf"},
    )
    assert phone.customer_snapshot is None

    manual = intake_from_manual(
        svc,
        {
            "event_date": date(2026, 8, 1),
            "time_window_text": "abends",
            "location_text": "Berlin",
        },
    )
    assert manual.customer_snapshot is None


def test_no_customer_identity_records_created_on_inquiry_create() -> None:
    repo = InMemoryCustomerIdentityRepository()
    before = len(repo._by_id)
    InquiryService(InMemoryInquiryRepository()).create_inquiry(
        inquiry_source="manual",
        intake_message="Name: Alex",
        **_base_kwargs(),
    )
    assert len(repo._by_id) == before


def test_inquiry_to_order_behavior_unchanged() -> None:
    from tests.helpers.order_seed import seed_order

    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    inquiry_svc = InquiryService(inquiry_repo)
    kwargs = _base_kwargs()
    kwargs["customer_linkage"] = {"placeholder": True}
    inquiry = inquiry_svc.create_inquiry(
        inquiry_source="manual",
        intake_message="Name: Alex\nE-Mail: alex@example.com\nTelefon: 030 11 22",
        **kwargs,
    )
    inquiry = inquiry_svc.assign_customer_reference(
        inquiry.inquiry_id,
        customer_id="cust-1",
        snapshot=inquiry.customer_snapshot or _snapshot(contact_name="Alex"),
    )
    order, _version = seed_order(order_repo, inquiry)
    assert order.source_inquiry_id == inquiry.inquiry_id
    assert not hasattr(order, "customer_id")


def test_contact_projection_and_linkage_semantics_unchanged() -> None:
    inquiry = Inquiry(
        inquiry_id="q-1",
        event_date=date(2026, 8, 1),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={"customer_id": "legacy-link"},
        time_window_text="",
        location_text="",
        guest_count_estimate=None,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
        intake_message="Name: Alex\nE-Mail: a@example.com",
        customer_id="cust-new",
        customer_snapshot=_snapshot(contact_name="Alex", email="a@example.com"),
    )
    identity = derive_contact_identity(inquiry)
    assert identity[0] == "linkage:customer:legacy-link"
    assert identity[1] == "linkage_customer"


def test_customer_identity_change_does_not_mutate_persisted_inquiry_snapshot(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(tmp_path / "core.db")
    bootstrap_customer_identity_schema(conn)
    conn.commit()
    identity_repo = InMemoryCustomerIdentityRepository()
    now = datetime(2026, 8, 1, tzinfo=UTC)
    identity = CustomerIdentity(
        customer_id="cust-1",
        display_name="Old Name",
        company_name="Old Co",
        status="active",
        created_at=now,
        updated_at=now,
    )
    identity_repo.add(identity)
    snapshot = _snapshot(company_name="Old Co", contact_name="Old Name")
    inquiry_repo = SQLiteInquiryRepository(tmp_path / "core.db")
    inquiry = Inquiry(
        inquiry_id=str(uuid.uuid4()),
        event_date=date(2026, 8, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="",
        location_text="",
        guest_count_estimate=None,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
        customer_id="cust-1",
        customer_snapshot=snapshot,
    )
    inquiry_repo.save(inquiry)
    changed = replace(identity, display_name="New Name", company_name="New Co")
    assert changed.display_name == "New Name"
    loaded = inquiry_repo.get_by_id(inquiry.inquiry_id)
    assert loaded is not None
    assert loaded.customer_snapshot == snapshot


def test_office_api_detail_exposes_optional_customer_reference_fields() -> None:
    inquiry = Inquiry(
        inquiry_id=str(uuid.uuid4()),
        event_date=date(2026, 8, 1),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="",
        location_text="",
        guest_count_estimate=None,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
        customer_id="cust-1",
        customer_snapshot=_snapshot(contact_name="Alex"),
    )
    detail = views.inquiry_detail(inquiry, [], today=date(2026, 8, 1))
    assert detail["customer_id"] == "cust-1"
    assert detail["customer_snapshot"] == {
        "company_name": None,
        "contact_name": "Alex",
        "email": None,
        "phone": None,
    }


def test_snapshot_from_intake_message_matches_labelled_fields() -> None:
    snap = snapshot_from_intake_message(
        "Firma: ACME\nTelefon: 030 123456\nE-Mail: a@example.com"
    )
    assert snap == _snapshot(
        company_name="ACME",
        contact_name=None,
        email="a@example.com",
        phone="+4930123456",
    )

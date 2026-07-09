"""Unit tests — SQLite repositories behind the existing Protocols (persistence adapter only)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.repositories.sqlite_inquiry_repository import SQLiteInquiryRepository
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.progression_service import ProgressionService


def _sample_inquiry() -> Inquiry:
    now = datetime.now(timezone.utc)
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
    )


def test_inquiry_roundtrip_preserves_all_fields(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "test.db")
    inquiry = _sample_inquiry()
    repo.save(inquiry)
    loaded = repo.get_by_id(inquiry.inquiry_id)
    assert loaded == inquiry  # incl. tz-aware datetimes, linkage dict, intake fields


def test_sqlite_inquiry_migration_from_pre_intake_context_schema(tmp_path: Path) -> None:
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
    now = datetime.now(timezone.utc).isoformat()
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


def test_order_roundtrip_and_version_ordering(tmp_path: Path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
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


def test_order_update_missing_raises(tmp_path: Path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "test.db")
    osvc = OrderService(repo)
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
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
    osvc = OrderService(repo)
    core = OperationalCoreService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
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
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    cp = prog.get_order_progression_checkpoint(order.order_id)
    assert cp is not None
    assert cp.blocked is False
    assert cp.candidate_order_version_id == v1.order_version_id

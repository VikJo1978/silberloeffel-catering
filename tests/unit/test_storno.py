"""Unit tests — order cancellation (STORNO_EXECUTION_PACK_V1)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.operational_core_events import OrderCancelled
from catering_system.domain.ready_to_send import READY_REASON_ORDER_CANCELLED
from catering_system.repositories.in_memory_order_repository import InMemoryOrderRepository
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.wochenuebersicht_service import WochenuebersichtService


def _sample_inquiry() -> Inquiry:
    now = datetime.now(timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
    )


def _setup() -> tuple[InMemoryOrderRepository, OrderService, OperationalCoreService, list[object]]:
    repo = InMemoryOrderRepository()
    events: list[object] = []
    return repo, OrderService(repo), OperationalCoreService(repo, event_sink=events.append), events


def test_cancel_sets_fact_and_emits() -> None:
    repo, osvc, core, events = _setup()
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    cancelled = core.cancel_order(order.order_id)
    assert cancelled.cancelled_at is not None
    stored = repo.get_order(order.order_id)
    assert stored is not None and stored.cancelled_at is not None
    assert events == [OrderCancelled(order_id=order.order_id)]


def test_cancel_is_idempotent() -> None:
    _repo, osvc, core, events = _setup()
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    first = core.cancel_order(order.order_id)
    second = core.cancel_order(order.order_id)
    assert second == first
    assert len(events) == 1


def test_cancel_unknown_order_raises() -> None:
    _repo, _osvc, core, _events = _setup()
    with pytest.raises(ValueError):
        core.cancel_order("missing")


def test_cancel_preserves_history_candidate_effective() -> None:
    """§1: nothing deleted, nothing reverted — references stay as historical truth."""
    repo, osvc, core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    core.cancel_order(order.order_id)
    stored = repo.get_order(order.order_id)
    assert stored is not None
    assert stored.candidate_order_version_id == v1.order_version_id
    assert stored.effective_order_version_id == v1.order_version_id
    assert [v.version_number for v in repo.list_order_versions(order.order_id)] == [1]


def test_operational_commands_refused_after_cancel() -> None:
    _repo, osvc, core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    core.cancel_order(order.order_id)
    with pytest.raises(ValueError, match="cancelled"):
        core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    with pytest.raises(ValueError, match="cancelled"):
        core.make_order_version_effective(order.order_id, v1.order_version_id)


def test_order_side_mutations_refused_after_cancel() -> None:
    _repo, osvc, core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    core.cancel_order(order.order_id)
    with pytest.raises(ValueError, match="Storno"):
        osvc.create_relevant_order_change_version(
            order,
            event_date=date(2026, 10, 2),
            time_window_text="abends",
            location_text="Kiel",
            guest_count_estimate=30,
            planning_mode=PLANNING_MODES[0],
        )
    with pytest.raises(ValueError, match="Storno"):
        osvc.set_candidate_order_version(order.order_id, v1.order_version_id)


def test_ready_to_send_blocked_with_cancelled_reason() -> None:
    """§3: cancelled beats everything, even a previously fully-released order."""
    _repo, osvc, core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    assert core.evaluate_ready_to_send(order.order_id).ready is True
    core.cancel_order(order.order_id)
    ev = core.evaluate_ready_to_send(order.order_id)
    assert ev.ready is False
    assert ev.reasons == (READY_REASON_ORDER_CANCELLED,)


def test_cancelled_order_disappears_from_wochenuebersicht() -> None:
    repo, osvc, core, _events = _setup()
    week = WochenuebersichtService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    assert len(week.get_week_overview(2026, 40).entries) == 1
    core.cancel_order(order.order_id)
    assert week.get_week_overview(2026, 40).entries == ()


def test_sqlite_roundtrip_and_pre_storno_migration(tmp_path: Path) -> None:
    """§4: cancelled_at persists; a pre-Storno db gets the column added in place."""
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)  # simulate a pre-Storno database (6-column orders)
    conn.executescript(
        """
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY, source_inquiry_id TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            candidate_order_version_id TEXT, effective_order_version_id TEXT
        );
        CREATE TABLE order_versions (
            order_version_id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
            version_number INTEGER NOT NULL, created_at TEXT NOT NULL,
            event_date TEXT NOT NULL, time_window_text TEXT NOT NULL,
            location_text TEXT NOT NULL, guest_count_estimate INTEGER,
            planning_mode TEXT NOT NULL, kitchen_print_confirmed_at TEXT
        );
        """
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
        ("pre-storno-id", "inq-1", now, now, None, None),
    )
    conn.commit()
    conn.close()

    repo = SQLiteOrderRepository(db)  # migration runs here
    legacy = repo.get_order("pre-storno-id")
    assert legacy is not None and legacy.cancelled_at is None

    core = OperationalCoreService(repo)
    cancelled = core.cancel_order("pre-storno-id")
    assert cancelled.cancelled_at is not None
    repo.close()

    repo2 = SQLiteOrderRepository(db)
    reloaded = repo2.get_order("pre-storno-id")
    assert reloaded is not None and reloaded.cancelled_at == cancelled.cancelled_at

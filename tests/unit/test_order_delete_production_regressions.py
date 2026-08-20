"""Regression tests for production Order hard-delete failures."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.core_transaction import (
    CoreCommandExecutor,
    DeferredEventSink,
    open_core_connection,
)
from catering_system.repositories.order_purge import purge_order_with_dependencies
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository


def _seed_order(repo: SQLiteOrderRepository) -> Order:
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    order = Order(
        order_id="order-transitive-fk",
        source_inquiry_id="inquiry-transitive-fk",
        created_at=now,
        updated_at=now,
    )
    version = OrderVersion(
        order_version_id="version-transitive-fk",
        order_id=order.order_id,
        version_number=1,
        created_at=now,
        event_date=date(2026, 9, 1),
        time_window_text="12:00",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
    )
    repo.save_order_with_initial_version(order, version)
    return order


def test_purge_removes_transitive_fk_children_without_order_id(tmp_path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "core.db")
    connection = repo._conn
    connection.execute("PRAGMA foreign_keys = ON")
    order = _seed_order(repo)

    # Production-shaped chain:
    # order-owned snapshot -> position(snapshot_id only) -> grandchild(position_id only).
    connection.executescript(
        """
        CREATE TABLE purge_owned_snapshot (
            snapshot_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL
        );
        CREATE TABLE purge_snapshot_position (
            position_id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL,
            FOREIGN KEY (snapshot_id)
                REFERENCES purge_owned_snapshot(snapshot_id)
        );
        CREATE TABLE purge_position_note (
            note_id TEXT PRIMARY KEY,
            position_id TEXT NOT NULL,
            FOREIGN KEY (position_id)
                REFERENCES purge_snapshot_position(position_id)
        );
        """
    )
    connection.execute(
        "INSERT INTO purge_owned_snapshot (snapshot_id, order_id) VALUES (?, ?)",
        ("snapshot-1", order.order_id),
    )
    connection.execute(
        "INSERT INTO purge_snapshot_position (position_id, snapshot_id) VALUES (?, ?)",
        ("position-1", "snapshot-1"),
    )
    connection.execute(
        "INSERT INTO purge_position_note (note_id, position_id) VALUES (?, ?)",
        ("note-1", "position-1"),
    )
    connection.commit()

    purge_order_with_dependencies(repo, order.order_id)

    assert repo.get_order(order.order_id) is None
    assert connection.execute(
        "SELECT COUNT(*) FROM purge_owned_snapshot"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM purge_snapshot_position"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM purge_position_note"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_commit_integrity_error_rolls_back_and_connection_is_reusable(tmp_path) -> None:
    connection = open_core_connection(tmp_path / "core.db")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE commit_parent (
            parent_id TEXT PRIMARY KEY
        );
        CREATE TABLE commit_child (
            child_id TEXT PRIMARY KEY,
            parent_id TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES commit_parent(parent_id)
        );
        INSERT INTO commit_parent (parent_id) VALUES ('parent-1');
        INSERT INTO commit_child (child_id, parent_id)
        VALUES ('child-1', 'parent-1');
        """
    )

    delivered: list[object] = []
    events = DeferredEventSink(delivered.append)
    executor = CoreCommandExecutor(connection, events)

    def violate_at_commit() -> None:
        connection.execute("PRAGMA defer_foreign_keys = ON")
        connection.execute(
            "DELETE FROM commit_parent WHERE parent_id = ?",
            ("parent-1",),
        )
        events("must-not-escape")

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        executor.run(violate_at_commit)

    assert connection.in_transaction is False
    assert delivered == []
    assert connection.execute(
        "SELECT parent_id FROM commit_parent"
    ).fetchall() == [("parent-1",)]

    # The same shared connection must accept the next command.
    executor.run(
        lambda: connection.execute(
            "INSERT INTO commit_parent (parent_id) VALUES (?)",
            ("parent-2",),
        )
    )
    assert connection.execute(
        "SELECT parent_id FROM commit_parent ORDER BY parent_id"
    ).fetchall() == [("parent-1",), ("parent-2",)]
    connection.close()

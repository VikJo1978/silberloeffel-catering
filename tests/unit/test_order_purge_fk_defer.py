from datetime import UTC, date, datetime

from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.order_purge import purge_order_with_dependencies
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository


def test_sqlite_purge_defers_fk_checks_until_all_owned_rows_are_deleted(
    tmp_path,
) -> None:
    repo = SQLiteOrderRepository(tmp_path / "core.db")
    connection = repo._conn
    connection.execute("PRAGMA foreign_keys = ON")

    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    order = Order(
        order_id="order-fk",
        source_inquiry_id="inquiry-fk",
        created_at=now,
        updated_at=now,
    )
    version = OrderVersion(
        order_version_id="version-fk",
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

    # Parent is deliberately created before child, so sqlite_master iteration
    # attempts to delete the referenced row first. Immediate FK checking would
    # fail here even though both rows belong to the same order and are removed
    # by the same purge transaction.
    connection.execute(
        "CREATE TABLE purge_fk_parent ("
        "parent_id TEXT PRIMARY KEY, order_id TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE purge_fk_child ("
        "child_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, parent_id TEXT NOT NULL, "
        "FOREIGN KEY(parent_id) REFERENCES purge_fk_parent(parent_id))"
    )
    connection.execute(
        "INSERT INTO purge_fk_parent (parent_id, order_id) VALUES (?, ?)",
        ("parent-1", order.order_id),
    )
    connection.execute(
        "INSERT INTO purge_fk_child (child_id, order_id, parent_id) VALUES (?, ?, ?)",
        ("child-1", order.order_id, "parent-1"),
    )
    connection.commit()

    purge_order_with_dependencies(repo, order.order_id)

    assert repo.get_order(order.order_id) is None
    assert connection.execute("SELECT COUNT(*) FROM purge_fk_parent").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM purge_fk_child").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

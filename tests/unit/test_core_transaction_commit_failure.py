import sqlite3

import pytest

from catering_system.repositories.core_transaction import CoreCommandExecutor


def test_commit_integrity_error_rolls_back_and_leaves_executor_reusable() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("CREATE TABLE parent (id TEXT PRIMARY KEY)")
    connection.execute(
        "CREATE TABLE child ("
        "id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, "
        "FOREIGN KEY(parent_id) REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)"
    )
    executor = CoreCommandExecutor(connection)

    def violate_deferred_fk() -> None:
        connection.execute("INSERT INTO child (id, parent_id) VALUES ('c1', 'missing')")

    with pytest.raises(sqlite3.IntegrityError):
        executor.run(violate_deferred_fk)

    assert not connection.in_transaction
    assert connection.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 0
    assert executor.run(lambda: "ok") == "ok"

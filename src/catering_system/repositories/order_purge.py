"""Maintenance-only hard delete for accidental/test Orders.

Normal Order persistence is append-only. This helper is deliberately separate
from ordinary business writes: it temporarily suspends SQLite delete-protection
triggers inside one transaction, removes rows owned by the target order, and
restores every trigger before the transaction can commit.
"""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import Protocol, cast

from catering_system.repositories.order_repository import OrderRepository


class _SQLiteBackedOrderRepository(Protocol):
    _conn: sqlite3.Connection

    def _write_scope(self) -> AbstractContextManager[object]: ...


class _PurgeCapableOrderRepository(Protocol):
    def purge_order(self, order_id: str) -> None: ...


_ForeignKeyViolation = tuple[str, int | None, str, int]


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _foreign_key_violations(
    connection: sqlite3.Connection,
) -> set[_ForeignKeyViolation]:
    return {
        (
            str(row[0]),
            int(row[1]) if row[1] is not None else None,
            str(row[2]),
            int(row[3]),
        )
        for row in connection.execute("PRAGMA foreign_key_check").fetchall()
    }


def _purge_new_fk_dependents(
    connection: sqlite3.Connection,
    baseline: set[_ForeignKeyViolation],
) -> None:
    """Delete rows orphaned transitively by the maintenance purge.

    Direct order-owned rows are discovered by ``order_id`` /
    ``order_version_id`` below. Some of those rows own child rows only through
    another key (for example snapshot_id). Deferred FK checking lets the root
    delete finish first; this loop then follows the actual FK violations until
    the whole dependent closure is gone.

    Pre-existing unrelated FK violations are deliberately left untouched.
    """

    while True:
        new_violations = _foreign_key_violations(connection) - baseline
        if not new_violations:
            return

        targets: set[tuple[str, int]] = set()
        for table_name, rowid, parent_table, fk_id in new_violations:
            if rowid is None:
                raise sqlite3.IntegrityError(
                    "maintenance purge cannot resolve dependent row in "
                    f"WITHOUT ROWID table {table_name!r} "
                    f"(parent={parent_table!r}, fk_id={fk_id})"
                )
            targets.add((table_name, rowid))

        deleted = 0
        for table_name, rowid in sorted(targets):
            deleted += connection.execute(
                f"DELETE FROM {_quote_identifier(table_name)} WHERE rowid = ?",
                (rowid,),
            ).rowcount

        if deleted == 0:
            raise sqlite3.IntegrityError(
                "maintenance purge could not remove newly orphaned FK dependents"
            )


def _sqlite_purge(repo: _SQLiteBackedOrderRepository, order_id: str) -> None:
    connection = repo._conn
    with repo._write_scope():
        # sqlite3 starts transactions lazily. `defer_foreign_keys` only applies
        # to the active transaction, so explicitly begin one in standalone
        # repository mode before enabling deferred FK validation. Core API mode
        # already enters this helper with its coordinator transaction active.
        if not connection.in_transaction:
            connection.execute("BEGIN")
        connection.execute("PRAGMA defer_foreign_keys = ON")
        baseline_fk_violations = _foreign_key_violations(connection)

        if (
            connection.execute(
                "SELECT 1 FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            is None
        ):
            raise KeyError(order_id)

        version_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT order_version_id FROM order_versions WHERE order_id = ?",
                (order_id,),
            ).fetchall()
        ]
        triggers = [
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'trigger' AND sql IS NOT NULL ORDER BY name"
            ).fetchall()
        ]
        for trigger_name, _trigger_sql in triggers:
            connection.execute(f"DROP TRIGGER {_quote_identifier(trigger_name)}")

        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table_name in tables:
            if table_name in {"orders", "order_versions"}:
                continue
            quoted_table = _quote_identifier(table_name)
            columns = {
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({quoted_table})"
                ).fetchall()
            }
            if "order_id" in columns:
                connection.execute(
                    f"DELETE FROM {quoted_table} WHERE order_id = ?", (order_id,)
                )
            if "order_version_id" in columns and version_ids:
                placeholders = ",".join("?" for _ in version_ids)
                connection.execute(
                    f"DELETE FROM {quoted_table} "
                    f"WHERE order_version_id IN ({placeholders})",
                    tuple(version_ids),
                )

        # Break root references before deleting immutable version history.
        connection.execute(
            "UPDATE orders SET candidate_order_version_id = NULL, "
            "effective_order_version_id = NULL WHERE order_id = ?",
            (order_id,),
        )
        connection.execute("DELETE FROM order_versions WHERE order_id = ?", (order_id,))
        deleted = connection.execute(
            "DELETE FROM orders WHERE order_id = ?", (order_id,)
        ).rowcount
        if deleted != 1:
            raise KeyError(order_id)

        _purge_new_fk_dependents(connection, baseline_fk_violations)

        for _trigger_name, trigger_sql in triggers:
            connection.execute(trigger_sql)


def purge_order_with_dependencies(repo: OrderRepository, order_id: str) -> None:
    """Purge one Order and every row directly or transitively owned by it.

    Inquiry/Offer rows are intentionally untouched because they are keyed by
    their own aggregate identifiers, not by ``order_id``.
    """
    connection = getattr(repo, "_conn", None)
    write_scope = getattr(repo, "_write_scope", None)
    if isinstance(connection, sqlite3.Connection) and callable(write_scope):
        _sqlite_purge(cast(_SQLiteBackedOrderRepository, repo), order_id)
        return
    purge = getattr(repo, "purge_order", None)
    if not callable(purge):
        raise TypeError("order repository does not support maintenance purge")
    cast(_PurgeCapableOrderRepository, repo).purge_order(order_id)

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


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlite_purge(repo: _SQLiteBackedOrderRepository, order_id: str) -> None:
    connection = repo._conn
    with repo._write_scope():
        # The purge spans many tables whose FK dependencies are not guaranteed
        # to follow sqlite_master ordering. Keep foreign_keys enabled, but defer
        # their validation until the surrounding atomic transaction commits.
        # This allows all owned rows to disappear before SQLite checks the final
        # graph and still fails closed if any reference survives the purge.
        connection.execute("PRAGMA defer_foreign_keys = ON")

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
            elif "order_version_id" in columns and version_ids:
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

        for _trigger_name, trigger_sql in triggers:
            connection.execute(trigger_sql)


def purge_order_with_dependencies(repo: OrderRepository, order_id: str) -> None:
    """Purge one Order and every row directly owned by its id/version ids.

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

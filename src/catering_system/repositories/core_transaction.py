"""Shared-connection transaction coordination for the Core Office API
(PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §6.1).

One SQLite connection, owned here, is shared by the inquiry repository, the
order repository, and the command ledger so that a precondition read, the
business write and the idempotency record are one atomic unit: either
everything is durable or nothing is. Repository methods run in their
externally-managed mode inside `CoreCommandExecutor.run` and must not
auto-commit.

Domain events are deferred: services `_emit` into a buffer during the
transaction and the buffer is flushed only after a successful COMMIT — an
event escaping a rolled-back transaction would announce a change that never
happened (pack §6.1, round-3 clarification).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

_BUSY_TIMEOUT_MS = 2000  # pack §6.4: below the panel's 5 s command timeout

T = TypeVar("T")


class CoreBusyError(Exception):
    """SQLite reported locked/busy after the busy timeout; the transaction
    was rolled back and nothing was written (maps to 503 core_busy)."""


def open_core_connection(db_path: str | Path) -> sqlite3.Connection:
    """Autocommit-mode connection: BEGIN/COMMIT are owned explicitly by
    CoreCommandExecutor, never implicitly by the sqlite3 module."""
    connection = sqlite3.connect(str(db_path), isolation_level=None)
    connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    return connection


def _is_busy(error: sqlite3.OperationalError) -> bool:
    text = str(error)
    return "database is locked" in text or "database is busy" in text


class DeferredEventSink:
    """Buffers domain events during a transaction; flushes post-commit."""

    def __init__(self, downstream: Callable[[object], None] | None = None) -> None:
        self._downstream = downstream
        self._buffer: list[object] = []

    def __call__(self, event: object) -> None:
        self._buffer.append(event)

    def flush(self) -> None:
        events, self._buffer = self._buffer, []
        if self._downstream is not None:
            for event in events:
                self._downstream(event)

    def discard(self) -> None:
        self._buffer = []


class CoreCommandExecutor:
    """Owns BEGIN IMMEDIATE / COMMIT / ROLLBACK on the shared connection."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        events: DeferredEventSink | None = None,
    ) -> None:
        self._conn = connection
        self._events = events if events is not None else DeferredEventSink()

    @property
    def events(self) -> DeferredEventSink:
        return self._events

    def run(self, work: Callable[[], T]) -> T:
        """One atomic command: precondition reads, business writes, ledger
        insert. Raises CoreBusyError on lock contention (nothing written)."""
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            self._events.discard()
            if _is_busy(exc):
                raise CoreBusyError from exc
            raise
        try:
            result = work()
        except sqlite3.OperationalError as exc:
            self._rollback()
            if _is_busy(exc):
                raise CoreBusyError from exc
            raise
        except BaseException:
            self._rollback()
            raise
        try:
            self._conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            self._rollback()
            if _is_busy(exc):
                raise CoreBusyError from exc
            raise
        self._events.flush()
        return result

    def _rollback(self) -> None:
        self._events.discard()
        try:
            self._conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass  # nothing to roll back (e.g. BEGIN itself failed)

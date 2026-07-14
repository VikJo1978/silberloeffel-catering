"""Idempotency ledger for the Core Office API
(PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §6.1).

Lives inside core.db so that the business write and the command record are
one SQLite transaction — a crash can never leave a committed change without
its ledger row (which would let a replay duplicate it). Stores only the
minimal PII-free command results of pack §4.4 (IDs and timestamps). No
automatic expiry in V1 (round-1 decision).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_LEDGER = """
CREATE TABLE IF NOT EXISTS office_api_commands (
    command_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    result_status INTEGER NOT NULL,
    result_body TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def _migration_1_create_ledger(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_LEDGER)


_MIGRATIONS = ((1, "create_command_ledger", _migration_1_create_ledger),)


def command_fingerprint(
    route_template: str,
    path_ids: dict[str, str],
    args: dict[str, object],
    expect: dict[str, object],
    client_id: str,
) -> str:
    """Canonical whole-command fingerprint (pack §6.1, round-2): the same
    command_id re-sent to a different route, order, args, expect, or by a
    different client must conflict, never replay."""
    canonical = json.dumps(
        {
            "route_template": route_template,
            "path_ids": path_ids,
            "args": args,
            "expect": expect,
            "client_id": client_id,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RecordedCommand:
    command_id: str
    fingerprint: str
    result_status: int
    result_body: str


class OfficeCommandLedger:
    """Reads/writes ledger rows on the shared connection; never commits —
    the CoreCommandExecutor owns the transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        apply_migrations(connection, "office_api", _MIGRATIONS)

    def get(self, command_id: str) -> RecordedCommand | None:
        row = self._conn.execute(
            "SELECT command_id, fingerprint, result_status, result_body "
            "FROM office_api_commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return RecordedCommand(
            command_id=row[0],
            fingerprint=row[1],
            result_status=row[2],
            result_body=row[3],
        )

    def record(
        self,
        command_id: str,
        fingerprint: str,
        result_status: int,
        result_body: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO office_api_commands VALUES (?, ?, ?, ?, ?)",
            (
                command_id,
                fingerprint,
                result_status,
                result_body,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

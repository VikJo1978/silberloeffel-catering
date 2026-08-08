"""Idempotency ledger for the Kitchen Print Agent HTTP API (Phase 3B)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from catering_system.repositories.sqlite_migrations import apply_migrations

KITCHEN_AGENT_CLIENT_ID = "kitchen-print-agent"

_CREATE_LEDGER = """
CREATE TABLE IF NOT EXISTS kitchen_api_commands (
    command_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    result_status INTEGER NOT NULL,
    result_body TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def _migration_1_create_kitchen_api_ledger(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_LEDGER)


_MIGRATIONS = (
    (1, "create_kitchen_api_ledger", _migration_1_create_kitchen_api_ledger),
)


def kitchen_command_fingerprint(
    *,
    route_template: str,
    command_id: str,
    args: dict[str, object] | None = None,
    client_id: str = KITCHEN_AGENT_CLIENT_ID,
) -> str:
    canonical = json.dumps(
        {
            "route_template": route_template,
            "command_id": command_id,
            "args": args or {},
            "client_id": client_id,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RecordedKitchenCommand:
    command_id: str
    fingerprint: str
    result_status: int
    result_body: str


class KitchenCommandLedger:
    """Reads/writes kitchen command rows on a shared SQLite connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        apply_migrations(connection, "kitchen_api", _MIGRATIONS)

    def get(self, command_id: str) -> RecordedKitchenCommand | None:
        row = self._conn.execute(
            "SELECT command_id, fingerprint, result_status, result_body "
            "FROM kitchen_api_commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return RecordedKitchenCommand(
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
            "INSERT INTO kitchen_api_commands VALUES (?, ?, ?, ?, ?)",
            (
                command_id,
                fingerprint,
                result_status,
                result_body,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


class InMemoryKitchenCommandLedger:
    def __init__(self) -> None:
        self._rows: dict[str, RecordedKitchenCommand] = {}

    def get(self, command_id: str) -> RecordedKitchenCommand | None:
        return self._rows.get(command_id)

    def record(
        self,
        command_id: str,
        fingerprint: str,
        result_status: int,
        result_body: str,
    ) -> None:
        self._rows[command_id] = RecordedKitchenCommand(
            command_id=command_id,
            fingerprint=fingerprint,
            result_status=result_status,
            result_body=result_body,
        )

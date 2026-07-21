"""SQLite adapter for append-only contact internal notes."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from catering_system.domain.contact_internal_note import (
    ContactInternalNote,
    validate_contact_internal_note_category,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS contact_internal_notes (
    note_id TEXT PRIMARY KEY,
    contact_key TEXT NOT NULL,
    category TEXT NOT NULL,
    note_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_contact_internal_notes_contact_created
ON contact_internal_notes (contact_key, created_at DESC)
"""

_APPEND_ONLY_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS trg_contact_internal_notes_no_update
    BEFORE UPDATE ON contact_internal_notes
    BEGIN SELECT RAISE(ABORT, 'contact internal notes are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_contact_internal_notes_no_delete
    BEFORE DELETE ON contact_internal_notes
    BEGIN SELECT RAISE(ABORT, 'contact internal notes are append-only'); END""",
)


def _migration_1_create_table(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_TABLE)
    connection.execute(_CREATE_INDEX)
    for trigger in _APPEND_ONLY_TRIGGERS:
        connection.execute(trigger)


_MIGRATIONS = ((1, "create_contact_internal_notes", _migration_1_create_table),)


class SQLiteContactInternalNoteRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "contact_internal_notes", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteContactInternalNoteRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "contact_internal_notes", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def add(self, note: ContactInternalNote) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO contact_internal_notes (
                    note_id, contact_key, category, note_text, created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    note.note_id,
                    note.contact_key,
                    note.category,
                    note.note_text,
                    note.created_at.isoformat(),
                    note.created_by,
                ),
            )

    def list_for_contact(self, contact_key: str) -> list[ContactInternalNote]:
        rows = self._conn.execute(
            """
            SELECT note_id, contact_key, category, note_text, created_at, created_by
            FROM contact_internal_notes
            WHERE contact_key = ?
            ORDER BY created_at DESC
            """,
            (contact_key,),
        ).fetchall()
        return [_row_to_note(row) for row in rows]


def _row_to_note(row: tuple[object, ...]) -> ContactInternalNote:
    return ContactInternalNote(
        note_id=str(row[0]),
        contact_key=str(row[1]),
        category=validate_contact_internal_note_category(str(row[2])),
        note_text=str(row[3]),
        created_at=datetime.fromisoformat(str(row[4])),
        created_by=str(row[5]),
    )

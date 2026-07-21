"""SQLite adapter for immutable contact profiles and aliases."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from catering_system.domain.contact_profile import (
    ContactProfile,
    ContactProfileAlias,
    ContactProfileAliasType,
)
from catering_system.intake.intake_contact import normalize_phone
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_PROFILES = """
CREATE TABLE IF NOT EXISTS contact_profiles (
    contact_profile_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    merged_into_id TEXT
)
"""

_CREATE_ALIASES = """
CREATE TABLE IF NOT EXISTS contact_profile_aliases (
    alias_type TEXT NOT NULL,
    alias_value TEXT NOT NULL,
    contact_profile_id TEXT NOT NULL,
    PRIMARY KEY (alias_type, alias_value),
    FOREIGN KEY (contact_profile_id) REFERENCES contact_profiles(contact_profile_id)
)
"""

_CREATE_INDEXES = (
    """CREATE INDEX IF NOT EXISTS idx_contact_profiles_search_name
    ON contact_profiles (display_name)""",
    """CREATE INDEX IF NOT EXISTS idx_contact_profiles_search_email
    ON contact_profiles (email)""",
    """CREATE INDEX IF NOT EXISTS idx_contact_profiles_search_phone
    ON contact_profiles (phone)""",
    """CREATE INDEX IF NOT EXISTS idx_contact_profiles_merged_into
    ON contact_profiles (merged_into_id)""",
)


def _migration_1_create_profiles(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_PROFILES)
    connection.execute(_CREATE_ALIASES)
    for statement in _CREATE_INDEXES:
        connection.execute(statement)


_MIGRATIONS = ((1, "create_contact_profiles", _migration_1_create_profiles),)


class SQLiteContactProfileRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "contact_profiles", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteContactProfileRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "contact_profiles", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def create_profile(self, profile: ContactProfile) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO contact_profiles (
                    contact_profile_id, display_name, email, phone,
                    created_at, updated_at, merged_into_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.contact_profile_id,
                    profile.display_name,
                    profile.email,
                    profile.phone,
                    profile.created_at.isoformat(),
                    profile.updated_at.isoformat(),
                    profile.merged_into_id,
                ),
            )

    def get_profile(self, contact_profile_id: str) -> ContactProfile | None:
        row = self._conn.execute(
            """
            SELECT contact_profile_id, display_name, email, phone,
                   created_at, updated_at, merged_into_id
            FROM contact_profiles WHERE contact_profile_id = ?
            """,
            (contact_profile_id,),
        ).fetchone()
        return _row_to_profile(row) if row else None

    def update_profile_fields(self, profile: ContactProfile) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                UPDATE contact_profiles
                SET display_name = ?, email = ?, phone = ?, updated_at = ?
                WHERE contact_profile_id = ?
                """,
                (
                    profile.display_name,
                    profile.email,
                    profile.phone,
                    profile.updated_at.isoformat(),
                    profile.contact_profile_id,
                ),
            )

    def mark_merged(self, contact_profile_id: str, *, merged_into_id: str) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                UPDATE contact_profiles
                SET merged_into_id = ?
                WHERE contact_profile_id = ?
                """,
                (merged_into_id, contact_profile_id),
            )

    def list_merged_into(self, contact_profile_id: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT contact_profile_id FROM contact_profiles
            WHERE merged_into_id = ?
            ORDER BY created_at, contact_profile_id
            """,
            (contact_profile_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def find_profile_id_by_alias(
        self, alias_type: ContactProfileAliasType, alias_value: str
    ) -> str | None:
        row = self._conn.execute(
            """
            SELECT contact_profile_id FROM contact_profile_aliases
            WHERE alias_type = ? AND alias_value = ?
            """,
            (alias_type, alias_value),
        ).fetchone()
        return str(row[0]) if row else None

    def upsert_alias(self, alias: ContactProfileAlias) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO contact_profile_aliases (
                    alias_type, alias_value, contact_profile_id
                ) VALUES (?, ?, ?)
                ON CONFLICT(alias_type, alias_value) DO UPDATE SET
                    contact_profile_id = excluded.contact_profile_id
                """,
                (alias.alias_type, alias.alias_value, alias.contact_profile_id),
            )

    def search_profile_ids(self, q: str) -> list[str]:
        needle = q.strip()
        if not needle:
            rows = self._conn.execute(
                """
                SELECT contact_profile_id FROM contact_profiles
                WHERE merged_into_id IS NULL
                ORDER BY updated_at DESC, contact_profile_id
                """
            ).fetchall()
            return [str(row[0]) for row in rows]

        like = f"%{needle.casefold()}%"
        phone = normalize_phone(needle)
        rows = self._conn.execute(
            """
            SELECT contact_profile_id FROM contact_profiles
            WHERE merged_into_id IS NULL
              AND (
                lower(display_name) LIKE ?
                OR lower(COALESCE(email, '')) LIKE ?
                OR lower(COALESCE(phone, '')) LIKE ?
                OR (? != '' AND phone = ?)
              )
            ORDER BY updated_at DESC, contact_profile_id
            """,
            (like, like, like, phone, phone),
        ).fetchall()
        return [str(row[0]) for row in rows]


def _row_to_profile(row: tuple[object, ...]) -> ContactProfile:
    return ContactProfile(
        contact_profile_id=str(row[0]),
        display_name=str(row[1]),
        email=str(row[2]) if row[2] is not None else None,
        phone=str(row[3]) if row[3] is not None else None,
        created_at=datetime.fromisoformat(str(row[4])),
        updated_at=datetime.fromisoformat(str(row[5])),
        merged_into_id=str(row[6]) if row[6] is not None else None,
    )

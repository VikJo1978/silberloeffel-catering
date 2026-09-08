"""Ephemeral multi-user edit coordination for the Office Panel.

This is deliberately not a business lock.  Inquiry/Offer/Order optimistic
preconditions remain authoritative.  The lease only prevents two employees
from unknowingly spending time editing the same Office record.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterator, Literal, cast

from catering_system.repositories.sqlite_migrations import apply_migrations

OfficeEditEntityType = Literal["inquiry", "offer", "order"]
_ENTITY_TYPES = frozenset({"inquiry", "offer", "order"})
_DEFAULT_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class OfficeEditLease:
    entity_type: OfficeEditEntityType
    entity_id: str
    holder_account_id: str
    holder_display_name: str
    acquired_at: datetime
    renewed_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class OfficeEditLeaseClaim:
    lease: OfficeEditLease
    owned_by_requester: bool


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS office_edit_leases (
    entity_type TEXT NOT NULL CHECK (entity_type IN ('inquiry', 'offer', 'order')),
    entity_id TEXT NOT NULL,
    holder_account_id TEXT NOT NULL,
    holder_display_name TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
)
"""

_CREATE_EXPIRY_INDEX = """
CREATE INDEX IF NOT EXISTS idx_office_edit_leases_expires_at
ON office_edit_leases (expires_at)
"""


def _migration_1(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_TABLE)
    connection.execute(_CREATE_EXPIRY_INDEX)


_MIGRATIONS = ((1, "create_office_edit_leases", _migration_1),)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _entity_type(value: str) -> OfficeEditEntityType:
    if value not in _ENTITY_TYPES:
        raise ValueError(f"unsupported office edit entity type: {value!r}")
    return cast(OfficeEditEntityType, value)


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("office edit lease timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


class SQLiteOfficeEditLeaseRepository:
    """Small component-scoped lease store sharing the Office auth connection."""

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteOfficeEditLeaseRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        apply_migrations(connection, "office_edit_lease", _MIGRATIONS)
        return repo

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        apply_migrations(self._conn, "office_edit_lease", _MIGRATIONS)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def claim_or_observe(
        self,
        entity_type: str,
        entity_id: str,
        *,
        holder_account_id: str,
        holder_display_name: str,
        now: datetime | None = None,
        ttl: timedelta = _DEFAULT_TTL,
    ) -> OfficeEditLeaseClaim:
        kind = _entity_type(entity_type)
        record_id = _required(entity_id, "entity_id")
        account_id = _required(holder_account_id, "holder_account_id")
        display_name = _required(holder_display_name, "holder_display_name")
        current_time = (now or _utc_now()).astimezone(UTC)
        if ttl <= timedelta(0):
            raise ValueError("office edit lease ttl must be positive")

        with self._transaction():
            existing = self._get(kind, record_id)
            if existing is None or existing.expires_at <= current_time:
                lease = OfficeEditLease(
                    entity_type=kind,
                    entity_id=record_id,
                    holder_account_id=account_id,
                    holder_display_name=display_name,
                    acquired_at=current_time,
                    renewed_at=current_time,
                    expires_at=current_time + ttl,
                )
                self._upsert(lease)
                return OfficeEditLeaseClaim(lease=lease, owned_by_requester=True)

            if existing.holder_account_id == account_id:
                renewed = OfficeEditLease(
                    entity_type=existing.entity_type,
                    entity_id=existing.entity_id,
                    holder_account_id=account_id,
                    holder_display_name=display_name,
                    acquired_at=existing.acquired_at,
                    renewed_at=current_time,
                    expires_at=current_time + ttl,
                )
                self._upsert(renewed)
                return OfficeEditLeaseClaim(lease=renewed, owned_by_requester=True)

            return OfficeEditLeaseClaim(
                lease=existing,
                owned_by_requester=False,
            )

    def takeover(
        self,
        entity_type: str,
        entity_id: str,
        *,
        holder_account_id: str,
        holder_display_name: str,
        now: datetime | None = None,
        ttl: timedelta = _DEFAULT_TTL,
    ) -> OfficeEditLease:
        kind = _entity_type(entity_type)
        record_id = _required(entity_id, "entity_id")
        account_id = _required(holder_account_id, "holder_account_id")
        display_name = _required(holder_display_name, "holder_display_name")
        current_time = (now or _utc_now()).astimezone(UTC)
        if ttl <= timedelta(0):
            raise ValueError("office edit lease ttl must be positive")
        lease = OfficeEditLease(
            entity_type=kind,
            entity_id=record_id,
            holder_account_id=account_id,
            holder_display_name=display_name,
            acquired_at=current_time,
            renewed_at=current_time,
            expires_at=current_time + ttl,
        )
        with self._transaction():
            self._upsert(lease)
        return lease

    def release(
        self,
        entity_type: str,
        entity_id: str,
        *,
        holder_account_id: str,
    ) -> bool:
        kind = _entity_type(entity_type)
        record_id = _required(entity_id, "entity_id")
        account_id = _required(holder_account_id, "holder_account_id")
        with self._transaction():
            deleted = self._conn.execute(
                """
                DELETE FROM office_edit_leases
                WHERE entity_type = ? AND entity_id = ? AND holder_account_id = ?
                """,
                (kind, record_id, account_id),
            ).rowcount
        return deleted == 1

    def get_active(
        self,
        entity_type: str,
        entity_id: str,
        *,
        now: datetime | None = None,
    ) -> OfficeEditLease | None:
        kind = _entity_type(entity_type)
        record_id = _required(entity_id, "entity_id")
        current_time = (now or _utc_now()).astimezone(UTC)
        existing = self._get(kind, record_id)
        if existing is None or existing.expires_at <= current_time:
            return None
        return existing

    def _get(
        self, entity_type: OfficeEditEntityType, entity_id: str
    ) -> OfficeEditLease | None:
        row = self._conn.execute(
            """
            SELECT entity_type, entity_id, holder_account_id, holder_display_name,
                   acquired_at, renewed_at, expires_at
            FROM office_edit_leases
            WHERE entity_type = ? AND entity_id = ?
            """,
            (entity_type, entity_id),
        ).fetchone()
        if row is None:
            return None
        return OfficeEditLease(
            entity_type=_entity_type(str(row[0])),
            entity_id=str(row[1]),
            holder_account_id=str(row[2]),
            holder_display_name=str(row[3]),
            acquired_at=_parse_timestamp(str(row[4])),
            renewed_at=_parse_timestamp(str(row[5])),
            expires_at=_parse_timestamp(str(row[6])),
        )

    def _upsert(self, lease: OfficeEditLease) -> None:
        self._conn.execute(
            """
            INSERT INTO office_edit_leases (
                entity_type, entity_id, holder_account_id, holder_display_name,
                acquired_at, renewed_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                holder_account_id = excluded.holder_account_id,
                holder_display_name = excluded.holder_display_name,
                acquired_at = excluded.acquired_at,
                renewed_at = excluded.renewed_at,
                expires_at = excluded.expires_at
            """,
            (
                lease.entity_type,
                lease.entity_id,
                lease.holder_account_id,
                lease.holder_display_name,
                lease.acquired_at.isoformat(),
                lease.renewed_at.isoformat(),
                lease.expires_at.isoformat(),
            ),
        )

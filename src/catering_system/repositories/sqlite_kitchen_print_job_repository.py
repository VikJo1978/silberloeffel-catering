"""SQLite persistence for Phase 3 kitchen print attempts.

The component owns only attempt facts. The atomic acknowledgement method also
updates the existing ``order_versions.kitchen_print_confirmed_at`` fact in the
same SQLite transaction; no second store or status column is introduced.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Iterator

from catering_system.domain.kitchen_print_job import (
    KITCHEN_PRINT_REJECTION_CODES,
    KitchenPrintJob,
    KitchenPrintPolicy,
    validate_kitchen_print_job_transition,
)
from catering_system.domain.order import OrderVersion
from catering_system.repositories.sqlite_migrations import apply_migrations

_REJECTION_CODES_SQL = ", ".join(
    f"'{code}'" for code in sorted(KITCHEN_PRINT_REJECTION_CODES)
)

_CREATE_JOBS = f"""
CREATE TABLE kitchen_print_jobs (
    print_job_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    order_version_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    requested_at TEXT NOT NULL,
    accept_deadline_at TEXT NOT NULL,
    accepted_at TEXT,
    ack_deadline_at TEXT,
    rejected_at TEXT,
    rejection_code TEXT CHECK (
        rejection_code IS NULL OR rejection_code IN ({_REJECTION_CODES_SQL})
    ),
    acknowledged_at TEXT,
    superseded_at TEXT,
    supersedes_print_job_id TEXT,
    CHECK (
        julianday(requested_at) IS NOT NULL
        AND substr(requested_at, -6) = '+00:00'
        AND julianday(accept_deadline_at) IS NOT NULL
        AND substr(accept_deadline_at, -6) = '+00:00'
        AND julianday(accept_deadline_at) > julianday(requested_at)
    ),
    CHECK (
        accepted_at IS NULL OR (
            julianday(accepted_at) IS NOT NULL
            AND substr(accepted_at, -6) = '+00:00'
            AND julianday(accepted_at) >= julianday(requested_at)
        )
    ),
    CHECK (
        ack_deadline_at IS NULL OR (
            julianday(ack_deadline_at) IS NOT NULL
            AND substr(ack_deadline_at, -6) = '+00:00'
            AND julianday(ack_deadline_at) > julianday(accepted_at)
        )
    ),
    CHECK (
        rejected_at IS NULL OR (
            julianday(rejected_at) IS NOT NULL
            AND substr(rejected_at, -6) = '+00:00'
            AND julianday(rejected_at) >= julianday(requested_at)
            AND (
                accepted_at IS NULL
                OR julianday(rejected_at) >= julianday(accepted_at)
            )
        )
    ),
    CHECK (
        acknowledged_at IS NULL OR (
            julianday(acknowledged_at) IS NOT NULL
            AND substr(acknowledged_at, -6) = '+00:00'
            AND julianday(acknowledged_at) >= julianday(accepted_at)
        )
    ),
    CHECK (
        superseded_at IS NULL OR (
            julianday(superseded_at) IS NOT NULL
            AND substr(superseded_at, -6) = '+00:00'
            AND julianday(superseded_at) >= julianday(requested_at)
        )
    ),
    CHECK ((accepted_at IS NULL) = (ack_deadline_at IS NULL)),
    CHECK ((rejected_at IS NULL) = (rejection_code IS NULL)),
    CHECK (
        acknowledged_at IS NULL OR (
            accepted_at IS NOT NULL
            AND rejected_at IS NULL
            AND superseded_at IS NULL
        )
    ),
    CHECK (
        superseded_at IS NULL OR (
            rejected_at IS NULL
            AND acknowledged_at IS NULL
        )
    )
)
"""

_TRIGGERS = (
    """CREATE TRIGGER kitchen_print_job_owner_insert
    BEFORE INSERT ON kitchen_print_jobs
    WHEN NOT EXISTS (
        SELECT 1 FROM orders o
        JOIN order_versions v ON v.order_id = o.order_id
        WHERE o.order_id = NEW.order_id
          AND v.order_version_id = NEW.order_version_id
    )
    BEGIN SELECT RAISE(ABORT, 'print job order/version ownership is invalid'); END""",
    """CREATE TRIGGER kitchen_print_job_attempt_chain_insert
    BEFORE INSERT ON kitchen_print_jobs
    WHEN (
        NEW.supersedes_print_job_id IS NULL
        AND NEW.attempt_number <> 1
    ) OR (
        NEW.supersedes_print_job_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM kitchen_print_jobs previous
            WHERE previous.print_job_id = NEW.supersedes_print_job_id
              AND previous.order_version_id = NEW.order_version_id
              AND previous.attempt_number + 1 = NEW.attempt_number
        )
    )
    BEGIN SELECT RAISE(ABORT, 'print job attempt chain is invalid'); END""",
    """CREATE TRIGGER kitchen_print_job_immutable_update
    BEFORE UPDATE ON kitchen_print_jobs
    WHEN NEW.print_job_id IS NOT OLD.print_job_id
      OR NEW.order_id IS NOT OLD.order_id
      OR NEW.order_version_id IS NOT OLD.order_version_id
      OR NEW.attempt_number IS NOT OLD.attempt_number
      OR NEW.requested_at IS NOT OLD.requested_at
      OR NEW.accept_deadline_at IS NOT OLD.accept_deadline_at
      OR NEW.supersedes_print_job_id IS NOT OLD.supersedes_print_job_id
      OR (OLD.accepted_at IS NOT NULL AND NEW.accepted_at IS NOT OLD.accepted_at)
      OR (OLD.ack_deadline_at IS NOT NULL AND NEW.ack_deadline_at IS NOT OLD.ack_deadline_at)
      OR (OLD.rejected_at IS NOT NULL AND NEW.rejected_at IS NOT OLD.rejected_at)
      OR (OLD.rejection_code IS NOT NULL AND NEW.rejection_code IS NOT OLD.rejection_code)
      OR (OLD.acknowledged_at IS NOT NULL AND NEW.acknowledged_at IS NOT OLD.acknowledged_at)
      OR (OLD.superseded_at IS NOT NULL AND NEW.superseded_at IS NOT OLD.superseded_at)
    BEGIN SELECT RAISE(ABORT, 'print job facts are immutable once recorded'); END""",
    """CREATE TRIGGER kitchen_print_job_no_delete
    BEFORE DELETE ON kitchen_print_jobs
    BEGIN SELECT RAISE(ABORT, 'print job attempt history cannot be deleted'); END""",
    """CREATE TRIGGER kitchen_print_job_version_no_delete
    BEFORE DELETE ON order_versions
    WHEN EXISTS (
        SELECT 1 FROM kitchen_print_jobs
        WHERE order_version_id = OLD.order_version_id
    )
    BEGIN SELECT RAISE(ABORT, 'order version has print job history'); END""",
    """CREATE TRIGGER kitchen_print_job_version_no_move
    BEFORE UPDATE OF order_version_id, order_id ON order_versions
    WHEN EXISTS (
        SELECT 1 FROM kitchen_print_jobs
        WHERE order_version_id = OLD.order_version_id
    ) AND (
        NEW.order_version_id IS NOT OLD.order_version_id
        OR NEW.order_id IS NOT OLD.order_id
    )
    BEGIN SELECT RAISE(ABORT, 'order version has print job history'); END""",
)


def _migration_1_create_kitchen_print_jobs(connection: sqlite3.Connection) -> None:
    required = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('orders', 'order_versions')"
        ).fetchall()
    }
    if required != {"orders", "order_versions"}:
        raise ValueError("kitchen_print migration requires existing order tables")
    connection.execute(_CREATE_JOBS)
    connection.execute(
        "CREATE UNIQUE INDEX uq_kitchen_print_attempt "
        "ON kitchen_print_jobs (order_version_id, attempt_number)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX uq_kitchen_print_live_job "
        "ON kitchen_print_jobs (order_version_id) "
        "WHERE acknowledged_at IS NULL "
        "AND rejected_at IS NULL AND superseded_at IS NULL"
    )
    connection.execute(
        "CREATE INDEX idx_kitchen_print_order "
        "ON kitchen_print_jobs (order_id, order_version_id, attempt_number)"
    )
    connection.execute(
        "CREATE INDEX idx_kitchen_print_version_requested "
        "ON kitchen_print_jobs (order_version_id, requested_at)"
    )
    connection.execute(
        "CREATE INDEX idx_kitchen_print_open_deadlines "
        "ON kitchen_print_jobs (ack_deadline_at, accept_deadline_at, order_version_id) "
        "WHERE acknowledged_at IS NULL "
        "AND rejected_at IS NULL AND superseded_at IS NULL"
    )
    for trigger in _TRIGGERS:
        connection.execute(trigger)


_MIGRATIONS = (
    (1, "create_kitchen_print_jobs", _migration_1_create_kitchen_print_jobs),
)


class SQLiteKitchenPrintJobRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        self._transaction_depth = 0
        try:
            apply_migrations(self._conn, "kitchen_print", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteKitchenPrintJobRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        repo._transaction_depth = 0
        apply_migrations(connection, "kitchen_print", _MIGRATIONS)
        return repo

    @contextmanager
    def _immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        if not self._manage_transactions:
            yield self._conn
            return
        self._transaction_depth += 1
        if self._transaction_depth == 1:
            self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
            if self._transaction_depth == 1:
                self._conn.commit()
        except Exception:
            if self._transaction_depth == 1:
                self._conn.rollback()
            raise
        finally:
            self._transaction_depth -= 1

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def save(self, job: KitchenPrintJob) -> None:
        with self._write_scope():
            self._insert(job)

    def get(self, print_job_id: str) -> KitchenPrintJob | None:
        row = self._conn.execute(
            "SELECT * FROM kitchen_print_jobs WHERE print_job_id = ?",
            (print_job_id,),
        ).fetchone()
        return self._row_to_job(row) if row is not None else None

    def list_for_version(self, order_version_id: str) -> list[KitchenPrintJob]:
        rows = self._conn.execute(
            "SELECT * FROM kitchen_print_jobs WHERE order_version_id = ? "
            "ORDER BY attempt_number",
            (order_version_id,),
        ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def list_for_order(self, order_id: str) -> list[KitchenPrintJob]:
        rows = self._conn.execute(
            "SELECT * FROM kitchen_print_jobs WHERE order_id = ? "
            "ORDER BY order_version_id, attempt_number",
            (order_id,),
        ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def update(self, job: KitchenPrintJob) -> None:
        previous = self.get(job.print_job_id)
        if previous is None:
            raise KeyError(job.print_job_id)
        validate_kitchen_print_job_transition(previous, job)
        with self._write_scope():
            self._update_facts(job)

    def save_reprint(
        self,
        previous: KitchenPrintJob,
        updated_previous: KitchenPrintJob | None,
        new_job: KitchenPrintJob,
    ) -> None:
        stored = self.get(previous.print_job_id)
        if stored != previous:
            raise ValueError("stale previous print job")
        if new_job.supersedes_print_job_id != previous.print_job_id:
            raise ValueError("reprint must reference the previous print job")
        if updated_previous is not None:
            validate_kitchen_print_job_transition(previous, updated_previous)
        with self._write_scope():
            if updated_previous is not None:
                self._update_facts(updated_previous)
            self._insert(new_job)

    def acknowledge_and_confirm(
        self, job: KitchenPrintJob, confirmed_version: OrderVersion
    ) -> None:
        previous_job = self.get(job.print_job_id)
        if previous_job is None:
            raise KeyError(job.print_job_id)
        validate_kitchen_print_job_transition(previous_job, job)
        if job.acknowledged_at is None:
            raise ValueError("atomic confirmation requires acknowledged_at")
        if (
            confirmed_version.order_id != job.order_id
            or confirmed_version.order_version_id != job.order_version_id
        ):
            raise ValueError("confirmed version does not belong to print job")

        current = self._conn.execute(
            "SELECT kitchen_print_confirmed_at FROM order_versions "
            "WHERE order_version_id = ? AND order_id = ?",
            (job.order_version_id, job.order_id),
        ).fetchone()
        if current is None:
            raise KeyError(job.order_version_id)
        current_confirmation = _dt(current[0]) if current[0] is not None else None
        if current_confirmation is None:
            if confirmed_version.kitchen_print_confirmed_at != job.acknowledged_at:
                raise ValueError("confirmation facts must share one timestamp")
        elif confirmed_version.kitchen_print_confirmed_at != current_confirmation:
            raise ValueError("existing kitchen confirmation is not revocable")

        with self._write_scope():
            if current_confirmation is None:
                updated = self._conn.execute(
                    "UPDATE order_versions SET kitchen_print_confirmed_at = ? "
                    "WHERE order_version_id = ? AND order_id = ? "
                    "AND kitchen_print_confirmed_at IS NULL",
                    (
                        job.acknowledged_at.isoformat(),
                        job.order_version_id,
                        job.order_id,
                    ),
                ).rowcount
                if updated != 1:
                    raise ValueError("stale kitchen print confirmation")
            self._update_facts(job)

    def claim_next_eligible(
        self, now: datetime, policy: KitchenPrintPolicy
    ) -> KitchenPrintJob | None:
        now_iso = now.isoformat()
        ack_deadline_at = now + policy.acknowledgment_timeout
        ack_deadline_iso = ack_deadline_at.isoformat()
        with self._immediate_transaction():
            row = self._conn.execute(
                """
                SELECT * FROM kitchen_print_jobs
                WHERE acknowledged_at IS NULL
                  AND rejected_at IS NULL
                  AND superseded_at IS NULL
                  AND accepted_at IS NULL
                  AND julianday(accept_deadline_at) > julianday(?)
                ORDER BY accept_deadline_at ASC, requested_at ASC, print_job_id ASC
                LIMIT 1
                """,
                (now_iso,),
            ).fetchone()
            if row is None:
                return None
            job = self._row_to_job(row)
            updated = self._conn.execute(
                """
                UPDATE kitchen_print_jobs
                SET accepted_at = ?, ack_deadline_at = ?
                WHERE print_job_id = ?
                  AND accepted_at IS NULL
                  AND rejected_at IS NULL
                  AND superseded_at IS NULL
                  AND acknowledged_at IS NULL
                """,
                (now_iso, ack_deadline_iso, job.print_job_id),
            ).rowcount
            if updated != 1:
                return None
        return replace(
            job,
            accepted_at=now,
            ack_deadline_at=ack_deadline_at,
        )

    def _insert(self, job: KitchenPrintJob) -> None:
        self._conn.execute(
            "INSERT INTO kitchen_print_jobs VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            self._values(job),
        )

    def _update_facts(self, job: KitchenPrintJob) -> None:
        updated = self._conn.execute(
            """
            UPDATE kitchen_print_jobs SET
                accepted_at = ?, ack_deadline_at = ?,
                rejected_at = ?, rejection_code = ?,
                acknowledged_at = ?, superseded_at = ?
            WHERE print_job_id = ?
            """,
            (
                _iso(job.accepted_at),
                _iso(job.ack_deadline_at),
                _iso(job.rejected_at),
                job.rejection_code,
                _iso(job.acknowledged_at),
                _iso(job.superseded_at),
                job.print_job_id,
            ),
        ).rowcount
        if updated != 1:
            raise KeyError(job.print_job_id)

    @staticmethod
    def _values(job: KitchenPrintJob) -> tuple[object, ...]:
        return (
            job.print_job_id,
            job.order_id,
            job.order_version_id,
            job.attempt_number,
            job.requested_at.isoformat(),
            job.accept_deadline_at.isoformat(),
            _iso(job.accepted_at),
            _iso(job.ack_deadline_at),
            _iso(job.rejected_at),
            job.rejection_code,
            _iso(job.acknowledged_at),
            _iso(job.superseded_at),
            job.supersedes_print_job_id,
        )

    @staticmethod
    def _row_to_job(row: tuple[object, ...]) -> KitchenPrintJob:
        return KitchenPrintJob(
            print_job_id=str(row[0]),
            order_id=str(row[1]),
            order_version_id=str(row[2]),
            attempt_number=int(str(row[3])),
            requested_at=_dt(str(row[4])),
            accept_deadline_at=_dt(str(row[5])),
            accepted_at=_dt(str(row[6])) if row[6] is not None else None,
            ack_deadline_at=_dt(str(row[7])) if row[7] is not None else None,
            rejected_at=_dt(str(row[8])) if row[8] is not None else None,
            rejection_code=str(row[9]) if row[9] is not None else None,
            acknowledged_at=_dt(str(row[10])) if row[10] is not None else None,
            superseded_at=_dt(str(row[11])) if row[11] is not None else None,
            supersedes_print_job_id=str(row[12]) if row[12] is not None else None,
        )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)

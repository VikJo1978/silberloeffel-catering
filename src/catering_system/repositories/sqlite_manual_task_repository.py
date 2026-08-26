"""SQLite adapter for persisted manual office tasks."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from catering_system.domain.manual_task import (
    ManualTask,
    ManualTaskSubjectType,
    validate_manual_task,
    validate_manual_task_subject_type,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS manual_tasks (
    task_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    due_at TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    created_by_employee_id TEXT NOT NULL,
    assigned_to_employee_id TEXT,
    subject_type TEXT NOT NULL,
    subject_id TEXT,
    CHECK (subject_type IN ('NONE', 'ORDER', 'INQUIRY', 'CONTACT')),
    CHECK (
        (subject_type = 'NONE' AND subject_id IS NULL)
        OR (subject_type <> 'NONE' AND subject_id IS NOT NULL)
    )
)
"""

_INDEXES = (
    """
    CREATE INDEX IF NOT EXISTS idx_manual_tasks_open
    ON manual_tasks (completed_at, due_at, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_manual_tasks_subject
    ON manual_tasks (subject_type, subject_id, completed_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_manual_tasks_assignee
    ON manual_tasks (assigned_to_employee_id, completed_at)
    """,
)

_COMPLETION_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS trg_manual_tasks_completion_no_rewrite
    BEFORE UPDATE OF completed_at ON manual_tasks
    WHEN OLD.completed_at IS NOT NULL
      AND NEW.completed_at IS NOT OLD.completed_at
    BEGIN SELECT RAISE(ABORT, 'manual task completion cannot be rewritten'); END
    """,
)


def _migration_1_create_manual_tasks(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_TABLE)
    for statement in _INDEXES:
        connection.execute(statement)
    for trigger in _COMPLETION_TRIGGERS:
        connection.execute(trigger)


_MIGRATIONS = ((1, "create_manual_tasks", _migration_1_create_manual_tasks),)


def _apply_migrations_in_current_transaction(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (component, version)
        )
        """
    )
    existing = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT version, name FROM schema_migrations WHERE component = ?",
            ("manual_tasks",),
        ).fetchall()
    }
    for version, name, apply in _MIGRATIONS:
        if version in existing:
            if existing[version] != name:
                raise RuntimeError(
                    "manual_tasks migration "
                    f"{version} name mismatch: database={existing[version]!r}, code={name!r}"
                )
            continue
        apply(connection)
        connection.execute(
            "INSERT INTO schema_migrations (component, version, name, applied_at) "
            "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            ("manual_tasks", version, name),
        )


class SQLiteManualTaskRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "manual_tasks", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteManualTaskRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        if connection.in_transaction:
            _apply_migrations_in_current_transaction(connection)
        else:
            apply_migrations(connection, "manual_tasks", _MIGRATIONS)
        return repo

    def _write_scope(self):
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def get(self, task_id: str) -> ManualTask | None:
        row = self._conn.execute(
            """
            SELECT task_id, title, description, due_at, created_at, completed_at,
                   created_by_employee_id, assigned_to_employee_id,
                   subject_type, subject_id
            FROM manual_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        return _row_to_task(row) if row else None

    def save(self, task: ManualTask) -> None:
        validated = validate_manual_task(task)
        self._ensure_subject_exists(validated.subject_type, validated.subject_id)
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO manual_tasks (
                    task_id, title, description, due_at, created_at, completed_at,
                    created_by_employee_id, assigned_to_employee_id,
                    subject_type, subject_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    due_at = excluded.due_at,
                    created_at = excluded.created_at,
                    completed_at = excluded.completed_at,
                    created_by_employee_id = excluded.created_by_employee_id,
                    assigned_to_employee_id = excluded.assigned_to_employee_id,
                    subject_type = excluded.subject_type,
                    subject_id = excluded.subject_id
                """,
                _values(validated),
            )

    def list_open(self) -> list[ManualTask]:
        rows = self._conn.execute(
            """
            SELECT task_id, title, description, due_at, created_at, completed_at,
                   created_by_employee_id, assigned_to_employee_id,
                   subject_type, subject_id
            FROM manual_tasks
            WHERE completed_at IS NULL
            ORDER BY due_at IS NULL, due_at, created_at, task_id
            """
        ).fetchall()
        return [_row_to_task(row) for row in rows]

    def list_for_subject(
        self, subject_type: ManualTaskSubjectType, subject_id: str
    ) -> list[ManualTask]:
        typed_subject = validate_manual_task_subject_type(subject_type)
        rows = self._conn.execute(
            """
            SELECT task_id, title, description, due_at, created_at, completed_at,
                   created_by_employee_id, assigned_to_employee_id,
                   subject_type, subject_id
            FROM manual_tasks
            WHERE subject_type = ? AND subject_id = ?
            ORDER BY due_at IS NULL, due_at, created_at, task_id
            """,
            (typed_subject, subject_id),
        ).fetchall()
        return [_row_to_task(row) for row in rows]

    def complete(self, task_id: str, completed_at: datetime) -> ManualTask:
        current = self.get(task_id)
        if current is None:
            raise KeyError(task_id)
        if current.completed_at is not None:
            return current
        completed = validate_manual_task(
            ManualTask(
                task_id=current.task_id,
                title=current.title,
                description=current.description,
                due_at=current.due_at,
                created_at=current.created_at,
                completed_at=completed_at,
                created_by_employee_id=current.created_by_employee_id,
                assigned_to_employee_id=current.assigned_to_employee_id,
                subject_type=current.subject_type,
                subject_id=current.subject_id,
            )
        )
        completed_timestamp = completed.completed_at
        assert completed_timestamp is not None
        with self._write_scope():
            updated = self._conn.execute(
                """
                UPDATE manual_tasks
                SET completed_at = ?
                WHERE task_id = ? AND completed_at IS NULL
                """,
                (completed_timestamp.isoformat(), task_id),
            ).rowcount
        if updated == 0:
            existing = self.get(task_id)
            if existing is None:
                raise KeyError(task_id)
            return existing
        return completed

    def _ensure_subject_exists(
        self, subject_type: ManualTaskSubjectType, subject_id: str | None
    ) -> None:
        if subject_type == "NONE":
            return
        assert subject_id is not None
        table, column = _SUBJECT_TABLES[subject_type]
        try:
            row = self._conn.execute(
                f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1",
                (subject_id,),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                raise sqlite3.IntegrityError(
                    f"manual task {subject_type.lower()} subject table does not exist"
                ) from exc
            raise
        if row is None:
            raise sqlite3.IntegrityError(
                f"manual task {subject_type.lower()} subject does not exist"
            )


def _values(task: ManualTask) -> tuple[object, ...]:
    return (
        task.task_id,
        task.title,
        task.description,
        task.due_at.isoformat() if task.due_at is not None else None,
        task.created_at.isoformat(),
        task.completed_at.isoformat() if task.completed_at is not None else None,
        task.created_by_employee_id,
        task.assigned_to_employee_id,
        task.subject_type,
        task.subject_id,
    )


_SUBJECT_TABLES = {
    "ORDER": ("orders", "order_id"),
    "INQUIRY": ("inquiries", "inquiry_id"),
    "CONTACT": ("contact_profiles", "contact_profile_id"),
}


def _row_to_task(row: tuple[object, ...]) -> ManualTask:
    return validate_manual_task(
        ManualTask(
            task_id=str(row[0]),
            title=str(row[1]),
            description=str(row[2]),
            due_at=datetime.fromisoformat(str(row[3])) if row[3] is not None else None,
            created_at=datetime.fromisoformat(str(row[4])),
            completed_at=(
                datetime.fromisoformat(str(row[5])) if row[5] is not None else None
            ),
            created_by_employee_id=str(row[6]),
            assigned_to_employee_id=str(row[7]) if row[7] is not None else None,
            subject_type=validate_manual_task_subject_type(str(row[8])),
            subject_id=str(row[9]) if row[9] is not None else None,
        )
    )

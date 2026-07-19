"""Small component-scoped SQLite migration runner.

Repositories share one Core database but evolve independently. Each component
records monotonically increasing migrations in the same schema_migrations table.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]

_MIGRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    component TEXT NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    PRIMARY KEY (component, version)
)
"""


def apply_migrations(
    connection: sqlite3.Connection,
    component: str,
    migrations: Sequence[Migration],
) -> None:
    """Apply pending migrations once, transactionally and in version order."""
    ordered = sorted(migrations, key=lambda migration: migration[0])
    versions = [version for version, _name, _apply in ordered]
    if versions != list(range(1, len(ordered) + 1)):
        raise ValueError(f"{component} migrations must be contiguous from version 1")

    connection.execute(_MIGRATIONS_SCHEMA)
    applied = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT version, name FROM schema_migrations WHERE component = ?",
            (component,),
        ).fetchall()
    }
    unknown = set(applied).difference(versions)
    if unknown:
        raise RuntimeError(
            f"database has unknown {component} migration versions: {sorted(unknown)}"
        )
    applied_versions = sorted(applied)
    if applied_versions != versions[: len(applied_versions)]:
        raise RuntimeError(
            f"database has incomplete {component} migration history: {applied_versions}"
        )

    for version, name, apply in ordered:
        if version in applied:
            if applied[version] != name:
                raise RuntimeError(
                    f"{component} migration {version} name mismatch: "
                    f"database={applied[version]!r}, code={name!r}"
                )
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing = connection.execute(
                "SELECT name FROM schema_migrations "
                "WHERE component = ? AND version = ?",
                (component, version),
            ).fetchone()
            if existing is not None:
                if existing[0] != name:
                    raise RuntimeError(
                        f"{component} migration {version} name mismatch: "
                        f"database={existing[0]!r}, code={name!r}"
                    )
                connection.rollback()
                applied[version] = name
                continue
            apply(connection)
            connection.execute(
                "INSERT INTO schema_migrations "
                "(component, version, name, applied_at) "
                "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (component, version, name),
            )
        except sqlite3.IntegrityError:
            connection.rollback()
            existing = connection.execute(
                "SELECT name FROM schema_migrations "
                "WHERE component = ? AND version = ?",
                (component, version),
            ).fetchone()
            if existing is None or existing[0] != name:
                raise
            applied[version] = name
            continue
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
            applied[version] = name

#!/usr/bin/env python3
"""Secret-free health checks for the Core local and encrypted backup artifacts."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

_DEFAULT_DATABASE = Path("/home/viktor/catering-runtime/core.db")
_DEFAULT_LOCAL_DIR = Path("/home/viktor/catering-runtime/backups")
_DEFAULT_ENCRYPTED_DIR = Path("/home/viktor/catering-runtime/offsite-encrypted")
_DEFAULT_MAX_AGE_HOURS = 26.0
_DEFAULT_COUNT_TABLES = ("inquiries", "orders", "order_versions")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class HealthFailure(Exception):
    """Expected operator-visible backup health failure."""


def _newest(directory: Path, pattern: str, label: str) -> Path:
    candidates = [path for path in directory.glob(pattern) if path.is_file()]
    if not candidates:
        raise HealthFailure(f"{label}: no matching artifact")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _check_artifact_age(
    path: Path,
    *,
    max_age_hours: float,
    now_epoch: float,
    label: str,
) -> float:
    stat = path.stat()
    if stat.st_size <= 0:
        raise HealthFailure(f"{label}: artifact is empty")
    age_hours = (now_epoch - stat.st_mtime) / 3600
    if age_hours < -0.25:
        raise HealthFailure(f"{label}: artifact timestamp is in the future")
    if age_hours > max_age_hours:
        raise HealthFailure(
            f"{label}: artifact is stale ({age_hours:.1f}h > {max_age_hours:.1f}h)"
        )
    return max(age_hours, 0.0)


def _read_only_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _quick_check(path: Path) -> None:
    try:
        connection = _read_only_connection(path)
        try:
            row = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise HealthFailure(f"local backup integrity: SQLite error: {exc}") from exc
    if row != ("ok",):
        detail = str(row[0]) if row else "no result"
        raise HealthFailure(f"local backup integrity: quick_check failed: {detail}")


def _table_count(path: Path, table: str) -> int:
    if _IDENTIFIER.fullmatch(table) is None:
        raise HealthFailure(f"count comparison: invalid table name {table!r}")
    try:
        connection = _read_only_connection(path)
        try:
            row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise HealthFailure(f"count comparison: {table}: SQLite error: {exc}") from exc
    if row is None:
        raise HealthFailure(f"count comparison: {table}: no count result")
    return int(row[0])


def _compare_counts(database: Path, backup: Path, tables: tuple[str, ...]) -> None:
    for table in tables:
        live_count = _table_count(database, table)
        backup_count = _table_count(backup, table)
        if live_count != backup_count:
            raise HealthFailure(
                f"count comparison: {table}: live={live_count} backup={backup_count}"
            )


def check_health(
    *,
    database: Path,
    local_dir: Path,
    encrypted_dir: Path,
    max_age_hours: float,
    compare_live_counts: bool,
    count_tables: tuple[str, ...],
    now_epoch: float,
) -> list[str]:
    if max_age_hours <= 0:
        raise HealthFailure("configuration: max age must be positive")
    if compare_live_counts and not database.is_file():
        raise HealthFailure("count comparison: live database is missing")

    local = _newest(local_dir, "core-????-??-??.db", "local backup")
    local_age = _check_artifact_age(
        local,
        max_age_hours=max_age_hours,
        now_epoch=now_epoch,
        label="local backup",
    )
    _quick_check(local)

    if compare_live_counts:
        _compare_counts(database, local, count_tables)

    encrypted = _newest(
        encrypted_dir,
        "core-????-??-??.db.gpg",
        "offsite encrypted cache",
    )
    encrypted_age = _check_artifact_age(
        encrypted,
        max_age_hours=max_age_hours,
        now_epoch=now_epoch,
        label="offsite encrypted cache",
    )

    messages = [
        f"OK local_backup age={local_age:.1f}h quick_check=ok",
        f"OK offsite_encrypted age={encrypted_age:.1f}h",
    ]
    if compare_live_counts:
        messages.append("OK live_count_comparison tables=" + ",".join(count_tables))
    return messages


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check Core backup freshness/integrity. Live row-count comparison is "
            "optional and intended only immediately after creating the local backup."
        )
    )
    parser.add_argument("--database", type=Path, default=_DEFAULT_DATABASE)
    parser.add_argument("--local-dir", type=Path, default=_DEFAULT_LOCAL_DIR)
    parser.add_argument("--encrypted-dir", type=Path, default=_DEFAULT_ENCRYPTED_DIR)
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=_DEFAULT_MAX_AGE_HOURS,
    )
    parser.add_argument(
        "--compare-live-counts",
        action="store_true",
        help=(
            "compare selected table counts with the live DB; use only immediately "
            "after backup creation, not as an all-day health check"
        ),
    )
    parser.add_argument(
        "--count-table",
        action="append",
        dest="count_tables",
        help=(
            "table included in live/backup count comparison; repeatable; defaults "
            "to inquiries, orders, order_versions"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    count_tables = tuple(args.count_tables or _DEFAULT_COUNT_TABLES)
    try:
        messages = check_health(
            database=args.database,
            local_dir=args.local_dir,
            encrypted_dir=args.encrypted_dir,
            max_age_hours=args.max_age_hours,
            compare_live_counts=args.compare_live_counts,
            count_tables=count_tables,
            now_epoch=time.time(),
        )
    except (HealthFailure, OSError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

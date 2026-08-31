from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_CHECKER = _ROOT / "infra/backup/check_backup_health.py"


def _make_database(path: Path, *, extra_order: bool = False) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE inquiries (inquiry_id TEXT PRIMARY KEY);
            CREATE TABLE orders (order_id TEXT PRIMARY KEY);
            CREATE TABLE order_versions (order_version_id TEXT PRIMARY KEY);
            INSERT INTO inquiries VALUES ('inq-1');
            INSERT INTO orders VALUES ('order-1');
            INSERT INTO order_versions VALUES ('version-1');
            """
        )
        if extra_order:
            connection.execute("INSERT INTO orders VALUES ('order-2')")
        connection.commit()
    finally:
        connection.close()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    database = tmp_path / "core.db"
    local_dir = tmp_path / "backups"
    encrypted_dir = tmp_path / "offsite-encrypted"
    local_dir.mkdir()
    encrypted_dir.mkdir()

    _make_database(database)
    backup = local_dir / "core-2026-08-31.db"
    source = sqlite3.connect(database)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    encrypted = encrypted_dir / "core-2026-08-31.db.gpg"
    encrypted.write_bytes(b"encrypted-test-artifact")
    return database, local_dir, encrypted_dir, backup, encrypted


def _run(
    database: Path,
    local_dir: Path,
    encrypted_dir: Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_CHECKER),
            "--database",
            str(database),
            "--local-dir",
            str(local_dir),
            "--encrypted-dir",
            str(encrypted_dir),
            "--max-age-hours",
            "26",
            *extra,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_backup_health_accepts_fresh_valid_artifacts(tmp_path: Path) -> None:
    database, local_dir, encrypted_dir, _, _ = _fixture(tmp_path)

    result = _run(
        database,
        local_dir,
        encrypted_dir,
        "--compare-live-counts",
    )

    assert result.returncode == 0
    assert "OK local_backup" in result.stdout
    assert "quick_check=ok" in result.stdout
    assert "OK offsite_encrypted" in result.stdout
    assert "OK live_count_comparison" in result.stdout
    assert result.stderr == ""


def test_backup_health_rejects_stale_local_backup(tmp_path: Path) -> None:
    database, local_dir, encrypted_dir, backup, _ = _fixture(tmp_path)
    stale = time.time() - 27 * 3600
    os.utime(backup, (stale, stale))

    result = _run(database, local_dir, encrypted_dir)

    assert result.returncode == 1
    assert "FAIL local backup: artifact is stale" in result.stderr


def test_backup_health_rejects_corrupt_local_backup(tmp_path: Path) -> None:
    database, local_dir, encrypted_dir, backup, _ = _fixture(tmp_path)
    backup.write_bytes(b"not-a-sqlite-database")

    result = _run(database, local_dir, encrypted_dir)

    assert result.returncode == 1
    assert "FAIL local backup integrity: SQLite error:" in result.stderr


def test_backup_health_rejects_live_count_mismatch(tmp_path: Path) -> None:
    database, local_dir, encrypted_dir, _, _ = _fixture(tmp_path)
    connection = sqlite3.connect(database)
    try:
        connection.execute("INSERT INTO orders VALUES ('order-after-backup')")
        connection.commit()
    finally:
        connection.close()

    result = _run(
        database,
        local_dir,
        encrypted_dir,
        "--compare-live-counts",
    )

    assert result.returncode == 1
    assert "FAIL count comparison: orders: live=2 backup=1" in result.stderr


def test_backup_health_rejects_stale_offsite_artifact(tmp_path: Path) -> None:
    database, local_dir, encrypted_dir, _, encrypted = _fixture(tmp_path)
    stale = time.time() - 27 * 3600
    os.utime(encrypted, (stale, stale))

    result = _run(database, local_dir, encrypted_dir)

    assert result.returncode == 1
    assert "FAIL offsite encrypted cache: artifact is stale" in result.stderr


def test_backup_health_rejects_missing_offsite_artifact(tmp_path: Path) -> None:
    database, local_dir, encrypted_dir, _, encrypted = _fixture(tmp_path)
    encrypted.unlink()

    result = _run(database, local_dir, encrypted_dir)

    assert result.returncode == 1
    assert "FAIL offsite encrypted cache: no matching artifact" in result.stderr

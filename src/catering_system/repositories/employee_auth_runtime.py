"""Managed employee-auth runtime wiring for long-lived Office Panel processes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import EmployeeAuthService

_BUSY_TIMEOUT_MS = 2000


@dataclass
class ManagedEmployeeAuthRuntime:
    """Owns one transaction-capable SQLite connection for employee auth."""

    repository: SQLiteEmployeeAuthRepository
    service: EmployeeAuthService

    def close(self) -> None:
        self.repository.close()


def open_managed_employee_auth_runtime(
    db_path: str | Path,
    *,
    now: Callable[[], datetime] | None = None,
) -> ManagedEmployeeAuthRuntime:
    """Open the Office Panel production employee-auth stack.

    Uses ``SQLiteEmployeeAuthRepository(db_path)`` so ``immediate_transaction()``
    performs real ``BEGIN IMMEDIATE`` / COMMIT / ROLLBACK. Schema migrations run
    on the owned connection during repository construction.

    The Office Panel HTTP server is intentionally single-threaded; this runtime
    must not be shared across concurrent request threads without external
    locking.
    """
    repository = SQLiteEmployeeAuthRepository(db_path)
    repository._conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    if now is not None:
        service = EmployeeAuthService(repository, now=now)
    else:
        service = EmployeeAuthService(repository)
    return ManagedEmployeeAuthRuntime(repository=repository, service=service)

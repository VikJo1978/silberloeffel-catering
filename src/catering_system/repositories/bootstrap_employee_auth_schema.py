"""Bootstrap AUTH_RBAC_V1 employee auth schema on a shared Core connection."""

from __future__ import annotations

import sqlite3

from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)


def bootstrap_employee_auth_schema(connection: sqlite3.Connection) -> None:
    SQLiteEmployeeAuthRepository.from_connection(connection)

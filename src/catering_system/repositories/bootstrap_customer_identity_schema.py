"""Bootstrap customer identity foundation schema on a shared Core connection."""

from __future__ import annotations

import sqlite3

from catering_system.repositories.sqlite_customer_identity_repository import (
    SQLiteCustomerIdentityRepository,
)
from catering_system.repositories.sqlite_phone_contact_point_repository import (
    SQLitePhoneContactPointRepository,
)


def bootstrap_customer_identity_schema(connection: sqlite3.Connection) -> None:
    """Apply foundation migrations once; safe under concurrent startup."""
    SQLiteCustomerIdentityRepository.from_connection(connection)
    SQLitePhoneContactPointRepository.from_connection(connection)

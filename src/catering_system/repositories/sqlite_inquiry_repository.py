"""SQLite inquiry repository — same InquiryRepository Protocol as the in-memory baseline.

Persistence adapter only: no business rules. Values re-validated through the
frozen domain validators on load.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import cast

from catering_system.domain.inquiry import (
    Inquiry,
    InquirySource,
    validate_call_verification_status,
    validate_crm_stage,
    validate_customer_linkage,
    validate_planning_mode,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS inquiries (
    inquiry_id TEXT PRIMARY KEY,
    event_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    inquiry_source TEXT NOT NULL,
    crm_stage TEXT NOT NULL,
    customer_linkage TEXT NOT NULL,
    time_window_text TEXT NOT NULL,
    location_text TEXT NOT NULL,
    guest_count_estimate INTEGER,
    planning_mode TEXT NOT NULL,
    call_verification_required INTEGER NOT NULL,
    call_verification_status TEXT NOT NULL
);
"""


class SQLiteInquiryRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save(self, inquiry: Inquiry) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO inquiries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                inquiry.inquiry_id,
                inquiry.event_date.isoformat(),
                inquiry.created_at.isoformat(),
                inquiry.updated_at.isoformat(),
                inquiry.inquiry_source,
                inquiry.crm_stage,
                json.dumps(inquiry.customer_linkage, sort_keys=True),
                inquiry.time_window_text,
                inquiry.location_text,
                inquiry.guest_count_estimate,
                inquiry.planning_mode,
                1 if inquiry.call_verification_required else 0,
                inquiry.call_verification_status,
            ),
        )
        self._conn.commit()

    def get_by_id(self, inquiry_id: str) -> Inquiry | None:
        row = self._conn.execute(
            "SELECT * FROM inquiries WHERE inquiry_id = ?", (inquiry_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_inquiry(row)

    def list_all(self) -> list[Inquiry]:
        rows = self._conn.execute(
            "SELECT * FROM inquiries ORDER BY event_date, inquiry_id"
        ).fetchall()
        return [self._row_to_inquiry(r) for r in rows]

    def _row_to_inquiry(self, row: tuple) -> Inquiry:
        return Inquiry(
            inquiry_id=row[0],
            event_date=date.fromisoformat(row[1]),
            created_at=datetime.fromisoformat(row[2]),
            updated_at=datetime.fromisoformat(row[3]),
            inquiry_source=cast(InquirySource, row[4]),
            crm_stage=validate_crm_stage(row[5]),
            customer_linkage=validate_customer_linkage(json.loads(row[6])),
            time_window_text=row[7],
            location_text=row[8],
            guest_count_estimate=row[9],
            planning_mode=validate_planning_mode(row[10]),
            call_verification_required=bool(row[11]),
            call_verification_status=validate_call_verification_status(row[12]),
        )

    def update(self, inquiry: Inquiry) -> None:
        if self.get_by_id(inquiry.inquiry_id) is None:
            raise KeyError(inquiry.inquiry_id)
        self.save(inquiry)

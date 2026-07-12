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
from catering_system.repositories.inquiry_repository import (
    DuplicateExternalReferenceError,
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
    call_verification_status TEXT NOT NULL,
    intake_subject TEXT,
    intake_message TEXT,
    intake_summary TEXT,
    intake_external_ref TEXT
);
"""

_INTAKE_COLUMNS = ("intake_subject", "intake_message", "intake_summary", "intake_external_ref")

_WEBSITE_EXTERNAL_REF_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_inquiries_website_external_ref
    ON inquiries (inquiry_source, intake_external_ref)
    WHERE inquiry_source = 'website_form'
      AND intake_external_ref IS NOT NULL
      AND intake_external_ref <> '';
"""


class SQLiteInquiryRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)
        # INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1 §4: defensive
        # in-place migration for pre-intake-context databases, same pattern as
        # SQLiteOrderRepository's STORNO cancelled_at column.
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(inquiries)").fetchall()}
        for col in _INTAKE_COLUMNS:
            if col not in cols:
                self._conn.execute(f"ALTER TABLE inquiries ADD COLUMN {col} TEXT")
        duplicate = self._conn.execute(
            "SELECT intake_external_ref FROM inquiries "
            "WHERE inquiry_source = 'website_form' "
            "AND intake_external_ref IS NOT NULL AND intake_external_ref <> '' "
            "GROUP BY intake_external_ref HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate is not None:
            self._conn.close()
            raise ValueError(
                "cannot enforce website intake idempotency: duplicate "
                f"submission_id {duplicate[0]!r}"
            )
        self._conn.execute(_WEBSITE_EXTERNAL_REF_INDEX)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save(self, inquiry: Inquiry) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO inquiries VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._values(inquiry),
                )
        except sqlite3.IntegrityError as exc:
            self._raise_duplicate_external_ref(inquiry, exc)
            raise

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
            intake_subject=row[13],
            intake_message=row[14],
            intake_summary=row[15],
            intake_external_ref=row[16],
        )

    def update(self, inquiry: Inquiry) -> None:
        try:
            with self._conn:
                updated = self._conn.execute(
                    """
                    UPDATE inquiries SET
                        event_date = ?, created_at = ?, updated_at = ?,
                        inquiry_source = ?, crm_stage = ?, customer_linkage = ?,
                        time_window_text = ?, location_text = ?,
                        guest_count_estimate = ?, planning_mode = ?,
                        call_verification_required = ?, call_verification_status = ?,
                        intake_subject = ?, intake_message = ?, intake_summary = ?,
                        intake_external_ref = ?
                    WHERE inquiry_id = ?
                    """,
                    self._values(inquiry)[1:] + (inquiry.inquiry_id,),
                ).rowcount
                if updated != 1:
                    raise KeyError(inquiry.inquiry_id)
        except sqlite3.IntegrityError as exc:
            self._raise_duplicate_external_ref(inquiry, exc)
            raise

    def _raise_duplicate_external_ref(
        self, inquiry: Inquiry, cause: sqlite3.IntegrityError
    ) -> None:
        if inquiry.inquiry_source != "website_form" or not inquiry.intake_external_ref:
            return
        existing = self.find_by_source_and_external_ref(
            inquiry.inquiry_source, inquiry.intake_external_ref
        )
        if existing is not None and existing.inquiry_id != inquiry.inquiry_id:
            raise DuplicateExternalReferenceError(
                "website_form submission_id already exists"
            ) from cause

    @staticmethod
    def _values(inquiry: Inquiry) -> tuple:
        return (
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
            inquiry.intake_subject,
            inquiry.intake_message,
            inquiry.intake_summary,
            inquiry.intake_external_ref,
        )

    def find_by_source_and_external_ref(
        self, inquiry_source: str, intake_external_ref: str
    ) -> Inquiry | None:
        # WEBSITE_FORM_INTAKE_IDEMPOTENCY_PACK_V1 §5: source-scoped on purpose
        # — intake_external_ref is written by more than one channel
        # (website_form's submission_id, configurator's proposal_id), so a
        # ref-only lookup could match across unrelated channels. No index:
        # not needed at this table's expected V1 row count (§5/§8).
        row = self._conn.execute(
            "SELECT * FROM inquiries WHERE inquiry_source = ? AND intake_external_ref = ? LIMIT 1",
            (inquiry_source, intake_external_ref),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_inquiry(row)

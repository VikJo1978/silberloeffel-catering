"""SQLite inquiry repository — same InquiryRepository Protocol as the in-memory baseline.

Persistence adapter only: no business rules. Values re-validated through the
frozen domain validators on load.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from datetime import date, datetime
from pathlib import Path
from typing import cast

from catering_system.domain.inquiry import (
    Inquiry,
    InquirySource,
    validate_call_verification_status,
    validate_crm_stage,
    validate_customer_linkage,
    validate_fulfillment_mode,
    validate_planning_mode,
)
from catering_system.domain.inquiry_timing import (
    normalize_legacy_time_window_text,
    validate_local_date_text,
    validate_local_time_text,
    validate_optional_acknowledged_by,
)
from catering_system.repositories.inquiry_repository import (
    DuplicateExternalReferenceError,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot,
    customer_address_to_mapping,
    customer_snapshot_from_mapping,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_INQUIRIES = """
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
    delivery_date_local TEXT,
    delivery_window_start_local TEXT,
    delivery_window_end_local TEXT,
    event_start_local TEXT,
    legacy_time_window_text TEXT,
    time_review_acknowledged_at TEXT,
    time_review_acknowledged_by TEXT,
    intake_subject TEXT,
    intake_message TEXT,
    intake_summary TEXT,
    intake_external_ref TEXT
);
"""

_CUSTOMER_REFERENCE_COLUMNS = (
    "customer_id",
    "snapshot_company_name",
    "snapshot_contact_name",
    "snapshot_email",
    "snapshot_phone",
)

_CUSTOMER_ADDRESS_COLUMNS = (
    "snapshot_delivery_address_mode",
    "snapshot_invoice_address_json",
    "snapshot_delivery_address_json",
)

_INTAKE_COLUMNS = (
    "intake_subject",
    "intake_message",
    "intake_summary",
    "intake_external_ref",
)

_WEBSITE_EXTERNAL_REF_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_inquiries_website_external_ref
    ON inquiries (inquiry_source, intake_external_ref)
    WHERE inquiry_source = 'website_form'
      AND intake_external_ref IS NOT NULL
      AND intake_external_ref <> '';
"""

_SELECT_COLUMNS = (
    "inquiry_id, event_date, created_at, updated_at, inquiry_source, crm_stage, "
    "customer_linkage, time_window_text, location_text, guest_count_estimate, "
    "planning_mode, call_verification_required, call_verification_status, "
    "delivery_date_local, delivery_window_start_local, delivery_window_end_local, "
    "event_start_local, legacy_time_window_text, time_review_acknowledged_at, "
    "time_review_acknowledged_by, intake_subject, intake_message, intake_summary, "
    "intake_external_ref, customer_id, snapshot_company_name, "
    "snapshot_contact_name, snapshot_email, snapshot_phone, "
    "snapshot_delivery_address_mode, snapshot_invoice_address_json, "
    "snapshot_delivery_address_json, fulfillment_mode"
)


def _migration_1_create_table(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_INQUIRIES)


def _migration_2_add_intake_context(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(inquiries)").fetchall()
    }
    for column in _INTAKE_COLUMNS:
        if column not in columns:
            connection.execute(f"ALTER TABLE inquiries ADD COLUMN {column} TEXT")


def _migration_3_unique_website_external_ref(
    connection: sqlite3.Connection,
) -> None:
    duplicate = connection.execute(
        "SELECT intake_external_ref FROM inquiries "
        "WHERE inquiry_source = 'website_form' "
        "AND intake_external_ref IS NOT NULL AND intake_external_ref <> '' "
        "GROUP BY intake_external_ref HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate is not None:
        raise ValueError(
            "cannot enforce website intake idempotency: duplicate "
            f"submission_id {duplicate[0]!r}"
        )
    connection.execute(_WEBSITE_EXTERNAL_REF_INDEX)


def _migration_4_add_customer_reference(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(inquiries)").fetchall()
    }
    for column in _CUSTOMER_REFERENCE_COLUMNS:
        if column not in columns:
            connection.execute(f"ALTER TABLE inquiries ADD COLUMN {column} TEXT")


def _migration_5_add_customer_addresses(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(inquiries)").fetchall()
    }
    for column in _CUSTOMER_ADDRESS_COLUMNS:
        if column not in columns:
            connection.execute(f"ALTER TABLE inquiries ADD COLUMN {column} TEXT")


def _migration_6_add_fulfillment_mode(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(inquiries)").fetchall()
    }
    if "fulfillment_mode" not in columns:
        connection.execute(
            "ALTER TABLE inquiries ADD COLUMN fulfillment_mode TEXT "
            "NOT NULL DEFAULT 'UNKNOWN'"
        )


def _migration_7_add_canonical_timing_fields(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(inquiries)").fetchall()
    }
    for column in (
        "delivery_date_local",
        "delivery_window_start_local",
        "delivery_window_end_local",
        "event_start_local",
        "legacy_time_window_text",
        "time_review_acknowledged_at",
        "time_review_acknowledged_by",
    ):
        if column not in columns:
            connection.execute(f"ALTER TABLE inquiries ADD COLUMN {column} TEXT")
    connection.execute(
        """
        UPDATE inquiries
           SET legacy_time_window_text = time_window_text
         WHERE legacy_time_window_text IS NULL
           AND trim(time_window_text) <> ''
        """
    )


_MIGRATIONS = (
    (1, "create_inquiries", _migration_1_create_table),
    (2, "add_intake_context", _migration_2_add_intake_context),
    (3, "unique_website_external_ref", _migration_3_unique_website_external_ref),
    (4, "add_customer_reference", _migration_4_add_customer_reference),
    (5, "add_customer_addresses", _migration_5_add_customer_addresses),
    (6, "add_fulfillment_mode", _migration_6_add_fulfillment_mode),
    (7, "add_canonical_timing_fields", _migration_7_add_canonical_timing_fields),
)


class SQLiteInquiryRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "inquiries", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> SQLiteInquiryRepository:
        """Externally-managed transaction mode (PROXMOX pack §6.1): the
        caller owns BEGIN/COMMIT/ROLLBACK on the shared connection; write
        methods here must not auto-commit. Migrations still apply."""
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "inquiries", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        # `with self._conn:` commits on exit — correct standalone, fatal
        # inside an externally-owned transaction.
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def save(self, inquiry: Inquiry) -> None:
        try:
            with self._write_scope():
                self._conn.execute(
                    "INSERT INTO inquiries (inquiry_id, event_date, created_at, updated_at, "
                    "inquiry_source, crm_stage, customer_linkage, time_window_text, "
                    "location_text, guest_count_estimate, planning_mode, "
                    "call_verification_required, call_verification_status, delivery_date_local, "
                    "delivery_window_start_local, delivery_window_end_local, event_start_local, "
                    "legacy_time_window_text, time_review_acknowledged_at, "
                    "time_review_acknowledged_by, intake_subject, intake_message, "
                    "intake_summary, intake_external_ref, customer_id, "
                    "snapshot_company_name, snapshot_contact_name, snapshot_email, "
                    "snapshot_phone, snapshot_delivery_address_mode, "
                    "snapshot_invoice_address_json, snapshot_delivery_address_json, "
                    "fulfillment_mode) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._values(inquiry),
                )
        except sqlite3.IntegrityError as exc:
            self._raise_duplicate_external_ref(inquiry, exc)
            raise

    def get_by_id(self, inquiry_id: str) -> Inquiry | None:
        row = self._conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM inquiries WHERE inquiry_id = ?",
            (inquiry_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_inquiry(row)

    def list_all(self) -> list[Inquiry]:
        rows = self._conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM inquiries ORDER BY event_date, inquiry_id"
        ).fetchall()
        return [self._row_to_inquiry(r) for r in rows]

    def _row_to_inquiry(self, row: tuple) -> Inquiry:
        snapshot = self._snapshot_from_row(row)
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
            delivery_date_local=(
                validate_local_date_text(row[13], "delivery_date_local")
                if row[13] is not None
                else None
            ),
            delivery_window_start_local=(
                validate_local_time_text(row[14], "delivery_window_start_local")
                if row[14] is not None
                else None
            ),
            delivery_window_end_local=(
                validate_local_time_text(row[15], "delivery_window_end_local")
                if row[15] is not None
                else None
            ),
            event_start_local=(
                validate_local_time_text(row[16], "event_start_local")
                if row[16] is not None
                else None
            ),
            legacy_time_window_text=normalize_legacy_time_window_text(
                row[17], "legacy_time_window_text"
            ),
            time_review_acknowledged_at=(
                datetime.fromisoformat(row[18]) if row[18] is not None else None
            ),
            time_review_acknowledged_by=validate_optional_acknowledged_by(
                row[19], "time_review_acknowledged_by"
            ),
            intake_subject=row[20],
            intake_message=row[21],
            intake_summary=row[22],
            intake_external_ref=row[23],
            customer_id=row[24],
            customer_snapshot=snapshot,
            fulfillment_mode=validate_fulfillment_mode(
                row[32] if len(row) > 32 and row[32] is not None else "UNKNOWN"
            ),
        )

    @staticmethod
    def _snapshot_from_row(row: tuple) -> InquiryCustomerSnapshot | None:
        company_name = row[25]
        contact_name = row[26]
        email = row[27]
        phone = row[28]
        mode = row[29] if len(row) > 29 else None
        invoice_json = row[30] if len(row) > 30 else None
        delivery_json = row[31] if len(row) > 31 else None
        if (
            company_name is None
            and contact_name is None
            and email is None
            and phone is None
            and mode is None
            and invoice_json is None
            and delivery_json is None
        ):
            return None
        invoice_address = None
        delivery_address = None
        if invoice_json is not None:
            invoice_address = json.loads(invoice_json)
        if delivery_json is not None:
            delivery_address = json.loads(delivery_json)
        return customer_snapshot_from_mapping(
            {
                "company_name": company_name,
                "contact_name": contact_name,
                "email": email,
                "phone": phone,
                "invoice_address": invoice_address,
                "delivery_address": delivery_address,
                "delivery_address_mode": mode,
            }
        )

    def update(self, inquiry: Inquiry) -> None:
        try:
            with self._write_scope():
                updated = self._conn.execute(
                    """
                    UPDATE inquiries SET
                        event_date = ?, created_at = ?, updated_at = ?,
                        inquiry_source = ?, crm_stage = ?, customer_linkage = ?,
                        time_window_text = ?, location_text = ?,
                        guest_count_estimate = ?, planning_mode = ?,
                        call_verification_required = ?, call_verification_status = ?,
                        delivery_date_local = ?, delivery_window_start_local = ?,
                        delivery_window_end_local = ?, event_start_local = ?,
                        legacy_time_window_text = ?, time_review_acknowledged_at = ?,
                        time_review_acknowledged_by = ?, intake_subject = ?,
                        intake_message = ?, intake_summary = ?,
                        intake_external_ref = ?, customer_id = ?,
                        snapshot_company_name = ?, snapshot_contact_name = ?,
                        snapshot_email = ?, snapshot_phone = ?,
                        snapshot_delivery_address_mode = ?,
                        snapshot_invoice_address_json = ?,
                        snapshot_delivery_address_json = ?,
                        fulfillment_mode = ?
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
        snapshot = inquiry.customer_snapshot
        if snapshot is None:
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
                inquiry.delivery_date_local,
                inquiry.delivery_window_start_local,
                inquiry.delivery_window_end_local,
                inquiry.event_start_local,
                inquiry.legacy_time_window_text,
                inquiry.time_review_acknowledged_at.isoformat()
                if inquiry.time_review_acknowledged_at is not None
                else None,
                inquiry.time_review_acknowledged_by,
                inquiry.intake_subject,
                inquiry.intake_message,
                inquiry.intake_summary,
                inquiry.intake_external_ref,
                inquiry.customer_id,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                inquiry.fulfillment_mode,
            )
        invoice_json = None
        delivery_json = None
        invoice_map = customer_address_to_mapping(snapshot.invoice_address)
        delivery_map = customer_address_to_mapping(snapshot.delivery_address)
        if invoice_map is not None:
            invoice_json = json.dumps(invoice_map, sort_keys=True, ensure_ascii=False)
        if delivery_map is not None:
            delivery_json = json.dumps(delivery_map, sort_keys=True, ensure_ascii=False)
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
            inquiry.delivery_date_local,
            inquiry.delivery_window_start_local,
            inquiry.delivery_window_end_local,
            inquiry.event_start_local,
            inquiry.legacy_time_window_text,
            inquiry.time_review_acknowledged_at.isoformat()
            if inquiry.time_review_acknowledged_at is not None
            else None,
            inquiry.time_review_acknowledged_by,
            inquiry.intake_subject,
            inquiry.intake_message,
            inquiry.intake_summary,
            inquiry.intake_external_ref,
            inquiry.customer_id,
            snapshot.company_name,
            snapshot.contact_name,
            snapshot.email,
            snapshot.phone,
            snapshot.delivery_address_mode,
            invoice_json,
            delivery_json,
            inquiry.fulfillment_mode,
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
            f"SELECT {_SELECT_COLUMNS} FROM inquiries "
            "WHERE inquiry_source = ? AND intake_external_ref = ? LIMIT 1",
            (inquiry_source, intake_external_ref),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_inquiry(row)

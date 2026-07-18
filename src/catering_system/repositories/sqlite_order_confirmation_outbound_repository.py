"""SQLite persistence for fake-outbox outbound send records."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from pathlib import Path

from catering_system.domain.order_confirmation_outbound import (
    FakeOutboxMessage,
    OrderConfirmationSendAttempt,
    SendEvidence,
)
from catering_system.repositories.order_confirmation_outbound_repository import (
    OrderConfirmationOutboundRepository,
)
from catering_system.repositories.sqlite_migrations import apply_migrations


def _migration_1_create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE order_confirmation_send_attempts (
            send_attempt_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            order_version_id TEXT NOT NULL,
            document_snapshot_id TEXT NOT NULL,
            document_hash TEXT NOT NULL,
            recipient_name TEXT,
            recipient_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            transport_kind TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            schema_version INTEGER NOT NULL
        );
        CREATE TABLE order_confirmation_fake_outbox_messages (
            fake_outbox_message_id TEXT PRIMARY KEY,
            send_attempt_id TEXT NOT NULL UNIQUE,
            order_id TEXT NOT NULL,
            document_snapshot_id TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            text_body TEXT NOT NULL,
            html_body TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            schema_version INTEGER NOT NULL
        );
        CREATE TABLE order_confirmation_send_evidence (
            send_evidence_id TEXT PRIMARY KEY,
            send_attempt_id TEXT NOT NULL UNIQUE,
            fake_outbox_message_id TEXT NOT NULL UNIQUE,
            order_id TEXT NOT NULL,
            document_snapshot_id TEXT NOT NULL UNIQUE,
            transport_kind TEXT NOT NULL,
            transport_message_reference TEXT NOT NULL,
            accepted_at TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            document_hash TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            outcome TEXT NOT NULL,
            schema_version INTEGER NOT NULL
        );
        CREATE INDEX idx_order_confirmation_send_attempts_order_id
            ON order_confirmation_send_attempts (order_id);
        CREATE INDEX idx_order_confirmation_send_attempts_document_snapshot_id
            ON order_confirmation_send_attempts (document_snapshot_id);
        CREATE INDEX idx_order_confirmation_fake_outbox_order_id
            ON order_confirmation_fake_outbox_messages (order_id);
        CREATE INDEX idx_order_confirmation_send_evidence_order_id
            ON order_confirmation_send_evidence (order_id);
        """
    )
    connection.executescript(
        """
        CREATE TRIGGER trg_order_confirmation_send_attempt_owner_insert
        BEFORE INSERT ON order_confirmation_send_attempts
        WHEN NOT EXISTS (
            SELECT 1 FROM orders o
            JOIN order_versions v ON v.order_id = o.order_id
            JOIN order_confirmation_document_snapshots d
              ON d.order_id = o.order_id
             AND d.order_version_id = v.order_version_id
            WHERE o.order_id = NEW.order_id
              AND v.order_version_id = NEW.order_version_id
              AND d.document_snapshot_id = NEW.document_snapshot_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'send attempt owner is invalid');
        END;
        CREATE TRIGGER trg_order_confirmation_send_attempt_immutable_update
        BEFORE UPDATE ON order_confirmation_send_attempts
        BEGIN
            SELECT RAISE(ABORT, 'send attempt is immutable');
        END;
        CREATE TRIGGER trg_order_confirmation_send_attempt_immutable_delete
        BEFORE DELETE ON order_confirmation_send_attempts
        BEGIN
            SELECT RAISE(ABORT, 'send attempt is immutable');
        END;
        CREATE TRIGGER trg_order_confirmation_fake_outbox_owner_insert
        BEFORE INSERT ON order_confirmation_fake_outbox_messages
        WHEN NOT EXISTS (
            SELECT 1 FROM order_confirmation_send_attempts a
            WHERE a.send_attempt_id = NEW.send_attempt_id
              AND a.order_id = NEW.order_id
              AND a.document_snapshot_id = NEW.document_snapshot_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'fake outbox owner is invalid');
        END;
        CREATE TRIGGER trg_order_confirmation_fake_outbox_immutable_update
        BEFORE UPDATE ON order_confirmation_fake_outbox_messages
        BEGIN
            SELECT RAISE(ABORT, 'fake outbox message is immutable');
        END;
        CREATE TRIGGER trg_order_confirmation_fake_outbox_immutable_delete
        BEFORE DELETE ON order_confirmation_fake_outbox_messages
        BEGIN
            SELECT RAISE(ABORT, 'fake outbox message is immutable');
        END;
        CREATE TRIGGER trg_order_confirmation_send_evidence_owner_insert
        BEFORE INSERT ON order_confirmation_send_evidence
        WHEN NOT EXISTS (
            SELECT 1 FROM order_confirmation_send_attempts a
            JOIN order_confirmation_fake_outbox_messages m
              ON m.send_attempt_id = a.send_attempt_id
            WHERE a.send_attempt_id = NEW.send_attempt_id
              AND m.fake_outbox_message_id = NEW.fake_outbox_message_id
              AND a.order_id = NEW.order_id
              AND a.document_snapshot_id = NEW.document_snapshot_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'send evidence owner is invalid');
        END;
        CREATE TRIGGER trg_order_confirmation_send_evidence_immutable_update
        BEFORE UPDATE ON order_confirmation_send_evidence
        BEGIN
            SELECT RAISE(ABORT, 'send evidence is immutable');
        END;
        CREATE TRIGGER trg_order_confirmation_send_evidence_immutable_delete
        BEFORE DELETE ON order_confirmation_send_evidence
        BEGIN
            SELECT RAISE(ABORT, 'send evidence is immutable');
        END;
        """
    )


_MIGRATIONS = ((1, "create_order_confirmation_outbound", _migration_1_create_tables),)


def _row_to_attempt(row: tuple) -> OrderConfirmationSendAttempt:
    from datetime import datetime

    return OrderConfirmationSendAttempt(
        send_attempt_id=row[0],
        order_id=row[1],
        order_version_id=row[2],
        document_snapshot_id=row[3],
        document_hash=row[4],
        recipient_name=row[5],
        recipient_email=row[6],
        subject=row[7],
        requested_at=datetime.fromisoformat(row[8]),
        requested_by=row[9],
        transport_kind=row[10],
        payload_hash=row[11],
        schema_version=row[12],
    )


def _row_to_message(row: tuple) -> FakeOutboxMessage:
    from datetime import datetime

    return FakeOutboxMessage(
        fake_outbox_message_id=row[0],
        send_attempt_id=row[1],
        order_id=row[2],
        document_snapshot_id=row[3],
        recipient_email=row[4],
        subject=row[5],
        text_body=row[6],
        html_body=row[7],
        payload_hash=row[8],
        created_at=datetime.fromisoformat(row[9]),
        schema_version=row[10],
    )


def _row_to_evidence(row: tuple) -> SendEvidence:
    from datetime import datetime

    return SendEvidence(
        send_evidence_id=row[0],
        send_attempt_id=row[1],
        fake_outbox_message_id=row[2],
        order_id=row[3],
        document_snapshot_id=row[4],
        transport_kind=row[5],
        transport_message_reference=row[6],
        accepted_at=datetime.fromisoformat(row[7]),
        recipient_email=row[8],
        document_hash=row[9],
        payload_hash=row[10],
        outcome=row[11],
        schema_version=row[12],
    )


class SQLiteOrderConfirmationOutboundRepository(OrderConfirmationOutboundRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "order_confirmation_outbound", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteOrderConfirmationOutboundRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "order_confirmation_outbound", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def get_attempt_by_id(
        self, send_attempt_id: str
    ) -> OrderConfirmationSendAttempt | None:
        row = self._conn.execute(
            "SELECT send_attempt_id, order_id, order_version_id, document_snapshot_id, "
            "document_hash, recipient_name, recipient_email, subject, requested_at, "
            "requested_by, transport_kind, payload_hash, schema_version "
            "FROM order_confirmation_send_attempts WHERE send_attempt_id = ?",
            (send_attempt_id,),
        ).fetchone()
        return _row_to_attempt(row) if row else None

    def get_evidence_by_document_snapshot_id(
        self, document_snapshot_id: str
    ) -> SendEvidence | None:
        row = self._conn.execute(
            "SELECT send_evidence_id, send_attempt_id, fake_outbox_message_id, order_id, "
            "document_snapshot_id, transport_kind, transport_message_reference, accepted_at, "
            "recipient_email, document_hash, payload_hash, outcome, schema_version "
            "FROM order_confirmation_send_evidence WHERE document_snapshot_id = ?",
            (document_snapshot_id,),
        ).fetchone()
        return _row_to_evidence(row) if row else None

    def get_evidence_by_order_id(self, order_id: str) -> SendEvidence | None:
        row = self._conn.execute(
            "SELECT send_evidence_id, send_attempt_id, fake_outbox_message_id, order_id, "
            "document_snapshot_id, transport_kind, transport_message_reference, accepted_at, "
            "recipient_email, document_hash, payload_hash, outcome, schema_version "
            "FROM order_confirmation_send_evidence WHERE order_id = ? "
            "ORDER BY accepted_at DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        return _row_to_evidence(row) if row else None

    def get_outbox_by_send_attempt_id(
        self, send_attempt_id: str
    ) -> FakeOutboxMessage | None:
        row = self._conn.execute(
            "SELECT fake_outbox_message_id, send_attempt_id, order_id, document_snapshot_id, "
            "recipient_email, subject, text_body, html_body, payload_hash, created_at, "
            "schema_version FROM order_confirmation_fake_outbox_messages "
            "WHERE send_attempt_id = ?",
            (send_attempt_id,),
        ).fetchone()
        return _row_to_message(row) if row else None

    def get_outbox_by_order_id(self, order_id: str) -> FakeOutboxMessage | None:
        row = self._conn.execute(
            "SELECT fake_outbox_message_id, send_attempt_id, order_id, document_snapshot_id, "
            "recipient_email, subject, text_body, html_body, payload_hash, created_at, "
            "schema_version FROM order_confirmation_fake_outbox_messages "
            "WHERE order_id = ? ORDER BY created_at DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        return _row_to_message(row) if row else None

    def insert_bundle(
        self,
        attempt: OrderConfirmationSendAttempt,
        message: FakeOutboxMessage,
        evidence: SendEvidence,
    ) -> None:
        with self._write_scope():
            self._conn.execute(
                "INSERT INTO order_confirmation_send_attempts ("
                "send_attempt_id, order_id, order_version_id, document_snapshot_id, "
                "document_hash, recipient_name, recipient_email, subject, requested_at, "
                "requested_by, transport_kind, payload_hash, schema_version"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt.send_attempt_id,
                    attempt.order_id,
                    attempt.order_version_id,
                    attempt.document_snapshot_id,
                    attempt.document_hash,
                    attempt.recipient_name,
                    attempt.recipient_email,
                    attempt.subject,
                    attempt.requested_at.isoformat(),
                    attempt.requested_by,
                    attempt.transport_kind,
                    attempt.payload_hash,
                    attempt.schema_version,
                ),
            )
            self._conn.execute(
                "INSERT INTO order_confirmation_fake_outbox_messages ("
                "fake_outbox_message_id, send_attempt_id, order_id, document_snapshot_id, "
                "recipient_email, subject, text_body, html_body, payload_hash, created_at, "
                "schema_version"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message.fake_outbox_message_id,
                    message.send_attempt_id,
                    message.order_id,
                    message.document_snapshot_id,
                    message.recipient_email,
                    message.subject,
                    message.text_body,
                    message.html_body,
                    message.payload_hash,
                    message.created_at.isoformat(),
                    message.schema_version,
                ),
            )
            self._conn.execute(
                "INSERT INTO order_confirmation_send_evidence ("
                "send_evidence_id, send_attempt_id, fake_outbox_message_id, order_id, "
                "document_snapshot_id, transport_kind, transport_message_reference, "
                "accepted_at, recipient_email, document_hash, payload_hash, outcome, "
                "schema_version"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence.send_evidence_id,
                    evidence.send_attempt_id,
                    evidence.fake_outbox_message_id,
                    evidence.order_id,
                    evidence.document_snapshot_id,
                    evidence.transport_kind,
                    evidence.transport_message_reference,
                    evidence.accepted_at.isoformat(),
                    evidence.recipient_email,
                    evidence.document_hash,
                    evidence.payload_hash,
                    evidence.outcome,
                    evidence.schema_version,
                ),
            )
            if self._manage_transactions:
                self._conn.commit()

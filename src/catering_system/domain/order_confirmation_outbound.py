"""Immutable fake-outbox outbound records — EMAIL_MVP_2 slice B2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

SCHEMA_VERSION = 1
TRANSPORT_KIND = "fake_outbox"
OUTCOME_ACCEPTED = "accepted_by_fake_outbox"
_PAYLOAD_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class OrderConfirmationSendAttempt:
    send_attempt_id: str
    order_id: str
    order_version_id: str
    document_snapshot_id: str
    document_hash: str
    recipient_name: str | None
    recipient_email: str
    subject: str
    requested_at: datetime
    requested_by: str
    transport_kind: str
    payload_hash: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported send attempt schema version")
        if self.transport_kind != TRANSPORT_KIND:
            raise ValueError("unsupported transport kind")
        if not _PAYLOAD_HASH.fullmatch(self.payload_hash):
            raise ValueError("payload_hash must be sha256:<hex>")


@dataclass(frozen=True)
class FakeOutboxMessage:
    fake_outbox_message_id: str
    send_attempt_id: str
    order_id: str
    document_snapshot_id: str
    recipient_email: str
    subject: str
    text_body: str
    html_body: str
    payload_hash: str
    created_at: datetime
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported fake outbox schema version")
        if not _PAYLOAD_HASH.fullmatch(self.payload_hash):
            raise ValueError("payload_hash must be sha256:<hex>")


@dataclass(frozen=True)
class SendEvidence:
    send_evidence_id: str
    send_attempt_id: str
    fake_outbox_message_id: str
    order_id: str
    document_snapshot_id: str
    transport_kind: str
    transport_message_reference: str
    accepted_at: datetime
    recipient_email: str
    document_hash: str
    payload_hash: str
    outcome: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported send evidence schema version")
        if self.transport_kind != TRANSPORT_KIND:
            raise ValueError("unsupported transport kind")
        if self.outcome != OUTCOME_ACCEPTED:
            raise ValueError("unsupported send outcome")
        if not _PAYLOAD_HASH.fullmatch(self.payload_hash):
            raise ValueError("payload_hash must be sha256:<hex>")

"""Canonical hash for frozen fake-outbox email payload."""

from __future__ import annotations

from catering_system.domain.offer_snapshot import compute_snapshot_hash


def payload_hash_body(
    *,
    schema_version: int,
    transport_kind: str,
    document_snapshot_id: str,
    document_hash: str,
    recipient_email: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "transport_kind": transport_kind,
        "document_snapshot_id": document_snapshot_id,
        "document_hash": document_hash,
        "recipient_email": recipient_email,
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body,
    }


def compute_payload_hash(body: dict[str, object]) -> str:
    return compute_snapshot_hash(body)

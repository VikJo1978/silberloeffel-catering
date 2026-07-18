"""Persistence port for fake-outbox outbound send records."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.order_confirmation_outbound import (
    FakeOutboxMessage,
    OrderConfirmationSendAttempt,
    SendEvidence,
)


class OrderConfirmationOutboundRepository(Protocol):
    def get_attempt_by_id(
        self, send_attempt_id: str
    ) -> OrderConfirmationSendAttempt | None: ...

    def get_evidence_by_document_snapshot_id(
        self, document_snapshot_id: str
    ) -> SendEvidence | None: ...

    def get_evidence_by_order_id(self, order_id: str) -> SendEvidence | None: ...

    def get_outbox_by_send_attempt_id(
        self, send_attempt_id: str
    ) -> FakeOutboxMessage | None: ...

    def get_outbox_by_order_id(self, order_id: str) -> FakeOutboxMessage | None: ...

    def insert_bundle(
        self,
        attempt: OrderConfirmationSendAttempt,
        message: FakeOutboxMessage,
        evidence: SendEvidence,
    ) -> None: ...

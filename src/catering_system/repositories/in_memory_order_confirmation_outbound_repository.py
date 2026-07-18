"""In-memory fake-outbox outbound persistence for tests."""

from __future__ import annotations

from catering_system.domain.order_confirmation_outbound import (
    FakeOutboxMessage,
    OrderConfirmationSendAttempt,
    SendEvidence,
)
from catering_system.repositories.order_confirmation_outbound_repository import (
    OrderConfirmationOutboundRepository,
)


class InMemoryOrderConfirmationOutboundRepository(OrderConfirmationOutboundRepository):
    def __init__(self) -> None:
        self._attempts: dict[str, OrderConfirmationSendAttempt] = {}
        self._messages: dict[str, FakeOutboxMessage] = {}
        self._evidence_by_snapshot: dict[str, SendEvidence] = {}
        self._evidence_by_order: dict[str, SendEvidence] = {}

    def get_attempt_by_id(
        self, send_attempt_id: str
    ) -> OrderConfirmationSendAttempt | None:
        return self._attempts.get(send_attempt_id)

    def get_evidence_by_document_snapshot_id(
        self, document_snapshot_id: str
    ) -> SendEvidence | None:
        return self._evidence_by_snapshot.get(document_snapshot_id)

    def get_evidence_by_order_id(self, order_id: str) -> SendEvidence | None:
        return self._evidence_by_order.get(order_id)

    def get_outbox_by_send_attempt_id(
        self, send_attempt_id: str
    ) -> FakeOutboxMessage | None:
        return self._messages.get(send_attempt_id)

    def get_outbox_by_order_id(self, order_id: str) -> FakeOutboxMessage | None:
        evidence = self._evidence_by_order.get(order_id)
        if evidence is None:
            return None
        return self._messages.get(evidence.send_attempt_id)

    def insert_bundle(
        self,
        attempt: OrderConfirmationSendAttempt,
        message: FakeOutboxMessage,
        evidence: SendEvidence,
    ) -> None:
        if self._evidence_by_snapshot.get(attempt.document_snapshot_id) is not None:
            raise ValueError("document snapshot already sent")
        self._attempts[attempt.send_attempt_id] = attempt
        self._messages[attempt.send_attempt_id] = message
        self._evidence_by_snapshot[evidence.document_snapshot_id] = evidence
        self._evidence_by_order[evidence.order_id] = evidence

"""Fake-outbox outbound send for frozen Auftragsbestätigung documents — B2."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from catering_system.domain.order import Order
from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentSnapshot,
    mask_recipient_email,
    short_document_hash,
)
from catering_system.domain.order_confirmation_outbound import (
    OUTCOME_ACCEPTED,
    TRANSPORT_KIND,
    FakeOutboxMessage,
    OrderConfirmationSendAttempt,
    SendEvidence,
)
from catering_system.domain.ready_to_send import ReadyToSendEvaluation
from catering_system.repositories.order_confirmation_document_repository import (
    OrderConfirmationDocumentRepository,
)
from catering_system.repositories.order_confirmation_outbound_repository import (
    OrderConfirmationOutboundRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_confirmation_document_hash import (
    compute_document_hash,
)
from catering_system.services.order_confirmation_outbound_payload import (
    build_outbound_payload,
)


class OrderConfirmationOutboundNotFoundError(LookupError):
    """Requested order or document snapshot does not exist."""


class OrderConfirmationOutboundAlreadySentError(ValueError):
    """Document snapshot already has successful fake-outbox evidence."""


class OrderConfirmationOutboundStaleVersionError(ValueError):
    """Expected effective order version is stale."""


class OrderConfirmationOutboundRecipientMissingError(ValueError):
    """Recipient email is missing or invalid."""


class OrderConfirmationOutboundBlockedError(ValueError):
    """Send preconditions are not satisfied."""


class OrderConfirmationOutboundPayloadInvalidError(ValueError):
    """Outbound payload or document hash is invalid."""


@dataclass(frozen=True)
class OutboundSendSummary:
    send_attempt_id: str
    send_evidence_id: str
    fake_outbox_message_id: str
    document_snapshot_id: str
    document_hash: str
    document_hash_short: str
    payload_hash: str
    payload_hash_short: str
    recipient_email_masked: str
    transport_kind: str
    outcome: str
    accepted_at: str
    real_delivery: bool = False


@dataclass(frozen=True)
class OutboundSendResult:
    attempt: OrderConfirmationSendAttempt
    message: FakeOutboxMessage
    evidence: SendEvidence
    summary: OutboundSendSummary
    real_delivery: bool = False


@dataclass(frozen=True)
class OutboundSendEligibility:
    state: str
    can_send: bool
    blocker_code: str | None = None
    ready_to_send: ReadyToSendEvaluation | None = None
    send_summary: OutboundSendSummary | None = None


def _email_syntax_ok(email: str | None) -> bool:
    if not email:
        return False
    local, separator, domain = email.partition("@")
    if not separator or not local.strip() or not domain.strip():
        return False
    return "." in domain


class OrderConfirmationOutboundService:
    def __init__(
        self,
        order_repository: OrderRepository,
        document_repository: OrderConfirmationDocumentRepository,
        outbound_repository: OrderConfirmationOutboundRepository,
        core: OperationalCoreService,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders = order_repository
        self._documents = document_repository
        self._outbound = outbound_repository
        self._core = core
        self._now = now or (lambda: datetime.now(UTC))

    def send_eligibility(
        self,
        order_id: str,
        *,
        document_snapshot_id: str | None = None,
    ) -> OutboundSendEligibility:
        order = self._orders.get_order(order_id)
        if order is None:
            raise OrderConfirmationOutboundNotFoundError(order_id)
        snapshot = self._resolve_snapshot(order_id, document_snapshot_id)
        if snapshot is None:
            return OutboundSendEligibility(
                state="dokument_fehlt",
                can_send=False,
                blocker_code="dokument_fehlt",
            )
        existing = self._outbound.get_evidence_by_document_snapshot_id(
            snapshot.document_snapshot_id
        )
        if existing is not None:
            return OutboundSendEligibility(
                state="testversand_protokolliert",
                can_send=False,
                send_summary=self._summary_from_bundle(snapshot, existing),
            )
        blocker = self._send_blocker(order, snapshot)
        if blocker is not None:
            return OutboundSendEligibility(
                state=blocker,
                can_send=False,
                blocker_code=blocker,
                ready_to_send=self._core.evaluate_ready_to_send(order_id),
            )
        return OutboundSendEligibility(
            state="testversand_bereit",
            can_send=True,
            ready_to_send=self._core.evaluate_ready_to_send(order_id),
        )

    def send_status(self, order_id: str) -> dict[str, object]:
        order = self._orders.get_order(order_id)
        if order is None:
            raise OrderConfirmationOutboundNotFoundError(order_id)
        snapshot = self._documents.get_latest_for_order(order_id)
        if snapshot is None:
            return {"state": "not_sent", "real_delivery": False}
        evidence = self._outbound.get_evidence_by_document_snapshot_id(
            snapshot.document_snapshot_id
        )
        if evidence is None:
            return {
                "state": "not_sent",
                "document_snapshot_id": snapshot.document_snapshot_id,
                "real_delivery": False,
            }
        return {
            "state": "sent",
            "real_delivery": False,
            **self._summary_from_bundle(snapshot, evidence).__dict__,
        }

    def fake_outbox_message(
        self, order_id: str, *, document_snapshot_id: str | None = None
    ) -> FakeOutboxMessage:
        snapshot = self._require_snapshot(order_id, document_snapshot_id)
        evidence = self._outbound.get_evidence_by_document_snapshot_id(
            snapshot.document_snapshot_id
        )
        if evidence is None:
            raise OrderConfirmationOutboundNotFoundError(order_id)
        message = self._outbound.get_outbox_by_send_attempt_id(evidence.send_attempt_id)
        if message is None or message.order_id != order_id:
            raise OrderConfirmationOutboundNotFoundError(order_id)
        return message

    def send_to_fake_outbox(
        self,
        order_id: str,
        document_snapshot_id: str,
        expected_effective_order_version_id: str,
        requested_by: str,
    ) -> OutboundSendResult:
        order = self._orders.get_order(order_id)
        if order is None:
            raise OrderConfirmationOutboundNotFoundError(order_id)
        if order.effective_order_version_id != expected_effective_order_version_id:
            raise OrderConfirmationOutboundStaleVersionError(
                "expected effective order version is stale"
            )
        snapshot = self._documents.get_by_id(document_snapshot_id)
        if snapshot is None or snapshot.order_id != order_id:
            raise OrderConfirmationOutboundNotFoundError(document_snapshot_id)
        existing = self._outbound.get_evidence_by_document_snapshot_id(
            document_snapshot_id
        )
        if existing is not None:
            raise OrderConfirmationOutboundAlreadySentError(document_snapshot_id)
        blocker = self._send_blocker(order, snapshot)
        if blocker is not None:
            if blocker == "empfaenger_fehlt":
                raise OrderConfirmationOutboundRecipientMissingError(blocker)
            if blocker == "pending_order_version_change":
                raise OrderConfirmationOutboundBlockedError(blocker)
            if blocker == "order_not_ready_to_send":
                evaluation = self._core.evaluate_ready_to_send(order_id)
                raise OrderConfirmationOutboundBlockedError(
                    f"{blocker}:{','.join(evaluation.reasons)}"
                )
            raise OrderConfirmationOutboundBlockedError(blocker)
        if compute_document_hash(snapshot) != snapshot.document_hash:
            raise OrderConfirmationOutboundPayloadInvalidError("document_hash_mismatch")
        payload = build_outbound_payload(snapshot)
        now = self._now()
        attempt_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        evidence_id = str(uuid.uuid4())
        attempt = OrderConfirmationSendAttempt(
            send_attempt_id=attempt_id,
            order_id=order_id,
            order_version_id=snapshot.order_version_id,
            document_snapshot_id=snapshot.document_snapshot_id,
            document_hash=snapshot.document_hash,
            recipient_name=payload.recipient_name,
            recipient_email=payload.recipient_email,
            subject=payload.subject,
            requested_at=now,
            requested_by=requested_by,
            transport_kind=TRANSPORT_KIND,
            payload_hash=payload.payload_hash,
        )
        message = FakeOutboxMessage(
            fake_outbox_message_id=message_id,
            send_attempt_id=attempt_id,
            order_id=order_id,
            document_snapshot_id=snapshot.document_snapshot_id,
            recipient_email=payload.recipient_email,
            subject=payload.subject,
            text_body=payload.text_body,
            html_body=payload.html_body,
            payload_hash=payload.payload_hash,
            created_at=now,
        )
        evidence = SendEvidence(
            send_evidence_id=evidence_id,
            send_attempt_id=attempt_id,
            fake_outbox_message_id=message_id,
            order_id=order_id,
            document_snapshot_id=snapshot.document_snapshot_id,
            transport_kind=TRANSPORT_KIND,
            transport_message_reference=message_id,
            accepted_at=now,
            recipient_email=payload.recipient_email,
            document_hash=snapshot.document_hash,
            payload_hash=payload.payload_hash,
            outcome=OUTCOME_ACCEPTED,
        )
        try:
            self._outbound.insert_bundle(attempt, message, evidence)
        except sqlite3.IntegrityError as exc:
            raise OrderConfirmationOutboundAlreadySentError(
                document_snapshot_id
            ) from exc
        except ValueError as exc:
            if "already sent" in str(exc):
                raise OrderConfirmationOutboundAlreadySentError(
                    document_snapshot_id
                ) from exc
            raise
        return self._bundle_result(snapshot, attempt, message, evidence)

    def _resolve_snapshot(
        self, order_id: str, document_snapshot_id: str | None
    ) -> OrderConfirmationDocumentSnapshot | None:
        if document_snapshot_id is not None:
            snapshot = self._documents.get_by_id(document_snapshot_id)
            if snapshot is None or snapshot.order_id != order_id:
                return None
            return snapshot
        return self._documents.get_latest_for_order(order_id)

    def _require_snapshot(
        self, order_id: str, document_snapshot_id: str | None
    ) -> OrderConfirmationDocumentSnapshot:
        snapshot = self._resolve_snapshot(order_id, document_snapshot_id)
        if snapshot is None:
            raise OrderConfirmationOutboundNotFoundError(order_id)
        return snapshot

    def _send_blocker(
        self, order: Order, snapshot: OrderConfirmationDocumentSnapshot
    ) -> str | None:
        if order.cancelled_at is not None:
            return "order_storniert"
        if order.effective_order_version_id is None:
            return "confirmation_document_not_current"
        if snapshot.order_version_id != order.effective_order_version_id:
            return "confirmation_document_not_current"
        if order.candidate_order_version_id is not None:
            return "pending_order_version_change"
        version = self._orders.get_order_version(order.effective_order_version_id)
        if version is None or version.kitchen_print_confirmed_at is None:
            return "kitchen_print_not_confirmed"
        if snapshot.recipient_status != "ready":
            return "empfaenger_fehlt"
        if not _email_syntax_ok(snapshot.recipient_email):
            return "empfaenger_fehlt"
        evaluation = self._core.evaluate_ready_to_send(order.order_id)
        if not evaluation.ready:
            return "order_not_ready_to_send"
        return None

    def _summary_from_bundle(
        self,
        snapshot: OrderConfirmationDocumentSnapshot,
        evidence: SendEvidence,
    ) -> OutboundSendSummary:
        return OutboundSendSummary(
            send_attempt_id=evidence.send_attempt_id,
            send_evidence_id=evidence.send_evidence_id,
            fake_outbox_message_id=evidence.fake_outbox_message_id,
            document_snapshot_id=evidence.document_snapshot_id,
            document_hash=evidence.document_hash,
            document_hash_short=short_document_hash(evidence.document_hash),
            payload_hash=evidence.payload_hash,
            payload_hash_short=short_document_hash(evidence.payload_hash),
            recipient_email_masked=mask_recipient_email(evidence.recipient_email) or "–",
            transport_kind=evidence.transport_kind,
            outcome=evidence.outcome,
            accepted_at=evidence.accepted_at.isoformat(),
            real_delivery=False,
        )

    def _bundle_result(
        self,
        snapshot: OrderConfirmationDocumentSnapshot,
        attempt: OrderConfirmationSendAttempt,
        message: FakeOutboxMessage,
        evidence: SendEvidence,
    ) -> OutboundSendResult:
        summary = self._summary_from_bundle(snapshot, evidence)
        return OutboundSendResult(
            attempt=attempt,
            message=message,
            evidence=evidence,
            summary=summary,
            real_delivery=False,
        )

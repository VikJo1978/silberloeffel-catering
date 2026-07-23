"""Build and read frozen Auftragsbestätigung document snapshots — EMAIL_MVP_1 B1.

Facts come from CustomerDocumentProjection (Inquiry + OrderVersion +
OrderCommercialSnapshot). Persistence remains OrderConfirmationDocumentSnapshot.
"""

from __future__ import annotations

import uuid
from typing import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from catering_system.domain.customer_document_projection import (
    CustomerAddress,
    CustomerDocumentProjection,
)
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import (
    MissingCommercialSnapshotError,
)
from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentPosition,
    OrderConfirmationDocumentSnapshot,
    OrderConfirmationVatBucket,
    RecipientStatus,
)
from catering_system.domain.order_payment_reminder import (
    PAYMENT_METHOD_LABELS,
    validate_payment_method,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_confirmation_document_repository import (
    OrderConfirmationDocumentRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.customer_document_projection import (
    CustomerDocumentProjectionService,
)
from catering_system.services.order_confirmation_document_hash import (
    compute_document_hash,
)


class OrderConfirmationDocumentNotFoundError(LookupError):
    """Raised when the requested snapshot does not exist."""


class OrderConfirmationDocumentBlockedError(ValueError):
    """Preconditions for snapshot creation are not satisfied."""


class OrderConfirmationDocumentStaleVersionError(ValueError):
    """Expected effective OrderVersion no longer matches Core truth."""


@dataclass(frozen=True)
class OrderConfirmationDocumentSummary:
    document_snapshot_id: str
    order_id: str
    order_version_id: str
    document_reference: str
    created_at: datetime
    created_by: str
    recipient_status: RecipientStatus
    recipient_email_masked: str | None
    document_hash_short: str
    net_total_cents: int
    vat_total_cents: int
    gross_total_cents: int
    effective_version_number: int


@dataclass(frozen=True)
class OrderConfirmationDocumentEligibility:
    available: bool
    state: str
    blocker_code: str | None = None
    can_prepare: bool = False
    snapshot: OrderConfirmationDocumentSummary | None = None


def document_reference(order_id: str, version_number: int) -> str:
    return f"AB-{order_id.split('-', maxsplit=1)[0].upper()}-V{version_number}"


class OrderConfirmationDocumentService:
    def __init__(
        self,
        order_repository: OrderRepository,
        inquiry_repository: InquiryRepository,
        document_repository: OrderConfirmationDocumentRepository,
        commercial_snapshot_repository: OrderCommercialSnapshotRepository,
        *,
        projection_service: CustomerDocumentProjectionService | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders = order_repository
        self._inquiries = inquiry_repository
        self._documents = document_repository
        self._commercial_snapshots = commercial_snapshot_repository
        self._projection = projection_service or CustomerDocumentProjectionService()
        self._now = now or (lambda: datetime.now(UTC))

    def eligibility(self, order_id: str) -> OrderConfirmationDocumentEligibility:
        order = self._orders.get_order(order_id)
        if order is None:
            raise OrderConfirmationDocumentNotFoundError(order_id)
        existing = self._documents.get_latest_for_order(order_id)
        if existing is not None:
            version = self._orders.get_order_version(existing.order_version_id)
            version_number = version.version_number if version is not None else 0
            return OrderConfirmationDocumentEligibility(
                available=True,
                state="dokument_erstellt",
                can_prepare=False,
                snapshot=self._summary(existing, version_number),
            )
        blocked = self._prepare_blocker(order)
        if blocked is not None:
            return OrderConfirmationDocumentEligibility(
                available=False,
                state=blocked,
                blocker_code=blocked,
                can_prepare=False,
            )
        inquiry = self._inquiries.get_by_id(order.source_inquiry_id)
        recipient_status = _recipient_status_from_inquiry(inquiry)
        state = (
            "empfaenger_fehlt"
            if recipient_status == "missing"
            else "bereit_zur_vorschau"
        )
        return OrderConfirmationDocumentEligibility(
            available=True,
            state=state,
            can_prepare=True,
        )

    def prepare_snapshot(
        self,
        order_id: str,
        expected_effective_order_version_id: str,
        created_by: str,
        *,
        invoice_address: CustomerAddress | None = None,
        delivery_address: CustomerAddress | None = None,
    ) -> OrderConfirmationDocumentSnapshot:
        order = self._orders.get_order(order_id)
        if order is None:
            raise OrderConfirmationDocumentNotFoundError(order_id)
        blocker = self._operational_blocker(order)
        if blocker is not None:
            raise OrderConfirmationDocumentBlockedError(blocker)
        if order.effective_order_version_id != expected_effective_order_version_id:
            raise OrderConfirmationDocumentStaleVersionError(
                "expected effective order version is stale"
            )
        existing = self._documents.get_by_order_version_id(
            expected_effective_order_version_id
        )
        if existing is not None:
            return existing
        assert order.effective_order_version_id is not None
        version = self._require_effective_version(order)
        commercial = self._commercial_snapshots.get_by_order_id(order.order_id)
        if commercial is None:
            raise MissingCommercialSnapshotError(order.order_id)
        inquiry = self._inquiries.get_by_id(order.source_inquiry_id)
        document_id = str(uuid.uuid4())
        created_at = self._now()
        projection = self._projection.build(
            document_type="ORDER_CONFIRMATION",
            document_id=document_id,
            created_at=created_at,
            order_version=version,
            commercial_snapshot=commercial,
            inquiry=inquiry,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
        )
        draft = _persist_snapshot_from_projection(
            projection,
            inquiry=inquiry,
            created_by=created_by,
            document_hash="sha256:" + ("0" * 64),
        )
        snapshot = _persist_snapshot_from_projection(
            projection,
            inquiry=inquiry,
            created_by=created_by,
            document_hash=compute_document_hash(draft),
        )
        self._documents.insert(snapshot)
        return snapshot

    def get_snapshot(
        self,
        order_id: str,
        document_snapshot_id: str,
    ) -> OrderConfirmationDocumentSnapshot:
        snapshot = self._documents.get_by_id(document_snapshot_id)
        if snapshot is None or snapshot.order_id != order_id:
            raise OrderConfirmationDocumentNotFoundError(document_snapshot_id)
        return snapshot

    def summary_for_snapshot(
        self, snapshot: OrderConfirmationDocumentSnapshot
    ) -> OrderConfirmationDocumentSummary:
        version = self._orders.get_order_version(snapshot.order_version_id)
        version_number = version.version_number if version is not None else 0
        return self._summary(snapshot, version_number)

    def get_latest_snapshot(
        self, order_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        return self._documents.get_latest_for_order(order_id)

    def _summary(
        self,
        snapshot: OrderConfirmationDocumentSnapshot,
        version_number: int,
    ) -> OrderConfirmationDocumentSummary:
        from catering_system.domain.order_confirmation_document import (
            mask_recipient_email,
            short_document_hash,
        )

        return OrderConfirmationDocumentSummary(
            document_snapshot_id=snapshot.document_snapshot_id,
            order_id=snapshot.order_id,
            order_version_id=snapshot.order_version_id,
            document_reference=snapshot.document_reference,
            created_at=snapshot.created_at,
            created_by=snapshot.created_by,
            recipient_status=snapshot.recipient_status,
            recipient_email_masked=mask_recipient_email(snapshot.recipient_email),
            document_hash_short=short_document_hash(snapshot.document_hash),
            net_total_cents=snapshot.net_total_cents,
            vat_total_cents=snapshot.vat_total_cents,
            gross_total_cents=snapshot.gross_total_cents,
            effective_version_number=version_number,
        )

    def _operational_blocker(self, order: Order) -> str | None:
        if order.cancelled_at is not None:
            return "nicht_verfuegbar"
        if order.effective_order_version_id is None:
            return "nicht_verfuegbar"
        version = self._orders.get_order_version(order.effective_order_version_id)
        if version is None:
            return "nicht_verfuegbar"
        if order.candidate_order_version_id is not None:
            return "aenderung_wartet"
        if version.kitchen_print_confirmed_at is None:
            return "aenderung_wartet"
        return None

    def _prepare_blocker(self, order: Order) -> str | None:
        blocked = self._operational_blocker(order)
        if blocked is not None:
            return blocked
        if self._commercial_snapshots.get_by_order_id(order.order_id) is None:
            return "nicht_verfuegbar"
        return None

    def _require_effective_version(self, order: Order) -> OrderVersion:
        version_id = order.effective_order_version_id
        assert version_id is not None
        version = self._orders.get_order_version(version_id)
        if version is None:
            raise OrderConfirmationDocumentBlockedError("nicht_verfuegbar")
        return version


def _recipient_status_from_inquiry(inquiry: Inquiry | None) -> RecipientStatus:
    if inquiry is None or inquiry.customer_snapshot is None:
        return "missing"
    return "ready" if inquiry.customer_snapshot.email else "missing"


def _persist_snapshot_from_projection(
    projection: CustomerDocumentProjection,
    *,
    inquiry: Inquiry | None,
    created_by: str,
    document_hash: str,
) -> OrderConfirmationDocumentSnapshot:
    positions, buckets = _positions_and_buckets(projection)
    if (
        projection.net_total_cents + projection.vat_total_cents
        != projection.gross_total_cents
    ):
        raise OrderConfirmationDocumentBlockedError("commercial_totals_invalid")
    contact = inquiry.customer_snapshot if inquiry is not None else None
    return OrderConfirmationDocumentSnapshot(
        document_snapshot_id=projection.document_id,
        order_id=projection.event.order_id,
        order_version_id=projection.event.order_version_id,
        offer_id=projection.commercial_reference.source_offer_id,
        offer_version_id=projection.commercial_reference.source_offer_version_id,
        document_reference=document_reference(
            projection.event.order_id, projection.event.version_number
        ),
        created_at=projection.created_at,
        created_by=created_by,
        recipient_name=projection.recipient.name,
        recipient_email=projection.recipient.email,
        recipient_company=contact.company_name if contact is not None else None,
        recipient_phone=contact.phone if contact is not None else None,
        recipient_status=("ready" if projection.recipient.email else "missing"),
        event_date=projection.event.event_date,
        time_window_text=projection.event.time_window_text,
        location_text=projection.event.location_text,
        guest_count_estimate=projection.event.guest_count_estimate,
        planning_mode=projection.event.planning_mode,
        positions=positions,
        vat_buckets=buckets,
        net_total_cents=projection.net_total_cents,
        vat_total_cents=projection.vat_total_cents,
        gross_total_cents=projection.gross_total_cents,
        payment_method=projection.payment_method,
        payment_customer_visible_text=projection.payment_customer_visible_text,
        document_hash=document_hash,
        document_warnings=tuple(projection.recipient.warnings),
    )


def _positions_and_buckets(
    projection: CustomerDocumentProjection,
) -> tuple[
    tuple[OrderConfirmationDocumentPosition, ...],
    tuple[OrderConfirmationVatBucket, ...],
]:
    mapped: list[OrderConfirmationDocumentPosition] = []
    bucket_totals: dict[int, dict[str, int]] = {}
    for position in projection.positions:
        mapped.append(
            OrderConfirmationDocumentPosition(
                position_id=position.position_id,
                kind=position.kind,
                name=position.name,
                description=position.description,
                composition=position.composition,
                quantity=position.quantity,
                unit_label=position.unit_label,
                unit_net_cents=position.unit_net_cents,
                net_total_cents=position.net_total_cents,
                vat_rate_percent=position.vat_rate_percent,
                vat_cents=position.vat_amount_cents,
                gross_cents=position.gross_total_cents,
                related_position_id=position.related_position_id,
            )
        )
        bucket = bucket_totals.setdefault(
            position.vat_rate_percent,
            {"base_net_cents": 0, "vat_cents": 0},
        )
        bucket["base_net_cents"] += position.net_total_cents
        bucket["vat_cents"] += position.vat_amount_cents
    buckets = tuple(
        OrderConfirmationVatBucket(
            rate_percent=rate,
            base_net_cents=values["base_net_cents"],
            vat_cents=values["vat_cents"],
        )
        for rate, values in sorted(bucket_totals.items())
    )
    return tuple(mapped), buckets


def payment_method_label(method: str) -> str:
    return PAYMENT_METHOD_LABELS[validate_payment_method(method)]

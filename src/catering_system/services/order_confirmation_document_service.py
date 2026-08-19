"""Build and read frozen Auftragsbestätigung document snapshots — EMAIL_MVP_1 B1.

Lifecycle: build CustomerDocumentProjection → evaluate eligibility → persist.
Create policy lives in evaluate_customer_document_eligibility only.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from catering_system.domain.customer_document_eligibility import (
    CustomerDocumentCreationBlocked,
)
from catering_system.domain.customer_document_eligibility import (
    CustomerDocumentEligibility as DocumentCreateEligibility,
)
from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerAddress,
    CustomerDocumentProjection,
    CustomerDocumentRecipient,
    customer_addresses_equal,
)
from catering_system.domain.inquiry import FulfillmentMode
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import OrderCommercialSnapshot
from catering_system.domain.order_confirmation_document import (
    SCHEMA_VERSION_V3,
    OrderConfirmationDocumentPosition,
    OrderConfirmationDocumentSnapshot,
    OrderConfirmationVatBucket,
    RecipientStatus,
)
from catering_system.domain.order_payment_reminder import (
    PAYMENT_METHOD_LABELS,
    OrderPaymentReminder,
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
from catering_system.repositories.payment_reminder_repository import (
    PaymentReminderRepository,
)
from catering_system.services.customer_document_eligibility import (
    evaluate_customer_document_eligibility,
)
from catering_system.services.customer_document_projection import (
    CustomerDocumentProjectionService,
    build_customer_document_recipient,
    resolve_document_payment,
)
from catering_system.services.order_confirmation_document_hash import (
    compute_document_hash,
)


class OrderConfirmationDocumentNotFoundError(LookupError):
    """Raised when the requested snapshot does not exist."""


class OrderConfirmationDocumentBlockedError(ValueError):
    """Legacy/internal refusal (e.g. invalid commercial totals).

    Create-policy refusals use CustomerDocumentCreationBlocked instead.
    """


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
        payment_reminder_repository: PaymentReminderRepository | None = None,
        projection_service: CustomerDocumentProjectionService | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders = order_repository
        self._inquiries = inquiry_repository
        self._documents = document_repository
        self._commercial_snapshots = commercial_snapshot_repository
        self._payment_reminders = payment_reminder_repository
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
        decision = self._evaluate_create(order)
        if not decision.allowed:
            primary = decision.blockers[0].code
            return OrderConfirmationDocumentEligibility(
                available=False,
                state=primary,
                blocker_code=primary,
                can_prepare=False,
            )
        return OrderConfirmationDocumentEligibility(
            available=True,
            state="bereit_zur_vorschau",
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
        existing = self._documents.get_by_order_version_id(
            expected_effective_order_version_id
        )
        if existing is not None:
            return existing

        version, commercial, recipient, fulfillment_mode = self._create_inputs(
            order,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
        )
        decision = evaluate_customer_document_eligibility(
            order=order,
            order_version=version,
            commercial_snapshot=commercial,
            recipient=recipient,
            fulfillment_mode=fulfillment_mode,
        )
        if not decision.allowed:
            raise CustomerDocumentCreationBlocked(decision)
        if order.effective_order_version_id != expected_effective_order_version_id:
            raise OrderConfirmationDocumentStaleVersionError(
                "expected effective order version is stale"
            )
        assert commercial is not None
        assert version is not None

        document_id = str(uuid.uuid4())
        created_at = self._now()
        payment_method, payment_customer_visible_text = resolve_document_payment(
            commercial, self._payment_reminder(order.order_id)
        )
        projection = self._projection.build(
            document_type="ORDER_CONFIRMATION",
            document_id=document_id,
            created_at=created_at,
            order_version=version,
            commercial_snapshot=commercial,
            inquiry=self._inquiries.get_by_id(order.source_inquiry_id),
            invoice_address=invoice_address,
            delivery_address=delivery_address,
            payment_method=payment_method,
            payment_customer_visible_text=payment_customer_visible_text,
        )
        projection = replace(projection, recipient=recipient)
        draft = _persist_snapshot_from_projection(
            projection,
            created_by=created_by,
            document_hash="sha256:" + ("0" * 64),
        )
        snapshot = _persist_snapshot_from_projection(
            projection,
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

    def _evaluate_create(
        self,
        order: Order,
        *,
        invoice_address: CustomerAddress | None = None,
        delivery_address: CustomerAddress | None = None,
    ) -> DocumentCreateEligibility:
        version, commercial, recipient, fulfillment_mode = self._create_inputs(
            order,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
        )
        return evaluate_customer_document_eligibility(
            order=order,
            order_version=version,
            commercial_snapshot=commercial,
            recipient=recipient,
            fulfillment_mode=fulfillment_mode,
        )

    def _create_inputs(
        self,
        order: Order,
        *,
        invoice_address: CustomerAddress | None = None,
        delivery_address: CustomerAddress | None = None,
    ) -> tuple[
        OrderVersion | None,
        OrderCommercialSnapshot | None,
        CustomerDocumentRecipient,
        FulfillmentMode,
    ]:
        version: OrderVersion | None = None
        if order.effective_order_version_id is not None:
            version = self._orders.get_order_version(order.effective_order_version_id)
        commercial = self._commercial_snapshots.get_by_order_id(order.order_id)
        inquiry = self._inquiries.get_by_id(order.source_inquiry_id)
        fulfillment_mode: FulfillmentMode = (
            inquiry.fulfillment_mode if inquiry is not None else "UNKNOWN"
        )
        recipient = build_customer_document_recipient(
            inquiry,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
            fulfillment_mode=fulfillment_mode,
        )
        if (
            invoice_address is None
            and delivery_address is None
            and version is not None
            and version.parent_order_version_id is not None
        ):
            context = self._orders.get_operational_context(version.order_version_id)
            if context is not None:
                exact_delivery = (
                    None if fulfillment_mode == "PICKUP" else context.delivery_address
                )
                differs = (
                    recipient.invoice_address is not None
                    and exact_delivery is not None
                    and not customer_addresses_equal(
                        recipient.invoice_address, exact_delivery
                    )
                )
                warnings = (WARNING_DELIVERY_ADDRESS_DIFFERS,) if differs else ()
                recipient = replace(
                    recipient,
                    delivery_address=exact_delivery,
                    delivery_address_differs=differs,
                    warnings=warnings,
                )
        return version, commercial, recipient, fulfillment_mode

    def _payment_reminder(self, order_id: str) -> OrderPaymentReminder | None:
        if self._payment_reminders is None:
            return None
        return self._payment_reminders.get(order_id)


def _persist_snapshot_from_projection(
    projection: CustomerDocumentProjection,
    *,
    created_by: str,
    document_hash: str,
) -> OrderConfirmationDocumentSnapshot:
    positions, buckets = _positions_and_buckets(projection)
    if (
        projection.net_total_cents + projection.vat_total_cents
        != projection.gross_total_cents
    ):
        raise OrderConfirmationDocumentBlockedError("commercial_totals_invalid")
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
        recipient_company=projection.recipient.company_name,
        recipient_phone=projection.recipient.phone,
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
        schema_version=SCHEMA_VERSION_V3,
        document_warnings=tuple(projection.recipient.warnings),
        invoice_address=projection.recipient.invoice_address,
        delivery_address=projection.recipient.delivery_address,
        delivery_address_differs=projection.recipient.delivery_address_differs,
        fulfillment_mode=projection.fulfillment_mode,
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

"""Build and read frozen Auftragsbestätigung document snapshots — EMAIL_MVP_1 B1."""

from __future__ import annotations

import uuid
from typing import Callable, Protocol, cast
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from catering_system.domain.inquiry import Inquiry
from catering_system.domain.offer import (
    PositionKind,
    PositionQuantityMode,
    VatRatePercent,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import (
    MissingCommercialSnapshotError,
    OrderCommercialSnapshot,
)
from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentPosition,
    OrderConfirmationDocumentSnapshot,
    OrderConfirmationVatBucket,
    RecipientStatus,
)
from catering_system.domain.order_payment_reminder import (
    PAYMENT_METHOD_LABELS,
    PaymentMethod,
    validate_payment_method,
)
from catering_system.intake.intake_contact import (
    labelled_intake_context,
    parse_intake_contact,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_confirmation_document_repository import (
    OrderConfirmationDocumentRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.order_confirmation_document_hash import (
    compute_document_hash,
)
from catering_system.services.order_print_projection_service import (
    format_quantity_display,
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


@dataclass(frozen=True)
class _CommercialFacts:
    offer_id: str
    offer_version_id: str
    payment_method: PaymentMethod
    payment_customer_visible_text: str
    positions: tuple[_PricedCommercialPosition, ...]


class _PricedCommercialPosition(Protocol):
    @property
    def position_id(self) -> str: ...

    @property
    def kind(self) -> PositionKind: ...

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str | None: ...

    @property
    def composition(self) -> str | None: ...

    @property
    def quantity(self) -> Decimal | None: ...

    @property
    def quantity_mode(self) -> PositionQuantityMode | None: ...

    @property
    def unit_label(self) -> str | None: ...

    @property
    def unit_net_cents(self) -> int: ...

    @property
    def net_total_cents(self) -> int: ...

    @property
    def vat_rate_percent(self) -> VatRatePercent: ...

    @property
    def vat_amount_cents(self) -> int: ...

    @property
    def gross_total_cents(self) -> int: ...

    @property
    def related_position_id(self) -> str | None: ...


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
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders = order_repository
        self._inquiries = inquiry_repository
        self._documents = document_repository
        self._commercial_snapshots = commercial_snapshot_repository
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
        commercial = self._resolve_commercial(order)
        inquiry = self._inquiries.get_by_id(order.source_inquiry_id)
        recipient = _recipient_snapshot(inquiry)
        positions, buckets, totals = _commercial_positions(
            commercial.positions,
            guest_count_estimate=version.guest_count_estimate,
        )
        reference = document_reference(order.order_id, version.version_number)
        draft = OrderConfirmationDocumentSnapshot(
            document_snapshot_id=str(uuid.uuid4()),
            order_id=order.order_id,
            order_version_id=version.order_version_id,
            offer_id=commercial.offer_id,
            offer_version_id=commercial.offer_version_id,
            document_reference=reference,
            created_at=self._now(),
            created_by=created_by,
            recipient_name=recipient["recipient_name"],
            recipient_email=recipient["recipient_email"],
            recipient_company=recipient["recipient_company"],
            recipient_phone=recipient["recipient_phone"],
            recipient_status=cast(RecipientStatus, recipient["recipient_status"]),
            event_date=version.event_date,
            time_window_text=version.time_window_text,
            location_text=version.location_text,
            guest_count_estimate=version.guest_count_estimate,
            planning_mode=version.planning_mode,
            positions=positions,
            vat_buckets=buckets,
            net_total_cents=totals["net_total_cents"],
            vat_total_cents=totals["vat_total_cents"],
            gross_total_cents=totals["gross_total_cents"],
            payment_method=commercial.payment_method,
            payment_customer_visible_text=commercial.payment_customer_visible_text,
            document_hash="sha256:" + ("0" * 64),
        )
        snapshot = OrderConfirmationDocumentSnapshot(
            document_snapshot_id=draft.document_snapshot_id,
            order_id=draft.order_id,
            order_version_id=draft.order_version_id,
            offer_id=draft.offer_id,
            offer_version_id=draft.offer_version_id,
            document_reference=draft.document_reference,
            created_at=draft.created_at,
            created_by=draft.created_by,
            recipient_name=draft.recipient_name,
            recipient_email=draft.recipient_email,
            recipient_company=draft.recipient_company,
            recipient_phone=draft.recipient_phone,
            recipient_status=draft.recipient_status,
            event_date=draft.event_date,
            time_window_text=draft.time_window_text,
            location_text=draft.location_text,
            guest_count_estimate=draft.guest_count_estimate,
            planning_mode=draft.planning_mode,
            positions=draft.positions,
            vat_buckets=draft.vat_buckets,
            net_total_cents=draft.net_total_cents,
            vat_total_cents=draft.vat_total_cents,
            gross_total_cents=draft.gross_total_cents,
            payment_method=draft.payment_method,
            payment_customer_visible_text=draft.payment_customer_visible_text,
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

    def _resolve_commercial(self, order: Order) -> _CommercialFacts:
        snapshot = self._commercial_snapshots.get_by_order_id(order.order_id)
        if snapshot is None:
            raise MissingCommercialSnapshotError(order.order_id)
        return _commercial_from_snapshot(snapshot)


def _commercial_from_snapshot(snapshot: OrderCommercialSnapshot) -> _CommercialFacts:
    return _CommercialFacts(
        offer_id=snapshot.source_offer_id,
        offer_version_id=snapshot.source_offer_version_id,
        payment_method=snapshot.payment_method,
        payment_customer_visible_text=snapshot.payment_customer_visible_text,
        positions=snapshot.positions,
    )


def _recipient_status_from_inquiry(inquiry: Inquiry | None) -> RecipientStatus:
    if inquiry is None:
        return "missing"
    parsed = parse_intake_contact(inquiry)
    return "ready" if parsed["email"] else "missing"


def _recipient_snapshot(
    inquiry: Inquiry | None,
) -> dict[str, RecipientStatus | str | None]:
    if inquiry is None:
        return {
            "recipient_name": None,
            "recipient_email": None,
            "recipient_company": None,
            "recipient_phone": None,
            "recipient_status": "missing",
        }
    labelled, _remaining = labelled_intake_context(inquiry.intake_message)
    parsed = parse_intake_contact(inquiry)
    company = labelled.get("Firma", "").strip() or None
    person = labelled.get("Name", "").strip() or None
    recipient_name = person or parsed["display_name"]
    email = parsed["email"]
    return {
        "recipient_name": recipient_name,
        "recipient_email": email,
        "recipient_company": company,
        "recipient_phone": parsed["phone"],
        "recipient_status": "ready" if email else "missing",
    }


def _commercial_positions(
    positions: tuple[_PricedCommercialPosition, ...],
    *,
    guest_count_estimate: int | None,
) -> tuple[
    tuple[OrderConfirmationDocumentPosition, ...],
    tuple[OrderConfirmationVatBucket, ...],
    dict[str, int],
]:
    mapped: list[OrderConfirmationDocumentPosition] = []
    bucket_totals: dict[int, dict[str, int]] = {}
    net_total = 0
    vat_total = 0
    gross_total = 0
    for position in positions:
        quantity = format_quantity_display(position, guest_count_estimate)
        mapped.append(
            OrderConfirmationDocumentPosition(
                position_id=position.position_id,
                kind=position.kind,
                name=position.name,
                description=position.description,
                composition=position.composition,
                quantity=quantity,
                unit_label=position.unit_label,
                unit_net_cents=position.unit_net_cents,
                net_total_cents=position.net_total_cents,
                vat_rate_percent=position.vat_rate_percent,
                vat_cents=position.vat_amount_cents,
                gross_cents=position.gross_total_cents,
                related_position_id=position.related_position_id,
            )
        )
        net_total += position.net_total_cents
        vat_total += position.vat_amount_cents
        gross_total += position.gross_total_cents
        bucket = bucket_totals.setdefault(
            position.vat_rate_percent,
            {"base_net_cents": 0, "vat_cents": 0},
        )
        bucket["base_net_cents"] += position.net_total_cents
        bucket["vat_cents"] += position.vat_amount_cents
    if net_total + vat_total != gross_total:
        raise OrderConfirmationDocumentBlockedError("commercial_totals_invalid")
    position_net = sum(item.net_total_cents for item in mapped)
    position_vat = sum(item.vat_cents for item in mapped)
    position_gross = sum(item.gross_cents for item in mapped)
    if (position_net, position_vat, position_gross) != (
        net_total,
        vat_total,
        gross_total,
    ):
        raise OrderConfirmationDocumentBlockedError("commercial_totals_invalid")
    buckets = tuple(
        OrderConfirmationVatBucket(
            rate_percent=rate,
            base_net_cents=values["base_net_cents"],
            vat_cents=values["vat_cents"],
        )
        for rate, values in sorted(bucket_totals.items())
    )
    return (
        tuple(mapped),
        buckets,
        {
            "net_total_cents": net_total,
            "vat_total_cents": vat_total,
            "gross_total_cents": gross_total,
        },
    )


def payment_method_label(method: str) -> str:
    return PAYMENT_METHOD_LABELS[validate_payment_method(method)]

"""Read-only print projection joining OrderVersion facts with commercial snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import FulfillmentMode
from catering_system.domain.offer import PositionQuantityMode
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import (
    MissingCommercialSnapshotError,
    OrderCommercialPosition,
    OrderCommercialSnapshot,
)
from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentSnapshot,
)
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_confirmation_document_repository import (
    OrderConfirmationDocumentRepository,
)
from catering_system.repositories.order_repository import OrderRepository

PrintIntent = Literal["preview", "change_preview", "final", "kitchen_job"]
PrintWatermark = Literal["ENTWURF", "VERALTET", "ÄNDERUNG – NOCH NICHT WIRKSAM"]


class PrintProjectionNotFoundError(LookupError):
    """Order or version does not exist, or version is not owned by the order."""


class PrintFinalRequiresEffectiveError(ValueError):
    """Final print intent requires the effective OrderVersion."""


@dataclass(frozen=True)
class PrintChangeLine:
    label: str
    before: str
    after: str


@dataclass(frozen=True)
class PrintEventBlock:
    order_id: str
    order_version_id: str
    version_number: int
    event_date: date
    time_window_text: str
    location_text: str
    guest_count_estimate: int | None
    planning_mode: str
    kitchen_print_confirmed_at: datetime | None
    order_cancelled_at: datetime | None
    is_candidate: bool
    is_effective: bool
    change_reason: str | None = None
    changed_fields: tuple[str, ...] = ()
    change_lines: tuple[PrintChangeLine, ...] = ()


@dataclass(frozen=True)
class PrintPositionLine:
    position_id: str
    kind: str
    name: str
    description: str | None
    composition: str | None
    notes: str | None
    quantity_display: str | None
    unit_label: str | None


@dataclass(frozen=True)
class PrintCommercialBlock:
    source: Literal["offer_conversion", "none"]
    offer_id: str | None = None
    offer_version_id: str | None = None
    accepted_variant_id: str | None = None
    variant_label: str | None = None
    payment_method: str | None = None
    gross_total_cents: int | None = None
    positions: tuple[PrintPositionLine, ...] = ()


@dataclass(frozen=True)
class PrintCustomerBlock:
    company_name: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    delivery_address_lines: tuple[str, ...] = ()
    fulfillment_mode: FulfillmentMode = "UNKNOWN"


@dataclass(frozen=True)
class PrintFlagsBlock:
    intent: PrintIntent
    is_preview: bool
    is_final_allowed: bool
    is_stale: bool
    watermark: PrintWatermark | None


@dataclass(frozen=True)
class OrderPrintProjection:
    event: PrintEventBlock
    commercial: PrintCommercialBlock
    flags: PrintFlagsBlock
    customer: PrintCustomerBlock = PrintCustomerBlock()


class _QuantityDisplaySource(Protocol):
    @property
    def quantity(self) -> Decimal | None: ...

    @property
    def quantity_mode(self) -> PositionQuantityMode | None: ...

    @property
    def unit_label(self) -> str | None: ...


def format_quantity_display(
    position: _QuantityDisplaySource, guest_count_estimate: int | None
) -> str | None:
    if position.quantity is None:
        return None
    quantity_text = _decimal_text(position.quantity)
    unit = position.unit_label or ""
    if position.quantity_mode == "per_person":
        if guest_count_estimate is None:
            per_person = f"{quantity_text} {unit}".strip()
            return f"{per_person} pro Gast".strip()
        total = position.quantity * guest_count_estimate
        total_text = _decimal_text(total)
        label = unit or "Portionen"
        return f"{total_text} {label}".strip()
    if unit:
        return f"{quantity_text} {unit}".strip()
    return quantity_text


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


class OrderPrintProjectionService:
    """Pure read service: no mutations, no renderer dependencies."""

    def __init__(
        self,
        order_repository: OrderRepository,
        commercial_snapshot_repository: OrderCommercialSnapshotRepository,
        confirmation_document_repository: OrderConfirmationDocumentRepository
        | None = None,
    ) -> None:
        self._orders = order_repository
        self._commercial_snapshots = commercial_snapshot_repository
        self._confirmation_documents = confirmation_document_repository

    def resolve(
        self,
        order_id: str,
        order_version_id: str,
        *,
        intent: PrintIntent = "preview",
    ) -> OrderPrintProjection:
        order = self._orders.get_order(order_id)
        if order is None:
            raise PrintProjectionNotFoundError(order_id)
        version = self._orders.get_order_version(order_version_id)
        if version is None or version.order_id != order_id:
            raise PrintProjectionNotFoundError(order_version_id)
        confirmation_snapshot = self._resolve_confirmation_snapshot(order, version)
        commercial = self._resolve_commercial(
            order, version, confirmation_snapshot=confirmation_snapshot
        )
        flags = self._resolve_flags(order, version, intent=intent)
        if intent == "final" and not flags.is_final_allowed:
            raise PrintFinalRequiresEffectiveError(
                "final print requires the effective order version"
            )
        return OrderPrintProjection(
            event=_event_block(
                order,
                version,
                self._resolve_parent_version(version),
            ),
            commercial=commercial,
            flags=flags,
            customer=_customer_block(confirmation_snapshot),
        )

    def _resolve_confirmation_snapshot(
        self, order: Order, version: OrderVersion
    ) -> OrderConfirmationDocumentSnapshot | None:
        if self._confirmation_documents is None:
            return None
        snapshot = self._confirmation_documents.get_by_order_version_id(
            version.order_version_id
        )
        if snapshot is None or snapshot.order_id != order.order_id:
            return None
        return snapshot

    def _resolve_parent_version(self, version: OrderVersion) -> OrderVersion | None:
        if version.parent_order_version_id is None:
            return None
        parent = self._orders.get_order_version(version.parent_order_version_id)
        if parent is None or parent.order_id != version.order_id:
            return None
        return parent

    def _resolve_commercial(
        self,
        order: Order,
        version: OrderVersion,
        *,
        confirmation_snapshot: OrderConfirmationDocumentSnapshot | None = None,
    ) -> PrintCommercialBlock:
        snapshot = self._commercial_snapshots.get_by_order_id(order.order_id)
        if snapshot is None:
            raise MissingCommercialSnapshotError(order.order_id)
        return _commercial_from_snapshot(
            snapshot,
            version.guest_count_estimate,
            confirmation_snapshot=confirmation_snapshot,
        )

    def _resolve_flags(
        self,
        order: Order,
        version: OrderVersion,
        *,
        intent: PrintIntent,
    ) -> PrintFlagsBlock:
        if intent == "kitchen_job":
            return PrintFlagsBlock(
                intent=intent,
                is_preview=False,
                is_final_allowed=False,
                is_stale=False,
                watermark=None,
            )

        is_effective = version.order_version_id == order.effective_order_version_id
        if intent == "final":
            return PrintFlagsBlock(
                intent=intent,
                is_preview=False,
                is_final_allowed=is_effective and order.cancelled_at is None,
                is_stale=False,
                watermark=None,
            )

        is_candidate_change = (
            version.order_version_id == order.candidate_order_version_id
            and version.parent_order_version_id is not None
            and not is_effective
        )
        watermark = self._preview_watermark(order, version, is_effective=is_effective)
        return PrintFlagsBlock(
            intent="change_preview" if is_candidate_change else intent,
            is_preview=not is_effective,
            is_final_allowed=is_effective and order.cancelled_at is None,
            is_stale=watermark == "VERALTET",
            watermark=watermark,
        )

    def _preview_watermark(
        self,
        order: Order,
        version: OrderVersion,
        *,
        is_effective: bool,
    ) -> PrintWatermark | None:
        if is_effective:
            return None
        if (
            version.order_version_id == order.candidate_order_version_id
            and version.parent_order_version_id is not None
        ):
            return "ÄNDERUNG – NOCH NICHT WIRKSAM"
        effective_id = order.effective_order_version_id
        if effective_id is None:
            return "ENTWURF"
        if effective_id == version.order_version_id:
            return None
        effective = self._orders.get_order_version(effective_id)
        if effective is None or effective.order_id != order.order_id:
            return "ENTWURF"
        if version.version_number < effective.version_number:
            return "VERALTET"
        return "ENTWURF"


def _event_block(
    order: Order, version: OrderVersion, previous: OrderVersion | None = None
) -> PrintEventBlock:
    return PrintEventBlock(
        order_id=order.order_id,
        order_version_id=version.order_version_id,
        version_number=version.version_number,
        event_date=version.event_date,
        time_window_text=version.time_window_text,
        location_text=version.location_text,
        guest_count_estimate=version.guest_count_estimate,
        planning_mode=version.planning_mode,
        kitchen_print_confirmed_at=version.kitchen_print_confirmed_at,
        order_cancelled_at=order.cancelled_at,
        is_candidate=version.order_version_id == order.candidate_order_version_id,
        is_effective=version.order_version_id == order.effective_order_version_id,
        change_reason=version.change_reason,
        changed_fields=version.changed_fields,
        change_lines=_change_lines(previous, version),
    )


def _commercial_from_snapshot(
    snapshot: OrderCommercialSnapshot,
    guest_count_estimate: int | None,
    *,
    confirmation_snapshot: OrderConfirmationDocumentSnapshot | None = None,
) -> PrintCommercialBlock:
    return PrintCommercialBlock(
        source="offer_conversion",
        offer_id=snapshot.source_offer_id,
        offer_version_id=snapshot.source_offer_version_id,
        accepted_variant_id=snapshot.source_variant_id,
        variant_label=snapshot.variant_label,
        payment_method=(
            confirmation_snapshot.payment_method
            if confirmation_snapshot is not None
            else snapshot.payment_method
        ),
        gross_total_cents=(
            confirmation_snapshot.gross_total_cents
            if confirmation_snapshot is not None
            else None
        ),
        positions=tuple(
            _position_line_from_snapshot(position, guest_count_estimate)
            for position in snapshot.positions
        ),
    )


def _position_line_from_snapshot(
    position: OrderCommercialPosition, guest_count_estimate: int | None
) -> PrintPositionLine:
    return PrintPositionLine(
        position_id=position.position_id,
        kind=position.kind,
        name=position.name,
        description=position.description,
        composition=position.composition,
        notes=position.notes,
        quantity_display=format_quantity_display(position, guest_count_estimate),
        unit_label=position.unit_label,
    )


def _customer_block(
    snapshot: OrderConfirmationDocumentSnapshot | None,
) -> PrintCustomerBlock:
    if snapshot is None:
        return PrintCustomerBlock()
    return PrintCustomerBlock(
        company_name=(snapshot.recipient_company or "").strip() or None,
        contact_name=(snapshot.recipient_name or "").strip() or None,
        phone=(snapshot.recipient_phone or "").strip() or None,
        delivery_address_lines=_address_lines(snapshot.delivery_address),
        fulfillment_mode=snapshot.fulfillment_mode or "UNKNOWN",
    )


def _address_lines(address: CustomerAddress | None) -> tuple[str, ...]:
    if address is None:
        return ()
    city_line = " ".join(
        part
        for part in (
            (address.postal_code or "").strip(),
            (address.city or "").strip(),
        )
        if part
    )
    return tuple(
        line
        for line in (
            (address.street or "").strip(),
            city_line,
            (address.country or "").strip(),
        )
        if line
    )


def _change_lines(
    previous: OrderVersion | None, current: OrderVersion
) -> tuple[PrintChangeLine, ...]:
    if previous is None:
        return ()
    lines: list[PrintChangeLine] = []
    _append_change(
        lines,
        "Datum",
        previous.event_date.strftime("%d.%m.%Y"),
        current.event_date.strftime("%d.%m.%Y"),
    )
    _append_change(
        lines,
        "Zeitfenster / Anlieferung",
        previous.time_window_text,
        current.time_window_text,
    )
    _append_change(lines, "Ort", previous.location_text, current.location_text)
    _append_change(
        lines,
        "Gästezahl geändert",
        _optional_int_text(previous.guest_count_estimate),
        _optional_int_text(current.guest_count_estimate),
    )
    return tuple(lines)


def _append_change(
    lines: list[PrintChangeLine], label: str, before: str, after: str
) -> None:
    if before != after:
        lines.append(PrintChangeLine(label=label, before=before, after=after))


def _optional_int_text(value: int | None) -> str:
    return str(value) if value is not None else "–"

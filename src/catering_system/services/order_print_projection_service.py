"""Read-only print projection joining OrderVersion facts with Offer menu data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferVariant,
    PositionQuantityMode,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository

PrintIntent = Literal["preview", "change_preview", "final"]
PrintWatermark = Literal["ENTWURF", "VERALTET", "ÄNDERUNG – NOCH NICHT WIRKSAM"]


class PrintProjectionNotFoundError(LookupError):
    """Order or version does not exist, or version is not owned by the order."""


class PrintFinalRequiresEffectiveError(ValueError):
    """Final print intent requires the effective OrderVersion."""


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
    positions: tuple[PrintPositionLine, ...] = ()


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
        offer_repository: OfferRepository,
    ) -> None:
        self._orders = order_repository
        self._offers = offer_repository

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
        commercial = self._resolve_commercial(order, version)
        flags = self._resolve_flags(order, version, intent=intent)
        if intent == "final" and not flags.is_final_allowed:
            raise PrintFinalRequiresEffectiveError(
                "final print requires the effective order version"
            )
        return OrderPrintProjection(
            event=_event_block(order, version),
            commercial=commercial,
            flags=flags,
        )

    def _resolve_commercial(
        self, order: Order, version: OrderVersion
    ) -> PrintCommercialBlock:
        offer = self._offers.get_by_source_inquiry_id(order.source_inquiry_id)
        if offer is None:
            return PrintCommercialBlock(source="none")
        link = offer.conversion_link
        if link is None or link.order_id != order.order_id:
            return PrintCommercialBlock(source="none")
        variant = _accepted_variant(offer, link.offer_version_id, link.variant_id)
        if variant is None:
            return PrintCommercialBlock(source="none")
        return PrintCommercialBlock(
            source="offer_conversion",
            offer_id=link.offer_id,
            offer_version_id=link.offer_version_id,
            accepted_variant_id=link.variant_id,
            variant_label=variant.label,
            positions=tuple(
                _position_line(position, version.guest_count_estimate)
                for position in variant.positions
            ),
        )

    def _resolve_flags(
        self,
        order: Order,
        version: OrderVersion,
        *,
        intent: PrintIntent,
    ) -> PrintFlagsBlock:
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


def _event_block(order: Order, version: OrderVersion) -> PrintEventBlock:
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
    )


def _accepted_variant(
    offer: Offer, offer_version_id: str, variant_id: str
) -> OfferVariant | None:
    version = next(
        (item for item in offer.versions if item.offer_version_id == offer_version_id),
        None,
    )
    if version is None:
        return None
    return next(
        (item for item in version.variants if item.variant_id == variant_id),
        None,
    )


def _position_line(
    position: OfferPosition, guest_count_estimate: int | None
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

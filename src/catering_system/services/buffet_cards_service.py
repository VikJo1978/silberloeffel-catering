"""Guest buffet cards read model built from OrderPrintProjection."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.order_print_projection_service import (
    OrderPrintProjection,
    OrderPrintProjectionService,
    PrintPositionLine,
    PrintProjectionNotFoundError,
)


@dataclass(frozen=True)
class BuffetCard:
    position_id: str
    name: str
    description: str | None
    composition: str | None
    notes: str | None


@dataclass(frozen=True)
class BuffetCardsView:
    projection: OrderPrintProjection
    cards: tuple[BuffetCard, ...]
    effective_version_number: int | None = None


def build_buffet_cards(projection: OrderPrintProjection) -> tuple[BuffetCard, ...]:
    return tuple(_card_from_position(line) for line in projection.commercial.positions)


def buffet_card_body(card: BuffetCard) -> str:
    parts: list[str] = []
    if card.description:
        parts.append(card.description)
    if card.composition:
        parts.append(card.composition)
    if card.notes:
        parts.append(card.notes)
    return "\n".join(parts)


def _card_from_position(line: PrintPositionLine) -> BuffetCard:
    return BuffetCard(
        position_id=line.position_id,
        name=line.name,
        description=line.description,
        composition=line.composition,
        notes=line.notes,
    )


class BuffetCardsService:
    """Read-only buffet cards resolver; no renderer or mutation dependencies."""

    def __init__(
        self,
        order_repository: OrderRepository,
        print_projection_service: OrderPrintProjectionService,
    ) -> None:
        self._orders = order_repository
        self._projection = print_projection_service

    def resolve(self, order_id: str, order_version_id: str) -> BuffetCardsView:
        projection = self._projection.resolve(
            order_id,
            order_version_id,
            intent="preview",
        )
        return BuffetCardsView(
            projection=projection,
            cards=build_buffet_cards(projection),
            effective_version_number=_effective_version_number(self._orders, order_id),
        )


def _effective_version_number(orders: OrderRepository, order_id: str) -> int | None:
    order = orders.get_order(order_id)
    if order is None or order.effective_order_version_id is None:
        return None
    effective = orders.get_order_version(order.effective_order_version_id)
    if effective is None or effective.order_id != order_id:
        return None
    return effective.version_number


__all__ = [
    "BuffetCard",
    "BuffetCardsService",
    "BuffetCardsView",
    "PrintProjectionNotFoundError",
    "build_buffet_cards",
    "buffet_card_body",
]

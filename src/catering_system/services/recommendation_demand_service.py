"""Read model for same-day production demand consumed by the configurator.

Only catalog item ids and lifecycle confidence leave Core through this projection.
Customer identity and other PII are deliberately excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from catering_system.domain.offer import OfferVariant, derive_offer_state
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)

DemandLifecycle = Literal["CONFIRMED_ORDER", "ACCEPTED_ORDER", "SENT_OFFER"]


@dataclass(frozen=True)
class SameDayDemandRow:
    catalog_item_id: str
    lifecycle: DemandLifecycle


class RecommendationDemandService:
    def __init__(
        self,
        orders: OrderRepository,
        offers: OfferRepository,
        commercial_snapshots: SQLiteOrderCommercialSnapshotRepository,
        *,
        today: date,
    ) -> None:
        self._orders = orders
        self._offers = offers
        self._commercial_snapshots = commercial_snapshots
        self._today = today

    def list_same_day(self, event_date: date) -> tuple[SameDayDemandRow, ...]:
        rows: list[SameDayDemandRow] = []
        covered_offer_ids: set[str] = set()

        for order in self._orders.list_orders():
            if order.cancelled_at is not None:
                continue
            version = self._target_order_version(order)
            if version is None or version.event_date != event_date:
                continue
            snapshot = self._commercial_snapshots.get_by_order_id(order.order_id)
            if snapshot is None:
                continue
            lifecycle: DemandLifecycle = (
                "CONFIRMED_ORDER"
                if order.effective_order_version_id is not None
                else "ACCEPTED_ORDER"
            )
            covered_offer_ids.add(snapshot.source_offer_id)
            for position in snapshot.positions:
                if position.kind == "catalog" and position.catalog_item_id is not None:
                    rows.append(
                        SameDayDemandRow(position.catalog_item_id, lifecycle)
                    )

        for offer in self._offers.list_all():
            if offer.offer_id in covered_offer_ids:
                continue
            version = max(offer.versions, key=lambda item: item.version_number)
            if version.event_date != event_date:
                continue
            if derive_offer_state(offer, version.offer_version_id, today=self._today) != "Sent":
                continue
            for variant in version.variants:
                rows.extend(self._variant_rows(variant))

        return tuple(sorted(rows, key=lambda row: (row.catalog_item_id, row.lifecycle)))

    def _target_order_version(self, order: Order) -> OrderVersion | None:
        target_id = order.effective_order_version_id or order.candidate_order_version_id
        if target_id is not None:
            version = self._orders.get_order_version(target_id)
            if version is not None and version.order_id == order.order_id:
                return version
        versions = self._orders.list_order_versions(order.order_id)
        return max(versions, key=lambda item: item.version_number, default=None)

    @staticmethod
    def _variant_rows(variant: OfferVariant) -> list[SameDayDemandRow]:
        return [
            SameDayDemandRow(position.catalog_item_id, "SENT_OFFER")
            for position in variant.positions
            if position.kind == "catalog" and position.catalog_item_id is not None
        ]

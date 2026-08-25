"""Derive explainable, non-blocking recommendation hints from customer history."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Protocol

from catering_system.domain.customer_order_history import CustomerOrderHistoryEntry
from catering_system.domain.customer_recommendation_hint import CustomerRecommendationHint


class CustomerOrderHistoryReader(Protocol):
    def list_for_customer(self, customer_id: str) -> list[CustomerOrderHistoryEntry]: ...


class CustomerRecommendationHintService:
    """Build deterministic hints without persisting inference or rewriting history."""

    FREQUENT_MIN_ORDERS = 2
    RECENT_WINDOW_DAYS = 90

    def __init__(self, history: CustomerOrderHistoryReader) -> None:
        self._history = history

    def list_for_customer(
        self, customer_id: str, *, as_of: date
    ) -> list[CustomerRecommendationHint]:
        orders = [
            entry
            for entry in self._history.list_for_customer(customer_id)
            if entry.cancelled_at is None
        ]
        by_item: dict[str, list[tuple[CustomerOrderHistoryEntry, str]]] = (
            defaultdict(list)
        )
        for entry in orders:
            seen_in_order: set[str] = set()
            for dish in entry.dishes:
                item_id = dish.catalog_item_id
                if item_id is None or item_id in seen_in_order:
                    continue
                seen_in_order.add(item_id)
                by_item[item_id].append((entry, dish.name))

        hints: list[CustomerRecommendationHint] = []
        for item_id, occurrences in by_item.items():
            occurrences.sort(
                key=lambda item: (
                    item[0].event_date,
                    item[0].order_created_at,
                    item[0].order_id,
                ),
                reverse=True,
            )
            latest_entry, latest_name = occurrences[0]
            source_order_ids = tuple(entry.order_id for entry, _ in occurrences)
            order_count = len(occurrences)

            if order_count >= self.FREQUENT_MIN_ORDERS:
                hints.append(
                    CustomerRecommendationHint(
                        kind="frequently_ordered",
                        catalog_item_id=item_id,
                        display_name=latest_name,
                        order_count=order_count,
                        last_ordered_on=latest_entry.event_date,
                        source_order_ids=source_order_ids,
                        explanation=(
                            f"In {order_count} previous orders; positive soft signal only."
                        ),
                        score_delta=2,
                    )
                )

            age_days = (as_of - latest_entry.event_date).days
            if 0 <= age_days <= self.RECENT_WINDOW_DAYS:
                hints.append(
                    CustomerRecommendationHint(
                        kind="recently_ordered",
                        catalog_item_id=item_id,
                        display_name=latest_name,
                        order_count=order_count,
                        last_ordered_on=latest_entry.event_date,
                        source_order_ids=source_order_ids,
                        explanation=(
                            f"Last ordered {age_days} day(s) ago; repetition penalty is advisory."
                        ),
                        score_delta=-3,
                    )
                )

        return sorted(
            hints,
            key=lambda hint: (
                hint.catalog_item_id,
                hint.kind,
                hint.last_ordered_on,
            ),
        )

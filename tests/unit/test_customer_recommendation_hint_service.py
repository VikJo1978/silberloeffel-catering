from datetime import UTC, date, datetime

from catering_system.domain.customer_order_history import (
    CustomerOrderHistoryDish,
    CustomerOrderHistoryEntry,
)
from catering_system.services.customer_recommendation_hint_service import (
    CustomerRecommendationHintService,
)


def _entry(
    order_id: str,
    event_date: date,
    *dishes: tuple[str, str],
    cancelled: bool = False,
) -> CustomerOrderHistoryEntry:
    return CustomerOrderHistoryEntry(
        order_id=order_id,
        source_inquiry_id=f"inquiry-{order_id}",
        order_version_id=f"version-{order_id}",
        event_date=event_date,
        guest_count=20,
        fulfillment_mode="DELIVERY",
        accepted_offer_id=f"offer-{order_id}",
        accepted_offer_version_id=f"offer-version-{order_id}",
        accepted_variant_id=f"variant-{order_id}",
        accepted_variant_label="Standard",
        dishes=tuple(
            CustomerOrderHistoryDish(
                position_id=f"{order_id}-{item_id}",
                name=name,
                kind="catalog",
                catalog_item_id=item_id,
                gross_total_cents=1000,
            )
            for item_id, name in dishes
        ),
        gross_total_cents=1000 * len(dishes),
        order_created_at=datetime(2026, 1, 1, tzinfo=UTC),
        cancelled_at=(datetime(2026, 1, 2, tzinfo=UTC) if cancelled else None),
    )


class _History:
    def __init__(self, entries: list[CustomerOrderHistoryEntry]) -> None:
        self.entries = entries
        self.customer_ids: list[str] = []

    def list_for_customer(self, customer_id: str) -> list[CustomerOrderHistoryEntry]:
        self.customer_ids.append(customer_id)
        return self.entries


def test_repeated_item_produces_explainable_positive_and_recent_soft_signals() -> None:
    history = _History(
        [
            _entry("order-2", date(2026, 8, 1), ("dish-1", "Mini-Burger")),
            _entry("order-1", date(2026, 5, 1), ("dish-1", "Mini-Burger")),
        ]
    )
    service = CustomerRecommendationHintService(history)

    hints = service.list_for_customer("customer-1", as_of=date(2026, 8, 25))

    assert history.customer_ids == ["customer-1"]
    assert [(hint.kind, hint.score_delta) for hint in hints] == [
        ("frequently_ordered", 2),
        ("recently_ordered", -3),
    ]
    assert all(hint.catalog_item_id == "dish-1" for hint in hints)
    assert all(hint.order_count == 2 for hint in hints)
    assert all(hint.source_order_ids == ("order-2", "order-1") for hint in hints)
    assert "soft signal only" in hints[0].explanation
    assert "advisory" in hints[1].explanation


def test_single_old_item_has_no_hint() -> None:
    service = CustomerRecommendationHintService(
        _History([_entry("order-1", date(2026, 1, 1), ("dish-1", "Suppe"))])
    )

    assert service.list_for_customer("customer-1", as_of=date(2026, 8, 25)) == []


def test_cancelled_orders_do_not_become_taste_evidence() -> None:
    service = CustomerRecommendationHintService(
        _History(
            [
                _entry(
                    "order-cancelled",
                    date(2026, 8, 20),
                    ("dish-1", "Suppe"),
                    cancelled=True,
                )
            ]
        )
    )

    assert service.list_for_customer("customer-1", as_of=date(2026, 8, 25)) == []


def test_custom_positions_without_catalog_identity_are_not_inferred() -> None:
    entry = _entry("order-1", date(2026, 8, 20))
    entry = CustomerOrderHistoryEntry(
        **{
            **entry.__dict__,
            "dishes": (
                CustomerOrderHistoryDish(
                    position_id="custom-1",
                    name="Spezialplatte",
                    kind="custom",
                    catalog_item_id=None,
                    gross_total_cents=1000,
                ),
            ),
        }
    )
    service = CustomerRecommendationHintService(_History([entry]))

    assert service.list_for_customer("customer-1", as_of=date(2026, 8, 25)) == []


def test_same_catalog_item_is_counted_once_per_order() -> None:
    service = CustomerRecommendationHintService(
        _History(
            [
                _entry(
                    "order-1",
                    date(2026, 8, 20),
                    ("dish-1", "Mini-Burger"),
                    ("dish-1", "Mini-Burger"),
                )
            ]
        )
    )

    hints = service.list_for_customer("customer-1", as_of=date(2026, 8, 25))

    assert len(hints) == 1
    assert hints[0].kind == "recently_ordered"
    assert hints[0].order_count == 1

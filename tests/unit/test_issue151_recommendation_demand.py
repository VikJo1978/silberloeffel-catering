from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import catering_system.services.recommendation_demand_service as demand_module
from catering_system.domain.order import Order, OrderVersion
from catering_system.services.recommendation_demand_service import (
    RecommendationDemandService,
    SameDayDemandRow,
)
from catering_system.ui.office_api import OfficeApi

EVENT_DATE = date(2026, 8, 23)
OTHER_DATE = date(2026, 8, 24)
NOW = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)


def _order(
    order_id: str,
    *,
    candidate: str | None = None,
    effective: str | None = None,
    cancelled: bool = False,
) -> Order:
    return Order(
        order_id=order_id,
        source_inquiry_id=f"inq-{order_id}",
        created_at=NOW,
        updated_at=NOW,
        candidate_order_version_id=candidate,
        effective_order_version_id=effective,
        cancelled_at=NOW if cancelled else None,
    )


def _version(
    version_id: str,
    order_id: str,
    event_date: date,
    number: int = 1,
) -> OrderVersion:
    return OrderVersion(
        order_version_id=version_id,
        order_id=order_id,
        version_number=number,
        created_at=NOW,
        event_date=event_date,
        time_window_text="18:00-19:00",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
    )


def _position(kind: str, catalog_item_id: str | None) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, catalog_item_id=catalog_item_id)


def _snapshot(source_offer_id: str, *positions: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(source_offer_id=source_offer_id, positions=positions)


def _offer(
    offer_id: str,
    *,
    event_date: date,
    state: str,
    positions: tuple[SimpleNamespace, ...],
) -> SimpleNamespace:
    variant = SimpleNamespace(positions=positions)
    version = SimpleNamespace(
        version_number=1,
        event_date=event_date,
        offer_version_id=f"ov-{offer_id}",
        variants=(variant,),
    )
    return SimpleNamespace(offer_id=offer_id, versions=(version,), state=state)


def test_same_day_demand_combines_orders_and_open_sent_offers(monkeypatch) -> None:
    confirmed = _order("confirmed", effective="v-confirmed")
    accepted = _order("accepted", candidate="v-accepted")
    cancelled = _order("cancelled", candidate="v-cancelled", cancelled=True)
    wrong_date = _order("wrong-date", candidate="v-wrong")
    no_snapshot = _order("no-snapshot", candidate="v-no-snapshot")

    versions = {
        "v-confirmed": _version("v-confirmed", "confirmed", EVENT_DATE),
        "v-accepted": _version("v-accepted", "accepted", EVENT_DATE),
        "v-cancelled": _version("v-cancelled", "cancelled", EVENT_DATE),
        "v-wrong": _version("v-wrong", "wrong-date", OTHER_DATE),
        "v-no-snapshot": _version("v-no-snapshot", "no-snapshot", EVENT_DATE),
    }

    orders = Mock()
    orders.list_orders.return_value = [
        confirmed,
        accepted,
        cancelled,
        wrong_date,
        no_snapshot,
    ]
    orders.get_order_version.side_effect = versions.get
    orders.list_order_versions.return_value = []

    commercial_snapshots = Mock()
    commercial_snapshots.get_by_order_id.side_effect = lambda order_id: {
        "confirmed": _snapshot(
            "covered-offer",
            _position("catalog", "item-z"),
            _position("custom", None),
            _position("catalog", None),
        ),
        "accepted": _snapshot("accepted-offer", _position("catalog", "item-a")),
        "no-snapshot": None,
    }.get(order_id)

    offers = Mock()
    offers.list_all.return_value = [
        _offer(
            "covered-offer",
            event_date=EVENT_DATE,
            state="Sent",
            positions=(_position("catalog", "must-not-duplicate"),),
        ),
        _offer(
            "sent-offer",
            event_date=EVENT_DATE,
            state="Sent",
            positions=(
                _position("catalog", "item-b"),
                _position("custom", None),
                _position("catalog", None),
            ),
        ),
        _offer(
            "rejected-offer",
            event_date=EVENT_DATE,
            state="Rejected",
            positions=(_position("catalog", "must-not-appear"),),
        ),
        _offer(
            "wrong-date-offer",
            event_date=OTHER_DATE,
            state="Sent",
            positions=(_position("catalog", "wrong-day"),),
        ),
    ]

    monkeypatch.setattr(
        demand_module,
        "derive_offer_state",
        lambda offer, _version_id, *, today: offer.state,
    )

    service = RecommendationDemandService(
        orders,
        offers,
        commercial_snapshots,
        today=lambda: EVENT_DATE,
    )

    assert service.list_same_day(EVENT_DATE) == (
        SameDayDemandRow("item-a", "ACCEPTED_ORDER"),
        SameDayDemandRow("item-b", "SENT_OFFER"),
        SameDayDemandRow("item-z", "CONFIRMED_ORDER"),
    )


def test_target_order_version_falls_back_to_latest_owned_version() -> None:
    orders = Mock()
    offers = Mock()
    snapshots = Mock()
    service = RecommendationDemandService(
        orders,
        offers,
        snapshots,
        today=lambda: EVENT_DATE,
    )

    order = _order("order-1", candidate="stale-target")
    orders.get_order_version.return_value = _version(
        "foreign", "different-order", EVENT_DATE
    )
    orders.list_order_versions.return_value = [
        _version("v1", "order-1", EVENT_DATE, 1),
        _version("v2", "order-1", EVENT_DATE, 2),
    ]

    selected = service._target_order_version(order)
    assert selected is not None
    assert selected.order_version_id == "v2"

    empty_order = _order("empty")
    orders.list_order_versions.return_value = []
    assert service._target_order_version(empty_order) is None


def test_office_api_shapes_recommendation_demand_without_full_initialization() -> None:
    api = OfficeApi.__new__(OfficeApi)
    api.recommendation_demand_service = Mock()
    api.recommendation_demand_service.list_same_day.return_value = (
        SameDayDemandRow("dish-1", "CONFIRMED_ORDER"),
        SameDayDemandRow("dish-2", "SENT_OFFER"),
    )

    assert api.recommendation_demand(EVENT_DATE) == {
        "event_date": "2026-08-23",
        "rows": [
            {"catalog_item_id": "dish-1", "lifecycle": "CONFIRMED_ORDER"},
            {"catalog_item_id": "dish-2", "lifecycle": "SENT_OFFER"},
        ],
    }

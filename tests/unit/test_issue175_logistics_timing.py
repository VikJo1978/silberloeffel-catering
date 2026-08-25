from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest

from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
)
from catering_system.domain.offer_charges import (
    BuffetChargeDefinition,
    DeliveryChargeDefinition,
    DishwareChargeDefinition,
    OfferChargesDefinition,
    ReturnLogisticsDefinition,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository

NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
DAY = date(2026, 9, 12)


def _charges() -> OfferChargesDefinition:
    return OfferChargesDefinition(
        delivery=DeliveryChargeDefinition(amount_cents=1000),
        dishware=DishwareChargeDefinition(
            base_mode="NONE", pauschale_per_person_cents=0
        ),
        buffet=BuffetChargeDefinition(base_mode="NONE", pauschale_per_person_cents=0),
        return_logistics=ReturnLogisticsDefinition(
            mode="SAME_DAY",
            pickup_window_text="22:00–23:00",
            same_day_fee_cents=2500,
            pickup_window_start_local=time(22, 0),
            pickup_window_end_local=time(23, 0),
        ),
    )


def _offer_version() -> OfferVersion:
    position = OfferPosition(
        position_id="position-1",
        kind="fee",
        name="Test",
        unit_net_cents=1000,
        net_total_cents=1000,
        vat_rate_percent=19,
        vat_amount_cents=190,
        gross_total_cents=1190,
    )
    variant = OfferVariant(
        variant_id="variant-1",
        offer_version_id="offer-version-1",
        label="Test",
        positions=(position,),
    )
    return OfferVersion(
        offer_version_id="offer-version-1",
        offer_id="offer-1",
        version_number=1,
        created_at=NOW,
        valid_until=date(2026, 9, 11),
        snapshot_id="snapshot-1",
        snapshot_hash="sha256:" + "a" * 64,
        event_date=DAY,
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count=20,
        planning_mode="caterer_suggestion",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Rechnung",
        variants=(variant,),
        charges_definition=_charges(),
        delivery_date_local=DAY,
        delivery_window_start_local=time(16, 0),
        delivery_window_end_local=time(17, 0),
    )


def test_offer_sqlite_roundtrip_preserves_canonical_logistics_timing(
    tmp_path: Path,
) -> None:
    repo = SQLiteOfferRepository(tmp_path / "offers.db")
    version = _offer_version()
    repo.save(
        Offer(
            offer_id="offer-1",
            source_inquiry_id="inquiry-1",
            created_at=NOW,
            versions=(version,),
        )
    )
    loaded = repo.get("offer-1")
    assert loaded is not None
    actual = loaded.versions[0]
    assert actual.delivery_date_local == DAY
    assert actual.delivery_window_start_local == time(16, 0)
    assert actual.delivery_window_end_local == time(17, 0)
    assert actual.charges_definition is not None
    return_plan = actual.charges_definition.return_logistics
    assert return_plan.pickup_window_start_local == time(22, 0)
    assert return_plan.pickup_window_end_local == time(23, 0)


def test_order_sqlite_roundtrip_preserves_canonical_delivery_window(
    tmp_path: Path,
) -> None:
    repo = SQLiteOrderRepository(tmp_path / "orders.db")
    order = Order("order-1", "inquiry-1", NOW, NOW)
    version = OrderVersion(
        order_version_id="order-version-1",
        order_id="order-1",
        version_number=1,
        created_at=NOW,
        event_date=DAY,
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
        delivery_date_local=DAY,
        delivery_window_start_local=time(16, 0),
        delivery_window_end_local=time(17, 0),
    )
    repo.save_order_with_initial_version(order, version)
    assert repo.get_order_version("order-version-1") == version


def test_structured_delivery_window_is_atomic_and_ordered() -> None:
    with pytest.raises(ValueError, match="date, start and end together"):
        OrderVersion(
            "v",
            "o",
            1,
            NOW,
            DAY,
            "legacy text",
            "Hamburg",
            10,
            "caterer_suggestion",
            delivery_date_local=DAY,
        )
    with pytest.raises(ValueError, match="start must be before end"):
        OrderVersion(
            "v",
            "o",
            1,
            NOW,
            DAY,
            "legacy text",
            "Hamburg",
            10,
            "caterer_suggestion",
            delivery_date_local=DAY,
            delivery_window_start_local=time(17, 0),
            delivery_window_end_local=time(16, 0),
        )


def test_return_canonical_window_is_optional_but_never_inferred() -> None:
    legacy = ReturnLogisticsDefinition(
        mode="SAME_DAY",
        pickup_window_text="später am Abend",
        same_day_fee_cents=0,
    )
    assert legacy.pickup_window_start_local is None
    assert legacy.pickup_window_end_local is None
    with pytest.raises(ValueError, match="both start and end"):
        ReturnLogisticsDefinition(
            mode="SAME_DAY",
            pickup_window_text="22:00–23:00",
            pickup_window_start_local=time(22, 0),
        )


def test_next_working_day_never_carries_canonical_pickup_times() -> None:
    with pytest.raises(ValueError, match="must not specify canonical pickup times"):
        ReturnLogisticsDefinition(
            mode="NEXT_WORKING_DAY",
            pickup_window_start_local=time(9, 0),
            pickup_window_end_local=time(10, 0),
        )

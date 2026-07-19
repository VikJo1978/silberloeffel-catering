"""Regression: catalog price edits must not rewrite OfferPosition snapshots."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from catering_system.domain.catalog import CatalogDish, CatalogDishUpdatePayload
from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
)
from catering_system.repositories.sqlite_catalog_repository import (
    SQLiteCatalogRepository,
)
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from catering_system.services.catalog_dish_write_service import CatalogDishWriteService

_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
_DISH_ID = "11111111-1111-4111-8111-111111111111"
_OFFER_ID = "22222222-2222-4222-8222-222222222222"
_INQUIRY_ID = "33333333-3333-4333-8333-333333333333"
_VERSION_ID = "44444444-4444-4444-8444-444444444441"
_VARIANT_ID = "55555555-5555-4555-8555-555555555551"
_POSITION_ID = "66666666-6666-4666-8666-666666666661"
_EVENT_DATE = date(2026, 8, 20)


def test_offer_position_unchanged_after_catalog_price_update(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    catalog_repo = SQLiteCatalogRepository(db)
    try:
        catalog_repo.insert_dish_if_absent(
            CatalogDish(
                dish_id=_DISH_ID,
                name="Schnitzel",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=850,
                allergens=("A",),
                active=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        offer_repo = SQLiteOfferRepository(db)
        position = OfferPosition(
            position_id=_POSITION_ID,
            kind="catalog",
            name="Schnitzel",
            unit_net_cents=850,
            net_total_cents=8500,
            vat_rate_percent=7,
            vat_amount_cents=595,
            gross_total_cents=9095,
        )
        version = OfferVersion(
            offer_version_id=_VERSION_ID,
            offer_id=_OFFER_ID,
            version_number=1,
            created_at=_NOW,
            valid_until=date(2026, 12, 31),
            snapshot_id="77777777-7777-4777-8777-777777777771",
            snapshot_hash="sha256:" + ("a" * 64),
            event_date=_EVENT_DATE,
            time_window_text="18:00–22:00",
            location_text="Hamburg",
            guest_count=80,
            planning_mode="caterer_suggestion",
            payment_method="RECHNUNG",
            payment_customer_visible_text="Zahlung per Rechnung",
            variants=(
                OfferVariant(
                    variant_id=_VARIANT_ID,
                    offer_version_id=_VERSION_ID,
                    label="Standard",
                    positions=(position,),
                ),
            ),
        )
        offer = Offer(
            offer_id=_OFFER_ID,
            source_inquiry_id=_INQUIRY_ID,
            created_at=_NOW,
            versions=(version,),
        )
        offer_repo.save(offer)

        write_service = CatalogDishWriteService(catalog_repo)
        write_service.update_dish(
            _DISH_ID,
            update=CatalogDishUpdatePayload(
                name="Schnitzel",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=900,
                allergens=("A",),
                active=True,
                effective_from=date(2026, 8, 1),
            ),
            expected_updated_at=_NOW,
            now=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
        )

        stored = offer_repo.get(_OFFER_ID)
        assert stored is not None
        stored_position = stored.versions[0].variants[0].positions[0]
        assert stored_position.unit_net_cents == 850
        assert stored_position.net_total_cents == 8500

        updated_dish = catalog_repo.get_dish(_DISH_ID)
        assert updated_dish is not None
        assert updated_dish.current_unit_net_cents == 900
        assert len(catalog_repo.list_price_history(_DISH_ID)) == 1
    finally:
        catalog_repo.close()

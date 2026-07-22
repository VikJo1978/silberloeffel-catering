"""Test-only commercial snapshot seeding for Orders created outside Offer convert."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from catering_system.domain.order_commercial_snapshot import (
    OrderCommercialPosition,
    OrderCommercialSnapshot,
)
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)


def seed_commercial_snapshot(
    snapshot_repository: OrderCommercialSnapshotRepository,
    order_id: str,
    *,
    created_at: datetime | None = None,
    position_name: str = "Seeded Menü",
) -> OrderCommercialSnapshot:
    """Persist a minimal valid snapshot so print/confirmation can resolve."""
    now = created_at or datetime.now(UTC)
    snapshot = OrderCommercialSnapshot(
        snapshot_id=str(uuid.uuid4()),
        order_id=order_id,
        source_offer_id=str(uuid.uuid4()),
        source_offer_version_id=str(uuid.uuid4()),
        source_variant_id=str(uuid.uuid4()),
        acceptance_id=str(uuid.uuid4()),
        accepted_at=now,
        recorded_by="test-seed",
        variant_label="Standard",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Rechnung laut Vereinbarung.",
        created_at=now,
        positions=(
            OrderCommercialPosition(
                position_id=str(uuid.uuid4()),
                kind="catalog",
                name=position_name,
                unit_net_cents=1000,
                net_total_cents=1000,
                vat_rate_percent=7,
                vat_amount_cents=70,
                gross_total_cents=1070,
                description="Seeded description",
                quantity=None,
                quantity_mode=None,
                unit_label=None,
            ),
        ),
    )
    snapshot_repository.create(snapshot)
    return snapshot

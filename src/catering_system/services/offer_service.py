"""Core offer service — first OfferVersion preparation from OfferSnapshot V1."""

from __future__ import annotations

import logging
import uuid

from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
)
from catering_system.domain.offer_snapshot import (
    OfferSnapshotPosition,
    OfferSnapshotV1,
    OfferSnapshotVariant,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.offer_snapshot_validation import validate_offer_snapshot

_log = logging.getLogger(__name__)


class OfferService:
    """Core-owned Offer lifecycle: first OfferVersion preparation only."""

    def __init__(
        self,
        offer_repository: OfferRepository,
        inquiry_repository: InquiryRepository,
        order_repository: OrderRepository,
    ) -> None:
        self._offer_repository = offer_repository
        self._inquiry_repository = inquiry_repository
        self._order_repository = order_repository

    def prepare_offer_version(
        self,
        inquiry_id: str,
        snapshot: dict[str, object] | OfferSnapshotV1,
    ) -> Offer:
        """Validate a snapshot and persist Offer + OfferVersion 1 for one Inquiry."""
        validated = (
            snapshot
            if isinstance(snapshot, OfferSnapshotV1)
            else validate_offer_snapshot(snapshot)
        )
        if validated.inquiry_id != inquiry_id:
            raise ValueError(
                "snapshot inquiry_id mismatch "
                f"(expected {inquiry_id!r}, got {validated.inquiry_id!r})"
            )

        inquiry = self._inquiry_repository.get_by_id(inquiry_id)
        if inquiry is None:
            raise KeyError(inquiry_id)

        if self._has_active_order(inquiry_id):
            raise ValueError(
                f"active order blocks offer preparation (inquiry_id={inquiry_id!r})"
            )

        if self._offer_repository.get_by_source_inquiry_id(inquiry_id) is not None:
            raise ValueError(
                f"offer already exists for inquiry (inquiry_id={inquiry_id!r})"
            )

        offer = _build_offer_from_snapshot(validated)
        self._offer_repository.save(offer)
        _log.info(
            "prepare_offer_version inquiry_id=%s offer_id=%s version=%s snapshot_id=%s",
            inquiry_id,
            offer.offer_id,
            offer.versions[0].version_number,
            offer.versions[0].snapshot_id,
        )
        return offer

    def _has_active_order(self, inquiry_id: str) -> bool:
        return any(
            order.source_inquiry_id == inquiry_id and order.cancelled_at is None
            for order in self._order_repository.list_orders()
        )


def _build_offer_from_snapshot(snapshot: OfferSnapshotV1) -> Offer:
    offer_id = str(uuid.uuid4())
    offer_version_id = str(uuid.uuid4())
    created_at = snapshot.snapshot_created_at
    version = OfferVersion(
        offer_version_id=offer_version_id,
        offer_id=offer_id,
        version_number=1,
        created_at=created_at,
        valid_until=snapshot.valid_until,
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.snapshot_hash,
        variants=tuple(
            _map_variant(variant, offer_version_id) for variant in snapshot.variants
        ),
    )
    return Offer(
        offer_id=offer_id,
        source_inquiry_id=snapshot.inquiry_id,
        created_at=created_at,
        versions=(version,),
    )


def _map_variant(
    variant: OfferSnapshotVariant, offer_version_id: str
) -> OfferVariant:
    return OfferVariant(
        variant_id=variant.variant_id,
        offer_version_id=offer_version_id,
        label=variant.label,
        positions=tuple(_map_position(position) for position in variant.positions),
    )


def _map_position(position: OfferSnapshotPosition) -> OfferPosition:
    return OfferPosition(
        position_id=position.position_id,
        kind=position.kind,
        name=position.name,
        unit_net_cents=position.unit_net_cents,
        net_total_cents=position.net_total_cents,
        vat_rate_percent=position.vat_rate_percent,
        vat_amount_cents=position.vat_amount_cents,
        gross_total_cents=position.gross_total_cents,
        related_position_id=position.related_position_id,
    )

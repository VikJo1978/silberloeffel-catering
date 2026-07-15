"""Core offer service — OfferVersion preparation and commercial evidence recording."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime

from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    SentChannel,
    SentEvidence,
    derive_offer_state,
    offer_allows_sent_recording,
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
    """Core-owned Offer lifecycle: preparation and commercial evidence recording."""

    def __init__(
        self,
        offer_repository: OfferRepository,
        inquiry_repository: InquiryRepository,
        order_repository: OrderRepository,
        *,
        now: Callable[[], datetime] | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._offer_repository = offer_repository
        self._inquiry_repository = inquiry_repository
        self._order_repository = order_repository
        self._now = now or (lambda: datetime.now(UTC))
        self._today = today or date.today

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

    def record_sent_evidence(
        self,
        offer_id: str,
        offer_version_id: str,
        *,
        sent_at: datetime,
        channel: SentChannel,
        recipient_reference: str,
        evidence_reference: str,
        recorded_by: str,
    ) -> Offer:
        """Append SentEvidence for one Prepared OfferVersion."""
        offer = self._offer_repository.get(offer_id)
        if offer is None:
            raise KeyError(offer_id)

        if not any(version.offer_version_id == offer_version_id for version in offer.versions):
            raise ValueError(
                f"offer_version_id {offer_version_id!r} is not a version of "
                f"offer {offer_id!r}"
            )

        if offer.acceptance_evidence is not None or offer.conversion_link is not None:
            raise ValueError("acceptance blocks sent recording")

        if any(item.offer_version_id == offer_version_id for item in offer.sent_evidence):
            raise ValueError(
                f"sent evidence already exists for offer_version_id={offer_version_id!r}"
            )

        if not offer_allows_sent_recording(
            offer, offer_version_id, today=self._today()
        ):
            raise ValueError(
                f"sent recording blocked (offer_id={offer_id!r}, "
                f"offer_version_id={offer_version_id!r}, "
                f"state={derive_offer_state(offer, offer_version_id, today=self._today())!r})"
            )

        recorded_at = self._now()
        evidence = SentEvidence(
            offer_id=offer_id,
            offer_version_id=offer_version_id,
            sent_at=sent_at,
            recorded_at=recorded_at,
            channel=channel,
            recipient_reference=recipient_reference,
            evidence_reference=evidence_reference,
            recorded_by=recorded_by,
        )
        updated = self._offer_repository.append_sent_evidence(evidence)
        _log.info(
            "record_sent_evidence offer_id=%s offer_version_id=%s channel=%s",
            offer_id,
            offer_version_id,
            channel,
        )
        return updated

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

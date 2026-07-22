"""Core offer service — OfferVersion preparation and commercial evidence recording."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from catering_system.domain.catalog import validate_allergen_codes
from catering_system.domain.inquiry import inquiry_allows_order_conversion
from catering_system.domain.inquiry_contact_completeness import (
    inquiry_contact_complete,
)
from catering_system.domain.offer import (
    AcceptanceChannel,
    AcceptanceEvidence,
    ConversionLink,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    SentChannel,
    SentEvidence,
    derive_offer_state,
    offer_allows_acceptance,
    offer_allows_conversion,
    offer_allows_sent_recording,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.offer_snapshot import (
    OfferSnapshotPosition,
    OfferSnapshotV1,
    OfferSnapshotV2,
    OfferSnapshotVariant,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.order_service import OrderService
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
        self._order_service = OrderService(order_repository)
        self._now = now or (lambda: datetime.now(UTC))
        self._today = today or date.today

    def prepare_offer_version(
        self,
        inquiry_id: str,
        snapshot: dict[str, object] | OfferSnapshotV1 | OfferSnapshotV2,
    ) -> Offer:
        """Validate a snapshot and persist Offer + OfferVersion 1 for one Inquiry."""
        validated = (
            snapshot
            if isinstance(snapshot, (OfferSnapshotV1, OfferSnapshotV2))
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

        if not inquiry_contact_complete(inquiry):
            raise ValueError(
                f"inquiry contact information incomplete (inquiry_id={inquiry_id!r})"
            )

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

        if not any(
            version.offer_version_id == offer_version_id for version in offer.versions
        ):
            raise ValueError(
                f"offer_version_id {offer_version_id!r} is not a version of "
                f"offer {offer_id!r}"
            )

        if offer.acceptance_evidence is not None or offer.conversion_link is not None:
            raise ValueError("acceptance blocks sent recording")

        self._require_contact_complete_inquiry(offer.source_inquiry_id)

        if any(
            item.offer_version_id == offer_version_id for item in offer.sent_evidence
        ):
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

    def record_acceptance_evidence(
        self,
        offer_id: str,
        offer_version_id: str,
        accepted_variant_id: str,
        *,
        accepted_at: datetime,
        channel: AcceptanceChannel,
        evidence_reference: str,
        recorded_by: str,
        note: str | None = None,
    ) -> Offer:
        """Append AcceptanceEvidence for one eligible sent OfferVersion/variant."""
        offer = self._offer_repository.get(offer_id)
        if offer is None:
            raise KeyError(offer_id)

        if not any(
            version.offer_version_id == offer_version_id for version in offer.versions
        ):
            raise ValueError(
                f"offer_version_id {offer_version_id!r} is not a version of "
                f"offer {offer_id!r}"
            )

        if offer.acceptance_evidence is not None:
            raise ValueError(f"acceptance already exists for offer_id={offer_id!r}")

        if offer.conversion_link is not None:
            raise ValueError("conversion link blocks acceptance recording")

        self._require_contact_complete_inquiry(offer.source_inquiry_id)

        version = next(
            item for item in offer.versions if item.offer_version_id == offer_version_id
        )
        if not any(
            variant.variant_id == accepted_variant_id for variant in version.variants
        ):
            raise ValueError("accepted variant does not belong to OfferVersion")

        if not offer_allows_acceptance(
            offer,
            offer_version_id,
            accepted_variant_id,
            today=self._today(),
        ):
            raise ValueError(
                f"acceptance blocked (offer_id={offer_id!r}, "
                f"offer_version_id={offer_version_id!r}, "
                f"accepted_variant_id={accepted_variant_id!r}, "
                f"state={derive_offer_state(offer, offer_version_id, today=self._today())!r})"
            )

        acceptance_id = str(uuid.uuid4())
        recorded_at = self._now()
        evidence = AcceptanceEvidence(
            acceptance_id=acceptance_id,
            offer_id=offer_id,
            accepted_offer_version_id=offer_version_id,
            accepted_variant_id=accepted_variant_id,
            accepted_at=accepted_at,
            recorded_at=recorded_at,
            channel=channel,
            evidence_reference=evidence_reference,
            recorded_by=recorded_by,
            note=note,
        )
        updated = self._offer_repository.append_acceptance_evidence(evidence)
        _log.info(
            "record_acceptance_evidence offer_id=%s offer_version_id=%s variant_id=%s",
            offer_id,
            offer_version_id,
            accepted_variant_id,
        )
        return updated

    def convert_accepted_offer(
        self,
        offer_id: str,
        offer_version_id: str,
        accepted_variant_id: str,
        acceptance_id: str,
    ) -> tuple[Offer, Order, OrderVersion]:
        """Convert an accepted OfferVersion into an Order and link the facts."""
        offer = self._offer_repository.get(offer_id)
        if offer is None:
            raise KeyError(offer_id)

        if not any(
            version.offer_version_id == offer_version_id for version in offer.versions
        ):
            raise ValueError(
                f"offer_version_id {offer_version_id!r} is not a version of "
                f"offer {offer_id!r}"
            )

        version = next(
            item for item in offer.versions if item.offer_version_id == offer_version_id
        )
        if not any(
            variant.variant_id == accepted_variant_id for variant in version.variants
        ):
            raise ValueError("accepted variant does not belong to OfferVersion")

        if not offer_allows_conversion(
            offer,
            offer_version_id,
            accepted_variant_id,
            acceptance_id,
        ):
            raise ValueError(
                f"conversion blocked (offer_id={offer_id!r}, "
                f"offer_version_id={offer_version_id!r}, "
                f"accepted_variant_id={accepted_variant_id!r}, "
                f"acceptance_id={acceptance_id!r}, "
                f"state={derive_offer_state(offer, offer_version_id, today=self._today())!r})"
            )

        inquiry = self._inquiry_repository.get_by_id(offer.source_inquiry_id)
        if inquiry is None:
            raise KeyError(offer.source_inquiry_id)
        if not inquiry_allows_order_conversion(inquiry):
            raise ValueError(
                "inquiry conversion blocked "
                f"(inquiry_id={inquiry.inquiry_id!r}, "
                f"crm_stage={inquiry.crm_stage!r}, "
                f"call_verification_required={inquiry.call_verification_required!r}, "
                f"call_verification_status={inquiry.call_verification_status!r})"
            )

        link = offer.conversion_link
        if link is not None:
            order = self._order_repository.get_order(link.order_id)
            if order is None:
                raise ValueError(
                    f"conversion link references missing order_id={link.order_id!r}"
                )
            versions = self._order_repository.list_order_versions(link.order_id)
            order_version = next(
                (item for item in versions if item.version_number == 1), None
            )
            if order_version is None:
                raise ValueError(
                    f"conversion link order_id={link.order_id!r} has no version 1"
                )
            return offer, order, order_version

        if self._has_linked_order(offer.source_inquiry_id):
            raise ValueError(
                f"active order blocks conversion (inquiry_id={offer.source_inquiry_id!r})"
            )

        # Contact-completeness gate for NEW conversions only — placed after the
        # conversion-link replay return above so an existing conversion is
        # never blocked retroactively (INQUIRY_CONTACT_COMPLETENESS_V1 §8).
        if not inquiry_contact_complete(inquiry):
            raise ValueError(
                "inquiry contact information incomplete "
                f"(inquiry_id={inquiry.inquiry_id!r})"
            )

        order, order_version = self._order_service.create_order_from_offer_version(
            offer.source_inquiry_id,
            version,
        )
        conversion_link = ConversionLink(
            offer_id=offer_id,
            offer_version_id=offer_version_id,
            variant_id=accepted_variant_id,
            acceptance_id=acceptance_id,
            order_id=order.order_id,
            created_at=self._now(),
        )
        updated = self._offer_repository.append_conversion_link(conversion_link)
        _log.info(
            "convert_accepted_offer offer_id=%s offer_version_id=%s order_id=%s",
            offer_id,
            offer_version_id,
            order.order_id,
        )
        return updated, order, order_version

    def _require_contact_complete_inquiry(self, inquiry_id: str) -> None:
        """One canonical contact gate for commercial progression. A missing
        inquiry row is not this gate's concern (prepare_offer_version already
        requires it); only an existing incomplete inquiry blocks."""
        inquiry = self._inquiry_repository.get_by_id(inquiry_id)
        if inquiry is not None and not inquiry_contact_complete(inquiry):
            raise ValueError(
                f"inquiry contact information incomplete (inquiry_id={inquiry_id!r})"
            )

    def _has_active_order(self, inquiry_id: str) -> bool:
        return any(
            order.source_inquiry_id == inquiry_id and order.cancelled_at is None
            for order in self._order_repository.list_orders()
        )

    def _has_linked_order(self, inquiry_id: str) -> bool:
        return any(
            order.source_inquiry_id == inquiry_id
            for order in self._order_repository.list_orders()
        )


def _build_offer_from_snapshot(snapshot: OfferSnapshotV1 | OfferSnapshotV2) -> Offer:
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
        event_date=snapshot.event.event_date,
        time_window_text=snapshot.event.time_window_text,
        location_text=snapshot.event.location_text,
        guest_count=snapshot.event.guest_count,
        planning_mode=snapshot.event.planning_mode,
        payment_method=snapshot.payment_terms.method,
        payment_customer_visible_text=snapshot.payment_terms.customer_visible_text,
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


def _map_variant(variant: OfferSnapshotVariant, offer_version_id: str) -> OfferVariant:
    return OfferVariant(
        variant_id=variant.variant_id,
        offer_version_id=offer_version_id,
        label=variant.label,
        description=variant.description,
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
        description=position.description,
        composition=position.composition,
        notes=position.notes,
        quantity=Decimal(position.quantity),
        quantity_mode=position.quantity_mode,
        unit_label=position.unit_label,
        catalog_item_id=position.catalog_item_id,
        allergens=(
            validate_allergen_codes(position.allergens)
            if position.allergens is not None
            else None
        ),
        vegan=position.vegan,
        vegetarian=position.vegetarian,
    )

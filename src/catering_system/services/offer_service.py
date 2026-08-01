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
from catering_system.domain.inquiry_timing import (
    TimingEvaluation,
    evaluate_timing,
    timing_acknowledgement_is_valid,
)
from catering_system.domain.inquiry_offer_preparation import (
    InquiryOfferPreparationBlocker,
    REASON_ACTIVE_ORDER_EXISTS,
    REASON_OFFER_ALREADY_EXISTS,
    evaluate_inquiry_offer_preparation,
)
from catering_system.domain.offer import (
    AcceptanceChannel,
    AcceptanceEvidence,
    ConversionLink,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    RejectionEvidence,
    SentChannel,
    SentEvidence,
    WithdrawalEvidence,
    derive_offer_state,
    offer_allows_acceptance,
    offer_allows_conversion,
    offer_allows_prepare_next_version,
    offer_allows_rejection,
    offer_allows_sent_recording,
    offer_allows_withdrawal,
    offer_has_newer_open_version,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.offer_snapshot import (
    OfferSnapshotPosition,
    OfferSnapshotV1,
    OfferSnapshotV2,
    OfferSnapshotVariant,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.order_service import OrderService
from catering_system.services.offer_snapshot_validation import validate_offer_snapshot
from catering_system.domain.order_commercial_snapshot import (
    build_order_commercial_snapshot,
)

_log = logging.getLogger(__name__)


class OfferPreparationBlockedError(ValueError):
    """First-Offer creation rejected by the shared Inquiry eligibility gate."""

    def __init__(
        self,
        inquiry_id: str,
        reasons: tuple[InquiryOfferPreparationBlocker, ...],
    ) -> None:
        self.inquiry_id = inquiry_id
        self.reasons = reasons
        if "inquiry_rejected" in reasons:
            message = "inquiry rejected blocks offer preparation"
        elif "inquiry_call_verification_unsatisfied" in reasons:
            message = "inquiry call verification unsatisfied"
        elif any(reason.startswith("inquiry_contact_missing_") for reason in reasons):
            message = "inquiry contact information incomplete"
        elif REASON_ACTIVE_ORDER_EXISTS in reasons:
            message = "active order blocks offer preparation"
        elif REASON_OFFER_ALREADY_EXISTS in reasons:
            message = "offer already exists for inquiry"
        else:
            message = "offer preparation blocked"
        super().__init__(f"{message} (inquiry_id={inquiry_id!r})")


class OfferTimingReviewRequiredError(ValueError):
    def __init__(
        self,
        *,
        inquiry_id: str,
        findings: tuple[str, ...],
        invalid_window: bool,
    ) -> None:
        self.inquiry_id = inquiry_id
        self.findings = findings
        self.invalid_window = invalid_window
        message = (
            "delivery window invalid"
            if invalid_window
            else "time review acknowledgement required"
        )
        super().__init__(f"{message} (inquiry_id={inquiry_id!r})")


class OfferService:
    """Core-owned Offer lifecycle: preparation and commercial evidence recording."""

    def __init__(
        self,
        offer_repository: OfferRepository,
        inquiry_repository: InquiryRepository,
        order_repository: OrderRepository,
        commercial_snapshot_repository: OrderCommercialSnapshotRepository | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._offer_repository = offer_repository
        self._inquiry_repository = inquiry_repository
        self._order_repository = order_repository
        self._commercial_snapshots = (
            commercial_snapshot_repository
            or InMemoryOrderCommercialSnapshotRepository()
        )
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

        eligibility = evaluate_inquiry_offer_preparation(
            inquiry,
            has_active_order=self._has_active_order(inquiry_id),
            has_existing_offer=(
                self._offer_repository.get_by_source_inquiry_id(inquiry_id) is not None
            ),
        )
        if eligibility.blocked:
            raise OfferPreparationBlockedError(
                inquiry_id,
                eligibility.reasons,
            )

        resolved_event = _resolved_event_timing(validated, inquiry)
        _require_offer_timing_ready(inquiry_id, resolved_event)
        offer = _build_offer_from_snapshot(validated, resolved_event=resolved_event)
        self._offer_repository.save(offer)
        _log.info(
            "prepare_offer_version inquiry_id=%s offer_id=%s version=%s snapshot_id=%s",
            inquiry_id,
            offer.offer_id,
            offer.versions[0].version_number,
            offer.versions[0].snapshot_id,
        )
        return offer

    def prepare_next_offer_version(
        self,
        offer_id: str,
        snapshot: dict[str, object] | OfferSnapshotV1 | OfferSnapshotV2,
        *,
        expected_latest_version_number: int,
    ) -> Offer:
        """Append OfferVersion N+1 for an existing Offer (revision path)."""
        validated = (
            snapshot
            if isinstance(snapshot, (OfferSnapshotV1, OfferSnapshotV2))
            else validate_offer_snapshot(snapshot)
        )
        offer = self._offer_repository.get(offer_id)
        if offer is None:
            raise KeyError(offer_id)

        if validated.inquiry_id != offer.source_inquiry_id:
            raise ValueError(
                "snapshot inquiry_id mismatch "
                f"(expected {offer.source_inquiry_id!r}, got {validated.inquiry_id!r})"
            )

        inquiry = self._inquiry_repository.get_by_id(offer.source_inquiry_id)
        if inquiry is None:
            raise KeyError(offer.source_inquiry_id)

        if not inquiry_contact_complete(inquiry):
            raise ValueError(
                "inquiry contact information incomplete "
                f"(inquiry_id={offer.source_inquiry_id!r})"
            )

        if self._has_active_order(offer.source_inquiry_id):
            raise ValueError(
                "active order blocks offer preparation "
                f"(inquiry_id={offer.source_inquiry_id!r})"
            )

        latest = max(item.version_number for item in offer.versions)
        if expected_latest_version_number != latest:
            raise ValueError(
                f"version conflict (expected latest_version_number="
                f"{expected_latest_version_number!r}, actual={latest!r})"
            )

        if not offer_allows_prepare_next_version(offer, today=self._today()):
            raise ValueError(
                f"prepare next version blocked (offer_id={offer_id!r}, "
                f"latest_state="
                f"{derive_offer_state(offer, max(offer.versions, key=lambda v: v.version_number).offer_version_id, today=self._today())!r})"
            )

        resolved_event = _resolved_event_timing(validated, inquiry)
        _require_offer_timing_ready(inquiry.inquiry_id, resolved_event)
        next_version = _build_next_version_from_snapshot(
            offer,
            validated,
            version_number=latest + 1,
            resolved_event=resolved_event,
        )
        updated = self._offer_repository.append_offer_version(offer_id, next_version)
        _log.info(
            "prepare_next_offer_version offer_id=%s version=%s snapshot_id=%s",
            offer_id,
            next_version.version_number,
            next_version.snapshot_id,
        )
        return updated

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

        today = self._today()
        if derive_offer_state(
            offer, offer_version_id, today=today
        ) == "Sent" and offer_has_newer_open_version(
            offer, offer_version_id, today=today
        ):
            raise ValueError(
                "acceptance_blocked_newer_version_exists "
                f"(offer_id={offer_id!r}, offer_version_id={offer_version_id!r})"
            )

        if not offer_allows_acceptance(
            offer,
            offer_version_id,
            accepted_variant_id,
            today=today,
        ):
            raise ValueError(
                f"acceptance blocked (offer_id={offer_id!r}, "
                f"offer_version_id={offer_version_id!r}, "
                f"accepted_variant_id={accepted_variant_id!r}, "
                f"state={derive_offer_state(offer, offer_version_id, today=today)!r})"
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

    def record_rejection_evidence(
        self,
        offer_id: str,
        offer_version_id: str,
        *,
        rejected_at: datetime,
        recorded_by: str,
        evidence_reference: str | None = None,
    ) -> Offer:
        """Append RejectionEvidence for one eligible sent OfferVersion."""
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
            raise ValueError("acceptance blocks rejection recording")

        self._require_contact_complete_inquiry(offer.source_inquiry_id)

        if any(
            item.offer_version_id == offer_version_id
            for item in offer.rejection_evidence
        ):
            raise ValueError(
                f"rejection evidence already exists for offer_version_id={offer_version_id!r}"
            )

        if not offer_allows_rejection(offer, offer_version_id, today=self._today()):
            raise ValueError(
                f"rejection blocked (offer_id={offer_id!r}, "
                f"offer_version_id={offer_version_id!r}, "
                f"state={derive_offer_state(offer, offer_version_id, today=self._today())!r})"
            )

        recorded_at = self._now()
        evidence = RejectionEvidence(
            offer_id=offer_id,
            offer_version_id=offer_version_id,
            rejected_at=rejected_at,
            recorded_at=recorded_at,
            recorded_by=recorded_by,
            evidence_reference=evidence_reference,
        )
        updated = self._offer_repository.append_rejection_evidence(evidence)
        _log.info(
            "record_rejection_evidence offer_id=%s offer_version_id=%s",
            offer_id,
            offer_version_id,
        )
        return updated

    def record_withdrawal_evidence(
        self,
        offer_id: str,
        offer_version_id: str,
        *,
        recorded_by: str,
        reason: str | None = None,
    ) -> Offer:
        """Append WithdrawalEvidence for one eligible Prepared or Sent version."""
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
            raise ValueError("acceptance blocks withdrawal recording")

        self._require_contact_complete_inquiry(offer.source_inquiry_id)

        if any(
            item.offer_version_id == offer_version_id
            for item in offer.withdrawal_evidence
        ):
            raise ValueError(
                f"withdrawal evidence already exists for offer_version_id={offer_version_id!r}"
            )

        if not offer_allows_withdrawal(offer, offer_version_id, today=self._today()):
            raise ValueError(
                f"withdrawal blocked (offer_id={offer_id!r}, "
                f"offer_version_id={offer_version_id!r}, "
                f"state={derive_offer_state(offer, offer_version_id, today=self._today())!r})"
            )

        evidence = WithdrawalEvidence(
            offer_id=offer_id,
            offer_version_id=offer_version_id,
            withdrawn_at=self._now(),
            recorded_by=recorded_by,
            reason=reason,
        )
        updated = self._offer_repository.append_withdrawal_evidence(evidence)
        _log.info(
            "record_withdrawal_evidence offer_id=%s offer_version_id=%s",
            offer_id,
            offer_version_id,
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
        acceptance = offer.acceptance_evidence
        if acceptance is None or acceptance.acceptance_id != acceptance_id:
            raise ValueError(
                f"acceptance_id {acceptance_id!r} does not match offer acceptance"
            )
        variant = next(
            item for item in version.variants if item.variant_id == accepted_variant_id
        )
        created_at = self._now()
        snapshot = build_order_commercial_snapshot(
            order_id=order.order_id,
            offer=offer,
            offer_version=version,
            variant=variant,
            acceptance=acceptance,
            created_at=created_at,
        )
        self._commercial_snapshots.create(snapshot)
        conversion_link = ConversionLink(
            offer_id=offer_id,
            offer_version_id=offer_version_id,
            variant_id=accepted_variant_id,
            acceptance_id=acceptance_id,
            order_id=order.order_id,
            created_at=created_at,
        )
        updated = self._offer_repository.append_conversion_link(conversion_link)
        _log.info(
            "convert_accepted_offer offer_id=%s offer_version_id=%s order_id=%s "
            "commercial_snapshot_id=%s",
            offer_id,
            offer_version_id,
            order.order_id,
            snapshot.snapshot_id,
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


def _build_offer_from_snapshot(
    snapshot: OfferSnapshotV1 | OfferSnapshotV2,
    *,
    resolved_event: ResolvedSnapshotEvent,
) -> Offer:
    offer_id = str(uuid.uuid4())
    version = _build_version_from_snapshot(
        snapshot,
        offer_id=offer_id,
        version_number=1,
        resolved_event=resolved_event,
    )
    return Offer(
        offer_id=offer_id,
        source_inquiry_id=snapshot.inquiry_id,
        created_at=snapshot.snapshot_created_at,
        versions=(version,),
    )


def _build_next_version_from_snapshot(
    offer: Offer,
    snapshot: OfferSnapshotV1 | OfferSnapshotV2,
    *,
    version_number: int,
    resolved_event: ResolvedSnapshotEvent,
) -> OfferVersion:
    return _build_version_from_snapshot(
        snapshot,
        offer_id=offer.offer_id,
        version_number=version_number,
        resolved_event=resolved_event,
    )


def _build_version_from_snapshot(
    snapshot: OfferSnapshotV1 | OfferSnapshotV2,
    *,
    offer_id: str,
    version_number: int,
    resolved_event: ResolvedSnapshotEvent,
) -> OfferVersion:
    offer_version_id = str(uuid.uuid4())
    return OfferVersion(
        offer_version_id=offer_version_id,
        offer_id=offer_id,
        version_number=version_number,
        created_at=snapshot.snapshot_created_at,
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
        delivery_date_local=resolved_event.delivery_date_local,
        delivery_window_start_local=resolved_event.delivery_window_start_local,
        delivery_window_end_local=resolved_event.delivery_window_end_local,
        event_start_local=resolved_event.event_start_local,
        legacy_time_window_text=resolved_event.legacy_time_window_text,
        time_review_acknowledged_at=resolved_event.time_review_acknowledged_at,
        time_review_acknowledged_by=resolved_event.time_review_acknowledged_by,
        variants=tuple(
            _map_variant(variant, offer_version_id) for variant in snapshot.variants
        ),
        customer_title=_normalize_narrative(snapshot.customer_text.title),
        customer_introduction=_normalize_narrative(snapshot.customer_text.introduction),
        customer_notes=_normalize_narrative(snapshot.customer_text.notes),
        budget_definition=snapshot.budget_definition,
        charges_definition=snapshot.charges_definition,
    )


def _normalize_narrative(value: str | None) -> str | None:
    """OFFER_DOCUMENT_SNAPSHOT_V1 narrative rule.

    None stays None; blank/whitespace-only becomes None (never stored as an
    empty string); non-blank keeps its inner text and line breaks with only
    the outer whitespace trimmed. ``introduction``/``notes`` arrive unstripped
    and may legitimately be empty (_require_long_text), so this is the single
    place that decides absence.
    """
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class ResolvedSnapshotEvent:
    def __init__(
        self,
        *,
        delivery_date_local: str | None,
        delivery_window_start_local: str | None,
        delivery_window_end_local: str | None,
        event_start_local: str | None,
        legacy_time_window_text: str | None,
        time_review_acknowledged_at: datetime | None,
        time_review_acknowledged_by: str | None,
        evaluation: TimingEvaluation,
    ) -> None:
        self.delivery_date_local = delivery_date_local
        self.delivery_window_start_local = delivery_window_start_local
        self.delivery_window_end_local = delivery_window_end_local
        self.event_start_local = event_start_local
        self.legacy_time_window_text = legacy_time_window_text
        self.time_review_acknowledged_at = time_review_acknowledged_at
        self.time_review_acknowledged_by = time_review_acknowledged_by
        self.evaluation = evaluation


def _resolved_event_timing(
    snapshot: OfferSnapshotV1 | OfferSnapshotV2,
    inquiry,
) -> ResolvedSnapshotEvent:
    delivery_date_local = snapshot.event.delivery_date_local
    delivery_window_start_local = snapshot.event.delivery_window_start_local
    delivery_window_end_local = snapshot.event.delivery_window_end_local
    event_start_local = snapshot.event.event_start_local
    legacy_time_window_text = snapshot.event.legacy_time_window_text
    acknowledged_at = snapshot.event.time_review_acknowledged_at
    acknowledged_by = snapshot.event.time_review_acknowledged_by
    if (
        delivery_date_local is None
        and delivery_window_start_local is None
        and delivery_window_end_local is None
        and event_start_local is None
        and legacy_time_window_text is None
        and acknowledged_at is None
        and acknowledged_by is None
    ):
        delivery_date_local = inquiry.delivery_date_local
        delivery_window_start_local = inquiry.delivery_window_start_local
        delivery_window_end_local = inquiry.delivery_window_end_local
        event_start_local = inquiry.event_start_local
        legacy_time_window_text = inquiry.legacy_time_window_text
        acknowledged_at = inquiry.time_review_acknowledged_at
        acknowledged_by = inquiry.time_review_acknowledged_by
    evaluation = evaluate_timing(
        event_date=snapshot.event.event_date,
        delivery_date_local=delivery_date_local,
        delivery_window_start_local=delivery_window_start_local,
        delivery_window_end_local=delivery_window_end_local,
        event_start_local=event_start_local,
        legacy_time_window_text=legacy_time_window_text,
    )
    return ResolvedSnapshotEvent(
        delivery_date_local=delivery_date_local,
        delivery_window_start_local=delivery_window_start_local,
        delivery_window_end_local=delivery_window_end_local,
        event_start_local=event_start_local,
        legacy_time_window_text=legacy_time_window_text,
        time_review_acknowledged_at=acknowledged_at,
        time_review_acknowledged_by=acknowledged_by,
        evaluation=evaluation,
    )


def _require_offer_timing_ready(
    inquiry_id: str, resolved_event: ResolvedSnapshotEvent
) -> None:
    if resolved_event.evaluation.has_invalid_window:
        raise OfferTimingReviewRequiredError(
            inquiry_id=inquiry_id,
            findings=resolved_event.evaluation.findings,
            invalid_window=True,
        )
    if not timing_acknowledgement_is_valid(
        resolved_event.evaluation,
        acknowledged_at=resolved_event.time_review_acknowledged_at,
        acknowledged_by=resolved_event.time_review_acknowledged_by,
    ):
        raise OfferTimingReviewRequiredError(
            inquiry_id=inquiry_id,
            findings=resolved_event.evaluation.findings,
            invalid_window=False,
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

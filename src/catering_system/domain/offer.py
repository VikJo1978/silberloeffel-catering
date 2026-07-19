"""Commercial Offer history — immutable facts, never operational Order truth."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from catering_system.domain.catalog import AllergenCode, validate_allergen_codes
from catering_system.domain.inquiry import PlanningMode, validate_planning_mode
from catering_system.domain.order_payment_reminder import (
    PaymentMethod,
    validate_payment_method,
)

_MAX_EVENT_TEXT_LEN = 500
_MAX_PAYMENT_VISIBLE_TEXT_LEN = 20_000

OfferState = Literal[
    "Prepared",
    "Sent",
    "Accepted",
    "Converted",
    "Rejected",
    "Withdrawn",
    "Superseded",
    "Expired",
]
PositionKind = Literal["catalog", "surcharge", "fee", "custom"]
PositionQuantityMode = Literal["total", "per_person"]
VatRatePercent = Literal[7, 19]
SentChannel = Literal["email", "postal", "in_person", "other"]
AcceptanceChannel = Literal["email", "phone", "signed_document", "in_person", "other"]
POSITION_KINDS: tuple[PositionKind, ...] = ("catalog", "surcharge", "fee", "custom")
POSITION_QUANTITY_MODES: tuple[PositionQuantityMode, ...] = ("total", "per_person")
VAT_RATES: tuple[VatRatePercent, ...] = (7, 19)
SENT_CHANNELS: tuple[SentChannel, ...] = ("email", "postal", "in_person", "other")
ACCEPTANCE_CHANNELS: tuple[AcceptanceChannel, ...] = (
    "email",
    "phone",
    "signed_document",
    "in_person",
    "other",
)

_BERLIN = ZoneInfo("Europe/Berlin")
_SNAPSHOT_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _require_non_negative_cents(value: int, field: str) -> None:
    if value < 0:
        raise ValueError(f"{field} must be non-negative")


def _require_bounded_text(value: str, field: str, *, max_len: int) -> None:
    _require_text(value, field)
    if len(value) > max_len:
        raise ValueError(f"{field} exceeds length limit")


def _optional_bounded_text(value: str | None, field: str, *, max_len: int) -> None:
    if value is None:
        return
    _require_bounded_text(value, field, max_len=max_len)


def _validate_optional_quantity(value: Decimal | None) -> None:
    if value is None:
        return
    if value < 0:
        raise ValueError("quantity must be non-negative")
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -3:
        raise ValueError("quantity exceeds fractional precision")


@dataclass(frozen=True)
class OfferPosition:
    """Frozen customer-visible line within one variant snapshot."""

    position_id: str
    kind: PositionKind
    name: str
    unit_net_cents: int
    net_total_cents: int
    vat_rate_percent: VatRatePercent
    vat_amount_cents: int
    gross_total_cents: int
    related_position_id: str | None = None
    description: str | None = None
    composition: str | None = None
    notes: str | None = None
    quantity: Decimal | None = None
    quantity_mode: PositionQuantityMode | None = None
    unit_label: str | None = None
    catalog_item_id: str | None = None
    allergens: tuple[AllergenCode, ...] | None = None
    vegan: bool | None = None
    vegetarian: bool | None = None

    def __post_init__(self) -> None:
        _require_text(self.position_id, "position_id")
        _require_text(self.name, "name")
        if self.kind not in POSITION_KINDS:
            raise ValueError("invalid position kind")
        if self.vat_rate_percent not in VAT_RATES:
            raise ValueError("vat_rate_percent must be 7 or 19")
        for field, value in (
            ("unit_net_cents", self.unit_net_cents),
            ("net_total_cents", self.net_total_cents),
            ("vat_amount_cents", self.vat_amount_cents),
            ("gross_total_cents", self.gross_total_cents),
        ):
            _require_non_negative_cents(value, field)
        _optional_bounded_text(self.description, "description", max_len=20_000)
        _optional_bounded_text(self.composition, "composition", max_len=20_000)
        _optional_bounded_text(self.notes, "notes", max_len=20_000)
        _optional_bounded_text(self.unit_label, "unit_label", max_len=500)
        _validate_optional_quantity(self.quantity)
        if (
            self.quantity_mode is not None
            and self.quantity_mode not in POSITION_QUANTITY_MODES
        ):
            raise ValueError("invalid quantity_mode")
        if self.kind == "surcharge":
            if self.related_position_id is None:
                raise ValueError("surcharge requires related_position_id")
        elif self.related_position_id is not None:
            raise ValueError("related_position_id is only valid for surcharges")
        if self.catalog_item_id is not None:
            _require_text(self.catalog_item_id, "catalog_item_id")
        if self.allergens is not None:
            object.__setattr__(
                self, "allergens", validate_allergen_codes(self.allergens)
            )


@dataclass(frozen=True)
class OfferVariant:
    """One immutable customer-selectable alternative inside an OfferVersion."""

    variant_id: str
    offer_version_id: str
    label: str
    positions: tuple[OfferPosition, ...]
    description: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.variant_id, "variant_id")
        _require_text(self.offer_version_id, "offer_version_id")
        _require_text(self.label, "label")
        _optional_bounded_text(self.description, "description", max_len=20_000)
        if not self.positions:
            raise ValueError("an OfferVariant requires at least one position")
        position_ids: set[str] = set()
        for position in self.positions:
            if position.position_id in position_ids:
                raise ValueError("position_id must be unique within an OfferVariant")
            position_ids.add(position.position_id)
        for position in self.positions:
            if position.kind == "surcharge":
                if position.related_position_id not in position_ids:
                    raise ValueError(
                        "surcharge must reference a position in the variant"
                    )


@dataclass(frozen=True)
class OfferVersion:
    """Prepared commercial snapshot identity and its embedded alternatives.

    ``snapshot_id`` and ``snapshot_hash`` anchor the immutable envelope.
    Event facts and payment terms are frozen commercial fields required for
    later Offer-to-Order conversion.
    """

    offer_version_id: str
    offer_id: str
    version_number: int
    created_at: datetime
    valid_until: date
    snapshot_id: str
    snapshot_hash: str
    event_date: date
    time_window_text: str
    location_text: str
    guest_count: int | None
    planning_mode: PlanningMode
    payment_method: PaymentMethod
    payment_customer_visible_text: str
    variants: tuple[OfferVariant, ...]

    def __post_init__(self) -> None:
        _require_text(self.offer_version_id, "offer_version_id")
        _require_text(self.offer_id, "offer_id")
        _require_text(self.snapshot_id, "snapshot_id")
        _require_aware(self.created_at, "created_at")
        if self.version_number < 1:
            raise ValueError("version_number must be at least 1")
        if not _SNAPSHOT_HASH.fullmatch(self.snapshot_hash):
            raise ValueError("snapshot_hash must be a lowercase sha256 digest")
        _require_bounded_text(
            self.time_window_text, "time_window_text", max_len=_MAX_EVENT_TEXT_LEN
        )
        _require_bounded_text(
            self.location_text, "location_text", max_len=_MAX_EVENT_TEXT_LEN
        )
        if self.guest_count is not None and self.guest_count < 1:
            raise ValueError("guest_count must be a positive integer")
        validate_planning_mode(self.planning_mode)
        validate_payment_method(self.payment_method)
        _require_bounded_text(
            self.payment_customer_visible_text,
            "payment_customer_visible_text",
            max_len=_MAX_PAYMENT_VISIBLE_TEXT_LEN,
        )
        if not self.variants:
            raise ValueError("an OfferVersion requires at least one variant")
        variant_ids: set[str] = set()
        for variant in self.variants:
            if variant.offer_version_id != self.offer_version_id:
                raise ValueError("variant belongs to a different OfferVersion")
            if variant.variant_id in variant_ids:
                raise ValueError("variant_id must be unique within an OfferVersion")
            variant_ids.add(variant.variant_id)


@dataclass(frozen=True)
class SentEvidence:
    """Append-only fact that one exact OfferVersion was presented."""

    offer_id: str
    offer_version_id: str
    sent_at: datetime
    recorded_at: datetime
    channel: SentChannel
    recipient_reference: str
    evidence_reference: str
    recorded_by: str

    def __post_init__(self) -> None:
        _require_text(self.offer_id, "offer_id")
        _require_text(self.offer_version_id, "offer_version_id")
        _require_aware(self.sent_at, "sent_at")
        _require_aware(self.recorded_at, "recorded_at")
        _require_text(self.recipient_reference, "recipient_reference")
        _require_text(self.evidence_reference, "evidence_reference")
        _require_text(self.recorded_by, "recorded_by")
        if self.channel not in SENT_CHANNELS:
            raise ValueError("invalid sent channel")
        if self.recorded_at < self.sent_at:
            raise ValueError("recorded_at cannot precede sent_at")


@dataclass(frozen=True)
class AcceptanceEvidence:
    """Append-only customer decision bound to one version and one variant."""

    acceptance_id: str
    offer_id: str
    accepted_offer_version_id: str
    accepted_variant_id: str
    accepted_at: datetime
    recorded_at: datetime
    channel: AcceptanceChannel
    evidence_reference: str
    recorded_by: str
    note: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.acceptance_id, "acceptance_id")
        _require_text(self.offer_id, "offer_id")
        _require_text(self.accepted_offer_version_id, "accepted_offer_version_id")
        _require_text(self.accepted_variant_id, "accepted_variant_id")
        _require_aware(self.accepted_at, "accepted_at")
        _require_aware(self.recorded_at, "recorded_at")
        _require_text(self.evidence_reference, "evidence_reference")
        _require_text(self.recorded_by, "recorded_by")
        if self.channel not in ACCEPTANCE_CHANNELS:
            raise ValueError("invalid acceptance channel")
        if self.recorded_at < self.accepted_at:
            raise ValueError("recorded_at cannot precede accepted_at")


@dataclass(frozen=True)
class RejectionEvidence:
    """Append-only customer rejection of one sent OfferVersion."""

    offer_id: str
    offer_version_id: str
    rejected_at: datetime
    recorded_at: datetime
    recorded_by: str
    evidence_reference: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.offer_id, "offer_id")
        _require_text(self.offer_version_id, "offer_version_id")
        _require_aware(self.rejected_at, "rejected_at")
        _require_aware(self.recorded_at, "recorded_at")
        _require_text(self.recorded_by, "recorded_by")
        if self.recorded_at < self.rejected_at:
            raise ValueError("recorded_at cannot precede rejected_at")


@dataclass(frozen=True)
class WithdrawalEvidence:
    """Append-only office withdrawal of a prepared or sent version."""

    offer_id: str
    offer_version_id: str
    withdrawn_at: datetime
    recorded_by: str
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.offer_id, "offer_id")
        _require_text(self.offer_version_id, "offer_version_id")
        _require_aware(self.withdrawn_at, "withdrawn_at")
        _require_text(self.recorded_by, "recorded_by")


OfferEvidence = SentEvidence | RejectionEvidence | WithdrawalEvidence


@dataclass(frozen=True)
class ConversionLink:
    """One-time reference from an accepted commercial decision to an Order."""

    offer_id: str
    offer_version_id: str
    variant_id: str
    acceptance_id: str
    order_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field, value in (
            ("offer_id", self.offer_id),
            ("offer_version_id", self.offer_version_id),
            ("variant_id", self.variant_id),
            ("acceptance_id", self.acceptance_id),
            ("order_id", self.order_id),
        ):
            _require_text(value, field)
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True)
class Offer:
    """Core-owned commercial aggregate reconstructed from immutable facts."""

    offer_id: str
    source_inquiry_id: str
    created_at: datetime
    versions: tuple[OfferVersion, ...]
    sent_evidence: tuple[SentEvidence, ...] = ()
    acceptance_evidence: AcceptanceEvidence | None = None
    rejection_evidence: tuple[RejectionEvidence, ...] = ()
    withdrawal_evidence: tuple[WithdrawalEvidence, ...] = ()
    conversion_link: ConversionLink | None = None

    def __post_init__(self) -> None:
        _require_text(self.offer_id, "offer_id")
        _require_text(self.source_inquiry_id, "source_inquiry_id")
        _require_aware(self.created_at, "created_at")
        if not self.versions:
            raise ValueError("an Offer requires a prepared OfferVersion")

        versions = {version.offer_version_id: version for version in self.versions}
        if len(versions) != len(self.versions):
            raise ValueError("offer_version_id must be unique within an Offer")
        for version in self.versions:
            if version.offer_id != self.offer_id:
                raise ValueError("OfferVersion belongs to a different Offer")
            if version.created_at < self.created_at:
                raise ValueError("OfferVersion cannot predate its Offer")
        numbers = sorted(version.version_number for version in self.versions)
        if numbers != list(range(1, len(self.versions) + 1)):
            raise ValueError("OfferVersion numbers must be contiguous from 1")
        if len({version.snapshot_id for version in self.versions}) != len(
            self.versions
        ):
            raise ValueError("snapshot_id must be unique within an Offer")

        sent = self._unique_evidence_versions(self.sent_evidence, "SentEvidence")
        rejected = self._unique_evidence_versions(
            self.rejection_evidence, "RejectionEvidence"
        )
        withdrawn = self._unique_evidence_versions(
            self.withdrawal_evidence, "WithdrawalEvidence"
        )
        evidence_items: tuple[OfferEvidence, ...] = (
            *self.sent_evidence,
            *self.rejection_evidence,
            *self.withdrawal_evidence,
        )
        for evidence in evidence_items:
            if evidence.offer_id != self.offer_id:
                raise ValueError("evidence belongs to a different Offer")
            if evidence.offer_version_id not in versions:
                raise ValueError("evidence references an unknown OfferVersion")
        if rejected & withdrawn:
            raise ValueError("a version cannot be both rejected and withdrawn")
        if not rejected <= sent:
            raise ValueError("only a sent OfferVersion can be rejected")
        sent_by_version = {
            evidence.offer_version_id: evidence for evidence in self.sent_evidence
        }
        for version_id, evidence in sent_by_version.items():
            if evidence.sent_at < versions[version_id].created_at:
                raise ValueError("SentEvidence cannot predate its OfferVersion")
        for evidence in self.rejection_evidence:
            if (
                evidence.rejected_at
                < sent_by_version[evidence.offer_version_id].sent_at
            ):
                raise ValueError("RejectionEvidence cannot predate SentEvidence")
        for evidence in self.withdrawal_evidence:
            version = versions[evidence.offer_version_id]
            earliest = sent_by_version.get(evidence.offer_version_id)
            boundary = earliest.sent_at if earliest is not None else version.created_at
            if evidence.withdrawn_at < boundary:
                raise ValueError("WithdrawalEvidence predates its lifecycle boundary")

        acceptance = self.acceptance_evidence
        if acceptance is not None:
            if acceptance.offer_id != self.offer_id:
                raise ValueError("acceptance belongs to a different Offer")
            accepted_version = versions.get(acceptance.accepted_offer_version_id)
            if accepted_version is None:
                raise ValueError("acceptance references an unknown OfferVersion")
            if acceptance.accepted_offer_version_id not in sent:
                raise ValueError("only a sent OfferVersion can be accepted")
            if (
                acceptance.accepted_at
                < sent_by_version[acceptance.accepted_offer_version_id].sent_at
            ):
                raise ValueError("AcceptanceEvidence cannot predate SentEvidence")
            if acceptance.accepted_offer_version_id in rejected | withdrawn:
                raise ValueError("a closed OfferVersion cannot be accepted")
            if not any(
                variant.variant_id == acceptance.accepted_variant_id
                for variant in accepted_version.variants
            ):
                raise ValueError("accepted variant does not belong to OfferVersion")
            later_sent = any(
                version.version_number > accepted_version.version_number
                and version.offer_version_id in sent
                for version in self.versions
            )
            if later_sent:
                raise ValueError("a superseded OfferVersion cannot be accepted")
            accepted_date = acceptance.accepted_at.astimezone(_BERLIN).date()
            if accepted_date > accepted_version.valid_until:
                raise ValueError("an expired OfferVersion cannot be accepted")
            if any(
                version.created_at > acceptance.accepted_at for version in self.versions
            ):
                raise ValueError("no OfferVersion may be prepared after acceptance")

        link = self.conversion_link
        if link is not None:
            if acceptance is None:
                raise ValueError("conversion requires AcceptanceEvidence")
            if link.offer_id != self.offer_id:
                raise ValueError("conversion belongs to a different Offer")
            if (
                link.offer_version_id != acceptance.accepted_offer_version_id
                or link.variant_id != acceptance.accepted_variant_id
                or link.acceptance_id != acceptance.acceptance_id
            ):
                raise ValueError("conversion does not match AcceptanceEvidence")
            if link.created_at < acceptance.recorded_at:
                raise ValueError("ConversionLink cannot predate AcceptanceEvidence")

    @staticmethod
    def _unique_evidence_versions(
        evidence: tuple[OfferEvidence, ...],
        name: str,
    ) -> set[str]:
        version_ids = [item.offer_version_id for item in evidence]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError(f"{name} must be unique per OfferVersion")
        return set(version_ids)


def _version(offer: Offer, offer_version_id: str) -> OfferVersion:
    for version in offer.versions:
        if version.offer_version_id == offer_version_id:
            return version
    raise ValueError("unknown OfferVersion")


def _evidence_version_ids(evidence: tuple[OfferEvidence, ...]) -> set[str]:
    return {item.offer_version_id for item in evidence}


def derive_offer_state(
    offer: Offer, offer_version_id: str, *, today: date
) -> OfferState:
    """Derive one version's commercial state from immutable facts only.

    Priority for sent versions: Converted/Accepted → Rejected/Withdrawn →
    Superseded → Expired → Sent. ``Expired`` wins over ``Sent`` when
    ``today`` is past ``valid_until`` and the version is still eligible.
    """
    version = _version(offer, offer_version_id)
    acceptance = offer.acceptance_evidence
    link = offer.conversion_link
    if link is not None and link.offer_version_id == offer_version_id:
        return "Converted"
    if (
        acceptance is not None
        and acceptance.accepted_offer_version_id == offer_version_id
    ):
        return "Accepted"

    rejected = _evidence_version_ids(offer.rejection_evidence)
    if offer_version_id in rejected:
        return "Rejected"
    withdrawn = _evidence_version_ids(offer.withdrawal_evidence)
    if offer_version_id in withdrawn:
        return "Withdrawn"

    sent = _evidence_version_ids(offer.sent_evidence)
    if offer_version_id in sent:
        if any(
            other.version_number > version.version_number
            and other.offer_version_id in sent
            for other in offer.versions
        ):
            return "Superseded"
        if today > version.valid_until:
            return "Expired"
        return "Sent"
    return "Prepared"


def offer_allows_acceptance(
    offer: Offer, offer_version_id: str, variant_id: str, *, today: date
) -> bool:
    """True only for one exact eligible sent version/variant."""
    if offer.acceptance_evidence is not None or offer.conversion_link is not None:
        return False
    try:
        version = _version(offer, offer_version_id)
    except ValueError:
        return False
    if not any(variant.variant_id == variant_id for variant in version.variants):
        return False
    return derive_offer_state(offer, offer_version_id, today=today) == "Sent"


def offer_allows_sent_recording(
    offer: Offer, offer_version_id: str, *, today: date
) -> bool:
    """True only when one exact OfferVersion may receive its first SentEvidence."""
    if offer.acceptance_evidence is not None or offer.conversion_link is not None:
        return False
    try:
        _version(offer, offer_version_id)
    except ValueError:
        return False
    if any(item.offer_version_id == offer_version_id for item in offer.sent_evidence):
        return False
    return derive_offer_state(offer, offer_version_id, today=today) == "Prepared"


def offer_allows_conversion(
    offer: Offer,
    offer_version_id: str,
    variant_id: str,
    acceptance_id: str,
) -> bool:
    """Recognize a creatable conversion or an exact idempotent replay."""
    acceptance = offer.acceptance_evidence
    if acceptance is None:
        return False
    if (
        acceptance.accepted_offer_version_id != offer_version_id
        or acceptance.accepted_variant_id != variant_id
        or acceptance.acceptance_id != acceptance_id
    ):
        return False
    link = offer.conversion_link
    if link is None:
        return True
    return (
        link.offer_version_id == offer_version_id
        and link.variant_id == variant_id
        and link.acceptance_id == acceptance_id
    )


def offer_blocks_direct_inquiry_conversion(offer: Offer, *, today: date) -> bool:
    """Legacy Inquiry→Order must refuse while negotiation is active or already accepted.

    Scans every OfferVersion on the aggregate. ``Superseded`` alone does not
    block; a newer ``Prepared`` or eligible ``Sent`` version on the same Offer
    still does.
    """
    if offer.acceptance_evidence is not None or offer.conversion_link is not None:
        return True
    return any(
        derive_offer_state(offer, version.offer_version_id, today=today)
        in ("Prepared", "Sent")
        for version in offer.versions
    )

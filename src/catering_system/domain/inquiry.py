"""Inquiry aggregate — A1 internal scaffold."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

if TYPE_CHECKING:
    from catering_system.domain.inquiry_customer_snapshot import (
        InquiryCustomerSnapshot,
    )
    from catering_system.domain.offer import Offer, OfferState

InquirySource = Literal[
    "wix_form",  # legacy/adapter-compatible; not office-offered, not new-default
    "phone",  # legacy/adapter-compatible; office dropdown uses phone_by_office instead
    "manual",
    "phone_by_office",
    "missed_call",
    "ai_telefonist",
    "website_form",
    "configurator",
    "email",
]

# Frozen CRM pipeline (ordered; single source of truth for crm_stage).
CrmStage = Literal[
    "Neue Anfrage",
    "In Prüfung",
    "Vorschlag vorbereiten",
    "Angebot in Bearbeitung",
    "Angebot gesendet / Rückmeldung offen",
    "Bestätigt / Auftrag",
    "Abgelehnt / verloren",
]
CRM_PIPELINE: tuple[CrmStage, ...] = (
    "Neue Anfrage",
    "In Prüfung",
    "Vorschlag vorbereiten",
    "Angebot in Bearbeitung",
    "Angebot gesendet / Rückmeldung offen",
    "Bestätigt / Auftrag",
    "Abgelehnt / verloren",
)
CRM_STAGE_SET: frozenset[str] = frozenset(CRM_PIPELINE)
ACTIVE_ORDER_CRM_STAGE: CrmStage = "Bestätigt / Auftrag"

PlanningMode = Literal["caterer_suggestion", "self_select"]
PLANNING_MODES: tuple[PlanningMode, ...] = ("caterer_suggestion", "self_select")
PLANNING_MODE_SET: frozenset[str] = frozenset(PLANNING_MODES)

CallVerificationStatus = Literal[
    "not_required",
    "pending",
    "verified",
    "failed",
    "blocked",
]
CALL_VERIFICATION_STATUSES: tuple[CallVerificationStatus, ...] = (
    "not_required",
    "pending",
    "verified",
    "failed",
    "blocked",
)
CALL_VERIFICATION_STATUS_SET: frozenset[str] = frozenset(CALL_VERIFICATION_STATUSES)

InquiryOfficeNextAction = Literal[
    "verify", "convert", "convert-accepted", "offer-pending"
]


@dataclass(frozen=True)
class InquiryOfferProjection:
    """Read-only commercial context for office UI; never persisted."""

    offer_id: str
    offer_version_id: str
    commercial_state: OfferState
    accepted_variant_id: str | None = None
    acceptance_id: str | None = None


@dataclass(frozen=True)
class InquiryOfficeState:
    """Pure office workflow projection; never persisted as another status axis."""

    is_open: bool
    next_action: InquiryOfficeNextAction | None
    offer: InquiryOfferProjection | None = None


class CustomerLinkage(TypedDict, total=False):
    customer_id: str
    contact_id: str
    placeholder: Literal[True]


ALLOWED_CUSTOMER_LINKAGE_KEYS: frozenset[str] = frozenset(
    {"customer_id", "contact_id", "placeholder"}
)


def validate_crm_stage(value: str) -> CrmStage:
    if value not in CRM_STAGE_SET:
        raise ValueError(
            f"crm_stage must be one of {sorted(CRM_STAGE_SET)}, got {value!r}"
        )
    return cast(CrmStage, value)


def validate_planning_mode(value: str) -> PlanningMode:
    if value not in PLANNING_MODE_SET:
        raise ValueError(
            f"planning_mode must be one of {sorted(PLANNING_MODE_SET)}, got {value!r}"
        )
    return cast(PlanningMode, value)


def validate_call_verification_status(value: str) -> CallVerificationStatus:
    if value not in CALL_VERIFICATION_STATUS_SET:
        raise ValueError(
            "call_verification_status must be one of "
            f"{sorted(CALL_VERIFICATION_STATUS_SET)}, got {value!r}"
        )
    return cast(CallVerificationStatus, value)


def validate_customer_linkage(value: dict[str, Any]) -> CustomerLinkage:
    if not isinstance(value, dict):
        raise TypeError("customer_linkage must be a dict")
    for key in value:
        if key not in ALLOWED_CUSTOMER_LINKAGE_KEYS:
            raise ValueError(
                f"customer_linkage keys must be subset of "
                f"{sorted(ALLOWED_CUSTOMER_LINKAGE_KEYS)}, got key {key!r}"
            )
    if value.get("placeholder") is not None and value.get("placeholder") is not True:
        raise ValueError(
            "customer_linkage['placeholder'] is only allowed as the literal True"
        )
    for sk in ("customer_id", "contact_id"):
        if sk in value and not isinstance(value[sk], str):
            raise ValueError(f"customer_linkage[{sk!r}] must be a str when present")
    return cast(CustomerLinkage, value)


@dataclass
class Inquiry:
    """Sales inquiry (A1)."""

    inquiry_id: str
    event_date: date
    created_at: datetime
    updated_at: datetime
    inquiry_source: InquirySource
    crm_stage: CrmStage
    customer_linkage: CustomerLinkage
    time_window_text: str
    location_text: str
    guest_count_estimate: int | None
    planning_mode: PlanningMode
    call_verification_required: bool
    call_verification_status: CallVerificationStatus
    # Intake context (INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1): freeform,
    # channel-agnostic notes about how/why the inquiry arrived. Not operational
    # truth — never read by progression/READY_TO_SEND/kiosk/Wochenübersicht,
    # never copied onto Order/OrderVersion at conversion time.
    intake_subject: str | None = None
    intake_message: str | None = None
    intake_summary: str | None = None
    intake_external_ref: str | None = None
    customer_id: str | None = None
    customer_snapshot: InquiryCustomerSnapshot | None = None


def inquiry_shows_convert_accepted_button(state: InquiryOfficeState) -> bool:
    """True only when the accepted-offer conversion command may be offered."""
    return (
        state.next_action == "convert-accepted"
        and state.offer is not None
        and state.offer.commercial_state == "Accepted"
    )


def inquiry_allows_convert_accepted_command(state: InquiryOfficeState) -> bool:
    """True when POST convert-accepted is allowed (initial create or idempotent replay)."""
    if inquiry_shows_convert_accepted_button(state):
        return True
    return (
        state.next_action == "convert-accepted"
        and state.offer is not None
        and state.offer.commercial_state == "Converted"
        and state.offer.accepted_variant_id is not None
        and state.offer.acceptance_id is not None
    )


def inquiry_allows_order_conversion(inquiry: Inquiry) -> bool:
    """Core gate: rejected inquiries cannot convert; required calls need verification."""
    if inquiry.crm_stage == "Abgelehnt / verloren":
        return False
    if not inquiry.call_verification_required:
        return True
    return inquiry.call_verification_status == "verified"


def inquiry_crm_stage_is_compatible_with_active_order(stage: CrmStage) -> bool:
    """An active linked order requires the inquiry's confirmed-order stage."""
    return stage == ACTIVE_ORDER_CRM_STAGE


def derive_inquiry_offer_projection(
    offer: Offer, *, today: date
) -> InquiryOfferProjection:
    """Pick the one commercial version the office UI should surface for an Inquiry."""
    from catering_system.domain.offer import derive_offer_state

    link = offer.conversion_link
    if link is not None:
        return InquiryOfferProjection(
            offer_id=offer.offer_id,
            offer_version_id=link.offer_version_id,
            commercial_state="Converted",
            accepted_variant_id=link.variant_id,
            acceptance_id=link.acceptance_id,
        )
    acceptance = offer.acceptance_evidence
    if acceptance is not None:
        return InquiryOfferProjection(
            offer_id=offer.offer_id,
            offer_version_id=acceptance.accepted_offer_version_id,
            commercial_state="Accepted",
            accepted_variant_id=acceptance.accepted_variant_id,
            acceptance_id=acceptance.acceptance_id,
        )
    latest = max(offer.versions, key=lambda version: version.version_number)
    return InquiryOfferProjection(
        offer_id=offer.offer_id,
        offer_version_id=latest.offer_version_id,
        commercial_state=derive_offer_state(
            offer, latest.offer_version_id, today=today
        ),
    )


def derive_inquiry_office_state(
    inquiry: Inquiry,
    *,
    has_order: bool,
    has_active_order: bool,
    offer: Offer | None = None,
    today: date | None = None,
) -> InquiryOfficeState:
    """Derive queue membership and the one truthful primary office action."""
    if has_active_order and not has_order:
        raise ValueError("an active order is also an existing order")
    if today is None:
        raise ValueError("today is required when deriving inquiry office state")
    offer_projection = (
        derive_inquiry_offer_projection(offer, today=today)
        if offer is not None
        else None
    )
    if inquiry.crm_stage == "Abgelehnt / verloren" or has_order:
        return InquiryOfficeState(
            is_open=False, next_action=None, offer=offer_projection
        )
    is_open = True
    if (
        inquiry.call_verification_required
        and inquiry.call_verification_status != "verified"
    ):
        return InquiryOfficeState(
            is_open=is_open, next_action="verify", offer=offer_projection
        )
    from catering_system.domain.inquiry_contact_completeness import (
        inquiry_contact_complete,
    )

    contact_complete = inquiry_contact_complete(inquiry)
    if offer_projection is not None:
        commercial = offer_projection.commercial_state
        if commercial == "Accepted":
            # Contact-completeness gate (INQUIRY_CONTACT_COMPLETENESS_V1 §8):
            # an accepted offer must not be convertible while e-mail/phone are
            # missing. Converted offers below stay untouched — an existing
            # conversion link is never blocked retroactively.
            if not contact_complete:
                return InquiryOfficeState(
                    is_open=is_open, next_action=None, offer=offer_projection
                )
            return InquiryOfficeState(
                is_open=is_open,
                next_action="convert-accepted",
                offer=offer_projection,
            )
        if commercial == "Converted":
            if inquiry_allows_order_conversion(inquiry):
                return InquiryOfficeState(
                    is_open=False,
                    next_action="convert-accepted",
                    offer=offer_projection,
                )
            return InquiryOfficeState(
                is_open=is_open, next_action=None, offer=offer_projection
            )
        if commercial in ("Prepared", "Sent"):
            return InquiryOfficeState(
                is_open=is_open,
                next_action="offer-pending",
                offer=offer_projection,
            )
    if inquiry_allows_order_conversion(inquiry) and contact_complete:
        return InquiryOfficeState(
            is_open=is_open, next_action="convert", offer=offer_projection
        )
    return InquiryOfficeState(is_open=is_open, next_action=None, offer=offer_projection)


def apply_inquiry_customer_reference(
    inquiry: Inquiry,
    *,
    customer_id: str,
    snapshot: "InquiryCustomerSnapshot",
) -> Inquiry:
    """Explicit assignment only — never auto-match or auto-create CustomerIdentity."""
    from catering_system.domain.inquiry_customer_snapshot import (
        InquiryCustomerSnapshot,
        validate_customer_id_reference,
    )

    if not isinstance(snapshot, InquiryCustomerSnapshot):
        raise TypeError("snapshot must be InquiryCustomerSnapshot")
    next_id = validate_customer_id_reference(customer_id)
    if inquiry.customer_id is not None and inquiry.customer_id != next_id:
        raise ValueError("customer_id is already assigned and cannot change")
    if snapshot.is_empty():
        raise ValueError("snapshot is required when assigning customer_id")
    if inquiry.customer_snapshot is not None and inquiry.customer_snapshot != snapshot:
        raise ValueError("customer_snapshot is immutable once stored")
    return replace(
        inquiry,
        customer_id=next_id,
        customer_snapshot=snapshot,
    )

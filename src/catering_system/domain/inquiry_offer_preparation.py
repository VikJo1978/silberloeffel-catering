"""Shared eligibility for creating the first Offer from an Inquiry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from catering_system.domain.inquiry import Inquiry
from catering_system.domain.progression_blockers import (
    REASON_INQUIRY_CALL_VERIFICATION_UNSATISFIED,
    REASON_INQUIRY_CONTACT_MISSING_EMAIL,
    REASON_INQUIRY_CONTACT_MISSING_EMAIL_AND_PHONE,
    REASON_INQUIRY_CONTACT_MISSING_PHONE,
    REASON_INQUIRY_REJECTED,
    evaluate_inquiry_to_order_progression,
)

REASON_ACTIVE_ORDER_EXISTS: Literal["active_order_exists"] = "active_order_exists"
REASON_OFFER_ALREADY_EXISTS: Literal["offer_already_exists"] = "offer_already_exists"

InquiryOfferPreparationBlocker = Literal[
    "inquiry_rejected",
    "inquiry_call_verification_unsatisfied",
    "inquiry_contact_missing_email",
    "inquiry_contact_missing_phone",
    "inquiry_contact_missing_email_and_phone",
    "active_order_exists",
    "offer_already_exists",
]

_INQUIRY_BLOCKERS = frozenset(
    {
        REASON_INQUIRY_REJECTED,
        REASON_INQUIRY_CALL_VERIFICATION_UNSATISFIED,
        REASON_INQUIRY_CONTACT_MISSING_EMAIL,
        REASON_INQUIRY_CONTACT_MISSING_PHONE,
        REASON_INQUIRY_CONTACT_MISSING_EMAIL_AND_PHONE,
    }
)


@dataclass(frozen=True)
class InquiryOfferPreparationEligibility:
    """Structured first-Offer gate shared by reads and write enforcement."""

    blocked: bool
    reasons: tuple[InquiryOfferPreparationBlocker, ...] = ()


def evaluate_inquiry_offer_preparation(
    inquiry: Inquiry,
    *,
    has_active_order: bool,
    has_existing_offer: bool,
) -> InquiryOfferPreparationEligibility:
    """Evaluate only facts that may block creation of OfferVersion 1.

    Historical cancelled Orders deliberately do not appear in this contract:
    callers pass whether an *active* Order exists, not whether any Order has
    ever existed.
    """

    progression = evaluate_inquiry_to_order_progression(inquiry)
    reasons = [
        cast(InquiryOfferPreparationBlocker, reason)
        for reason in progression.reasons
        if reason in _INQUIRY_BLOCKERS
    ]
    if has_active_order:
        reasons.append(REASON_ACTIVE_ORDER_EXISTS)
    if has_existing_offer:
        reasons.append(REASON_OFFER_ALREADY_EXISTS)
    return InquiryOfferPreparationEligibility(
        blocked=bool(reasons),
        reasons=tuple(reasons),
    )


__all__ = [
    "InquiryOfferPreparationBlocker",
    "InquiryOfferPreparationEligibility",
    "REASON_ACTIVE_ORDER_EXISTS",
    "REASON_OFFER_ALREADY_EXISTS",
    "evaluate_inquiry_offer_preparation",
]

"""Customer verification classification — Slice B4 (Core/office-side boundary)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from catering_system.domain.inquiry import CallVerificationStatus, CustomerLinkage


class ClientClassification(str, Enum):
    """Office/Core intake classification; not operational release state."""

    KNOWN = "known"
    NEW = "new"
    SUSPICIOUS = "suspicious"


@dataclass(frozen=True)
class CustomerVerificationDecision:
    """Result of B4 evaluation; drives inquiry verification fields when applied."""

    classification: ClientClassification
    call_verification_required: bool
    call_verification_status: CallVerificationStatus


def customer_linkage_indicates_known_client(customer_linkage: CustomerLinkage) -> bool:
    """True when CRM linkage IDs are present (non-empty); placeholder alone is not known."""
    cid = customer_linkage.get("customer_id")
    coid = customer_linkage.get("contact_id")
    if isinstance(cid, str) and cid.strip():
        return True
    if isinstance(coid, str) and coid.strip():
        return True
    return False


def classify_from_linkage_and_contact_matches(
    *,
    customer_linkage: CustomerLinkage,
    email_matched: bool,
    phone_matched: bool,
) -> CustomerVerificationDecision:
    """Classify from existing linkage and narrow email/phone match flags (caller-supplied)."""
    if customer_linkage_indicates_known_client(customer_linkage):
        return CustomerVerificationDecision(
            classification=ClientClassification.KNOWN,
            call_verification_required=False,
            call_verification_status="not_required",
        )
    if not email_matched and not phone_matched:
        return CustomerVerificationDecision(
            classification=ClientClassification.NEW,
            call_verification_required=True,
            call_verification_status="pending",
        )
    return CustomerVerificationDecision(
        classification=ClientClassification.SUSPICIOUS,
        call_verification_required=True,
        call_verification_status="pending",
    )

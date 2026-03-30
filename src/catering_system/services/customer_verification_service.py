"""Customer verification decision — Slice B4 Core/office-side evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from catering_system.domain.customer_verification import (
    CustomerVerificationDecision,
    classify_from_linkage_and_contact_matches,
)
from catering_system.domain.inquiry import Inquiry, validate_customer_linkage


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _apply_decision_to_inquiry(
    inquiry: Inquiry,
    decision: CustomerVerificationDecision,
    *,
    at: datetime | None = None,
) -> Inquiry:
    now = at or _utc_now()
    cur = inquiry.call_verification_status
    if cur in ("verified", "failed", "blocked"):
        return inquiry
    return replace(
        inquiry,
        call_verification_required=decision.call_verification_required,
        call_verification_status=decision.call_verification_status,
        updated_at=now,
    )


class CustomerVerificationService:
    """Evaluates linkage + contact-match signals; does not persist or implement release-side logic."""

    def evaluate(
        self,
        *,
        customer_linkage: Mapping[str, Any],
        email_matched: bool = False,
        phone_matched: bool = False,
    ) -> CustomerVerificationDecision:
        linkage = validate_customer_linkage(dict(customer_linkage))
        return classify_from_linkage_and_contact_matches(
            customer_linkage=linkage,
            email_matched=email_matched,
            phone_matched=phone_matched,
        )

    def apply_decision_to_inquiry(
        self,
        inquiry: Inquiry,
        decision: CustomerVerificationDecision,
        *,
        at: datetime | None = None,
    ) -> Inquiry:
        """Set verification fields from a B4 decision; never downgrades terminal verification states."""
        return _apply_decision_to_inquiry(inquiry, decision, at=at)


def merge_verification_decision_into_inquiry(
    inquiry: Inquiry,
    decision: CustomerVerificationDecision,
    *,
    at: datetime | None = None,
) -> Inquiry:
    """Module-level helper; same rules as CustomerVerificationService.apply_decision_to_inquiry."""
    return _apply_decision_to_inquiry(inquiry, decision, at=at)

"""Shared first-Offer eligibility contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.inquiry_offer_preparation import (
    evaluate_inquiry_offer_preparation,
)

_NOW = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)


def _inquiry(**overrides: object) -> Inquiry:
    values: dict[str, object] = {
        "inquiry_id": "11111111-1111-4111-8111-111111111111",
        "event_date": date(2026, 10, 3),
        "created_at": _NOW,
        "updated_at": _NOW,
        "inquiry_source": "manual",
        "crm_stage": "Neue Anfrage",
        "customer_linkage": {},
        "time_window_text": "18:00–22:00",
        "location_text": "Hamburg",
        "guest_count_estimate": 40,
        "planning_mode": "caterer_suggestion",
        "call_verification_required": False,
        "call_verification_status": "not_required",
        "customer_snapshot": InquiryCustomerSnapshot(
            email="kunde@example.test",
            phone="+49401234567",
        ),
        "fulfillment_mode": "PICKUP",
    }
    values.update(overrides)
    return Inquiry(**values)  # type: ignore[arg-type]


def _evaluate(
    inquiry: Inquiry,
    *,
    has_active_order: bool = False,
    has_existing_offer: bool = False,
):
    return evaluate_inquiry_offer_preparation(
        inquiry,
        has_active_order=has_active_order,
        has_existing_offer=has_existing_offer,
    )


def test_eligible_inquiry_has_no_blockers() -> None:
    assert _evaluate(_inquiry()).reasons == ()


def test_rejected_and_required_verification_are_structured_blockers() -> None:
    rejected = _evaluate(_inquiry(crm_stage="Abgelehnt / verloren"))
    pending = _evaluate(
        _inquiry(
            call_verification_required=True,
            call_verification_status="pending",
        )
    )
    assert rejected.reasons == ("inquiry_rejected",)
    assert pending.reasons == ("inquiry_call_verification_unsatisfied",)


def test_contact_blocker_uses_existing_progression_reason() -> None:
    inquiry = replace(
        _inquiry(),
        customer_snapshot=InquiryCustomerSnapshot(phone="+49401234567"),
    )
    assert _evaluate(inquiry).reasons == ("inquiry_contact_missing_email",)


def test_unknown_fulfillment_blocks_offer_preparation() -> None:
    eligibility = _evaluate(_inquiry(fulfillment_mode="UNKNOWN"))
    assert eligibility.reasons == ("fulfillment_mode_unresolved",)


def test_pickup_does_not_require_delivery_address() -> None:
    assert _evaluate(_inquiry(fulfillment_mode="PICKUP")).blocked is False


def test_delivery_requires_resolved_delivery_context() -> None:
    unresolved = _inquiry(fulfillment_mode="DELIVERY")
    assert _evaluate(unresolved).reasons == ("delivery_address_unresolved",)


def test_delivery_same_as_invoice_is_resolved_when_invoice_address_exists() -> None:
    inquiry = _inquiry(
        fulfillment_mode="DELIVERY",
        customer_snapshot=InquiryCustomerSnapshot(
            email="kunde@example.test",
            phone="+49401234567",
            invoice_address=CustomerAddress(
                street="Musterstraße 1",
                postal_code="20095",
                city="Hamburg",
                country="DE",
            ),
            delivery_address_mode="SAME_AS_INVOICE",
        ),
    )
    assert _evaluate(inquiry).blocked is False


def test_delivery_separate_address_is_resolved() -> None:
    inquiry = _inquiry(
        fulfillment_mode="DELIVERY",
        customer_snapshot=InquiryCustomerSnapshot(
            email="kunde@example.test",
            phone="+49401234567",
            invoice_address=CustomerAddress(
                street="Musterstraße 1",
                postal_code="20095",
                city="Hamburg",
                country="DE",
            ),
            delivery_address=CustomerAddress(
                street="Eventweg 7",
                postal_code="22041",
                city="Hamburg",
                country="DE",
            ),
            delivery_address_mode="SEPARATE",
        ),
    )
    assert _evaluate(inquiry).blocked is False


def test_active_order_and_existing_offer_have_distinct_blockers() -> None:
    eligibility = _evaluate(
        _inquiry(),
        has_active_order=True,
        has_existing_offer=True,
    )
    assert eligibility.reasons == (
        "active_order_exists",
        "offer_already_exists",
    )


def test_cancelled_historical_order_is_not_an_eligibility_input() -> None:
    # Callers deliberately provide only the active-Order fact.
    assert _evaluate(_inquiry(), has_active_order=False).blocked is False

"""Unit tests — REMOVE_LEGACY_ORDER_CREATION_V1 / conversion lookup gate."""

from __future__ import annotations

from datetime import date

import pytest

from tests.helpers.order_seed import seed_order

from catering_system.domain.contact_projection import derive_contact_status
from catering_system.domain.inquiry import derive_inquiry_office_state
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService

_TODAY = date(2026, 7, 15)


def _inquiry(
    repo: InMemoryInquiryRepository,
    *,
    crm_stage: str = "Neue Anfrage",
    call_verification_required: bool = False,
    call_verification_status: str = "not_required",
    email: str = "kunde@example.invalid",
    phone: str = "+49301234567",
):
    return InquiryService(repo).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage=crm_stage,  # type: ignore[arg-type]
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=12,
        planning_mode="caterer_suggestion",
        call_verification_required=call_verification_required,
        call_verification_status=call_verification_status,  # type: ignore[arg-type]
        contact_email=email,
        contact_phone=phone,
        intake_message=f"Firma: GateCo\nE-Mail: {email}\nTelefon: {phone}\n",
    )


def test_convert_without_order_requires_accepted_offer() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    with pytest.raises(ValueError, match="accepted offer required"):
        OrderService(orders).convert_inquiry_to_order(inquiry)
    assert orders.list_orders() == []


def test_convert_returns_existing_seeded_order() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    first_order, first_version = seed_order(orders, inquiry)
    second_order, second_version = OrderService(orders).convert_inquiry_to_order(
        inquiry
    )
    assert second_order.order_id == first_order.order_id
    assert second_version.order_version_id == first_version.order_version_id
    assert len(orders.list_orders()) == 1
    assert len(orders.list_order_versions(first_order.order_id)) == 1


def test_cancelled_order_lookup_returns_existing_without_second_create() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    first_order, first_version = seed_order(orders, inquiry)
    OperationalCoreService(orders).cancel_order(first_order.order_id)
    second_order, second_version = OrderService(orders).convert_inquiry_to_order(
        inquiry
    )
    assert second_order.order_id == first_order.order_id
    assert second_version.order_version_id == first_version.order_version_id
    assert len(orders.list_orders()) == 1


def test_ready_inquiry_projects_prepare_offer_not_convert() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _inquiry(inquiries)
    state = derive_inquiry_office_state(
        inquiry,
        has_order=False,
        has_active_order=False,
        today=_TODAY,
    )
    assert state.next_action == "prepare-offer"
    assert state.is_open is True


def test_seeded_order_leaves_open_queue_but_stays_in_history() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    seed_order(orders, inquiry)
    state = derive_inquiry_office_state(
        inquiry,
        has_order=True,
        has_active_order=True,
        today=_TODAY,
    )
    assert state.is_open is False
    assert state.next_action is None
    assert any(row.inquiry_id == inquiry.inquiry_id for row in inquiries.list_all())


def test_contact_status_becomes_kunde_when_order_exists() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    assert derive_contact_status(linked_order_count=0) == "interessent"
    seed_order(orders, inquiry)
    assert derive_contact_status(linked_order_count=1) == "kunde"


def test_repository_rejects_second_order_for_same_inquiry() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    seed_order(orders, inquiry)
    with pytest.raises(ValueError, match="inquiry already has a linked order"):
        seed_order(orders, inquiry)

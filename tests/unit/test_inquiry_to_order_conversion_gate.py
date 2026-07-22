"""Unit tests — INQUIRY_TO_ORDER_CONVERSION_GATE_V1."""

from __future__ import annotations

from datetime import date

import pytest

from catering_system.domain.contact_projection import derive_contact_status
from catering_system.domain.inquiry import derive_inquiry_office_state
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.ui.office_panel import OfficePanel

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


def test_valid_inquiry_creates_exactly_one_order() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    order, version = OrderService(orders).convert_inquiry_to_order(inquiry)
    assert version.version_number == 1
    assert order.source_inquiry_id == inquiry.inquiry_id
    assert len(orders.list_orders()) == 1
    assert len(orders.list_order_versions(order.order_id)) == 1


def test_repeated_conversion_returns_same_order_without_new_version() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    service = OrderService(orders)
    first_order, first_version = service.convert_inquiry_to_order(inquiry)
    second_order, second_version = service.convert_inquiry_to_order(inquiry)
    assert second_order.order_id == first_order.order_id
    assert second_version.order_version_id == first_version.order_version_id
    assert len(orders.list_orders()) == 1
    assert len(orders.list_order_versions(first_order.order_id)) == 1


def test_cancelled_order_blocks_second_order_and_returns_existing() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    service = OrderService(orders)
    first_order, first_version = service.convert_inquiry_to_order(inquiry)
    OperationalCoreService(orders).cancel_order(first_order.order_id)
    second_order, second_version = service.convert_inquiry_to_order(inquiry)
    assert second_order.order_id == first_order.order_id
    assert second_version.order_version_id == first_version.order_version_id
    assert len(orders.list_orders()) == 1


def test_rejected_inquiry_is_blocked() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries, crm_stage="Abgelehnt / verloren")
    with pytest.raises(ValueError, match="conversion blocked"):
        OrderService(orders).convert_inquiry_to_order(inquiry)
    assert orders.list_orders() == []


def test_incomplete_inquiry_is_blocked() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=12,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    with pytest.raises(ValueError, match="contact information incomplete"):
        OrderService(orders).convert_inquiry_to_order(inquiry)


def test_verification_required_but_pending_is_blocked() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(
        inquiries,
        call_verification_required=True,
        call_verification_status="pending",
    )
    with pytest.raises(ValueError, match="conversion blocked"):
        OrderService(orders).convert_inquiry_to_order(inquiry)


def test_order_existence_closes_open_queue() -> None:
    state = derive_inquiry_office_state(
        _inquiry(InMemoryInquiryRepository()),
        has_order=True,
        has_active_order=False,
        today=_TODAY,
    )
    assert state.is_open is False
    assert state.next_action is None


def test_converted_inquiry_leaves_open_queue_but_stays_in_history() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    OrderService(orders).convert_inquiry_to_order(inquiry)
    InquiryService(inquiries).update_inquiry(
        inquiry.inquiry_id, crm_stage="Bestätigt / Auftrag"
    )
    panel = OfficePanel(inquiries, orders, offer_repo=InMemoryOfferRepository())
    queue = panel.render_queue(None)
    assert inquiry.inquiry_id not in queue or "Offene Anfragen" in queue
    # open-inquiry counter excludes converted
    assert panel._open_inquiries_count() == 0  # noqa: SLF001
    detail = panel.render_inquiry(inquiry.inquiry_id) or ""
    assert inquiry.inquiry_id[:8] in detail or "Auftrag" in detail
    assert "Auftrag öffnen" in detail or "Auftrag vorhanden" in detail


def test_contact_status_becomes_kunde_after_conversion() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    assert derive_contact_status(linked_order_count=0) == "interessent"
    OrderService(orders).convert_inquiry_to_order(inquiry)
    assert derive_contact_status(linked_order_count=1) == "kunde"


def test_in_memory_repository_rejects_duplicate_linked_order() -> None:
    from datetime import UTC, datetime
    import uuid

    from catering_system.domain.order import Order, OrderVersion

    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _inquiry(inquiries)
    OrderService(orders).convert_inquiry_to_order(inquiry)
    now = datetime.now(UTC)
    order_id = str(uuid.uuid4())
    with pytest.raises(ValueError, match="already has a linked order"):
        orders.save_order_with_initial_version(
            Order(
                order_id=order_id,
                source_inquiry_id=inquiry.inquiry_id,
                created_at=now,
                updated_at=now,
            ),
            OrderVersion(
                order_version_id=str(uuid.uuid4()),
                order_id=order_id,
                version_number=1,
                created_at=now,
                event_date=inquiry.event_date,
                time_window_text=inquiry.time_window_text,
                location_text=inquiry.location_text,
                guest_count_estimate=inquiry.guest_count_estimate,
                planning_mode=inquiry.planning_mode,
            ),
        )

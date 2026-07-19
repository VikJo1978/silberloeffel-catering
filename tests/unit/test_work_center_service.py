"""Unit tests — WorkCenterService Arbeitszentrale read projection (5A-1)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from catering_system.domain.inquiry import Inquiry
from catering_system.domain.offer import (
    AcceptanceEvidence,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    SentEvidence,
)
from catering_system.domain.order import Order
from catering_system.integration import auerswald_sync
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
from catering_system.services.work_center_service import WorkCenterService

_TODAY = date(2026, 7, 15)
_NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
_OFFER_ID_A = "11111111-1111-4111-8111-111111111111"
_OFFER_ID_B = "11111111-1111-4111-8111-111111111112"
_V1_ID_A = "33333333-3333-4333-8333-333333333331"
_V1_ID_B = "33333333-3333-4333-8333-333333333332"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"
_ACCEPTANCE_ID = "55555555-5555-5555-5555-555555555555"
_HASH = "sha256:" + ("a" * 64)


def _service(
    *,
    inquiries: InMemoryInquiryRepository | None = None,
    offers: InMemoryOfferRepository | None = None,
    orders: InMemoryOrderRepository | None = None,
    missed_calls_open: int = 0,
) -> WorkCenterService:
    return WorkCenterService(
        inquiries or InMemoryInquiryRepository(),
        offers or InMemoryOfferRepository(),
        orders or InMemoryOrderRepository(),
        today=lambda: _TODAY,
        missed_calls_open=lambda: missed_calls_open,
    )


def _save_inquiry(repo: InMemoryInquiryRepository, **overrides: object) -> Inquiry:
    service = InquiryService(repo)
    payload: dict[str, object] = {
        "event_date": date(2026, 10, 1),
        "inquiry_source": "manual",
        "crm_stage": "Neue Anfrage",
        "customer_linkage": {},
        "time_window_text": "mittags",
        "location_text": "Hamburg",
        "guest_count_estimate": 25,
        "planning_mode": "caterer_suggestion",
        "call_verification_required": False,
        "call_verification_status": "not_required",
    }
    payload.update(overrides)
    return service.create_inquiry(**payload)  # type: ignore[arg-type]


def _offer_version(
    *, offer_id: str, version_id: str, sent: bool = False
) -> OfferVersion:
    return OfferVersion(
        offer_version_id=version_id,
        offer_id=offer_id,
        version_number=1,
        created_at=_NOW,
        valid_until=date(2026, 7, 31),
        snapshot_id="77777777-7777-4777-8777-777777777771",
        snapshot_hash=_HASH,
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count=80,
        planning_mode="caterer_suggestion",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        variants=(
            OfferVariant(
                variant_id=_VARIANT_ID,
                offer_version_id=version_id,
                label="Variante A",
                positions=(
                    OfferPosition(
                        position_id=_POSITION_ID,
                        kind="catalog",
                        name="Fingerfood Paket",
                        unit_net_cents=290,
                        net_total_cents=23200,
                        vat_rate_percent=7,
                        vat_amount_cents=1624,
                        gross_total_cents=24824,
                    ),
                ),
            ),
        ),
    )


def _save_offer(
    repo: InMemoryOfferRepository,
    *,
    offer_id: str,
    version_id: str,
    inquiry_id: str,
    sent: bool = False,
    accepted: bool = False,
) -> Offer:
    sent_evidence = (
        (
            SentEvidence(
                offer_id=offer_id,
                offer_version_id=version_id,
                sent_at=_NOW,
                recorded_at=_NOW + timedelta(minutes=1),
                channel="email",
                recipient_reference="kunde@example.invalid",
                evidence_reference="mail-1",
                recorded_by="office",
            ),
        )
        if sent
        else ()
    )
    acceptance = (
        AcceptanceEvidence(
            acceptance_id=_ACCEPTANCE_ID,
            offer_id=offer_id,
            accepted_offer_version_id=version_id,
            accepted_variant_id=_VARIANT_ID,
            accepted_at=_NOW + timedelta(days=1),
            recorded_at=_NOW + timedelta(days=1, minutes=5),
            channel="email",
            evidence_reference="reply-1",
            recorded_by="office",
        )
        if accepted
        else None
    )
    offer = Offer(
        offer_id=offer_id,
        source_inquiry_id=inquiry_id,
        created_at=_NOW,
        versions=(_offer_version(offer_id=offer_id, version_id=version_id, sent=sent),),
        sent_evidence=sent_evidence,
        acceptance_evidence=acceptance,
        rejection_evidence=(),
        withdrawal_evidence=(),
        conversion_link=None,
    )
    repo.save(offer)
    return offer


def _save_upcoming_order(
    inquiries: InMemoryInquiryRepository,
    orders: InMemoryOrderRepository,
    *,
    event_date: date,
    effective: bool = True,
    cancelled: bool = False,
) -> Order:
    inquiry = _save_inquiry(inquiries, event_date=event_date)
    order_service = OrderService(orders)
    core = OperationalCoreService(orders)
    order, version = order_service.convert_inquiry_to_order(inquiry)
    updated_version = replace(version, event_date=event_date)
    orders.update_order_version(updated_version)
    if effective:
        core.confirm_kitchen_print(order.order_id, version.order_version_id)
        core.make_order_version_effective(order.order_id, version.order_version_id)
    if cancelled:
        core.cancel_order(order.order_id)
    result = orders.get_order(order.order_id)
    assert result is not None
    return result


def test_empty_system_snapshot() -> None:
    snapshot = _service().snapshot()
    assert snapshot.rueckrufe_open == 0
    assert snapshot.missed_calls_open == 0
    assert snapshot.offers_waiting == 0
    assert snapshot.offers_accepted == 0
    assert snapshot.upcoming_orders == 0
    assert snapshot.open_tasks == 0
    assert snapshot.today_calendar_entries == 0


def test_inquiry_callback_count() -> None:
    inquiries = InMemoryInquiryRepository()
    _save_inquiry(
        inquiries,
        call_verification_required=True,
        call_verification_status="pending",
    )
    _save_inquiry(
        inquiries,
        call_verification_required=True,
        call_verification_status="pending",
    )
    _save_inquiry(inquiries)

    snapshot = _service(inquiries=inquiries).snapshot()
    assert snapshot.rueckrufe_open == 2


def test_missed_calls_available() -> None:
    snapshot = _service(missed_calls_open=2).snapshot()
    assert snapshot.missed_calls_open == 2


def test_missed_calls_unavailable_returns_zero() -> None:
    assert auerswald_sync.count_open_missed_calls("", "", "") == 0
    with patch.object(
        auerswald_sync,
        "fetch_missed_board",
        return_value=(None, "connection refused"),
    ):
        assert auerswald_sync.count_open_missed_calls("http://sync", "u", "p") == 0


def test_prepared_and_sent_offer_counts() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    inquiry_a = _save_inquiry(inquiries)
    inquiry_b = _save_inquiry(inquiries)
    _save_offer(
        offers,
        offer_id=_OFFER_ID_A,
        version_id=_V1_ID_A,
        inquiry_id=inquiry_a.inquiry_id,
        sent=False,
    )
    _save_offer(
        offers,
        offer_id=_OFFER_ID_B,
        version_id=_V1_ID_B,
        inquiry_id=inquiry_b.inquiry_id,
        sent=True,
    )

    snapshot = _service(inquiries=inquiries, offers=offers).snapshot()
    assert snapshot.offers_waiting == 2
    assert snapshot.offers_accepted == 0


def test_accepted_offer_count() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    inquiry = _save_inquiry(inquiries)
    _save_offer(
        offers,
        offer_id=_OFFER_ID_A,
        version_id=_V1_ID_A,
        inquiry_id=inquiry.inquiry_id,
        sent=True,
        accepted=True,
    )

    snapshot = _service(inquiries=inquiries, offers=offers).snapshot()
    assert snapshot.offers_waiting == 0
    assert snapshot.offers_accepted == 1


def test_active_upcoming_orders_count() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    _save_upcoming_order(
        inquiries,
        orders,
        event_date=date(2026, 8, 1),
        effective=True,
    )
    _save_upcoming_order(
        inquiries,
        orders,
        event_date=date(2026, 7, 10),
        effective=True,
    )
    _save_upcoming_order(
        inquiries,
        orders,
        event_date=date(2026, 9, 1),
        effective=False,
    )

    snapshot = _service(inquiries=inquiries, orders=orders).snapshot()
    assert snapshot.upcoming_orders == 1


def test_cancelled_orders_are_excluded_from_upcoming() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    _save_upcoming_order(
        inquiries,
        orders,
        event_date=date(2026, 8, 1),
        effective=True,
        cancelled=True,
    )

    snapshot = _service(inquiries=inquiries, orders=orders).snapshot()
    assert snapshot.upcoming_orders == 0

"""Unit tests — event calendar projection read model (5E-1a)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from catering_system.domain.offer import (
    AcceptanceEvidence,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    RejectionEvidence,
    SentEvidence,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.calendar_projection_service import (
    CalendarProjectionService,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.work_center_service import WorkCenterService

_TODAY = date(2026, 7, 15)
_NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_V1_ID = "33333333-3333-4333-8333-333333333331"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"
_ACCEPTANCE_ID = "55555555-5555-5555-5555-555555555555"
_HASH = "sha256:" + ("a" * 64)


def _service(
    *,
    inquiries: InMemoryInquiryRepository | None = None,
    offers: InMemoryOfferRepository | None = None,
    orders: InMemoryOrderRepository | None = None,
) -> CalendarProjectionService:
    return CalendarProjectionService(
        inquiries or InMemoryInquiryRepository(),
        offers or InMemoryOfferRepository(),
        orders or InMemoryOrderRepository(),
        today=lambda: _TODAY,
    )


def _save_inquiry(repo: InMemoryInquiryRepository, **overrides: object):
    service = InquiryService(repo)
    payload: dict[str, object] = {
        "event_date": date(2026, 8, 1),
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


def _offer_version(*, event_date: date = date(2026, 8, 20)) -> OfferVersion:
    return OfferVersion(
        offer_version_id=_V1_ID,
        offer_id=_OFFER_ID,
        version_number=1,
        created_at=_NOW,
        valid_until=date(2026, 7, 31),
        snapshot_id="77777777-7777-4777-8777-777777777771",
        snapshot_hash=_HASH,
        event_date=event_date,
        time_window_text="18:00–22:00",
        location_text="Hamburg Angebot",
        guest_count=80,
        planning_mode="caterer_suggestion",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        variants=(
            OfferVariant(
                variant_id=_VARIANT_ID,
                offer_version_id=_V1_ID,
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
    inquiry_id: str,
    *,
    sent: bool = False,
    accepted: bool = False,
    rejected: bool = False,
    event_date: date = date(2026, 8, 20),
) -> Offer:
    sent_evidence = (
        (
            SentEvidence(
                offer_id=_OFFER_ID,
                offer_version_id=_V1_ID,
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
            offer_id=_OFFER_ID,
            accepted_offer_version_id=_V1_ID,
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
    rejection = (
        (
            RejectionEvidence(
                offer_id=_OFFER_ID,
                offer_version_id=_V1_ID,
                rejected_at=_NOW + timedelta(days=2),
                recorded_at=_NOW + timedelta(days=2, minutes=1),
                recorded_by="office",
            ),
        )
        if rejected
        else ()
    )
    offer = Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=inquiry_id,
        created_at=_NOW,
        versions=(_offer_version(event_date=event_date),),
        sent_evidence=sent_evidence,
        acceptance_evidence=acceptance,
        rejection_evidence=rejection,
        withdrawal_evidence=(),
        conversion_link=None,
    )
    repo.save(offer)
    return offer


def test_inquiry_only_tentative_entry() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(inquiries, intake_subject="Sommerfest")
    rows = _service(inquiries=inquiries).list_entries(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.entry_id == f"inquiry:{inquiry.inquiry_id}:event"
    assert row.entry_kind == "event_tentative"
    assert row.entity_type == "inquiry"
    assert row.title == "Sommerfest"


def test_offer_replaces_inquiry() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    inquiry = _save_inquiry(inquiries)
    _save_offer(offers, inquiry.inquiry_id, sent=True)
    rows = _service(inquiries=inquiries, offers=offers).list_entries(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.entry_id == f"offer:{_OFFER_ID}:event"
    assert row.entry_kind == "event_tentative"
    assert row.event_date == date(2026, 8, 20)
    assert row.location_text == "Hamburg Angebot"


def test_accepted_offer_remains_tentative_until_conversion() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    inquiry = _save_inquiry(inquiries)
    _save_offer(offers, inquiry.inquiry_id, sent=True, accepted=True)
    rows = _service(inquiries=inquiries, offers=offers).list_entries(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    assert len(rows) == 1
    assert rows[0].entry_kind == "event_tentative"
    assert rows[0].entity_type == "offer"


def test_active_order_replaces_offer() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    orders = InMemoryOrderRepository()
    inquiry = _save_inquiry(inquiries)
    _save_offer(offers, inquiry.inquiry_id, sent=True)
    order, _version = OrderService(orders).convert_inquiry_to_order(inquiry)
    rows = _service(inquiries=inquiries, offers=offers, orders=orders).list_entries(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    assert len(rows) == 1
    assert rows[0].entry_id == f"order:{order.order_id}:event"
    assert rows[0].entity_type == "order"


def test_effective_order_is_confirmed() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _save_inquiry(inquiries)
    order, version = OrderService(orders).convert_inquiry_to_order(inquiry)
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, version.order_version_id)
    core.make_order_version_effective(order.order_id, version.order_version_id)
    rows = _service(inquiries=inquiries, orders=orders).list_entries(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    assert len(rows) == 1
    assert rows[0].entry_kind == "event_confirmed"


def test_candidate_only_order_is_planned() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _save_inquiry(inquiries)
    order, _version = OrderService(orders).convert_inquiry_to_order(inquiry)
    rows = _service(inquiries=inquiries, orders=orders).list_entries(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    assert len(rows) == 1
    assert rows[0].entry_kind == "event_planned"
    assert rows[0].entry_id == f"order:{order.order_id}:event"


def test_cancelled_order_excluded() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _save_inquiry(inquiries)
    order, _version = OrderService(orders).convert_inquiry_to_order(inquiry)
    OperationalCoreService(orders).cancel_order(order.order_id)
    rows = _service(inquiries=inquiries, orders=orders).list_entries(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    assert rows == []


def test_cancelled_order_suppresses_inquiry_and_offer() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    orders = InMemoryOrderRepository()
    inquiry = _save_inquiry(inquiries, intake_subject="War Auftrag")
    _save_offer(offers, inquiry.inquiry_id, sent=True)
    order, _version = OrderService(orders).convert_inquiry_to_order(inquiry)
    OperationalCoreService(orders).cancel_order(order.order_id)
    rows = _service(inquiries=inquiries, offers=offers, orders=orders).list_entries(
        date(2026, 1, 1), date(2026, 12, 31)
    )
    assert rows == []


def test_rejected_offer_falls_back_to_inquiry() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    inquiry = _save_inquiry(inquiries, intake_subject="Weiterhin offen")
    _save_offer(offers, inquiry.inquiry_id, sent=True, rejected=True)
    rows = _service(inquiries=inquiries, offers=offers).list_entries(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    assert len(rows) == 1
    assert rows[0].entry_id == f"inquiry:{inquiry.inquiry_id}:event"
    assert rows[0].title == "Weiterhin offen"


def test_no_duplicate_per_source_inquiry_id() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    orders = InMemoryOrderRepository()
    inquiry = _save_inquiry(inquiries)
    _save_offer(offers, inquiry.inquiry_id, sent=True, accepted=True)
    order, version = OrderService(orders).convert_inquiry_to_order(inquiry)
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, version.order_version_id)
    core.make_order_version_effective(order.order_id, version.order_version_id)
    rows = _service(inquiries=inquiries, offers=offers, orders=orders).list_entries(
        date(2026, 1, 1), date(2026, 12, 31)
    )
    inquiry_ids = [row.source_inquiry_id for row in rows]
    assert inquiry_ids.count(inquiry.inquiry_id) == 1


def test_range_boundaries_inclusive() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(inquiries, event_date=date(2026, 8, 10))
    service = _service(inquiries=inquiries)
    assert len(service.list_entries(date(2026, 8, 10), date(2026, 8, 10))) == 1
    assert service.list_entries(date(2026, 8, 11), date(2026, 8, 20)) == []
    assert service.list_entries(date(2026, 8, 1), date(2026, 8, 9)) == []
    assert service.list_entries(date(2026, 8, 10), date(2026, 8, 11))[0].entry_id == (
        f"inquiry:{inquiry.inquiry_id}:event"
    )


def test_work_center_today_calendar_entries_matches_projection() -> None:
    inquiries = InMemoryInquiryRepository()
    _save_inquiry(inquiries, event_date=_TODAY, intake_subject="Heute")
    _save_inquiry(inquiries, event_date=date(2026, 9, 1), intake_subject="Später")
    calendar = _service(inquiries=inquiries)
    snapshot = WorkCenterService(
        inquiries,
        InMemoryOfferRepository(),
        InMemoryOrderRepository(),
        today=lambda: _TODAY,
        calendar_projection_service=calendar,
    ).snapshot()
    assert snapshot.today_calendar_entries == calendar.count_on(_TODAY) == 1

"""Unit tests — system task projection read model (5D-1a)."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

from datetime import UTC, date, datetime, timedelta

from catering_system.domain.offer import (
    AcceptanceEvidence,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    SentEvidence,
)
from catering_system.domain.order_payment_reminder import OrderPaymentReminder
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.in_memory_payment_reminder_repository import (
    InMemoryPaymentReminderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.payment_reminder_service import PaymentReminderService
from catering_system.services.task_projection_service import TaskProjectionService
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
    payment_reminders: InMemoryPaymentReminderRepository | None = None,
) -> TaskProjectionService:
    inquiry_repo = inquiries or InMemoryInquiryRepository()
    offer_repo = offers or InMemoryOfferRepository()
    order_repo = orders or InMemoryOrderRepository()
    reminder_repo = payment_reminders or InMemoryPaymentReminderRepository()
    payment = PaymentReminderService(
        reminder_repo,
        order_repo,
        today=lambda: _TODAY,
    )
    return TaskProjectionService(
        inquiry_repo,
        offer_repo,
        order_repo,
        payment,
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
        "contact_email": "kunde@example.com",
        "contact_phone": "+49301234567",
    }
    payload.update(overrides)
    return service.create_inquiry(**payload)  # type: ignore[arg-type]


def _offer_version(*, sent: bool = False) -> OfferVersion:
    return OfferVersion(
        offer_version_id=_V1_ID,
        offer_id=_OFFER_ID,
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
    offer = Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=inquiry_id,
        created_at=_NOW,
        versions=(_offer_version(sent=sent),),
        sent_evidence=sent_evidence,
        acceptance_evidence=acceptance,
        rejection_evidence=(),
        withdrawal_evidence=(),
        conversion_link=None,
    )
    repo.save(offer)
    return offer


def test_verify_task_emitted() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(
        inquiries,
        call_verification_required=True,
        call_verification_status="pending",
        intake_subject="Rückruf nötig",
    )
    rows = _service(inquiries=inquiries).list_tasks()
    assert len(rows) == 1
    row = rows[0]
    assert row.task_id == f"inquiry:{inquiry.inquiry_id}:verify"
    assert row.category == "verify"
    assert row.title == "Kundenprüfung durchführen"
    assert row.entity_type == "inquiry"
    assert row.action_href == f"/inquiry/{inquiry.inquiry_id}"


def test_prepare_offer_task_emitted() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(inquiries, intake_subject="Bereit")
    rows = _service(inquiries=inquiries).list_tasks()
    assert len(rows) == 1
    assert rows[0].task_id == f"inquiry:{inquiry.inquiry_id}:prepare-offer"
    assert rows[0].category == "prepare_offer"


def test_convert_accepted_task_emitted() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    inquiry = _save_inquiry(inquiries)
    _save_offer(offers, inquiry.inquiry_id, sent=True, accepted=True)
    rows = _service(inquiries=inquiries, offers=offers).list_tasks()
    assert len(rows) == 1
    assert rows[0].task_id == f"offer:{_OFFER_ID}:convert-accepted"
    assert rows[0].entity_type == "offer"
    assert rows[0].action_href == f"/offer/{_OFFER_ID}"


def test_offer_pending_not_emitted() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    inquiry = _save_inquiry(inquiries)
    _save_offer(offers, inquiry.inquiry_id, sent=True)
    assert _service(inquiries=inquiries, offers=offers).list_tasks() == []


def test_prepare_next_version_task_emitted_for_expired() -> None:
    inquiries = InMemoryInquiryRepository()
    offers = InMemoryOfferRepository()
    inquiry = _save_inquiry(inquiries, intake_subject="Revision nötig")
    expired = Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=inquiry.inquiry_id,
        created_at=_NOW,
        versions=(
            OfferVersion(
                offer_version_id=_V1_ID,
                offer_id=_OFFER_ID,
                version_number=1,
                created_at=_NOW,
                valid_until=date(2026, 7, 1),
                snapshot_id="77777777-7777-4777-8777-777777777771",
                snapshot_hash=_HASH,
                event_date=date(2026, 8, 20),
                time_window_text="18:00–22:00",
                location_text="Hamburg",
                guest_count=80,
                planning_mode="caterer_suggestion",
                payment_method="RECHNUNG",
                payment_customer_visible_text="Zahlung per Rechnung",
                variants=_offer_version().variants,
            ),
        ),
        sent_evidence=(
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
        ),
        acceptance_evidence=None,
        rejection_evidence=(),
        withdrawal_evidence=(),
        conversion_link=None,
    )
    offers.save(expired)
    rows = _service(inquiries=inquiries, offers=offers).list_tasks()
    assert len(rows) == 1
    assert rows[0].task_id == f"offer:{_OFFER_ID}:prepare-next-version"
    assert rows[0].category == "prepare_next_version"
    assert rows[0].title == "Neue Angebotsversion vorbereiten"
    assert rows[0].action_href == f"/offer/{_OFFER_ID}"


def test_print_confirm_task_emitted() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _save_inquiry(inquiries)
    order, version = seed_order(orders, inquiry)
    rows = _service(inquiries=inquiries, orders=orders).list_tasks()
    task_ids = {row.task_id for row in rows}
    assert (
        f"order:{order.order_id}:print-confirm:{version.order_version_id}" in task_ids
    )
    print_row = next(row for row in rows if row.category == "order_print")
    assert print_row.title == "Druck bestätigen"


def test_effective_task_not_emitted_after_manual_print_confirmation() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _save_inquiry(inquiries)
    order, version = seed_order(orders, inquiry)
    OperationalCoreService(orders).confirm_kitchen_print(
        order.order_id, version.order_version_id
    )
    rows = _service(inquiries=inquiries, orders=orders).list_tasks()
    assert not any(row.category == "order_effective" for row in rows)


def test_payment_task_emitted_with_overdue_urgency() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    reminders = InMemoryPaymentReminderRepository()
    inquiry = _save_inquiry(inquiries, event_date=date(2026, 8, 1))
    order, _version = seed_order(orders, inquiry)
    reminders.save(
        OrderPaymentReminder(
            order_id=order.order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-1",
            sent_on=date(2026, 6, 1),
            due_on=date(2026, 7, 1),
            updated_at=_NOW,
        )
    )
    rows = _service(
        inquiries=inquiries,
        orders=orders,
        payment_reminders=reminders,
    ).list_tasks()
    payment_row = next(row for row in rows if row.category == "payment")
    assert payment_row.task_id == f"order:{order.order_id}:payment"
    assert payment_row.urgency == "overdue"
    assert payment_row.title == "Zahlungserinnerung senden"
    assert payment_row.due_at == date(2026, 6, 16)


def test_payment_method_change_retires_old_task_and_projects_new_one() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    reminders = InMemoryPaymentReminderRepository()
    inquiry = _save_inquiry(inquiries, event_date=date(2026, 8, 1))
    order, _version = seed_order(orders, inquiry)
    reminders.save(
        OrderPaymentReminder(
            order_id=order.order_id,
            payment_method="RECHNUNG",
            updated_at=_NOW,
        )
    )
    payment = PaymentReminderService(
        reminders,
        orders,
        now=lambda: _NOW,
        today=lambda: _TODAY,
    )
    before = _service(
        inquiries=inquiries,
        orders=orders,
        payment_reminders=reminders,
    ).list_tasks()
    assert any(row.title == "Rechnung in der Buchhaltung erstellen" for row in before)

    payment.change_payment_method(
        order.order_id,
        new_payment_method="BAR_VOR_ORT",
        reason="Barzahlung vereinbart",
        actor_reference="Alice",
    )

    after = _service(
        inquiries=inquiries,
        orders=orders,
        payment_reminders=reminders,
    ).list_tasks()
    payment_row = next(row for row in after if row.category == "payment")
    assert payment_row.title == "Quittung vorbereiten/drucken"
    assert not any(
        row.title == "Rechnung in der Buchhaltung erstellen" for row in after
    )
    history = payment.view(order.order_id).method_changes
    assert history[0].retired_task_title == "Rechnung in der Buchhaltung erstellen"


def test_sort_overdue_payment_before_verify() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    reminders = InMemoryPaymentReminderRepository()
    _save_inquiry(
        inquiries,
        call_verification_required=True,
        call_verification_status="pending",
    )
    order, _version = seed_order(
        orders, _save_inquiry(inquiries, location_text="Second")
    )
    reminders.save(
        OrderPaymentReminder(
            order_id=order.order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-9",
            sent_on=date(2026, 6, 1),
            due_on=date(2026, 7, 1),
            updated_at=_NOW,
        )
    )
    rows = _service(
        inquiries=inquiries,
        orders=orders,
        payment_reminders=reminders,
    ).list_tasks()
    assert rows[0].category == "payment"
    assert rows[0].urgency == "overdue"
    assert rows[1].category == "verify"


def test_work_center_open_tasks_matches_projection_count() -> None:
    inquiries = InMemoryInquiryRepository()
    _save_inquiry(
        inquiries,
        call_verification_required=True,
        call_verification_status="pending",
    )
    task_service = _service(inquiries=inquiries)
    snapshot = WorkCenterService(
        inquiries,
        InMemoryOfferRepository(),
        InMemoryOrderRepository(),
        today=lambda: _TODAY,
        task_projection_service=task_service,
    ).snapshot()
    assert snapshot.open_tasks == len(task_service.list_tasks()) == 1

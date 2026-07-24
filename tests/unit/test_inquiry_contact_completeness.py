"""INQUIRY_CONTACT_COMPLETENESS_V1 — domain, intake rules, gates, API, UI."""

from __future__ import annotations

import sys
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from catering_system.domain.inquiry import (
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
    derive_inquiry_office_state,
)
from catering_system.domain.inquiry_contact_completeness import (
    complete_inquiry_contact_information,
    contact_completeness_blocker_text,
    derive_contact_completeness,
    derive_inquiry_contact_completeness,
    inquiry_contact_complete,
    missing_contact_fields,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot,
    snapshot_from_structured_contact,
)
from catering_system.domain.progression_blockers import (
    evaluate_inquiry_to_order_progression,
)
from catering_system.intake.email_adapter import intake_from_email
from catering_system.intake.manual_adapter import intake_from_manual
from catering_system.intake.phone_adapter import intake_from_phone
from catering_system.intake.website_form_adapter import intake_from_website_form
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.offer_service import OfferService
from catering_system.services.order_service import OrderService

_NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_TODAY = date(2026, 7, 1)
# after the shared _valid_snapshot's snapshot_created_at (2026-07-15T08:30Z)
_SENT_AT = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
_OFFER_TODAY = date(2026, 7, 16)

_COMPLETE = InquiryCustomerSnapshot(email="kunde@example.com", phone="+49301234567")


def _inquiry(**overrides: object) -> Inquiry:
    base: dict[str, object] = dict(
        inquiry_id=str(uuid.uuid4()),
        event_date=date(2026, 9, 1),
        created_at=_NOW,
        updated_at=_NOW,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
        customer_snapshot=_COMPLETE,
    )
    base.update(overrides)
    return Inquiry(**base)  # type: ignore[arg-type]


def _service(repo: InMemoryInquiryRepository | None = None) -> InquiryService:
    return InquiryService(repo or InMemoryInquiryRepository())


def _create_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = dict(
        event_date=date(2026, 9, 1),
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
    )
    base.update(overrides)
    return base


# --- §12 Domain: completeness states ----------------------------------------


def test_complete_email_and_phone() -> None:
    assert derive_contact_completeness(_COMPLETE) == "complete"
    assert inquiry_contact_complete(_inquiry())


def test_missing_email() -> None:
    snapshot = InquiryCustomerSnapshot(phone="+49301234567")
    assert derive_contact_completeness(snapshot) == "missing_email"
    assert missing_contact_fields("missing_email") == ("email",)


def test_missing_phone() -> None:
    snapshot = InquiryCustomerSnapshot(email="a@b.de")
    assert derive_contact_completeness(snapshot) == "missing_phone"
    assert missing_contact_fields("missing_phone") == ("phone",)


def test_missing_both_and_none_snapshot() -> None:
    assert derive_contact_completeness(None) == "missing_email_and_phone"
    assert (
        derive_contact_completeness(InquiryCustomerSnapshot(contact_name="Alex"))
        == "missing_email_and_phone"
    )
    assert missing_contact_fields("missing_email_and_phone") == ("email", "phone")


def test_blocker_texts_german() -> None:
    assert contact_completeness_blocker_text("missing_email") == "E-Mail-Adresse fehlt"
    assert contact_completeness_blocker_text("missing_phone") == "Telefonnummer fehlt"
    assert (
        contact_completeness_blocker_text("missing_email_and_phone")
        == "E-Mail-Adresse und Telefonnummer fehlen"
    )
    assert contact_completeness_blocker_text("complete") is None


# --- §12 Domain: append-only completion --------------------------------------


def test_append_only_email_completion() -> None:
    inquiry = _inquiry(customer_snapshot=InquiryCustomerSnapshot(phone="+49301234567"))
    updated = complete_inquiry_contact_information(inquiry, email="Neu@Example.com")
    assert updated.customer_snapshot == InquiryCustomerSnapshot(
        email="neu@example.com", phone="+49301234567"
    )


def test_append_only_phone_completion() -> None:
    inquiry = _inquiry(customer_snapshot=InquiryCustomerSnapshot(email="a@b.de"))
    updated = complete_inquiry_contact_information(inquiry, phone="030 99 88 77")
    assert updated.customer_snapshot == InquiryCustomerSnapshot(
        email="a@b.de", phone="+49309988 77".replace(" ", "")
    )


def test_completion_of_both_missing_fields() -> None:
    inquiry = _inquiry(customer_snapshot=None)
    updated = complete_inquiry_contact_information(
        inquiry, email="a@b.de", phone="+49 30 1"
    )
    assert derive_inquiry_contact_completeness(updated) == "complete"


def test_identical_retry_idempotent() -> None:
    inquiry = _inquiry()
    again = complete_inquiry_contact_information(
        inquiry, email="kunde@example.com", phone="+49301234567"
    )
    assert again is inquiry


def test_email_overwrite_rejected() -> None:
    with pytest.raises(ValueError, match="cannot change"):
        complete_inquiry_contact_information(_inquiry(), email="other@example.com")


def test_phone_overwrite_rejected() -> None:
    with pytest.raises(ValueError, match="cannot change"):
        complete_inquiry_contact_information(_inquiry(), phone="+49409999999")


def test_invalid_email_rejected() -> None:
    inquiry = _inquiry(customer_snapshot=None)
    with pytest.raises(ValueError, match="email"):
        complete_inquiry_contact_information(inquiry, email="keine-mail")


def test_invalid_phone_rejected() -> None:
    inquiry = _inquiry(customer_snapshot=None)
    with pytest.raises(ValueError, match="phone"):
        complete_inquiry_contact_information(inquiry, phone="---")


def test_completion_without_values_rejected() -> None:
    with pytest.raises(ValueError, match="requires email or phone"):
        complete_inquiry_contact_information(_inquiry())


def test_name_and_company_unchanged_during_completion() -> None:
    inquiry = _inquiry(
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="ACME", contact_name="Alex", phone="+49301"
        )
    )
    updated = complete_inquiry_contact_information(inquiry, email="a@b.de")
    assert updated.customer_snapshot is not None
    assert updated.customer_snapshot.company_name == "ACME"
    assert updated.customer_snapshot.contact_name == "Alex"


def test_service_completion_persists_and_bumps_updated_at() -> None:
    repo = InMemoryInquiryRepository()
    service = _service(repo)
    created = service.create_inquiry(
        inquiry_source="manual",
        contact_phone="+49301234567",
        **_create_kwargs(),
    )
    updated = service.complete_inquiry_contact_information(
        created.inquiry_id, email="a@b.de"
    )
    stored = repo.get_by_id(created.inquiry_id)
    assert stored is not None
    assert stored.customer_snapshot is not None
    assert stored.customer_snapshot.email == "a@b.de"
    assert updated.updated_at >= created.updated_at


def test_service_completion_idempotent_keeps_updated_at() -> None:
    repo = InMemoryInquiryRepository()
    service = _service(repo)
    created = service.create_inquiry(
        inquiry_source="manual",
        contact_email="a@b.de",
        contact_phone="+49301234567",
        **_create_kwargs(),
    )
    again = service.complete_inquiry_contact_information(
        created.inquiry_id, email="a@b.de"
    )
    assert again.updated_at == created.updated_at


# --- §12 Intake channel rules -------------------------------------------------


def _website_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_date": date(2026, 9, 10),
        "guest_count_estimate": 40,
        "name": "Alex Muster",
        "company": "Musterfirma",
        "email": "info@musterfirma.de",
        "phone": "0151 2345678",
        "message": "Bitte Angebot",
        "submission_id": "web-123",
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def test_website_form_with_email_and_phone_accepted() -> None:
    repo = InMemoryInquiryRepository()
    inquiry = intake_from_website_form(_service(repo), _website_payload())
    assert inquiry.customer_snapshot == InquiryCustomerSnapshot(
        company_name="Musterfirma",
        contact_name="Alex Muster",
        email="info@musterfirma.de",
        phone="+491512345678",
    )
    assert derive_inquiry_contact_completeness(inquiry) == "complete"


def test_website_form_without_email_rejected_nothing_saved() -> None:
    repo = InMemoryInquiryRepository()
    with pytest.raises(ValueError, match="requires email and phone"):
        intake_from_website_form(_service(repo), _website_payload(email=None))
    assert repo.list_all() == []


def test_website_form_without_phone_rejected_nothing_saved() -> None:
    repo = InMemoryInquiryRepository()
    with pytest.raises(ValueError, match="requires email and phone"):
        intake_from_website_form(_service(repo), _website_payload(phone=None))
    assert repo.list_all() == []


def test_website_form_invalid_email_rejected() -> None:
    repo = InMemoryInquiryRepository()
    with pytest.raises(ValueError):
        intake_from_website_form(_service(repo), _website_payload(email="keine-mail"))
    assert repo.list_all() == []


def test_configurator_with_both_accepted() -> None:
    service = _service()
    inquiry = service.create_inquiry(
        inquiry_source="configurator",
        contact_email="a@b.de",
        contact_phone="+49301234567",
        **_create_kwargs(),
    )
    assert derive_inquiry_contact_completeness(inquiry) == "complete"


def test_configurator_missing_email_rejected() -> None:
    repo = InMemoryInquiryRepository()
    with pytest.raises(ValueError, match="requires email and phone"):
        _service(repo).create_inquiry(
            inquiry_source="configurator",
            contact_phone="+49301234567",
            **_create_kwargs(),
        )
    assert repo.list_all() == []


def test_configurator_missing_phone_rejected() -> None:
    repo = InMemoryInquiryRepository()
    with pytest.raises(ValueError, match="requires email and phone"):
        _service(repo).create_inquiry(
            inquiry_source="configurator",
            contact_email="a@b.de",
            **_create_kwargs(),
        )
    assert repo.list_all() == []


def test_email_intake_creates_missing_phone_inquiry() -> None:
    service = _service()
    inquiry = intake_from_email(
        service,
        {
            "event_date": date(2026, 9, 10),
            "from": "kunde@example.com",
            "subject": "Anfrage",
            "body_text": "Hallo",
        },
    )
    assert derive_inquiry_contact_completeness(inquiry) == "missing_phone"
    state = derive_inquiry_office_state(
        replace(inquiry, call_verification_required=False),
        has_order=False,
        has_active_order=False,
        today=_TODAY,
    )
    assert state.next_action != "convert"


def test_phone_intake_creates_missing_email_inquiry() -> None:
    service = _service()
    inquiry = intake_from_phone(
        service,
        {
            "event_date": date(2026, 9, 10),
            "contact_phone": "030 555 666",
            "call_notes": "Rückruf morgen",
        },
    )
    assert derive_inquiry_contact_completeness(inquiry) == "missing_email"


def test_manual_intake_may_create_incomplete_inquiry() -> None:
    service = _service()
    inquiry = intake_from_manual(service, {"event_date": date(2026, 9, 10)})
    assert derive_inquiry_contact_completeness(inquiry) == "missing_email_and_phone"


def test_structured_snapshot_from_structured_input_wins_over_labels() -> None:
    snapshot = snapshot_from_structured_contact(
        contact_email="Structured@Example.com",
        contact_phone="030 111",
        intake_message="E-Mail: label@example.com\nTelefon: 040 999",
    )
    assert snapshot == InquiryCustomerSnapshot(
        email="structured@example.com", phone="+4930111"
    )


def test_structured_snapshot_falls_back_to_labels_per_field() -> None:
    snapshot = snapshot_from_structured_contact(
        contact_phone="030 111",
        intake_message="Firma: ACME\nE-Mail: label@example.com",
    )
    assert snapshot == InquiryCustomerSnapshot(
        company_name="ACME", email="label@example.com", phone="+4930111"
    )


# --- §12 Gates ----------------------------------------------------------------


def _offer_world(inquiry: Inquiry):  # noqa: ANN202
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    offers = InMemoryOfferRepository()
    orders = InMemoryOrderRepository()
    service = OfferService(offers, inquiries, orders, today=lambda: _OFFER_TODAY)
    return inquiries, offers, orders, service


def _snapshot_payload(inquiry_id: str) -> dict[str, object]:
    from tests.unit.test_offer_service import _valid_snapshot

    return _valid_snapshot(inquiry_id=inquiry_id)


def test_incomplete_inquiry_cannot_prepare_offer() -> None:
    inquiry = _inquiry(customer_snapshot=None)
    _inqs, _offers, _orders, service = _offer_world(inquiry)
    with pytest.raises(ValueError, match="contact information incomplete"):
        service.prepare_offer_version(
            inquiry.inquiry_id, _snapshot_payload(inquiry.inquiry_id)
        )


def test_incomplete_inquiry_cannot_mark_offer_sent() -> None:
    inquiry = _inquiry()
    inquiries, _offers, _orders, service = _offer_world(inquiry)
    offer = service.prepare_offer_version(
        inquiry.inquiry_id, _snapshot_payload(inquiry.inquiry_id)
    )
    # Simulate a legacy inquiry that lost its contacts before send.
    inquiries.update(replace(inquiry, customer_snapshot=None))
    with pytest.raises(ValueError, match="contact information incomplete"):
        service.record_sent_evidence(
            offer.offer_id,
            offer.versions[0].offer_version_id,
            sent_at=_SENT_AT,
            channel="email",
            recipient_reference="kunde",
            evidence_reference="mail-1",
            recorded_by="office",
        )


def test_incomplete_inquiry_cannot_record_acceptance() -> None:
    inquiry = _inquiry()
    inquiries, _offers, _orders, service = _offer_world(inquiry)
    offer = service.prepare_offer_version(
        inquiry.inquiry_id, _snapshot_payload(inquiry.inquiry_id)
    )
    version = offer.versions[0]
    service.record_sent_evidence(
        offer.offer_id,
        version.offer_version_id,
        sent_at=_SENT_AT,
        channel="email",
        recipient_reference="kunde",
        evidence_reference="mail-1",
        recorded_by="office",
    )
    inquiries.update(replace(inquiry, customer_snapshot=None))
    with pytest.raises(ValueError, match="contact information incomplete"):
        service.record_acceptance_evidence(
            offer.offer_id,
            version.offer_version_id,
            version.variants[0].variant_id,
            accepted_at=_SENT_AT,
            channel="email",
            evidence_reference="mail-2",
            recorded_by="office",
        )


def test_incomplete_inquiry_cannot_convert_accepted_offer() -> None:
    inquiry = _inquiry()
    inquiries, _offers, _orders, service = _offer_world(inquiry)
    offer = service.prepare_offer_version(
        inquiry.inquiry_id, _snapshot_payload(inquiry.inquiry_id)
    )
    version = offer.versions[0]
    service.record_sent_evidence(
        offer.offer_id,
        version.offer_version_id,
        sent_at=_SENT_AT,
        channel="email",
        recipient_reference="kunde",
        evidence_reference="mail-1",
        recorded_by="office",
    )
    accepted = service.record_acceptance_evidence(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        accepted_at=_SENT_AT,
        channel="email",
        evidence_reference="mail-2",
        recorded_by="office",
    )
    assert accepted.acceptance_evidence is not None
    inquiries.update(replace(inquiry, customer_snapshot=None))
    with pytest.raises(ValueError, match="contact information incomplete"):
        service.convert_accepted_offer(
            offer.offer_id,
            version.offer_version_id,
            version.variants[0].variant_id,
            accepted.acceptance_evidence.acceptance_id,
        )


def test_existing_conversion_replay_not_blocked_retroactively() -> None:
    inquiry = _inquiry()
    inquiries, _offers, _orders, service = _offer_world(inquiry)
    offer = service.prepare_offer_version(
        inquiry.inquiry_id, _snapshot_payload(inquiry.inquiry_id)
    )
    version = offer.versions[0]
    service.record_sent_evidence(
        offer.offer_id,
        version.offer_version_id,
        sent_at=_SENT_AT,
        channel="email",
        recipient_reference="kunde",
        evidence_reference="mail-1",
        recorded_by="office",
    )
    accepted = service.record_acceptance_evidence(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        accepted_at=_SENT_AT,
        channel="email",
        evidence_reference="mail-2",
        recorded_by="office",
    )
    assert accepted.acceptance_evidence is not None
    acceptance_id = accepted.acceptance_evidence.acceptance_id
    _offer1, order1, _v1 = service.convert_accepted_offer(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        acceptance_id,
    )
    # Even if the snapshot were emptied afterwards, the replay stays served.
    inquiries.update(replace(inquiry, customer_snapshot=None))
    _offer2, order2, _v2 = service.convert_accepted_offer(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        acceptance_id,
    )
    assert order2.order_id == order1.order_id


def test_incomplete_inquiry_cannot_direct_convert() -> None:
    inquiry = _inquiry(customer_snapshot=InquiryCustomerSnapshot(email="a@b.de"))
    svc = OrderService(InMemoryOrderRepository())
    with pytest.raises(ValueError, match="accepted offer required"):
        svc.convert_inquiry_to_order(inquiry)


def test_complete_inquiry_still_requires_accepted_offer() -> None:
    svc = OrderService(InMemoryOrderRepository())
    with pytest.raises(ValueError, match="accepted offer required"):
        svc.convert_inquiry_to_order(_inquiry())


def test_office_state_hides_convert_for_incomplete_inquiry() -> None:
    incomplete = _inquiry(customer_snapshot=None)
    state = derive_inquiry_office_state(
        incomplete, has_order=False, has_active_order=False, today=_TODAY
    )
    assert state.next_action is None
    complete_state = derive_inquiry_office_state(
        _inquiry(), has_order=False, has_active_order=False, today=_TODAY
    )
    assert complete_state.next_action == "prepare-offer"


def test_progression_reasons_include_contact_blockers() -> None:
    evaluation = evaluate_inquiry_to_order_progression(_inquiry(customer_snapshot=None))
    assert evaluation.blocked
    assert "inquiry_contact_missing_email_and_phone" in evaluation.reasons
    only_email = evaluate_inquiry_to_order_progression(
        _inquiry(customer_snapshot=InquiryCustomerSnapshot(email="a@b.de"))
    )
    assert only_email.reasons == ("inquiry_contact_missing_phone",)
    assert not evaluate_inquiry_to_order_progression(_inquiry()).blocked


def test_existing_verification_gate_still_applies() -> None:
    inquiry = _inquiry(
        call_verification_required=True,
        call_verification_status="pending",
    )
    svc = OrderService(InMemoryOrderRepository())
    with pytest.raises(ValueError, match="accepted offer required"):
        svc.convert_inquiry_to_order(inquiry)
    evaluation = evaluate_inquiry_to_order_progression(inquiry)
    assert "inquiry_call_verification_unsatisfied" in evaluation.reasons


def test_existing_order_unaffected_by_incomplete_source_inquiry() -> None:
    from tests.helpers.order_seed import seed_order

    orders = InMemoryOrderRepository()
    order, _version = seed_order(orders, _inquiry())
    # The stored Order keeps working even when the source inquiry is later
    # seen without contacts — no Order/OrderVersion schema fields involved.
    loaded = orders.get_order(order.order_id)
    assert loaded is not None
    assert loaded.cancelled_at is None


def test_crm_stage_not_changed_by_completion() -> None:
    repo = InMemoryInquiryRepository()
    service = _service(repo)
    created = service.create_inquiry(
        inquiry_source="manual",
        contact_phone="+49301234567",
        **_create_kwargs(),
    )
    updated = service.complete_inquiry_contact_information(
        created.inquiry_id, email="a@b.de"
    )
    assert updated.crm_stage == created.crm_stage
    assert updated.customer_id is None


# --- §12 Regression: persistence ---------------------------------------------


def test_sqlite_round_trip_and_legacy_null_snapshot(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    complete = _inquiry()
    legacy = _inquiry(customer_snapshot=None)
    repo.save(complete)
    repo.save(legacy)
    loaded_complete = repo.get_by_id(complete.inquiry_id)
    loaded_legacy = repo.get_by_id(legacy.inquiry_id)
    assert loaded_complete is not None
    assert loaded_complete.customer_snapshot == _COMPLETE
    assert loaded_legacy is not None
    assert loaded_legacy.customer_snapshot is None
    assert derive_inquiry_contact_completeness(loaded_legacy) == (
        "missing_email_and_phone"
    )
    repo.close()


def test_latest_inquiry_migration_is_v5() -> None:
    from catering_system.repositories.sqlite_inquiry_repository import _MIGRATIONS

    assert max(number for number, _name, _fn in _MIGRATIONS) == 6


def test_completion_persists_in_sqlite(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    service = InquiryService(repo)
    created = service.create_inquiry(
        inquiry_source="phone_by_office",
        contact_phone="030 44 55",
        **_create_kwargs(),
    )
    service.complete_inquiry_contact_information(created.inquiry_id, email="a@b.de")
    loaded = repo.get_by_id(created.inquiry_id)
    assert loaded is not None
    assert loaded.customer_snapshot == InquiryCustomerSnapshot(
        email="a@b.de", phone="+49304455"
    )
    repo.close()


# --- §12 API: contact-completion endpoint over live HTTP ----------------------


_API_TOKEN = "contact-completeness-test-token"
_API_AUTH = {"Authorization": f"Bearer {_API_TOKEN}"}


def _api_seed(db_path: Path) -> dict[str, str]:
    repo = SQLiteInquiryRepository(db_path)
    service = InquiryService(repo)
    missing_email = service.create_inquiry(
        inquiry_source="phone_by_office",
        contact_phone="+49301234567",
        **_create_kwargs(),
    )
    complete = service.create_inquiry(
        inquiry_source="manual",
        contact_email="voll@example.com",
        contact_phone="+49408887766",
        **_create_kwargs(),
    )
    repo.close()
    return {
        "missing_email": missing_email.inquiry_id,
        "missing_email_updated_at": missing_email.updated_at.isoformat(),
        "complete": complete.inquiry_id,
        "complete_updated_at": complete.updated_at.isoformat(),
    }


@pytest.fixture()
def contact_api(tmp_path: Path):
    import queue
    import threading

    from catering_system.ui.office_api import create_office_api_server

    db = tmp_path / "core.db"
    ids = _api_seed(db)
    ready: queue.Queue = queue.Queue()

    def run() -> None:
        server = create_office_api_server(str(db), _API_TOKEN, "127.0.0.1", 0)
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}", ids
    server.shutdown()
    server.server_close()


def _api_get(url: str, headers: dict | None = None):  # noqa: ANN202
    import json as _json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url, headers=headers if headers is not None else _API_AUTH
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, _json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, _json.loads(exc.read().decode() or "{}")


def _api_complete(
    base: str,
    inquiry_id: str,
    *,
    args: dict,
    expect: dict,
    headers: dict | None = None,
):  # noqa: ANN202
    import json as _json
    import urllib.error
    import urllib.request

    body = _json.dumps(
        {"command_id": str(uuid.uuid4()), "expect": expect, "args": args}
    ).encode()
    all_headers = {"Content-Type": "application/json"}
    all_headers.update(headers if headers is not None else _API_AUTH)
    req = urllib.request.Request(
        f"{base}/office/v1/inquiries/{inquiry_id}/contact-completion",
        data=body,
        headers=all_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, _json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, _json.loads(exc.read().decode() or "{}")


def test_api_contact_completion_success_removes_blocker(contact_api) -> None:
    base, ids = contact_api
    inquiry_id = ids["missing_email"]
    status, detail = _api_get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert status == 200
    assert detail["contact_completeness"] == "missing_email"
    assert detail["missing_contact_fields"] == ["email"]
    assert detail["contact_completion_allowed"] is True

    status, body = _api_complete(
        base,
        inquiry_id,
        args={"email": "Nachtrag@Example.com"},
        expect={"updated_at": detail["updated_at"]},
    )
    assert status == 200
    assert body["contact_completeness"] == "complete"
    assert body["missing_contact_fields"] == []

    status, detail = _api_get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert status == 200
    assert detail["contact_completeness"] == "complete"
    assert detail["contact_completion_allowed"] is False
    assert detail["customer_snapshot"]["email"] == "nachtrag@example.com"
    assert detail["customer_snapshot"]["phone"] == "+49301234567"


def test_api_contact_completion_unauthorized(contact_api) -> None:
    base, ids = contact_api
    status, body = _api_complete(
        base,
        ids["missing_email"],
        args={"email": "a@b.de"},
        expect={"updated_at": ids["missing_email_updated_at"]},
        headers={"Authorization": "Bearer wrong"},
    )
    assert (status, body) == (401, {"error": "unauthorized"})


def test_api_contact_completion_malformed_values(contact_api) -> None:
    base, ids = contact_api
    expect = {"updated_at": ids["missing_email_updated_at"]}
    status, body = _api_complete(
        base, ids["missing_email"], args={"email": "keine-mail"}, expect=expect
    )
    assert (status, body["error"]) == (400, "invalid_contact_value")
    status, body = _api_complete(base, ids["missing_email"], args={}, expect=expect)
    assert (status, body["error"]) == (400, "invalid_request")


def test_api_contact_completion_unknown_inquiry_404(contact_api) -> None:
    base, _ids = contact_api
    status, body = _api_complete(
        base,
        str(uuid.uuid4()),
        args={"email": "a@b.de"},
        expect={"updated_at": "2026-07-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (404, "not_found")


def test_api_contact_completion_stale_conflict(contact_api) -> None:
    base, ids = contact_api
    status, body = _api_complete(
        base,
        ids["missing_email"],
        args={"email": "a@b.de"},
        expect={"updated_at": "2020-01-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (409, "stale_state")


def test_api_contact_completion_overwrite_conflict_keeps_state(contact_api) -> None:
    base, ids = contact_api
    inquiry_id = ids["complete"]
    status, before = _api_get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert status == 200
    status, body = _api_complete(
        base,
        inquiry_id,
        args={"email": "anders@example.com"},
        expect={"updated_at": before["updated_at"]},
    )
    assert (status, body["error"]) == (409, "contact_conflict")
    status, after = _api_get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert status == 200
    assert after["customer_snapshot"] == before["customer_snapshot"]
    assert after["updated_at"] == before["updated_at"]


def test_api_contact_completion_identical_value_idempotent(contact_api) -> None:
    base, ids = contact_api
    inquiry_id = ids["complete"]
    status, before = _api_get(f"{base}/office/v1/inquiries/{inquiry_id}")
    status, body = _api_complete(
        base,
        inquiry_id,
        args={"email": "voll@example.com"},
        expect={"updated_at": before["updated_at"]},
    )
    assert status == 200
    assert body["contact_completeness"] == "complete"


def test_service_completion_does_not_log_contact_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    repo = InMemoryInquiryRepository()
    service = _service(repo)
    created = service.create_inquiry(
        inquiry_source="manual",
        contact_phone="+49301234599",
        **_create_kwargs(),
    )
    service.complete_inquiry_contact_information(
        created.inquiry_id, email="geheim@example.com"
    )
    assert "geheim@example.com" not in caplog.text
    assert "+49301234599" not in caplog.text


# --- §12 UI: Kontaktdaten block in the Office Panel ---------------------------


def _panel_detail(inquiry: Inquiry, *, ui_version: str = "legacy") -> str:
    from catering_system.repositories.in_memory_order_repository import (
        InMemoryOrderRepository as _Orders,
    )
    from catering_system.ui.office_panel import OfficePanel

    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    panel = OfficePanel(inquiries, _Orders(), ui_version=ui_version)
    html = panel.render_inquiry(inquiry.inquiry_id)
    assert html is not None
    return html


def test_ui_missing_email_state() -> None:
    html = _panel_detail(
        _inquiry(customer_snapshot=InquiryCustomerSnapshot(phone="+49301234567"))
    )
    assert "Kontaktdaten" in html
    assert "E-Mail-Adresse fehlt" in html
    assert "Kontaktdaten vervollständigen" in html
    assert "Kontaktdaten ergänzen" in html
    assert 'name="contact_email"' in html
    assert 'name="contact_phone"' not in html
    assert "+49301234567" in html


def test_ui_missing_phone_state() -> None:
    html = _panel_detail(
        _inquiry(customer_snapshot=InquiryCustomerSnapshot(email="a@b.de"))
    )
    assert "Telefonnummer fehlt" in html
    assert 'name="contact_phone"' in html
    assert 'name="contact_email"' not in html
    assert "a@b.de" in html


def test_ui_missing_both_state() -> None:
    html = _panel_detail(_inquiry(customer_snapshot=None))
    assert "E-Mail-Adresse und Telefonnummer fehlen" in html
    assert 'name="contact_email"' in html
    assert 'name="contact_phone"' in html


def test_ui_complete_state_has_no_contact_blocker() -> None:
    html = _panel_detail(_inquiry())
    assert "Kontaktdaten vollständig" in html
    assert "Kontaktdaten ergänzen" not in html
    assert "E-Mail-Adresse fehlt" not in html


def test_ui_v2_contact_card_states() -> None:
    html = _panel_detail(
        _inquiry(customer_snapshot=InquiryCustomerSnapshot(phone="+49301234567")),
        ui_version="v2",
    )
    assert "Kontaktdaten" in html
    assert "E-Mail-Adresse fehlt" in html
    assert "Kontaktdaten ergänzen" in html
    assert 'name="contact_email"' in html
    complete_html = _panel_detail(_inquiry(), ui_version="v2")
    assert "Kontaktdaten vollständig" in complete_html
    assert "Kontaktdaten ergänzen" not in complete_html


def test_ui_list_shows_calm_contact_badge() -> None:
    from catering_system.repositories.in_memory_order_repository import (
        InMemoryOrderRepository as _Orders,
    )
    from catering_system.ui.office_panel import OfficePanel

    inquiries = InMemoryInquiryRepository()
    inquiries.save(_inquiry(customer_snapshot=None))
    panel = OfficePanel(inquiries, _Orders())
    html = panel.render_anfragen()
    assert '<span class="blocked">Kontaktdaten fehlen</span>' in html
    inquiries_ok = InMemoryInquiryRepository()
    inquiries_ok.save(_inquiry())
    panel_ok = OfficePanel(inquiries_ok, _Orders())
    assert "Kontaktdaten fehlen" not in panel_ok.render_anfragen()


def test_ui_panel_completion_roundtrip() -> None:
    from catering_system.repositories.in_memory_order_repository import (
        InMemoryOrderRepository as _Orders,
    )
    from catering_system.ui.office_panel import OfficePanel

    inquiries = InMemoryInquiryRepository()
    inquiry = _inquiry(customer_snapshot=InquiryCustomerSnapshot(phone="+49301234567"))
    inquiries.save(inquiry)
    panel = OfficePanel(inquiries, _Orders())
    updated = panel.complete_inquiry_contacts(
        inquiry.inquiry_id, {"contact_email": "neu@example.com", "contact_phone": ""}
    )
    assert updated.customer_snapshot == InquiryCustomerSnapshot(
        email="neu@example.com", phone="+49301234567"
    )
    html = panel.render_inquiry(inquiry.inquiry_id)
    assert html is not None
    assert "Kontaktdaten vollständig" in html

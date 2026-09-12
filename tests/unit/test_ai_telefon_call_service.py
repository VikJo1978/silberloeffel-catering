from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.services.ai_telefon_call_service import (
    AiTelefonCallCannotConvert,
    AiTelefonCallService,
)
from catering_system.services.inquiry_service import InquiryService


def _service(tmp_path):
    db = tmp_path / "core.sqlite3"
    call_repo = SQLiteAiTelefonCallRepository(db)
    inquiry_repo = SQLiteInquiryRepository(db)
    now = datetime(2026, 9, 10, 18, 0, tzinfo=UTC)
    service = AiTelefonCallService(
        call_repo,
        inquiry_repository=inquiry_repo,
        inquiry_service=InquiryService(inquiry_repo),
        now=lambda: now,
    )
    return service, call_repo, inquiry_repo


def test_ingest_is_idempotent_by_strato_id(tmp_path) -> None:
    service, call_repo, inquiry_repo = _service(tmp_path)
    try:
        first = service.ingest(
            strato_id="07a45b4c-68e4-424e-a670-372c3d50df92",
            gmail_message_id="1a08c74d9191a5be",
            caller_phone="+4917642795029",
            contact_name="Viktor Merkel",
            email="",
            subject="Catering-Anfrage",
            summary="Geburtstagsfeier für 100 Personen.",
            raw_message="raw",
            event_type="Geburtstag",
            event_date=date(2027, 1, 12),
            event_start=time(16, 45),
            guest_count=100,
            location="Brooks Heide 3, 22549 Hamburg",
            budget_per_person_cents=3000,
        )
        replay = service.ingest(
            strato_id="07a45b4c-68e4-424e-a670-372c3d50df92",
            gmail_message_id="different-gmail-id",
            caller_phone="+4917642795029",
            contact_name="Viktor Merkel",
            email="",
            subject="ignored replay",
            summary="ignored replay",
            raw_message="ignored replay",
        )

        assert replay.call_id == first.call_id
        assert service.count_new() == 1
    finally:
        call_repo.close()
        inquiry_repo.close()


def test_full_call_converts_to_existing_inquiry_model(tmp_path) -> None:
    service, call_repo, inquiry_repo = _service(tmp_path)
    try:
        call = service.ingest(
            strato_id="07a45b4c-68e4-424e-a670-372c3d50df92",
            gmail_message_id="1a08c74d9191a5be",
            caller_phone="+4917642795029",
            contact_name="Viktor Merkel",
            email="",
            subject="Catering-Anfrage für Geburtstagsfeier am 12.01.2027",
            summary="100 Personen, 30 Euro pro Person, griechisches Buffet.",
            raw_message="raw",
            event_type="Geburtstag",
            event_date=date(2027, 1, 12),
            event_start=time(16, 45),
            guest_count=100,
            location="Brooks Heide 3, 22549 Hamburg",
            budget_per_person_cents=3000,
            customer_request="griechisches Buffet",
            callback_requested=True,
            callback_time=time(13, 20),
        )

        processed = service.convert_to_inquiry(call.call_id)

        assert processed.status == "PROCESSED"
        assert processed.result_type == "INQUIRY"
        assert processed.result_id is not None
        inquiry = inquiry_repo.get_by_id(processed.result_id)
        assert inquiry is not None
        assert inquiry.inquiry_source == "ai_telefonist"
        assert inquiry.event_date == date(2027, 1, 12)
        assert inquiry.event_start_local == time(16, 45)
        assert inquiry.guest_count_estimate == 100
        assert inquiry.location_text == "Brooks Heide 3, 22549 Hamburg"
        assert inquiry.intake_external_ref == call.strato_id
        assert inquiry.customer_snapshot is not None
        assert inquiry.customer_snapshot.contact_name == "Viktor Merkel"
        assert inquiry.customer_snapshot.phone == "+4917642795029"
    finally:
        call_repo.close()
        inquiry_repo.close()


def test_consultation_without_exact_date_stays_in_inbox(tmp_path) -> None:
    service, call_repo, inquiry_repo = _service(tmp_path)
    try:
        call = service.ingest(
            strato_id="c2131d3d-895b-450d-873b-c9d26582556c",
            gmail_message_id="1a08c86a7c385199",
            caller_phone="+4917642795029",
            contact_name="Viktor Jochenson",
            email="",
            subject="Beratung für privates Catering im Januar",
            summary="Ca. 60 Personen, kein konkretes Datum.",
            raw_message="raw",
            event_period="Januar",
            guest_count=60,
            customer_request="Ohne Schweinefleisch, vegetarische Optionen",
            callback_requested=True,
        )

        with pytest.raises(AiTelefonCallCannotConvert, match="event_date_required"):
            service.convert_to_inquiry(call.call_id)

        stored = service.get(call.call_id)
        assert stored is not None
        assert stored.status == "NEW"
        assert stored.event_date is None
    finally:
        call_repo.close()
        inquiry_repo.close()

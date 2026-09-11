from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, time, timezone, timedelta
from types import SimpleNamespace

import pytest

from catering_system.domain.ai_telefon_call import (
    AiTelefonCall,
    validate_ai_telefon_call,
    validate_ai_telefon_call_linked_type,
    validate_ai_telefon_call_result_type,
    validate_ai_telefon_call_status,
)
from catering_system.intake.strato_summary_email import (
    llm_extraction_contract,
    parse_strato_summary_mail,
    structured_call_facts_from_mapping,
)
from catering_system.repositories.ai_telefon_call_repository import (
    DuplicateAiTelefonCallError,
)
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

_CALL_ID = "8e5d6ac1-1a43-49b0-8803-d76ac86a9666"
_RESULT_ID = "88d2656a-f17c-4686-9f91-b6b9bad20a7c"
_NOW = datetime(2026, 9, 10, 18, 0, tzinfo=UTC)


def _valid_call(**changes: object) -> AiTelefonCall:
    values: dict[str, object] = {
        "call_id": _CALL_ID,
        "strato_id": "strato-1",
        "gmail_message_id": "gmail-1",
        "caller_phone": "+4917642795029",
        "contact_name": "Viktor Merkel",
        "email": "",
        "subject": "Catering-Anfrage",
        "summary": "Geburtstagsfeier für 100 Personen.",
        "raw_message": "raw",
        "event_type": "Geburtstag",
        "event_date": date(2027, 1, 12),
        "event_period": "Januar 2027",
        "event_start": time(16, 45),
        "guest_count": 100,
        "location": "Hamburg",
        "budget_per_person_cents": 3000,
        "fulfillment_mode": "UNKNOWN",
        "customer_request": "griechisches Buffet",
        "callback_requested": True,
        "callback_date": date(2026, 9, 11),
        "callback_time": time(13, 20),
        "status": "NEW",
        "result_type": None,
        "result_id": None,
        "linked_type": None,
        "linked_id": None,
        "received_at": _NOW,
        "processed_at": None,
        "updated_at": _NOW,
    }
    values.update(changes)
    return AiTelefonCall(**values)  # type: ignore[arg-type]


def _configured_service(tmp_path):
    db = tmp_path / "core.sqlite3"
    call_repo = SQLiteAiTelefonCallRepository(db)
    inquiry_repo = SQLiteInquiryRepository(db)
    service = AiTelefonCallService(
        call_repo,
        inquiry_repository=inquiry_repo,
        inquiry_service=InquiryService(inquiry_repo),
        now=lambda: _NOW,
        id_factory=lambda: _CALL_ID,
    )
    return service, call_repo, inquiry_repo


def test_domain_enum_validators_reject_unknown_values() -> None:
    assert validate_ai_telefon_call_status("NEW") == "NEW"
    assert validate_ai_telefon_call_result_type("TASK") == "TASK"
    assert validate_ai_telefon_call_linked_type("OFFER") == "OFFER"

    with pytest.raises(ValueError, match="status must be one of"):
        validate_ai_telefon_call_status("BROKEN")
    with pytest.raises(ValueError, match="result_type must be one of"):
        validate_ai_telefon_call_result_type("BROKEN")
    with pytest.raises(ValueError, match="linked_type must be one of"):
        validate_ai_telefon_call_linked_type("BROKEN")


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"guest_count": True}, TypeError),
        ({"guest_count": 0}, ValueError),
        ({"budget_per_person_cents": True}, TypeError),
        ({"budget_per_person_cents": 10_000_001}, ValueError),
        ({"callback_requested": "yes"}, TypeError),
        ({"updated_at": _NOW - timedelta(seconds=1)}, ValueError),
        (
            {
                "status": "PROCESSED",
                "processed_at": _NOW - timedelta(seconds=1),
            },
            ValueError,
        ),
        ({"result_type": "TASK", "result_id": None}, ValueError),
        ({"result_type": None, "result_id": _RESULT_ID}, ValueError),
        ({"linked_type": "OFFER", "linked_id": None}, ValueError),
        ({"linked_type": None, "linked_id": _RESULT_ID}, ValueError),
        (
            {
                "status": "NEW",
                "result_type": "TASK",
                "result_id": _RESULT_ID,
            },
            ValueError,
        ),
        ({"status": "PROCESSED", "processed_at": None}, ValueError),
        ({"event_start": "16:45"}, TypeError),
        ({"event_start": time(16, 45, tzinfo=timezone.utc)}, ValueError),
    ],
)
def test_domain_validation_rejects_invalid_state(
    changes: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        validate_ai_telefon_call(_valid_call(**changes))


def test_domain_validation_rejects_bad_ids_and_datetimes() -> None:
    with pytest.raises(TypeError):
        validate_ai_telefon_call(_valid_call(call_id=123))
    with pytest.raises(ValueError):
        validate_ai_telefon_call(_valid_call(call_id="not-a-uuid"))
    with pytest.raises(ValueError):
        validate_ai_telefon_call(
            _valid_call(call_id="8e5d6ac1-1a43-39b0-8803-d76ac86a9666")
        )
    with pytest.raises(ValueError):
        validate_ai_telefon_call(_valid_call(received_at=None))
    with pytest.raises(ValueError):
        validate_ai_telefon_call(
            _valid_call(received_at=datetime(2026, 9, 10, 18, 0))
        )
    with pytest.raises(TypeError):
        validate_ai_telefon_call(_valid_call(contact_name=123))


def test_domain_validation_accepts_processed_link() -> None:
    call = validate_ai_telefon_call(
        _valid_call(
            status="PROCESSED",
            result_type="LINKED",
            result_id=_RESULT_ID,
            linked_type="OFFER",
            linked_id=_RESULT_ID,
            processed_at=_NOW,
        )
    )

    assert call.status == "PROCESSED"
    assert call.linked_type == "OFFER"


@pytest.mark.parametrize("raw", [123, None])
def test_strato_parser_rejects_non_text(raw: object) -> None:
    with pytest.raises(TypeError):
        parse_strato_summary_mail(raw)  # type: ignore[arg-type]


def test_strato_parser_rejects_empty_and_required_fields() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_strato_summary_mail("   ")
    with pytest.raises(ValueError, match="Zusammenfassung"):
        parse_strato_summary_mail("ID: x")
    with pytest.raises(ValueError, match="ID"):
        parse_strato_summary_mail("Zusammenfassung: Test")


def test_strato_parser_uses_caller_as_phone_fallback() -> None:
    parsed = parse_strato_summary_mail(
        "Anrufer: +49 176 42795029\nZusammenfassung: Test\nID: id-1"
    )

    assert parsed.phone == "+4917642795029"
    assert parsed.name == ""


def test_llm_contract_and_typed_values() -> None:
    contract = llm_extraction_contract()
    assert contract["event_date"] is None
    assert contract["fulfillment_mode"] == "UNKNOWN"

    facts = structured_call_facts_from_mapping(
        {
            "event_date": date(2027, 1, 12),
            "event_start": time(16, 45),
            "guest_count": "60",
            "budget_per_person_cents": "3000",
            "fulfillment_mode": "delivery",
            "callback_requested": False,
        }
    )
    assert facts.event_date == date(2027, 1, 12)
    assert facts.event_start == time(16, 45)
    assert facts.guest_count == 60
    assert facts.budget_per_person_cents == 3000
    assert facts.fulfillment_mode == "DELIVERY"
    assert facts.callback_requested is False


@pytest.mark.parametrize(
    "mapping",
    [
        {"event_date": 1},
        {"event_date": "12.01.2027"},
        {"event_start": 1},
        {"event_start": "99:00"},
        {"event_start": time(16, 45, tzinfo=timezone.utc)},
        {"guest_count": True},
        {"guest_count": "x"},
        {"guest_count": 0},
        {"budget_per_person": True},
        {"budget_per_person": "x"},
        {"budget_per_person": -1},
        {"fulfillment_mode": 1},
        {"fulfillment_mode": "DRONE"},
        {"callback_requested": "yes"},
        {"event_type": 1},
    ],
)
def test_llm_fact_validation_rejects_invalid_values(
    mapping: dict[str, object]
) -> None:
    with pytest.raises((TypeError, ValueError)):
        structured_call_facts_from_mapping(mapping)


def test_llm_fact_validation_requires_mapping() -> None:
    with pytest.raises(TypeError):
        structured_call_facts_from_mapping([])  # type: ignore[arg-type]


def test_repository_update_missing_and_shared_connection() -> None:
    connection = sqlite3.connect(":memory:")
    repo = SQLiteAiTelefonCallRepository.from_connection(connection)
    try:
        assert repo.list_recent(limit=0) == []
        assert repo.get(_CALL_ID) is None
        with pytest.raises(KeyError):
            repo.update(validate_ai_telefon_call(_valid_call()))
    finally:
        connection.close()


def test_repository_duplicate_gmail_id_is_rejected(tmp_path) -> None:
    repo = SQLiteAiTelefonCallRepository(tmp_path / "core.sqlite3")
    try:
        repo.save(validate_ai_telefon_call(_valid_call()))
        duplicate = validate_ai_telefon_call(
            _valid_call(
                call_id=_RESULT_ID,
                strato_id="strato-2",
                gmail_message_id="gmail-1",
            )
        )
        with pytest.raises(DuplicateAiTelefonCallError):
            repo.save(duplicate)
    finally:
        repo.close()


def test_service_deduplicates_by_gmail_message_id(tmp_path) -> None:
    service, call_repo, inquiry_repo = _configured_service(tmp_path)
    try:
        first = service.ingest(
            strato_id="strato-1",
            gmail_message_id="gmail-1",
            caller_phone="+4917642795029",
            contact_name="Viktor Merkel",
            email="",
            subject="Test",
            summary="Test",
            raw_message="raw",
        )
        second = service.ingest(
            strato_id="strato-2",
            gmail_message_id="gmail-1",
            caller_phone="+4917642795029",
            contact_name="Viktor Merkel",
            email="",
            subject="Anders",
            summary="Anders",
            raw_message="raw",
        )
        assert second.call_id == first.call_id
    finally:
        call_repo.close()
        inquiry_repo.close()


def test_service_mark_done_is_idempotent_and_missing_call_raises(tmp_path) -> None:
    service, call_repo, inquiry_repo = _configured_service(tmp_path)
    try:
        call = service.ingest(
            strato_id="strato-done",
            gmail_message_id="gmail-done",
            caller_phone="",
            contact_name="",
            email="",
            subject="",
            summary="Nur Information",
            raw_message="raw",
        )
        done = service.mark_done(call.call_id)
        assert done.status == "DONE"
        assert service.mark_done(call.call_id) == done

        with pytest.raises(KeyError):
            service.mark_done(_RESULT_ID)
    finally:
        call_repo.close()
        inquiry_repo.close()


def test_service_inquiry_conversion_preconditions(tmp_path) -> None:
    db = tmp_path / "preconditions.sqlite3"
    call_repo = SQLiteAiTelefonCallRepository(db)
    try:
        unconfigured = AiTelefonCallService(
            call_repo,
            now=lambda: _NOW,
            id_factory=lambda: _CALL_ID,
        )
        call = unconfigured.ingest(
            strato_id="strato-unconfigured",
            gmail_message_id="gmail-unconfigured",
            caller_phone="+4917642795029",
            contact_name="Viktor Merkel",
            email="",
            subject="Test",
            summary="Test",
            raw_message="raw",
            event_date=date(2027, 1, 12),
        )
        with pytest.raises(AiTelefonCallCannotConvert, match="not configured"):
            unconfigured.convert_to_inquiry(call.call_id)
    finally:
        call_repo.close()

    service, call_repo, inquiry_repo = _configured_service(tmp_path)
    try:
        no_name = service.ingest(
            strato_id="strato-no-name",
            gmail_message_id="gmail-no-name",
            caller_phone="+4917642795029",
            contact_name="",
            email="",
            subject="Test",
            summary="Test",
            raw_message="raw",
            event_date=date(2027, 1, 12),
        )
        with pytest.raises(AiTelefonCallCannotConvert, match="contact_name_required"):
            service.convert_to_inquiry(no_name.call_id)

        no_phone = service.ingest(
            strato_id="strato-no-phone",
            gmail_message_id="gmail-no-phone",
            caller_phone="",
            contact_name="Viktor Merkel",
            email="",
            subject="Test",
            summary="Test",
            raw_message="raw",
            event_date=date(2027, 1, 12),
        )
        with pytest.raises(AiTelefonCallCannotConvert, match="phone_required"):
            service.convert_to_inquiry(no_phone.call_id)
    finally:
        call_repo.close()
        inquiry_repo.close()


def test_service_inquiry_conversion_carries_optional_context(tmp_path) -> None:
    service, call_repo, inquiry_repo = _configured_service(tmp_path)
    try:
        call = service.ingest(
            strato_id="strato-full",
            gmail_message_id="gmail-full",
            caller_phone="+4917642795029",
            contact_name="Viktor Merkel",
            email="vik@example.invalid",
            subject="Geburtstag",
            summary="Bitte Angebot erstellen.",
            raw_message="raw",
            event_date=date(2027, 1, 12),
            event_period="Januar",
            event_start=time(16, 45),
            guest_count=100,
            budget_per_person_cents=3000,
            customer_request="griechisches Buffet",
            callback_requested=True,
            callback_date=date(2026, 9, 11),
            callback_time=time(13, 20),
        )
        processed = service.convert_to_inquiry(call.call_id)
        repeated = service.convert_to_inquiry(call.call_id)

        assert repeated == processed
        assert processed.result_id is not None
        inquiry = inquiry_repo.get_by_id(processed.result_id)
        assert inquiry is not None
        assert "Zeitraum: Januar" in (inquiry.intake_message or "")
        assert "Budget: 30.00 EUR pro Person" in (inquiry.intake_message or "")
        assert "Wünsche: griechisches Buffet" in (inquiry.intake_message or "")
        assert "Rückruf gewünscht am 2026-09-11 um 13:20" in (
            inquiry.intake_message or ""
        )
    finally:
        call_repo.close()
        inquiry_repo.close()


class _FakeTaskService:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def create_task(self, **kwargs: object):
        self.kwargs = kwargs
        return SimpleNamespace(task_id=_RESULT_ID)


def test_service_task_conversion_and_linking(tmp_path) -> None:
    call_repo = SQLiteAiTelefonCallRepository(tmp_path / "tasks.sqlite3")
    fake_tasks = _FakeTaskService()
    service = AiTelefonCallService(
        call_repo,
        manual_task_service=fake_tasks,  # type: ignore[arg-type]
        now=lambda: _NOW,
        id_factory=lambda: _CALL_ID,
    )
    try:
        call = service.ingest(
            strato_id="strato-task",
            gmail_message_id="gmail-task",
            caller_phone="+4917642795029",
            contact_name="Viktor Schmidt",
            email="",
            subject="",
            summary="Gästezahl von 60 auf 70 ändern.",
            raw_message="raw",
        )
        task_result = service.convert_to_task(
            call.call_id,
            created_by_employee_id=_RESULT_ID,
            assigned_to_employee_id=_RESULT_ID,
        )
        assert task_result.result_type == "TASK"
        assert task_result.result_id == _RESULT_ID
        assert fake_tasks.kwargs["title"] == "Telefonanruf: Viktor Schmidt"
        assert "STRATO-ID: strato-task" in str(fake_tasks.kwargs["description"])
        assert service.convert_to_task(
            call.call_id, created_by_employee_id=_RESULT_ID
        ) == task_result

        second = service.ingest(
            strato_id="strato-link",
            gmail_message_id="gmail-link",
            caller_phone="+4917642795029",
            contact_name="Viktor Schmidt",
            email="",
            subject="Änderung Angebot",
            summary="Gästezahl ändern.",
            raw_message="raw",
        )
        linked = service.link_existing(
            second.call_id,
            linked_type="OFFER",
            linked_id=_RESULT_ID,
        )
        assert linked.result_type == "LINKED"
        assert linked.linked_type == "OFFER"
        assert linked.linked_id == _RESULT_ID
    finally:
        call_repo.close()


def test_service_task_conversion_requires_configuration(tmp_path) -> None:
    call_repo = SQLiteAiTelefonCallRepository(tmp_path / "no-tasks.sqlite3")
    service = AiTelefonCallService(
        call_repo,
        now=lambda: _NOW,
        id_factory=lambda: _CALL_ID,
    )
    try:
        call = service.ingest(
            strato_id="strato-no-task-service",
            gmail_message_id="gmail-no-task-service",
            caller_phone="",
            contact_name="",
            email="",
            subject="Test",
            summary="Test",
            raw_message="raw",
        )
        with pytest.raises(AiTelefonCallCannotConvert, match="not configured"):
            service.convert_to_task(call.call_id, created_by_employee_id=_RESULT_ID)
    finally:
        call_repo.close()


class _RaceRepository:
    def __init__(self) -> None:
        self.saved: AiTelefonCall | None = None

    def get(self, call_id: str) -> AiTelefonCall | None:
        return self.saved if self.saved and self.saved.call_id == call_id else None

    def save(self, call: AiTelefonCall) -> None:
        self.saved = call
        raise DuplicateAiTelefonCallError("race")

    def update(self, call: AiTelefonCall) -> None:
        self.saved = call

    def find_by_strato_id(self, strato_id: str) -> AiTelefonCall | None:
        if self.saved and self.saved.strato_id == strato_id:
            return self.saved
        return None

    def find_by_gmail_message_id(self, gmail_message_id: str) -> AiTelefonCall | None:
        if self.saved and self.saved.gmail_message_id == gmail_message_id:
            return self.saved
        return None

    def list_recent(self, *, limit: int = 100) -> list[AiTelefonCall]:
        return [self.saved] if self.saved else []

    def count_new(self) -> int:
        return int(self.saved is not None and self.saved.status == "NEW")


def test_service_handles_duplicate_insert_race() -> None:
    repo = _RaceRepository()
    service = AiTelefonCallService(
        repo,
        now=lambda: _NOW,
        id_factory=lambda: _CALL_ID,
    )

    call = service.ingest(
        strato_id="race-strato",
        gmail_message_id="race-gmail",
        caller_phone="",
        contact_name="",
        email="",
        subject="Test",
        summary="Test",
        raw_message="raw",
    )

    assert call.strato_id == "race-strato"
    assert service.get(call.call_id) == call
    assert service.list_recent() == [call]
    assert service.count_new() == 1

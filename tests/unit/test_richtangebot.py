from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import UUID

from catering_system.domain.ai_telefon_call import (
    AiTelefonCall,
    validate_ai_telefon_call,
)
from catering_system.domain.richtangebot import (
    DEFAULT_RICHTANGEBOT_DISCLAIMER,
    Richtangebot,
    validate_richtangebot,
)
from catering_system.repositories.sqlite_richtangebot_repository import (
    SQLiteRichtangebotRepository,
)
from catering_system.services.richtangebot_service import RichtangebotService


def _uuid(value: int) -> str:
    return str(UUID(int=value, version=4))


def test_richtangebot_accepts_fuzzy_date_time_and_guest_range() -> None:
    now = datetime(2026, 9, 11, 14, 0, tzinfo=UTC)
    value = validate_richtangebot(
        Richtangebot(
            richtangebot_id=_uuid(1),
            source_call_id=_uuid(2),
            created_at=now,
            updated_at=now,
            contact_name="Test Kunde",
            event_type="Taufe",
            event_date_text="im nächsten Jahr",
            event_time_text="noch offen",
            guest_count_min=100,
            guest_count_max=150,
            budget_per_person_cents=4000,
        )
    )

    assert value.event_date is None
    assert value.guest_count is None
    assert value.guest_count_min == 100
    assert value.guest_count_max == 150
    assert "unverbindliche" in value.disclaimer.lower()


def test_richtangebot_repository_roundtrip() -> None:
    connection = sqlite3.connect(":memory:")
    repo = SQLiteRichtangebotRepository.from_connection(connection)
    now = datetime(2026, 9, 11, 14, 0, tzinfo=UTC)
    value = Richtangebot(
        richtangebot_id=_uuid(3),
        source_call_id=_uuid(4),
        created_at=now,
        updated_at=now,
        contact_name="Test Kunde",
        caller_phone="+49123",
        event_type="Taufe",
        event_date_text="2027, Termin offen",
        event_time_text="noch offen",
        guest_count_min=100,
        guest_count_max=150,
        location="Hamburg",
        budget_per_person_cents=4000,
        customer_request="50 % Fingerfood, 50 % Buffet",
    )

    repo.save(value)
    loaded = repo.get(value.richtangebot_id)

    assert loaded is not None
    assert loaded.source_call_id == value.source_call_id
    assert loaded.guest_count_min == 100
    assert loaded.guest_count_max == 150
    assert loaded.disclaimer == DEFAULT_RICHTANGEBOT_DISCLAIMER


def test_service_creates_richtangebot_from_incomplete_ai_call_idempotently() -> None:
    connection = sqlite3.connect(":memory:")
    repo = SQLiteRichtangebotRepository.from_connection(connection)
    now = datetime(2026, 9, 11, 14, 0, tzinfo=UTC)
    service = RichtangebotService(
        repo,
        now=lambda: now,
        id_factory=lambda: _uuid(5),
    )
    call = validate_ai_telefon_call(
        AiTelefonCall(
            call_id=_uuid(6),
            strato_id="strato-test",
            gmail_message_id="gmail-test",
            caller_phone="+49123",
            contact_name="Test Kunde",
            email="",
            subject="Taufe",
            summary="Taufe für 100 bis 150 Personen, Termin noch offen.",
            raw_message="raw",
            event_type="Taufe",
            event_period="im nächsten Jahr",
            guest_count_min=100,
            guest_count_max=150,
            location="Hamburg",
            budget_per_person_cents=4000,
            received_at=now,
            updated_at=now,
        )
    )

    first = service.create_from_call(call)
    second = service.create_from_call(call)

    assert first == second
    assert first.event_date is None
    assert first.event_date_text == "im nächsten Jahr"
    assert first.event_time_text == "noch offen"
    assert first.guest_count_min == 100
    assert first.guest_count_max == 150

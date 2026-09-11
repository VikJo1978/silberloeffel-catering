from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, time, timezone
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace
from uuid import UUID

import pytest

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
from catering_system.ui import office_panel_richtangebot_runtime
from catering_system.ui.office_panel_richtangebot import (
    render_richtangebot_detail,
    render_richtangebote_section,
)
from catering_system.ui.office_panel_views import OfficePageContext


def _uuid(value: int) -> str:
    return str(UUID(int=value, version=4))


def _value(*, value_id: int = 10, source_id: int = 11) -> Richtangebot:
    now = datetime(2026, 9, 11, 14, 0, tzinfo=UTC)
    return Richtangebot(
        richtangebot_id=_uuid(value_id),
        source_call_id=_uuid(source_id),
        created_at=now,
        updated_at=now,
        contact_name="Test Kunde",
        caller_phone="+49123",
        email="test@example.invalid",
        event_type="Taufe",
        event_date_text="im nächsten Jahr",
        event_time_text="noch offen",
        guest_count_min=100,
        guest_count_max=150,
        location="Hamburg",
        budget_per_person_cents=4000,
        customer_request="50 % Fingerfood, 50 % Buffet",
    )


def test_richtangebot_accepts_fuzzy_date_time_and_guest_range() -> None:
    value = validate_richtangebot(_value(value_id=1, source_id=2))

    assert value.event_date is None
    assert value.guest_count is None
    assert value.guest_count_min == 100
    assert value.guest_count_max == 150
    assert "unverbindliche" in value.disclaimer.lower()


def test_richtangebot_accepts_exact_values_and_normalizes_text() -> None:
    now = datetime(2026, 9, 11, 14, 0, tzinfo=UTC)
    value = validate_richtangebot(
        Richtangebot(
            richtangebot_id=_uuid(20),
            source_call_id=_uuid(21),
            created_at=now,
            updated_at=now,
            contact_name="  Test Kunde  ",
            event_type="Taufe",
            event_date=date(2027, 5, 1),
            event_start=time(16, 30),
            guest_count=120,
            budget_total_cents=480000,
        )
    )

    assert value.contact_name == "Test Kunde"
    assert value.event_date == date(2027, 5, 1)
    assert value.event_start == time(16, 30)
    assert value.guest_count == 120
    assert value.budget_total_cents == 480000


def test_richtangebot_validation_rejects_invalid_business_facts() -> None:
    now = datetime(2026, 9, 11, 14, 0, tzinfo=UTC)
    base = _value(value_id=30, source_id=31)

    with pytest.raises(ValueError, match="updated_at"):
        validate_richtangebot(
            Richtangebot(
                **{
                    **base.__dict__,
                    "updated_at": datetime(2026, 9, 11, 13, 0, tzinfo=UTC),
                }
            )
        )
    with pytest.raises(TypeError, match="event_start"):
        validate_richtangebot(
            Richtangebot(**{**base.__dict__, "event_start": "16:00"})
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="wall-clock"):
        validate_richtangebot(
            Richtangebot(
                **{
                    **base.__dict__,
                    "event_start": time(16, 0, tzinfo=timezone.utc),
                }
            )
        )
    with pytest.raises(ValueError, match="cannot be combined"):
        validate_richtangebot(Richtangebot(**{**base.__dict__, "guest_count": 120}))
    with pytest.raises(ValueError, match="set together"):
        validate_richtangebot(
            Richtangebot(**{**base.__dict__, "guest_count_max": None})
        )
    with pytest.raises(ValueError, match="must not exceed"):
        validate_richtangebot(
            Richtangebot(
                **{
                    **base.__dict__,
                    "guest_count_min": 160,
                    "guest_count_max": 150,
                }
            )
        )
    with pytest.raises(ValueError, match="invalid Richtangebot status"):
        validate_richtangebot(
            Richtangebot(**{**base.__dict__, "status": "INVALID"})
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="customer contact"):
        validate_richtangebot(
            Richtangebot(
                richtangebot_id=_uuid(32),
                source_call_id=_uuid(33),
                created_at=now,
                updated_at=now,
                event_type="Taufe",
            )
        )
    with pytest.raises(ValueError, match="event or commercial fact"):
        validate_richtangebot(
            Richtangebot(
                richtangebot_id=_uuid(34),
                source_call_id=_uuid(35),
                created_at=now,
                updated_at=now,
                contact_name="Test Kunde",
            )
        )


def test_richtangebot_validation_rejects_bad_primitives() -> None:
    base = _value(value_id=40, source_id=41)
    with pytest.raises(ValueError, match="UUID"):
        validate_richtangebot(
            Richtangebot(**{**base.__dict__, "richtangebot_id": "nope"})
        )
    with pytest.raises(TypeError, match="text field"):
        validate_richtangebot(
            Richtangebot(**{**base.__dict__, "event_type": 123})
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="disclaimer"):
        validate_richtangebot(Richtangebot(**{**base.__dict__, "disclaimer": ""}))
    with pytest.raises(TypeError, match="guest_count"):
        validate_richtangebot(
            Richtangebot(
                **{
                    **base.__dict__,
                    "guest_count_min": None,
                    "guest_count_max": None,
                    "guest_count": True,
                }
            )
        )
    with pytest.raises(ValueError, match="guest_count"):
        validate_richtangebot(
            Richtangebot(
                **{
                    **base.__dict__,
                    "guest_count_min": None,
                    "guest_count_max": None,
                    "guest_count": 0,
                }
            )
        )
    with pytest.raises(TypeError, match="budget_per_person_cents"):
        validate_richtangebot(
            Richtangebot(**{**base.__dict__, "budget_per_person_cents": True})
        )
    with pytest.raises(ValueError, match="budget_per_person_cents"):
        validate_richtangebot(
            Richtangebot(**{**base.__dict__, "budget_per_person_cents": -1})
        )


def test_richtangebot_repository_roundtrip_update_and_list() -> None:
    connection = sqlite3.connect(":memory:")
    repo = SQLiteRichtangebotRepository.from_connection(connection)
    value = _value(value_id=3, source_id=4)

    repo.save(value)
    loaded = repo.get(value.richtangebot_id)

    assert loaded is not None
    assert loaded.source_call_id == value.source_call_id
    assert loaded.guest_count_min == 100
    assert loaded.guest_count_max == 150
    assert loaded.disclaimer == DEFAULT_RICHTANGEBOT_DISCLAIMER
    assert repo.find_by_source_call_id(value.source_call_id) == loaded
    assert repo.list_recent(limit=0) == []
    assert repo.list_recent(limit=10) == [loaded]

    updated = Richtangebot(**{**loaded.__dict__, "customer_request": "Geändert"})
    repo.update(updated)
    reloaded = repo.get(value.richtangebot_id)
    assert reloaded is not None
    assert reloaded.customer_request == "Geändert"

    missing = Richtangebot(**{**updated.__dict__, "richtangebot_id": _uuid(99)})
    with pytest.raises(KeyError):
        repo.update(missing)


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
    assert service.get(first.richtangebot_id) == first
    assert service.list_recent() == [first]
    assert first.event_date is None
    assert first.event_date_text == "im nächsten Jahr"
    assert first.event_time_text == "noch offen"
    assert first.guest_count_min == 100
    assert first.guest_count_max == 150


def test_richtangebot_views_cover_exact_range_and_empty_list() -> None:
    value = validate_richtangebot(_value(value_id=50, source_id=51))
    context = OfficePageContext(csrf_token="csrf", employee_account_id="employee-1")

    detail = render_richtangebot_detail(value, context=context)
    listing = render_richtangebote_section([value])

    assert "Richtangebot" in detail
    assert "im nächsten Jahr" in detail
    assert "100–150" in detail
    assert "40,00 € / Person" in detail
    assert DEFAULT_RICHTANGEBOT_DISCLAIMER in detail
    assert value.richtangebot_id in listing
    assert "100–150" in listing
    assert render_richtangebote_section([]) == ""

    exact = validate_richtangebot(
        Richtangebot(
            **{
                **value.__dict__,
                "richtangebot_id": _uuid(52),
                "source_call_id": _uuid(53),
                "event_date": date(2027, 5, 1),
                "event_date_text": "",
                "event_start": time(16, 30),
                "event_time_text": "",
                "guest_count": 120,
                "guest_count_min": None,
                "guest_count_max": None,
                "budget_per_person_cents": None,
            }
        )
    )
    exact_html = render_richtangebot_detail(exact, context=context)
    assert "01.05.2027" in exact_html
    assert "16:30" in exact_html
    assert ">120<" in exact_html
    assert "Nicht angegeben / Person" in exact_html


def test_richtangebot_runtime_wraps_local_server_and_leaves_remote_untouched(
    monkeypatch,
) -> None:
    class DummyHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    def fake_server(*args, **kwargs):
        return SimpleNamespace(RequestHandlerClass=DummyHandler)

    monkeypatch.setattr(
        office_panel_richtangebot_runtime,
        "create_ai_enabled_office_panel_server",
        fake_server,
    )

    remote = (
        office_panel_richtangebot_runtime.create_richtangebot_enabled_office_panel_server(
            object(), object(), "pw", remote=object()
        )
    )
    assert remote.RequestHandlerClass is DummyHandler

    connection = sqlite3.connect(":memory:")
    try:
        local = (
            office_panel_richtangebot_runtime.create_richtangebot_enabled_office_panel_server(
                SimpleNamespace(_conn=connection), object(), "pw"
            )
        )
        assert local.RequestHandlerClass.__name__ == "RichtangebotEnabledHandler"
    finally:
        connection.close()

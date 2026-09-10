from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from catering_system.domain.ai_telefon_call import AiTelefonCall
from catering_system.repositories.ai_telefon_call_repository import DuplicateAiTelefonCallError
from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)


def _call(*, strato_id: str, gmail_message_id: str) -> AiTelefonCall:
    now = datetime(2026, 9, 10, 18, 0, tzinfo=UTC)
    return AiTelefonCall(
        call_id="8e5d6ac1-1a43-49b0-8803-d76ac86a9666",
        strato_id=strato_id,
        gmail_message_id=gmail_message_id,
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
        location="Hamburg",
        budget_per_person_cents=3000,
        callback_requested=True,
        callback_time=time(13, 20),
        received_at=now,
        updated_at=now,
    )


def test_roundtrip_and_new_count(tmp_path) -> None:
    repo = SQLiteAiTelefonCallRepository(tmp_path / "core.sqlite3")
    try:
        call = _call(strato_id="strato-1", gmail_message_id="gmail-1")
        repo.save(call)

        loaded = repo.get(call.call_id)
        assert loaded == call
        assert repo.find_by_strato_id("strato-1") == call
        assert repo.find_by_gmail_message_id("gmail-1") == call
        assert repo.count_new() == 1
        assert repo.list_recent() == [call]
    finally:
        repo.close()


def test_duplicate_strato_id_is_rejected(tmp_path) -> None:
    repo = SQLiteAiTelefonCallRepository(tmp_path / "core.sqlite3")
    try:
        repo.save(_call(strato_id="same", gmail_message_id="gmail-1"))
        duplicate = _call(strato_id="same", gmail_message_id="gmail-2")
        duplicate = AiTelefonCall(**{**duplicate.__dict__, "call_id": "88d2656a-f17c-4686-9f91-b6b9bad20a7c"})
        with pytest.raises(DuplicateAiTelefonCallError):
            repo.save(duplicate)
    finally:
        repo.close()

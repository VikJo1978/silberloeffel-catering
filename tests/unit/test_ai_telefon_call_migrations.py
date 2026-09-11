from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from catering_system.repositories import sqlite_ai_telefon_call_repository as module
from catering_system.repositories.ai_telefon_call_repository import (
    DuplicateAiTelefonCallError,
)
from catering_system.repositories.sqlite_migrations import apply_migrations


@pytest.mark.parametrize("version", [1, 2])
def test_populated_legacy_database_migrates_to_v3_without_losing_facts(
    tmp_path, version
):
    db_path = tmp_path / "core.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        (Path(__file__).parents[1] / "fixtures/ai_telefon_calls_v1.sql").read_text()
    )
    connection.execute(
        "CREATE TABLE schema_migrations (component TEXT NOT NULL, version INTEGER NOT NULL, "
        "name TEXT NOT NULL, applied_at TEXT NOT NULL, PRIMARY KEY(component, version))"
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES ('ai_telefon_calls', 1, 'create_ai_telefon_calls', '2026-09-10')"
    )
    if version == 2:
        connection.execute(
            "ALTER TABLE ai_telefon_calls ADD COLUMN guest_count_min INTEGER"
        )
        connection.execute(
            "ALTER TABLE ai_telefon_calls ADD COLUMN guest_count_max INTEGER"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES ('ai_telefon_calls', 2, 'add_guest_count_range', '2026-09-10')"
        )
    # Other components sharing core.db must survive the table rebuild too.
    connection.execute("CREATE TABLE existing_offer (id TEXT PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO existing_offer VALUES ('offer', 'unchanged')")
    connection.execute(
        "INSERT INTO schema_migrations VALUES ('other', 1, 'other', '2026-09-10')"
    )
    ids = []
    for index, result in enumerate([None, "INQUIRY", "TASK", "LINKED", None]):
        call_id = str(uuid4())
        ids.append(call_id)
        row = dict(
            call_id=call_id,
            strato_id=f"strato-{index}",
            gmail_message_id=f"gmail-{index}",
            caller_phone="+49123",
            contact_name="Änne Müller",
            email="test@example.invalid",
            subject="Taufe",
            summary="100 bis 150 Gäste im nächsten Jahr",
            raw_message="Original\nText",
            event_type="Taufe",
            event_date="2027-01-12" if index == 1 else None,
            event_period="im nächsten Jahr",
            event_start="16:45" if index == 1 else None,
            guest_count=100 if index == 1 else None,
            location="Hamburg",
            budget_per_person_cents=4000,
            fulfillment_mode="DELIVERY",
            customer_request="Vegetarisch",
            callback_requested=[None, 1, 0, 1, None][index],
            callback_date="2026-09-12",
            callback_time="13:20",
            status="PROCESSED" if result else ("DONE" if index == 4 else "NEW"),
            result_type=result,
            result_id=str(uuid4()) if result else None,
            linked_type="OFFER" if result == "LINKED" else None,
            linked_id=str(uuid4()) if result == "LINKED" else None,
            received_at=f"2026-09-10T18:0{index}:00+00:00",
            processed_at="2026-09-10T19:00:00+00:00" if result else None,
            updated_at="2026-09-10T19:00:00+00:00",
        )
        if version == 2:
            row.update(
                guest_count_min=100 if index == 0 else None,
                guest_count_max=150 if index == 0 else None,
            )
        connection.execute(
            f"INSERT INTO ai_telefon_calls ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
    connection.commit()
    legacy_columns = [
        row[1] for row in connection.execute("PRAGMA table_info(ai_telefon_calls)")
    ]
    select = (
        f"SELECT {', '.join(legacy_columns)} FROM ai_telefon_calls ORDER BY call_id"
    )
    before = connection.execute(select).fetchall()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE ai_telefon_calls SET result_type='RICHTANGEBOT' WHERE call_id=?",
            (ids[0],),
        )
    connection.rollback()

    apply_migrations(connection, "ai_telefon_calls", module._MIGRATIONS[:3])
    assert connection.execute(select).fetchall() == before
    assert connection.execute(
        "SELECT version FROM schema_migrations WHERE component='ai_telefon_calls' ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,)]
    assert connection.execute("SELECT * FROM existing_offer").fetchall() == [
        ("offer", "unchanged")
    ]
    assert connection.execute(
        "SELECT name FROM schema_migrations WHERE component='other'"
    ).fetchone() == ("other",)
    assert (
        connection.execute(
            "SELECT name FROM sqlite_master WHERE name='ai_telefon_calls_pre_richtangebot'"
        ).fetchone()
        is None
    )
    indexes = {
        row[1]: row[2]
        for row in connection.execute("PRAGMA index_list(ai_telefon_calls)")
    }
    assert indexes["uq_ai_telefon_calls_strato_id"] == 1
    assert indexes["uq_ai_telefon_calls_gmail_message_id"] == 1
    assert indexes["idx_ai_telefon_calls_status_received"] == 0
    for column, value in [
        ("status", "INVALID"),
        ("result_type", "INVALID"),
        ("fulfillment_mode", "INVALID"),
        ("linked_type", "INVALID"),
        ("callback_requested", 2),
    ]:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"UPDATE ai_telefon_calls SET {column}=? WHERE call_id=?",
                (value, ids[0]),
            )
        connection.rollback()
    connection.execute(
        "UPDATE ai_telefon_calls SET result_type='RICHTANGEBOT' WHERE call_id=?",
        (ids[0],),
    )
    connection.rollback()
    apply_migrations(connection, "ai_telefon_calls", module._MIGRATIONS[:3])
    assert connection.execute(select).fetchall() == before
    connection.close()

    # Opening the production repository also upgrades an existing v3 DB to v4.
    repo = module.SQLiteAiTelefonCallRepository(db_path)
    call = repo.get(ids[0])
    assert call is not None
    assert call.event_time_text == ""
    assert call.guest_count_min == (100 if version == 2 else None)
    assert call.guest_count_max == (150 if version == 2 else None)
    assert repo.count_new() == 1
    assert [item.call_id for item in repo.list_recent()] == list(reversed(ids))
    for item in repo.list_recent():
        assert repo.find_by_strato_id(item.strato_id) == item
        assert repo.find_by_gmail_message_id(item.gmail_message_id) == item
    for fields in [
        dict(gmail_message_id="fresh-gmail"),
        dict(strato_id="fresh-strato"),
    ]:
        with pytest.raises(DuplicateAiTelefonCallError):
            repo.save(replace(call, call_id=str(uuid4()), **fields))
    updated = replace(
        call,
        event_time_text="zwischen 16 und 18 Uhr vereinbart",
        status="PROCESSED",
        result_type="RICHTANGEBOT",
        result_id=str(uuid4()),
        processed_at=call.updated_at,
    )
    repo.update(updated)
    repo.close()
    reopened = module.SQLiteAiTelefonCallRepository(db_path)
    try:
        assert reopened.get(call.call_id) == updated
    finally:
        reopened.close()

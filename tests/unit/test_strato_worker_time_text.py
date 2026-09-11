from __future__ import annotations

import base64
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)


@pytest.mark.parametrize(
    "script", ["strato_gmail_worker", "strato_gmail_import_example"]
)
def test_gmail_import_preserves_textual_time_without_exact_start(
    tmp_path, monkeypatch, script
):
    path = Path(__file__).parents[2] / "scripts" / f"{script}.py"
    spec = importlib.util.spec_from_file_location(script, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = "Anrufer: +49123\nName: Test Kunde\nBetreff: Taufe\nZusammenfassung: Lieferung zwischen 16 und 18 Uhr vereinbart.\nID: strato-time\n"
    message = {
        "internalDate": "1789128000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": module.STRATO_SENDER},
                {"name": "Subject", "value": module.STRATO_SUBJECT},
            ],
            "body": {"data": base64.urlsafe_b64encode(raw.encode()).decode()},
        },
    }
    api = SimpleNamespace()
    api.users = lambda: api
    api.messages = lambda: api
    api.list = lambda **kwargs: SimpleNamespace(
        execute=lambda: {"messages": [{"id": "gmail-time"}]}
    )
    api.get = lambda **kwargs: SimpleNamespace(execute=lambda: message)
    # No network, credentials or optional Google/OpenAI SDKs are needed.
    for name in [
        "google",
        "google.oauth2",
        "google.oauth2.credentials",
        "googleapiclient",
        "googleapiclient.discovery",
    ]:
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["google.oauth2.credentials"].Credentials = SimpleNamespace(
        from_authorized_user_file=lambda *args: object()
    )
    sys.modules["googleapiclient.discovery"].build = lambda *args, **kwargs: api
    structured = {
        "event_time_text": "zwischen 16 und 18 Uhr vereinbart",
        "event_start": None,
    }
    db = tmp_path / "core.db"
    if script == "strato_gmail_worker":

        def extract(summary, **kwargs):
            assert "zwischen 16 und 18 Uhr" in summary
            return structured

        monkeypatch.setattr(module, "_openai_structured_facts", extract)

        def run():
            return module.import_once(
                db_path=db, token_path=tmp_path / "unused", model="test"
            )

        prompt = module._prompt(raw, datetime(2026, 9, 11, tzinfo=UTC))
        assert "event_time_text" in prompt
        assert (
            "Keinen exakten Beginn aus einem Zeitfenster auswählen oder erfinden"
            in prompt
        )
    else:
        (tmp_path / "strato-time.json").write_text(json.dumps(structured))

        def run():
            return module.import_once(
                db_path=db, token_path=tmp_path / "unused", structured_json_dir=tmp_path
            )

    assert run() == 1
    assert run() == 0
    repo = SQLiteAiTelefonCallRepository(db)
    try:
        call = repo.find_by_strato_id("strato-time")
        assert call is not None
        assert call.event_start is None
        assert call.event_time_text == structured["event_time_text"]
        assert call.event_date is None
    finally:
        repo.close()

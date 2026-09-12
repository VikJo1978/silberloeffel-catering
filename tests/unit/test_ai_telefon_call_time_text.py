from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, time
from html import escape

import pytest

from catering_system.domain.ai_telefon_call import validate_ai_telefon_call
from catering_system.intake.strato_summary_email import (
    llm_extraction_contract,
    llm_extraction_json_schema,
    structured_call_facts_from_mapping,
)
from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_richtangebot_repository import (
    SQLiteRichtangebotRepository,
)
from catering_system.services.ai_telefon_call_service import AiTelefonCallService
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.richtangebot_service import (
    RichtangebotService,
    can_create_richtangebot,
)
from catering_system.ui.office_panel_ai_telefonist import render_ai_telefon_call_detail
from catering_system.ui.office_panel_richtangebot import (
    render_richtangebot_detail,
    render_richtangebote_section,
)
from catering_system.ui.office_panel_views import OfficePageContext


@pytest.mark.parametrize(
    "text,exact",
    [
        ("nachmittags", None),
        ("gegen 16 Uhr", None),
        ("zwischen 16 und 18 Uhr vereinbart", None),
        ("nach Absprache", None),
        (None, None),
        ("", "16:45"),
        ("Lieferung zwischen 15 und 16 Uhr, Beginn 16:45 Uhr", "16:45"),
        ('<script>alert("x")</script>', None),
    ],
)
def test_time_facts_survive_ingest_storage_richtangebot_and_manual_inquiry(
    tmp_path, text, exact
):
    db = tmp_path / "core.db"
    calls = SQLiteAiTelefonCallRepository(db)
    inquiries = SQLiteInquiryRepository(db)
    offers = SQLiteRichtangebotRepository(db)
    try:
        facts = structured_call_facts_from_mapping(
            {"event_date": "2027-01-12", "event_start": exact, "event_time_text": text}
        )
        service = AiTelefonCallService(
            calls,
            inquiry_repository=inquiries,
            inquiry_service=InquiryService(inquiries),
        )
        call = service.ingest(
            strato_id="strato-time",
            gmail_message_id="gmail-time",
            caller_phone="+49123",
            contact_name="Test Kunde",
            subject="Taufe",
            summary="Zeitangabe aus dem Gespräch",
            raw_message="raw",
            **asdict(facts),
        )
        calls.close()
        calls = SQLiteAiTelefonCallRepository(db)
        loaded = calls.get(call.call_id)
        assert loaded == call
        assert loaded.event_start == (time(16, 45) if exact else None)
        assert loaded.event_time_text == (text or "")
        assert loaded.event_date == date(2027, 1, 12)
        value = RichtangebotService(offers).create_from_call(loaded)
        assert offers.get(value.richtangebot_id) == value
        assert value.event_start == loaded.event_start
        assert value.event_time_text == (text or ("" if exact else "noch offen"))
        context = OfficePageContext(csrf_token="csrf")
        if text:
            for html in [
                render_ai_telefon_call_detail(loaded),
                render_richtangebot_detail(value, context=context),
                render_richtangebote_section([value]),
            ]:
                assert escape(text) in html
                assert "<script>alert(" not in html
        assert inquiries.list_all() == []
        # Only the explicit employee conversion creates an inquiry.
        service = AiTelefonCallService(
            calls,
            inquiry_repository=inquiries,
            inquiry_service=InquiryService(inquiries),
        )
        result = service.convert_to_inquiry(call.call_id)
        inquiry = inquiries.get_by_id(result.result_id)
        assert inquiry.event_start_local == loaded.event_start
        assert inquiry.time_window_text == (text or ("ab 16:45 Uhr" if exact else ""))
        updated = replace(loaded, event_time_text="abends nach Absprache")
        calls.update(updated)
        assert calls.get(call.call_id) == updated
    finally:
        calls.close()
        inquiries.close()
        offers.close()


def test_time_text_contract_is_nullable_and_rejects_non_text():
    assert llm_extraction_contract()["event_time_text"] is None
    schema = llm_extraction_json_schema()
    assert "event_time_text" in schema["required"]
    assert schema["properties"]["event_time_text"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }
    with pytest.raises(TypeError):
        structured_call_facts_from_mapping({"event_time_text": 1600})


def test_time_text_is_validated_and_counts_as_commercial_context(tmp_path):
    repo = SQLiteAiTelefonCallRepository(tmp_path / "core.db")
    try:
        call = AiTelefonCallService(
            repo, now=lambda: datetime(2026, 9, 11, tzinfo=UTC)
        ).ingest(
            strato_id="s",
            gmail_message_id="g",
            caller_phone="+49123",
            contact_name="",
            email="",
            subject="",
            summary="nachmittags",
            raw_message="",
            event_time_text=" nachmittags ",
        )
        assert call.event_time_text == "nachmittags"
        assert can_create_richtangebot(call)
        assert not can_create_richtangebot(replace(call, event_time_text=""))
        with pytest.raises(TypeError):
            validate_ai_telefon_call(replace(call, event_time_text=16))
        assert (
            len(
                validate_ai_telefon_call(
                    replace(call, event_time_text="a" * 501)
                ).event_time_text
            )
            == 500
        )
    finally:
        repo.close()

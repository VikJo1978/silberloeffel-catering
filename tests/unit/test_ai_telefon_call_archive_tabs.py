from __future__ import annotations

from datetime import UTC, datetime

from catering_system.domain.ai_telefon_call import AiTelefonCall
from catering_system.ui.office_panel_ai_telefonist import render_ai_telefon_calls


def _call(call_id: str, *, status: str, result_type: str | None = None) -> AiTelefonCall:
    now = datetime(2026, 9, 12, 6, 0, tzinfo=UTC)
    return AiTelefonCall(
        call_id=call_id,
        strato_id=f"strato-{call_id}",
        gmail_message_id=f"gmail-{call_id}",
        caller_phone="+49123456789",
        contact_name=f"Kontakt {call_id}",
        email="",
        subject="Testanruf",
        summary="Test",
        raw_message="Test",
        status=status,  # type: ignore[arg-type]
        result_type=result_type,  # type: ignore[arg-type]
        result_id=(f"result-{call_id}" if result_type else None),
        received_at=now,
        processed_at=(now if status == "PROCESSED" else None),
        updated_at=now,
    )


def test_call_list_defaults_to_open_and_exposes_archive_tabs() -> None:
    html = render_ai_telefon_calls(
        [
            _call("open", status="NEW"),
            _call("processed", status="PROCESSED", result_type="INQUIRY"),
            _call("done", status="DONE"),
        ]
    )

    assert "Offen (1)" in html
    assert "Archiv (2)" in html
    assert "Alle (3)" in html
    assert 'href="/ki-telefonassistent#archiv"' in html
    assert 'href="/ki-telefonassistent#alle"' in html

    assert "ai-call-open" in html
    assert html.count("ai-call-archive") >= 3
    assert ".ai-call-archive{display:none}" in html
    assert "#archiv:target~.chat-layout .ai-call-open{display:none}" in html
    assert "#archiv:target~.chat-layout .ai-call-archive{display:block}" in html
    assert "#alle:target~.chat-layout .ai-call-archive{display:block}" in html


def test_call_list_badge_still_counts_only_new_calls() -> None:
    html = render_ai_telefon_calls(
        [
            _call("open-1", status="NEW"),
            _call("open-2", status="NEW"),
            _call("processed", status="PROCESSED", result_type="RICHTANGEBOT"),
        ]
    )

    assert "2 neu" in html
    assert "Offen (2)" in html
    assert "Archiv (1)" in html
    assert "Alle (3)" in html

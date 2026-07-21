"""Unit tests — CONTACT_INTERNAL_NOTES_V1."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest

from catering_system.domain.contact_internal_note import (
    CONTACT_INTERNAL_NOTE_CATEGORIES,
    MAX_CONTACT_INTERNAL_NOTE_LENGTH,
)
from catering_system.repositories.in_memory_contact_internal_note_repository import (
    InMemoryContactInternalNoteRepository,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_contact_internal_note_repository import (
    SQLiteContactInternalNoteRepository,
)
from catering_system.services.contact_internal_note_service import (
    ContactInternalNoteService,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.office_panel import OfficePanel, create_office_panel_server
from catering_system.ui.office_panel_contact_detail import render_kontakt_detail
from catering_system.ui.office_panel_views import OfficePageContext

_PASSWORD = "test-secret"
_AUTH = ("office", _PASSWORD)


def _panel_with_contact(
    *,
    note_repo: InMemoryContactInternalNoteRepository | None = None,
    phone: str = "+4917642795029",
    company: str = "JK-art",
) -> tuple[OfficePanel, str]:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=12,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_message=f"Firma: {company}\nTelefon: {phone}\n",
    )
    panel = OfficePanel(
        inquiries,
        orders,
        contact_note_repo=note_repo or InMemoryContactInternalNoteRepository(),
    )
    rows = panel._contact_list_rows()
    contact_key = str(rows[0]["contact_key"])
    return panel, contact_key


def test_add_valid_note() -> None:
    service = ContactInternalNoteService(
        InMemoryContactInternalNoteRepository(), created_by="office-panel"
    )
    note = service.add_note(
        "intake:phone:+4917642795029",
        category="Allgemein",
        note_text="  Bevorzugt Lieferung vormittags  ",
    )
    assert note.note_text == "Bevorzugt Lieferung vormittags"
    assert note.created_by == "office-panel"
    assert note.category == "Allgemein"


def test_note_persists_after_sqlite_reload(tmp_path: Path) -> None:
    db = tmp_path / "notes.db"
    repo = SQLiteContactInternalNoteRepository(db)
    service = ContactInternalNoteService(repo, created_by="office-panel")
    service.add_note(
        "intake:phone:+4917642795029",
        category="Vorlieben",
        note_text="Keine Nüsse",
    )
    repo.close()

    reloaded = SQLiteContactInternalNoteRepository(db)
    notes = reloaded.list_for_contact("intake:phone:+4917642795029")
    assert len(notes) == 1
    assert notes[0].note_text == "Keine Nüsse"
    assert notes[0].category == "Vorlieben"
    reloaded.close()


def test_note_appears_on_correct_contact_detail() -> None:
    panel, contact_key = _panel_with_contact()
    panel.add_contact_note(
        contact_key, {"category": "Lieferung", "note_text": "Tor 2 benutzen"}
    )
    page = panel.render_kontakt(contact_key)
    assert page is not None
    assert "Interne Notizen" in page
    assert "Tor 2 benutzen" in page
    assert "Lieferung" in page
    assert "office-panel" in page


def test_notes_are_isolated_between_contacts() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    note_repo = InMemoryContactInternalNoteRepository()
    InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=12,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_message="Firma: Alpha\nTelefon: +491111111111\n",
    )
    InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 2),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_message="Firma: Beta\nTelefon: +492222222222\n",
    )
    panel = OfficePanel(inquiries, orders, contact_note_repo=note_repo)
    keys = {
        str(row["display_name"]): str(row["contact_key"])
        for row in panel._contact_list_rows()
    }
    panel.add_contact_note(
        keys["Alpha"], {"category": "Allgemein", "note_text": "Nur Alpha"}
    )
    panel.add_contact_note(
        keys["Beta"], {"category": "Allgemein", "note_text": "Nur Beta"}
    )

    alpha_page = panel.render_kontakt(keys["Alpha"]) or ""
    beta_page = panel.render_kontakt(keys["Beta"]) or ""
    assert "Nur Alpha" in alpha_page and "Nur Beta" not in alpha_page
    assert "Nur Beta" in beta_page and "Nur Alpha" not in beta_page


@pytest.mark.parametrize("category", CONTACT_INTERNAL_NOTE_CATEGORIES)
def test_every_allowed_category_works(category: str) -> None:
    service = ContactInternalNoteService(
        InMemoryContactInternalNoteRepository(), created_by="office-panel"
    )
    note = service.add_note("intake:phone:+49123", category=category, note_text="ok")
    assert note.category == category


def test_invalid_category_rejected() -> None:
    service = ContactInternalNoteService(
        InMemoryContactInternalNoteRepository(), created_by="office-panel"
    )
    with pytest.raises(ValueError, match="category"):
        service.add_note("k", category="Spam", note_text="x")


def test_empty_note_rejected() -> None:
    service = ContactInternalNoteService(
        InMemoryContactInternalNoteRepository(), created_by="office-panel"
    )
    with pytest.raises(ValueError, match="empty"):
        service.add_note("k", category="Allgemein", note_text="   ")


def test_note_longer_than_4000_rejected() -> None:
    service = ContactInternalNoteService(
        InMemoryContactInternalNoteRepository(), created_by="office-panel"
    )
    with pytest.raises(ValueError, match="at most"):
        service.add_note(
            "k",
            category="Allgemein",
            note_text="x" * (MAX_CONTACT_INTERNAL_NOTE_LENGTH + 1),
        )


def test_html_script_content_is_escaped() -> None:
    detail = {
        "contact_key": "intake:phone:+49123",
        "display_name": "Test",
        "email": None,
        "phone": "+49123",
        "inquiries": [],
        "offers": [],
        "orders": [],
        "internal_notes": [
            {
                "category": "Allgemein",
                "note_text": "<script>alert(1)</script>\nZeile 2",
                "created_at": "2026-07-21T10:00:00+00:00",
                "created_by": "office-panel",
            }
        ],
    }
    page = render_kontakt_detail(detail, context=OfficePageContext(csrf_token="csrf"))
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "Zeile 2" in page
    assert "<br>" in page


def test_author_cannot_be_overridden_by_request() -> None:
    panel, contact_key = _panel_with_contact()
    panel.add_contact_note(
        contact_key,
        {
            "category": "Allgemein",
            "note_text": "Text",
            "created_by": "attacker",
            "author": "attacker",
        },
    )
    notes = panel.contact_note_service.list_for_contact(contact_key)
    assert notes[0].created_by == "office-panel"


def test_post_redirects_after_successful_creation() -> None:
    import threading
    import urllib.parse
    import urllib.request

    note_repo = InMemoryContactInternalNoteRepository()
    panel, contact_key = _panel_with_contact(note_repo=note_repo)
    server = create_office_panel_server(
        panel._inquiries,
        panel._orders,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        contact_note_repo=note_repo,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    encoded = quote(contact_key, safe="")
    try:
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, base, *_AUTH)
        opener = urllib.request.build_opener(
            urllib.request.HTTPBasicAuthHandler(password_mgr),
            urllib.request.HTTPRedirectHandler(),
        )
        # fetch CSRF from GET
        with opener.open(f"{base}/kontakt/{encoded}") as response:
            body = response.read().decode()
        csrf = body.split('name="_csrf_token" value="')[1].split('"')[0]
        data = urllib.parse.urlencode(
            {
                "_csrf_token": csrf,
                "category": "Zahlung",
                "note_text": "Rechnung per Überweisung",
                "created_by": "attacker",
            }
        ).encode()
        request = urllib.request.Request(
            f"{base}/kontakt/{encoded}/notizen", data=data, method="POST"
        )
        with opener.open(request) as response:
            final_url = response.geturl()
            page = response.read().decode()
        assert final_url == f"{base}/kontakt/{encoded}"
        assert "Rechnung per Überweisung" in page
        assert "attacker" not in page
        assert "office-panel" in page
    finally:
        server.shutdown()
        server.server_close()


def test_sqlite_append_only_rejects_update(tmp_path: Path) -> None:
    db = tmp_path / "notes.db"
    repo = SQLiteContactInternalNoteRepository(db)
    service = ContactInternalNoteService(repo, created_by="office-panel")
    note = service.add_note("k", category="Allgemein", note_text="eins")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repo._conn.execute(
            "UPDATE contact_internal_notes SET note_text = ? WHERE note_id = ?",
            ("zwei", note.note_id),
        )
    repo.close()

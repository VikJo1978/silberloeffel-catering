"""Unit tests — CONTACT_INTERNAL_NOTES_V1 with stable contact profiles + search."""

from __future__ import annotations

import sqlite3
import threading
import urllib.parse
import urllib.request
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
from catering_system.repositories.in_memory_contact_profile_repository import (
    InMemoryContactProfileRepository,
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
from catering_system.repositories.sqlite_contact_profile_repository import (
    SQLiteContactProfileRepository,
)
from catering_system.services.contact_internal_note_service import (
    ContactInternalNoteService,
)
from catering_system.services.contact_profile_service import ContactProfileService
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.office_panel import OfficePanel, create_office_panel_server
from catering_system.ui.office_panel_contact_detail import render_kontakt_detail
from catering_system.ui.office_panel_views import OfficePageContext

_PASSWORD = "test-secret"
_AUTH = ("office", _PASSWORD)
_PHONE = "+4917642795029"


def _services(
    *,
    note_repo: InMemoryContactInternalNoteRepository | None = None,
    profile_repo: InMemoryContactProfileRepository | None = None,
) -> tuple[ContactProfileService, ContactInternalNoteService]:
    profiles = ContactProfileService(profile_repo or InMemoryContactProfileRepository())
    notes = ContactInternalNoteService(
        note_repo or InMemoryContactInternalNoteRepository(),
        profiles,
        created_by="office-panel",
    )
    return profiles, notes


def _panel_with_contact(
    *,
    note_repo: InMemoryContactInternalNoteRepository | None = None,
    profile_repo: InMemoryContactProfileRepository | None = None,
    phone: str = _PHONE,
    company: str = "JK-art",
    email: str = "jk@example.invalid",
    customer_linkage: dict[str, str] | None = None,
) -> tuple[OfficePanel, str, object]:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage=customer_linkage or {},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=12,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_message=f"Firma: {company}\nE-Mail: {email}\nTelefon: {phone}\n",
    )
    panel = OfficePanel(
        inquiries,
        orders,
        contact_note_repo=note_repo or InMemoryContactInternalNoteRepository(),
        contact_profile_repo=profile_repo or InMemoryContactProfileRepository(),
    )
    rows = panel._contact_list_rows()
    contact_key = str(rows[0]["contact_key"])
    return panel, contact_key, inquiry


def test_add_valid_note() -> None:
    profiles, notes = _services()
    profile_id = profiles._ensure(  # noqa: SLF001
        [("email", "a@example.invalid")],
        display_name="A",
        email="a@example.invalid",
        phone=None,
    )
    note = notes.add_note(
        profile_id, category="Allgemein", note_text="  Bevorzugt vormittags  "
    )
    assert note.note_text == "Bevorzugt vormittags"
    assert note.created_by == "office-panel"
    assert note.contact_profile_id == profile_id


def test_note_persists_after_sqlite_reload(tmp_path: Path) -> None:
    db = tmp_path / "notes.db"
    profile_repo = SQLiteContactProfileRepository(db)
    note_repo = SQLiteContactInternalNoteRepository(db)
    profiles = ContactProfileService(profile_repo)
    notes = ContactInternalNoteService(note_repo, profiles, created_by="office-panel")
    profile_id = profiles._ensure(  # noqa: SLF001
        [("phone", _PHONE)],
        display_name="JK-art",
        email=None,
        phone=_PHONE,
    )
    notes.add_note(profile_id, category="Vorlieben", note_text="Keine Nüsse")
    profile_repo.close()
    note_repo.close()

    profile_repo2 = SQLiteContactProfileRepository(db)
    note_repo2 = SQLiteContactInternalNoteRepository(db)
    profiles2 = ContactProfileService(profile_repo2)
    notes2 = ContactInternalNoteService(
        note_repo2, profiles2, created_by="office-panel"
    )
    loaded = notes2.list_for_profile(profile_id)
    assert len(loaded) == 1
    assert loaded[0].note_text == "Keine Nüsse"
    profile_repo2.close()
    note_repo2.close()


def test_note_survives_customer_linkage_upgrade() -> None:
    panel, contact_key, inquiry = _panel_with_contact()
    assert contact_key.startswith("intake:email:")
    panel.add_contact_note(
        contact_key, {"category": "Allgemein", "note_text": "Stammkunde"}
    )

    InquiryService(panel._inquiries).update_inquiry(
        inquiry.inquiry_id,
        customer_linkage={"customer_id": "cust-jk"},
        event_date=inquiry.event_date,
        crm_stage=inquiry.crm_stage,
        time_window_text=inquiry.time_window_text,
        location_text=inquiry.location_text,
        guest_count_estimate=inquiry.guest_count_estimate,
        planning_mode=inquiry.planning_mode,
        intake_message=inquiry.intake_message,
    )
    rows = panel._contact_list_rows()
    new_key = str(rows[0]["contact_key"])
    assert new_key == "linkage:customer:cust-jk"

    page = panel.render_kontakt(new_key)
    assert page is not None
    assert "Stammkunde" in page

    # second note after linkage belongs to the same profile
    panel.add_contact_note(
        new_key, {"category": "Zahlung", "note_text": "Rechnung per Überweisung"}
    )
    page2 = panel.render_kontakt(new_key) or ""
    assert "Stammkunde" in page2
    assert "Rechnung per Überweisung" in page2

    # old UI key still resolves via alias
    page_old = panel.render_kontakt(contact_key)
    assert page_old is not None
    assert "Stammkunde" in page_old


def test_phone_and_email_aliases_resolve() -> None:
    panel, contact_key, _inquiry = _panel_with_contact()
    panel.render_kontakt(contact_key)
    profile_id = panel.contact_profile_service.find_by_alias("contact_key", contact_key)
    assert profile_id is not None
    assert panel.contact_profile_service.find_by_alias(
        "email", "jk@example.invalid"
    ) == (profile_id)
    assert panel.contact_profile_service.find_by_alias("phone", _PHONE) == profile_id


def test_notes_are_isolated_between_contacts() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    note_repo = InMemoryContactInternalNoteRepository()
    profile_repo = InMemoryContactProfileRepository()
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
    panel = OfficePanel(
        inquiries,
        orders,
        contact_note_repo=note_repo,
        contact_profile_repo=profile_repo,
    )
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
    profiles, notes = _services()
    profile_id = profiles._ensure(  # noqa: SLF001
        [("inquiry", "i1")], display_name="X", email=None, phone=None
    )
    note = notes.add_note(profile_id, category=category, note_text="ok")
    assert note.category == category


def test_invalid_category_rejected() -> None:
    profiles, notes = _services()
    profile_id = profiles._ensure(  # noqa: SLF001
        [("inquiry", "i1")], display_name="X", email=None, phone=None
    )
    with pytest.raises(ValueError, match="category"):
        notes.add_note(profile_id, category="Spam", note_text="x")


def test_empty_note_rejected() -> None:
    profiles, notes = _services()
    profile_id = profiles._ensure(  # noqa: SLF001
        [("inquiry", "i1")], display_name="X", email=None, phone=None
    )
    with pytest.raises(ValueError, match="empty"):
        notes.add_note(profile_id, category="Allgemein", note_text="   ")


def test_note_longer_than_4000_rejected() -> None:
    profiles, notes = _services()
    profile_id = profiles._ensure(  # noqa: SLF001
        [("inquiry", "i1")], display_name="X", email=None, phone=None
    )
    with pytest.raises(ValueError, match="at most"):
        notes.add_note(
            profile_id,
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


def test_author_cannot_be_overridden_by_request() -> None:
    panel, contact_key, _inquiry = _panel_with_contact()
    panel.add_contact_note(
        contact_key,
        {
            "category": "Allgemein",
            "note_text": "Text",
            "created_by": "attacker",
            "author": "attacker",
        },
    )
    profile_id = panel.contact_profile_service.find_by_alias("contact_key", contact_key)
    assert profile_id is not None
    notes = panel.contact_note_service.list_for_profile(profile_id)
    assert notes[0].created_by == "office-panel"


def test_post_redirects_after_successful_creation() -> None:
    note_repo = InMemoryContactInternalNoteRepository()
    profile_repo = InMemoryContactProfileRepository()
    panel, contact_key, _inquiry = _panel_with_contact(
        note_repo=note_repo, profile_repo=profile_repo
    )
    server = create_office_panel_server(
        panel._inquiries,
        panel._orders,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        contact_note_repo=note_repo,
        contact_profile_repo=profile_repo,
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
    finally:
        server.shutdown()
        server.server_close()


def test_sqlite_append_only_rejects_update(tmp_path: Path) -> None:
    db = tmp_path / "notes.db"
    profile_repo = SQLiteContactProfileRepository(db)
    note_repo = SQLiteContactInternalNoteRepository(db)
    profiles = ContactProfileService(profile_repo)
    notes = ContactInternalNoteService(note_repo, profiles, created_by="office-panel")
    profile_id = profiles._ensure(  # noqa: SLF001
        [("inquiry", "i1")], display_name="X", email=None, phone=None
    )
    note = notes.add_note(profile_id, category="Allgemein", note_text="eins")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        note_repo._conn.execute(  # noqa: SLF001
            "UPDATE contact_internal_notes SET note_text = ? WHERE note_id = ?",
            ("zwei", note.note_id),
        )
    profile_repo.close()
    note_repo.close()


def test_search_by_name() -> None:
    panel, _key, _inquiry = _panel_with_contact(company="JK-art")
    page = panel.render_kontakte("jk-art")
    assert "JK-art" in page
    assert "Keine Kontakte für" not in page


def test_search_by_email() -> None:
    panel, _key, _inquiry = _panel_with_contact(email="jk@example.invalid")
    page = panel.render_kontakte("JK@EXAMPLE.INVALID")
    assert "JK-art" in page


def test_search_by_local_phone_format() -> None:
    panel, _key, _inquiry = _panel_with_contact(phone=_PHONE)
    page = panel.render_kontakte("017642795029")
    assert "JK-art" in page


def test_search_by_e164_phone_format() -> None:
    panel, _key, _inquiry = _panel_with_contact(phone=_PHONE)
    page = panel.render_kontakte(_PHONE)
    assert "JK-art" in page


def test_empty_search_shows_all() -> None:
    panel, _key, _inquiry = _panel_with_contact()
    page = panel.render_kontakte("")
    assert "JK-art" in page
    assert "Kontakte durchsuchen" in page


def test_no_result_search() -> None:
    panel, _key, _inquiry = _panel_with_contact()
    page = panel.render_kontakte("zzz-nichts")
    assert "Keine Kontakte für" in page
    assert "JK-art" not in page or "Keine Kontakte für" in page


def test_collect_inquiry_aliases_includes_linkage_contact() -> None:
    from catering_system.domain.contact_profile import collect_inquiry_aliases

    inquiries = InMemoryInquiryRepository()
    inquiry = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={"contact_id": "hub-42"},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_message="Firma: LinkageCo\nE-Mail: link@example.invalid\n",
    )
    aliases = dict(collect_inquiry_aliases(inquiry))
    assert aliases["linkage_contact"] == "hub-42"
    assert aliases["email"] == "link@example.invalid"
    assert aliases["inquiry"] == inquiry.inquiry_id


def test_alias_merge_unifies_email_and_phone_profiles() -> None:
    profiles = ContactProfileService(InMemoryContactProfileRepository())
    email_id = profiles._ensure(  # noqa: SLF001
        [("email", "merge@example.invalid")],
        display_name="Email First",
        email="merge@example.invalid",
        phone=None,
    )
    phone_id = profiles._ensure(  # noqa: SLF001
        [("phone", _PHONE)],
        display_name="Phone First",
        email=None,
        phone=_PHONE,
    )
    assert email_id != phone_id

    merged = profiles._ensure(  # noqa: SLF001
        [("email", "merge@example.invalid"), ("phone", _PHONE)],
        display_name="Merged",
        email="merge@example.invalid",
        phone=_PHONE,
    )
    assert merged == email_id  # oldest wins
    assert profiles.resolve_root_profile_id(phone_id) == email_id
    assert profiles.find_by_alias("email", "merge@example.invalid") == email_id
    assert profiles.find_by_alias("phone", _PHONE) == email_id


def test_notes_visible_across_merged_profiles() -> None:
    profile_repo = InMemoryContactProfileRepository()
    note_repo = InMemoryContactInternalNoteRepository()
    profiles = ContactProfileService(profile_repo)
    notes = ContactInternalNoteService(note_repo, profiles, created_by="office-panel")
    first = profiles._ensure(  # noqa: SLF001
        [("email", "keep@example.invalid")],
        display_name="Keep",
        email="keep@example.invalid",
        phone=None,
    )
    notes.add_note(first, category="Allgemein", note_text="Vor Merge")
    second = profiles._ensure(  # noqa: SLF001
        [("phone", "+491701111111")],
        display_name="Other",
        email=None,
        phone="+491701111111",
    )
    notes.add_note(second, category="Allgemein", note_text="Auch vor Merge")
    root = profiles._ensure(  # noqa: SLF001
        [("email", "keep@example.invalid"), ("phone", "+491701111111")],
        display_name="Keep",
        email="keep@example.invalid",
        phone="+491701111111",
    )
    texts = {note.note_text for note in notes.list_for_profile(root)}
    assert texts == {"Vor Merge", "Auch vor Merge"}


def test_linkage_contact_projection_binds_alias() -> None:
    from datetime import UTC, datetime

    from catering_system.domain.contact_projection import ContactProjection

    profiles = ContactProfileService(InMemoryContactProfileRepository())
    profile_id = profiles.ensure_for_projection(
        ContactProjection(
            contact_key="linkage:contact:ct-9",
            identity_source="linkage_contact",
            display_name="Linked",
            email="ct9@example.invalid",
            phone=None,
            inquiry_count=1,
            open_inquiries=1,
            active_orders=0,
            last_activity=datetime.now(UTC),
            inquiry_ids=("inq-1",),
        )
    )
    assert profiles.find_by_alias("linkage_contact", "ct-9") == profile_id
    assert profiles.find_by_alias("contact_key", "linkage:contact:ct-9") == profile_id
    assert profiles.find_by_alias("inquiry", "inq-1") == profile_id


def test_find_by_alias_miss_and_missing_profile_resolve() -> None:
    profiles = ContactProfileService(InMemoryContactProfileRepository())
    assert profiles.find_by_alias("email", "missing@example.invalid") is None
    assert profiles.resolve_root_profile_id("ghost-id") == "ghost-id"


def test_merge_cycle_and_nested_merge_ids_for_notes() -> None:
    from datetime import UTC, datetime, timedelta

    from catering_system.domain.contact_profile import ContactProfile

    repo = InMemoryContactProfileRepository()
    profiles = ContactProfileService(repo)
    now = datetime.now(UTC)
    for profile_id, merged_into in (
        ("a", "b"),
        ("b", "a"),  # cycle
    ):
        repo.create_profile(
            ContactProfile(
                contact_profile_id=profile_id,
                display_name=profile_id.upper(),
                email=None,
                phone=None,
                created_at=now,
                updated_at=now,
                merged_into_id=merged_into,
            )
        )
    assert profiles.resolve_root_profile_id("a") in {"a", "b"}

    repo2 = InMemoryContactProfileRepository()
    profiles2 = ContactProfileService(repo2)
    for offset, profile_id, merged_into in (
        (0, "root", None),
        (1, "child", "root"),
        (2, "grandchild", "child"),
    ):
        repo2.create_profile(
            ContactProfile(
                contact_profile_id=profile_id,
                display_name=profile_id,
                email=None,
                phone=None,
                created_at=now + timedelta(seconds=offset),
                updated_at=now + timedelta(seconds=offset),
                merged_into_id=merged_into,
            )
        )
    assert profiles2.profile_ids_for_notes("grandchild") == [
        "root",
        "child",
        "grandchild",
    ]


def test_merge_roots_skips_missing_profile_ids() -> None:
    profiles = ContactProfileService(InMemoryContactProfileRepository())
    kept = profiles._ensure(  # noqa: SLF001
        [("inquiry", "keep")], display_name="Keep", email=None, phone=None
    )
    assert profiles._merge_roots([kept, "missing-root"]) == kept  # noqa: SLF001


def test_add_note_rejects_blank_profile_id() -> None:
    _profiles, notes = _services()
    with pytest.raises(ValueError, match="contact_profile_id"):
        notes.add_note("   ", category="Allgemein", note_text="x")


def test_in_memory_duplicate_profile_create_rejected() -> None:
    from datetime import UTC, datetime

    from catering_system.domain.contact_profile import ContactProfile

    repo = InMemoryContactProfileRepository()
    now = datetime.now(UTC)
    profile = ContactProfile(
        contact_profile_id="dup",
        display_name="Dup",
        email=None,
        phone=None,
        created_at=now,
        updated_at=now,
    )
    repo.create_profile(profile)
    with pytest.raises(KeyError):
        repo.create_profile(profile)


def test_sqlite_profile_search_and_from_connection(tmp_path: Path) -> None:
    db = tmp_path / "profiles.db"
    repo = SQLiteContactProfileRepository(db)
    profiles = ContactProfileService(repo)
    profile_id = profiles._ensure(  # noqa: SLF001
        [("email", "search@example.invalid"), ("phone", _PHONE)],
        display_name="SearchCo",
        email="search@example.invalid",
        phone=_PHONE,
    )
    other = profiles._ensure(  # noqa: SLF001
        [("email", "other@example.invalid")],
        display_name="OtherCo",
        email="other@example.invalid",
        phone=None,
    )

    assert set(repo.search_profile_ids("")) == {profile_id, other}
    assert repo.search_profile_ids("searchco") == [profile_id]
    assert repo.search_profile_ids("SEARCH@EXAMPLE.INVALID") == [profile_id]
    assert repo.search_profile_ids("017642795029") == [profile_id]
    assert repo.search_profile_ids(_PHONE) == [profile_id]
    assert repo.search_profile_ids("zzz-nichts") == []

    shared = sqlite3.connect(str(db))
    via_conn = SQLiteContactProfileRepository.from_connection(shared)
    assert via_conn.get_profile(profile_id) is not None
    assert via_conn.find_profile_id_by_alias("email", "search@example.invalid") == (
        profile_id
    )
    via_conn.update_profile_fields(
        via_conn.get_profile(profile_id)  # type: ignore[arg-type]
    )
    shared.close()
    repo.close()


def test_sqlite_notes_from_connection_and_empty_list(tmp_path: Path) -> None:
    db = tmp_path / "notes.db"
    conn = sqlite3.connect(str(db))
    notes = SQLiteContactInternalNoteRepository.from_connection(conn)
    assert notes.list_for_profiles([]) == []
    profiles = SQLiteContactProfileRepository.from_connection(conn)
    service = ContactProfileService(profiles)
    note_service = ContactInternalNoteService(notes, service, created_by="office-panel")
    profile_id = service._ensure(  # noqa: SLF001
        [("inquiry", "n1")], display_name="N", email=None, phone=None
    )
    note_service.add_note(profile_id, category="Allgemein", note_text="via conn")
    assert notes.list_for_profiles([profile_id])[0].note_text == "via conn"
    conn.close()


def test_sqlite_notes_migration_from_contact_key_preview(tmp_path: Path) -> None:
    db = tmp_path / "legacy_notes.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (component, version)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE contact_internal_notes (
            note_id TEXT PRIMARY KEY,
            contact_key TEXT NOT NULL,
            category TEXT NOT NULL,
            note_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO schema_migrations (component, version, name, applied_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            "contact_internal_notes",
            1,
            "create_contact_internal_notes",
            "2026-07-01T00:00:00Z",
        ),
    )
    conn.execute(
        """
        INSERT INTO contact_internal_notes
        (note_id, contact_key, category, note_text, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-1",
            "intake:email:old@example.invalid",
            "Allgemein",
            "legacy",
            "2026-07-01T00:00:00+00:00",
            "office-panel",
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteContactInternalNoteRepository(db)
    columns = {
        str(row[1])
        for row in repo._conn.execute(  # noqa: SLF001
            "PRAGMA table_info(contact_internal_notes)"
        )
    }
    assert "contact_profile_id" in columns
    assert "contact_key" not in columns
    assert repo.list_for_profiles(["any"]) == []
    repo.close()


def test_http_kontakte_search_query_and_no_results() -> None:
    note_repo = InMemoryContactInternalNoteRepository()
    profile_repo = InMemoryContactProfileRepository()
    panel, _key, _inquiry = _panel_with_contact(
        note_repo=note_repo, profile_repo=profile_repo, company="SearchHTTP"
    )
    server = create_office_panel_server(
        panel._inquiries,
        panel._orders,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        contact_note_repo=note_repo,
        contact_profile_repo=profile_repo,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, base, *_AUTH)
        opener = urllib.request.build_opener(
            urllib.request.HTTPBasicAuthHandler(password_mgr)
        )
        with opener.open(f"{base}/kontakte?q=SearchHTTP") as response:
            hit = response.read().decode()
        assert "SearchHTTP" in hit
        assert 'name="q" value="SearchHTTP"' in hit

        with opener.open(f"{base}/kontakte?q=zzz-nichts") as response:
            miss = response.read().decode()
        assert "Keine Kontakte für" in miss

        with opener.open(f"{base}/kontakte") as response:
            all_page = response.read().decode()
        assert "SearchHTTP" in all_page
        assert "Kontakte durchsuchen" in all_page
    finally:
        server.shutdown()
        server.server_close()


def test_ensure_profile_accepts_datetime_last_activity() -> None:
    from datetime import UTC, datetime

    panel, _key, _inquiry = _panel_with_contact()
    profile_id = panel._ensure_profile_for_contact_row(  # noqa: SLF001
        {
            "contact_key": "intake:email:dt@example.invalid",
            "identity_source": "intake_email",
            "display_name": "DateTime Row",
            "email": "dt@example.invalid",
            "phone": None,
            "inquiry_count": 1,
            "open_inquiries": 0,
            "active_orders": 0,
            "last_activity": datetime.now(UTC),
        }
    )
    assert profile_id
    assert (
        panel.contact_profile_service.find_by_alias("email", "dt@example.invalid")
        == profile_id
    )


def test_sqlite_append_only_rejects_delete(tmp_path: Path) -> None:
    db = tmp_path / "notes.db"
    profile_repo = SQLiteContactProfileRepository(db)
    note_repo = SQLiteContactInternalNoteRepository(db)
    profiles = ContactProfileService(profile_repo)
    notes = ContactInternalNoteService(note_repo, profiles, created_by="office-panel")
    profile_id = profiles._ensure(  # noqa: SLF001
        [("inquiry", "del")], display_name="X", email=None, phone=None
    )
    note = notes.add_note(profile_id, category="Allgemein", note_text="bleib")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        note_repo._conn.execute(  # noqa: SLF001
            "DELETE FROM contact_internal_notes WHERE note_id = ?",
            (note.note_id,),
        )
    profile_repo.close()
    note_repo.close()

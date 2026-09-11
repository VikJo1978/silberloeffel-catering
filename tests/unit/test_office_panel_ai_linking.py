from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from catering_system.domain.ai_telefon_call import AiTelefonCall
from catering_system.ui.office_panel_ai_runtime import (
    _link_candidates,
    _linked_target_exists,
)
from catering_system.ui.office_panel_ai_telefonist import (
    AiTelefonLinkCandidate,
    render_ai_telefon_call_detail,
)
from catering_system.ui.office_panel_views import OfficePageContext

_CALL_ID = "8e5d6ac1-1a43-49b0-8803-d76ac86a9666"
_INQUIRY_ID = "88d2656a-f17c-4686-9f91-b6b9bad20a7c"
_OFFER_ID = "25c49f5c-7b5d-44c0-9e82-7bbcb391897c"
_ORDER_ID = "b8e70476-13e2-4230-bbce-e2feaf09a2c6"


def _call() -> AiTelefonCall:
    received = datetime(2026, 9, 10, 18, 0, tzinfo=UTC)
    return AiTelefonCall(
        call_id=_CALL_ID,
        strato_id="9b03db78-d1bb-4866-b15e-2f92d99a4917",
        gmail_message_id="1a08c90969d6e2e2",
        caller_phone="+4917642795029",
        contact_name="Viktor Schmidt",
        email="",
        subject="Änderung eines bestehenden Angebots",
        summary="Bitte Gästezahl von 60 auf 70 ändern und zurückrufen.",
        raw_message="Zusammenfassung: Test",
        event_date=None,
        status="NEW",
        received_at=received,
        updated_at=received,
    )


def test_render_link_search_and_select_controls() -> None:
    context = OfficePageContext(csrf_token="csrf-token", employee_account_id="employee-1")
    candidate = AiTelefonLinkCandidate(
        linked_type="OFFER",
        linked_id=_OFFER_ID,
        title="Angebot · Viktor Schmidt",
        details="12.01.2027 · Hamburg · " + _OFFER_ID,
    )

    html = render_ai_telefon_call_detail(
        _call(),
        context=context,
        link_query="Schmidt",
        link_candidates=(candidate,),
    )

    assert "Mit bestehendem Vorgang verknüpfen" in html
    assert "Der gewählte Vorgang wird nicht verändert" in html
    assert 'name="q" value="Schmidt"' in html
    assert "Angebot · Viktor Schmidt" in html
    assert f'name="linked_id" value="{_OFFER_ID}"' in html
    assert 'name="linked_type" value="OFFER"' in html
    assert 'name="_csrf_token" value="csrf-token"' in html
    assert "Verknüpfen" in html


def test_render_link_search_empty_and_no_result_states() -> None:
    no_search = render_ai_telefon_call_detail(_call())
    no_result = render_ai_telefon_call_detail(_call(), link_query="Niemand")

    assert "Noch keine Suche ausgeführt" in no_search
    assert "Kein passender Vorgang gefunden" in no_result


def test_link_candidates_searches_inquiry_offer_and_order_context() -> None:
    inquiry = SimpleNamespace(
        inquiry_id=_INQUIRY_ID,
        event_date=date(2027, 1, 12),
        location_text="Hamburg",
        intake_subject="Änderung Viktor Schmidt",
        customer_snapshot=SimpleNamespace(
            contact_name="Viktor Schmidt",
            contact_phone="+4917642795029",
        ),
    )
    offer = SimpleNamespace(
        offer_id=_OFFER_ID,
        source_inquiry_id=_INQUIRY_ID,
        versions=(
            SimpleNamespace(
                version_number=1,
                event_date=date(2027, 1, 12),
                location_text="Hamburg",
            ),
        ),
    )
    order = SimpleNamespace(order_id=_ORDER_ID, source_inquiry_id=_INQUIRY_ID)
    order_version = SimpleNamespace(
        version_number=1,
        event_date=date(2027, 1, 12),
        location_text="Hamburg",
    )
    inquiry_repo = SimpleNamespace(list_all=lambda: [inquiry])
    offer_repo = SimpleNamespace(list_all=lambda: [offer])
    order_repo = SimpleNamespace(
        list_orders=lambda: [order],
        list_order_versions=lambda order_id: [order_version],
    )

    candidates = _link_candidates(
        "Schmidt",
        inquiry_repo,
        order_repo,
        offer_repo,
        allowed_types=frozenset({"INQUIRY", "OFFER", "ORDER"}),
    )

    assert [candidate.linked_type for candidate in candidates] == [
        "INQUIRY",
        "OFFER",
        "ORDER",
    ]
    assert all("Viktor Schmidt" in candidate.title for candidate in candidates)
    assert _link_candidates(
        "S",
        inquiry_repo,
        order_repo,
        offer_repo,
        allowed_types=frozenset({"INQUIRY", "OFFER", "ORDER"}),
    ) == ()
    order_only = _link_candidates(
        "Schmidt",
        inquiry_repo,
        order_repo,
        offer_repo,
        allowed_types=frozenset({"ORDER"}),
    )
    assert [candidate.linked_type for candidate in order_only] == ["ORDER"]


def test_link_target_existence_checks_real_repository_lookup() -> None:
    inquiry_repo = SimpleNamespace(
        get_by_id=lambda value: object() if value == _INQUIRY_ID else None
    )
    offer_repo = SimpleNamespace(get=lambda value: object() if value == _OFFER_ID else None)
    order_repo = SimpleNamespace(
        get_order=lambda value: object() if value == _ORDER_ID else None
    )

    assert _linked_target_exists(
        "INQUIRY", _INQUIRY_ID, inquiry_repo, order_repo, offer_repo
    )
    assert _linked_target_exists("OFFER", _OFFER_ID, inquiry_repo, order_repo, offer_repo)
    assert _linked_target_exists("ORDER", _ORDER_ID, inquiry_repo, order_repo, offer_repo)
    assert not _linked_target_exists(
        "OFFER", _OFFER_ID, inquiry_repo, order_repo, None
    )
    assert not _linked_target_exists("CONTACT", _INQUIRY_ID, inquiry_repo, order_repo, offer_repo)
    assert not _linked_target_exists("ORDER", "", inquiry_repo, order_repo, offer_repo)

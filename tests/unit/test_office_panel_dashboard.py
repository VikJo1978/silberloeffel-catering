from __future__ import annotations

from datetime import date, timedelta

from catering_system.ui.office_api_views import berlin_today

from catering_system.domain.work_center import WorkCenterSnapshot
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.office_panel import OfficePageContext, OfficePanel
from catering_system.ui.office_panel_dashboard import (
    ArbeitszentraleData,
    render_arbeitszentrale,
)


def _snapshot(**overrides: int) -> WorkCenterSnapshot:
    values = {
        "rueckrufe_open": 0,
        "missed_calls_open": 0,
        "offers_waiting": 0,
        "offers_accepted": 0,
        "upcoming_orders": 0,
        "open_tasks": 0,
        "today_calendar_entries": 0,
        "pending_order_changes": 0,
    }
    values.update(overrides)
    return WorkCenterSnapshot(**values)


def _task(
    *,
    category: str = "order_print",
    title: str = "Druck bestätigen",
    subtitle: str = "Business Lunch",
    entity_type: str = "order",
    entity_id: str = "order-1",
    action_label: str = "Auftrag öffnen",
    action_href: str = "/order/order-1",
) -> dict[str, object]:
    return {
        "task_id": f"{entity_type}:{entity_id}:{category}",
        "category": category,
        "title": title,
        "subtitle": subtitle,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action_label": action_label,
        "action_href": action_href,
        "due_at": None,
        "urgency": "normal",
        "opened_at": "2026-07-01T08:00:00+00:00",
    }


def _entry(
    *,
    event_date: str = "2026-07-20",
    title: str = "Business Lunch",
    entity_type: str = "order",
    entity_id: str = "order-1",
    guest_count: int | None = 28,
    time_window: str = "12:00",
) -> dict[str, object]:
    return {
        "entry_id": f"cal-{entity_id}",
        "entry_kind": "event_confirmed",
        "status_label": "Bestätigt",
        "title": title,
        "event_date": event_date,
        "time_window_text": time_window,
        "location_text": "Hamburg",
        "guest_count_estimate": guest_count,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action_label": "Auftrag öffnen",
        "action_href": f"/order/{entity_id}",
        "source_inquiry_id": "inq-1",
    }


def _data(**overrides: object) -> ArbeitszentraleData:
    values: dict[str, object] = {
        "context": OfficePageContext(csrf_token="csrf-real"),
        "today": date(2026, 7, 15),
        "snapshot": _snapshot(),
        "tasks": [],
        "calendar_entries": [],
        "contact_check_open": 0,
        "open_inquiries_open": 0,
        "kalender_view": "woche",
    }
    values.update(overrides)
    return ArbeitszentraleData(**values)  # type: ignore[arg-type]


def test_dashboard_header_title_subtitle_and_actions() -> None:
    page = render_arbeitszentrale(_data())

    assert "<h1>Heute im Büro</h1>" in page
    assert "Anfragen, Rückrufe und operative Aufgaben im Blick." in page
    assert 'href="/orders">Alle Aufträge</a>' in page
    assert 'href="/inquiry/new">+ Neue Anfrage</a>' in page
    assert "<form" not in page
    assert '<meta http-equiv="refresh" content="60">' in page
    assert "<script" not in page


def test_attention_cards_render_only_for_positive_counts() -> None:
    page = render_arbeitszentrale(
        _data(
            snapshot=_snapshot(rueckrufe_open=99, missed_calls_open=1),
            tasks=[_task(category="order_print")],
            contact_check_open=1,
            open_inquiries_open=1,
        )
    )

    assert "Was braucht Aufmerksamkeit?" in page
    assert "Rückrufe erforderlich" in page
    assert ">1</strong>" in page
    assert "Offene Anfragen" in page
    assert "Küchendruck" in page
    assert '<use href="#office-i-printer">' in page
    assert "Kundenprüfung" in page
    assert "Neue Anfragen" not in page
    assert "nächster Schritt" not in page


def test_attention_empty_state_without_any_counts() -> None:
    page = render_arbeitszentrale(_data())

    assert "Aktuell braucht nichts Aufmerksamkeit." in page
    assert '<article class="dashboard-attention-card">' not in page


def test_attention_cards_from_task_categories() -> None:
    page = render_arbeitszentrale(
        _data(
            open_inquiries_open=2,
            tasks=[
                _task(category="order_effective", entity_id="order-2"),
                _task(category="payment", entity_id="order-3"),
            ],
        )
    )

    assert "Offene Anfragen" in page
    assert "Anfragen prüfen" in page
    assert ">2</strong>" in page
    assert "Aufträge" in page
    assert "nächster Schritt" in page
    assert '<use href="#office-i-check">' in page
    assert "Küchendruck" not in page


def test_attention_separates_missed_calls_kundenpruefung_and_open_inquiries() -> None:
    page = render_arbeitszentrale(
        _data(
            snapshot=_snapshot(rueckrufe_open=1, missed_calls_open=15),
            contact_check_open=1,
            open_inquiries_open=1,
            tasks=[
                _task(
                    category="verify",
                    title="Kundenprüfung durchführen",
                    subtitle="Kontroll-Anfrage",
                    entity_type="inquiry",
                    entity_id="inq-1",
                    action_label="Anfrage öffnen",
                    action_href="/inquiry/inq-1",
                )
            ],
        )
    )

    assert (
        '<span class="dashboard-attention-name">Rückrufe</span><strong>15</strong>'
        in page
    )
    assert (
        '<span class="dashboard-attention-name">Kundenprüfung</span><strong>1</strong>'
        in page
    )
    assert (
        '<span class="dashboard-attention-name">Offene Anfragen</span><strong>1</strong>'
        in page
    )
    assert "Kundenprüfung durchführen" in page
    assert "Rückrufprüfung durchführen" not in page


def test_next_steps_lists_tasks_with_action_links() -> None:
    page = render_arbeitszentrale(
        _data(
            tasks=[
                _task(
                    category="verify",
                    title="Kundenprüfung durchführen",
                    subtitle="Müller GmbH",
                    entity_type="inquiry",
                    entity_id="i1",
                    action_label="Anfrage öffnen",
                    action_href="/inquiry/i1",
                )
            ]
        )
    )

    assert "Was als Nächstes ansteht" in page
    assert "Kundenprüfung durchführen" in page
    assert "Müller GmbH" in page
    assert 'href="/inquiry/i1">Anfrage öffnen</a>' in page


def test_next_steps_empty_state() -> None:
    page = render_arbeitszentrale(_data())
    assert "Keine offenen Schritte." in page


def test_events_join_next_step_from_tasks() -> None:
    page = render_arbeitszentrale(
        _data(
            tasks=[_task(category="order_print", entity_id="order-1")],
            calendar_entries=[
                _entry(event_date="2026-07-20", entity_id="order-1"),
                _entry(
                    event_date="2026-07-01",
                    entity_id="order-past",
                    title="Vergangenes Event",
                ),
            ],
        )
    )

    assert "Nächste Veranstaltungen" in page
    assert "Business Lunch" in page
    assert "28 Gäste" in page
    # joined next step from the matching task, not the bare status label
    assert "Druck bestätigen" in page
    # past events are not listed
    assert "Vergangenes Event" not in page


def test_events_fall_back_to_status_label() -> None:
    page = render_arbeitszentrale(_data(calendar_entries=[_entry(entity_id="order-9")]))
    assert "Bestätigt" in page


def test_calendar_week_strip_with_counts_and_toggle() -> None:
    page = render_arbeitszentrale(
        _data(calendar_entries=[_entry(event_date="2026-07-17")])
    )

    assert "dashboard-week-days" in page
    assert 'href="/?kalender=monat"' in page
    assert "Diese Woche" in page
    assert "Dieser Monat" in page
    # 2026-07-15 is a Wednesday; the 17th (Friday) carries one entry badge
    assert "<strong>17</strong><small>1</small>" in page
    assert 'id="diese-woche"' in page


def test_calendar_month_view() -> None:
    page = render_arbeitszentrale(
        _data(
            kalender_view="monat",
            calendar_entries=[_entry(event_date="2026-07-20")],
        )
    )

    assert "dashboard-month-days" in page
    assert "Juli 2026" in page
    assert ">20<small>1</small>" in page
    assert '<div class="dashboard-week-days">' not in page


def test_systemstatus_block_is_neutral_and_separate() -> None:
    page = render_arbeitszentrale(_data())

    assert "Systemstatus" in page
    assert "Website Intake" in page
    assert "Kiosk" in page
    assert "Drucker" in page
    assert "Keine Live-Prüfung eingerichtet." in page
    # no colored status classes inside the dashboard
    assert 'class="dashboard-service-state ok"' not in page
    assert 'class="dashboard-service-state unavailable"' not in page


def test_v2_panel_renders_new_dashboard() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 10, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Realer Testort",
        guest_count_estimate=12,
        planning_mode="caterer_suggestion",
        call_verification_required=True,
        call_verification_status="pending",
    )

    missed_calls = [{"call_id": f"c{i}", "phone": f"040{i}"} for i in range(15)]
    page = OfficePanel(inquiries, orders, ui_version="v2").render_queue(
        missed_calls,
        context=OfficePageContext(rueckruf_count=15, csrf_token="csrf"),
    )

    assert "<h1>Heute im Büro</h1>" in page
    assert (
        '<span class="dashboard-attention-name">Rückrufe</span><strong>15</strong>'
        in page
    )
    assert (
        '<span class="dashboard-attention-name">Kundenprüfung</span><strong>1</strong>'
        in page
    )
    assert (
        '<span class="dashboard-attention-name">Offene Anfragen</span><strong>1</strong>'
        in page
    )
    assert "Kundenprüfung durchführen" in page
    assert 'class="badge">15</span>' in page
    assert '<meta http-equiv="refresh" content="60">' in page
    assert "<script" not in page


def test_feature_flag_keeps_legacy_default_and_changes_only_dashboard() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    InquiryService(inquiries).create_inquiry(
        event_date=date.today(),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Realer Testort",
        guest_count_estimate=12,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )

    legacy = OfficePanel(inquiries, orders).render_queue([])
    v2 = OfficePanel(inquiries, orders, ui_version="v2").render_queue([])

    assert "Büro-Übersicht" in legacy
    assert "Heute im Büro" not in legacy
    assert '<meta http-equiv="refresh" content="60">' not in legacy
    assert "<h1>Heute im Büro</h1>" in v2
    assert "Arbeitszentrale" in v2
    assert '<meta http-equiv="refresh" content="60">' in v2


def test_v2_other_pages_do_not_auto_refresh() -> None:
    panel = _panel_with_order(berlin_today())

    for page in (
        panel.render_anfragen(),
        panel.render_auftraege(),
        panel.render_angebote(),
        panel.render_orders(),
    ):
        assert '<meta http-equiv="refresh" content="60">' not in page


# -- /orders (Alle Aufträge) -------------------------------------------------


def _panel_with_order(event_date: date) -> OfficePanel:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    panel = OfficePanel(inquiries, orders, ui_version="v2")
    inquiry = panel.inquiry_service.create_inquiry(
        event_date=event_date,
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="12:00",
        location_text="Hamburg",
        guest_count_estimate=28,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_subject="Business Lunch",
        contact_email="kunde@example.com",
        contact_phone="030 1234567",
    )
    panel.order_service.convert_inquiry_to_order(inquiry)
    return panel


def test_orders_view_lists_operative_row() -> None:
    panel = _panel_with_order(berlin_today())
    page = panel.render_orders()

    assert "Alle Aufträge" in page
    assert "Business Lunch" in page
    assert "28 Gäste" in page
    assert "Küchendruck bestätigen" in page
    assert ">Öffnen</a>" in page
    for label in ("Heute", "Diese Woche", "Dieser Monat", "Alle"):
        assert label in page
    # operative view stays narrow — exactly the six agreed columns
    assert page.count("<th>") == 6


def test_orders_view_zeitraum_filters_by_event_date() -> None:
    panel = _panel_with_order(berlin_today() + timedelta(days=400))

    assert "Business Lunch" in panel.render_orders()
    heute = panel.render_orders(zeitraum="heute")
    assert "Business Lunch" not in heute
    assert "keine Aufträge" in heute


def test_orders_view_heute_filter_matches_today() -> None:
    panel = _panel_with_order(berlin_today())
    page = panel.render_orders(zeitraum="heute")
    assert "Business Lunch" in page


def test_orders_view_search_by_kunde() -> None:
    panel = _panel_with_order(berlin_today())

    assert "Business Lunch" in panel.render_orders(q="business")
    assert "keine Aufträge" in panel.render_orders(q="zzz-nichts")

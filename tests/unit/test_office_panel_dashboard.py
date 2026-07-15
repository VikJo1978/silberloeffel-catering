from __future__ import annotations

from datetime import date

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
    WorkCenterDashboardUi,
    render_work_center_arbeitszentrale,
)


def _snapshot(**overrides: int) -> WorkCenterSnapshot:
    values = {
        "rueckrufe_open": 3,
        "missed_calls_open": 2,
        "offers_waiting": 2,
        "offers_accepted": 1,
        "upcoming_orders": 4,
        "open_tasks": 0,
        "today_calendar_entries": 0,
    }
    values.update(overrides)
    return WorkCenterSnapshot(**values)


def _ui(*, week_order_count: int = 4) -> WorkCenterDashboardUi:
    return WorkCenterDashboardUi(
        context=OfficePageContext(csrf_token="csrf-real"),
        today=date(2026, 7, 15),
        week_order_count=week_order_count,
    )


def test_work_center_dashboard_renders_cards_and_links() -> None:
    page = render_work_center_arbeitszentrale(_snapshot(), ui=_ui())

    assert "<h1>Arbeitszentrale</h1>" in page
    assert "Rückrufe" in page
    assert "<strong>5</strong> offen" in page
    assert "Kunden-Rückrufe" in page
    assert "Verpasste Anrufe" in page
    assert 'href="/rueckruf"' in page
    assert "2 warten auf Antwort" in page
    assert "1 angenommen" in page
    assert 'href="/angebote"' in page
    assert "4 diese Woche" in page
    assert 'href="/auftraege"' in page
    assert "Keine offenen Aufgaben" in page
    assert 'href="/aufgaben"' in page
    assert "Keine Termine heute" in page
    assert "<form" not in page
    assert "<script" not in page


def test_work_center_dashboard_placeholder_sections_when_counts_present() -> None:
    page = render_work_center_arbeitszentrale(
        _snapshot(open_tasks=2, today_calendar_entries=1),
        ui=_ui(),
    )

    assert "2 offene Aufgaben" in page
    assert 'href="/aufgaben"' in page
    assert "1 Termine heute" in page


def test_v2_panel_uses_work_center_snapshot() -> None:
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

    page = OfficePanel(inquiries, orders, ui_version="v2").render_queue(
        [{"call_id": "c1", "phone": "0401"}]
    )

    assert '<div class="wc-page">' in page
    assert "Kunden-Rückrufe" in page
    assert "Verpasste Anrufe" in page


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
    assert '<div class="wc-page">' not in legacy
    assert '<div class="wc-page">' in v2
    assert "Arbeitszentrale" in v2

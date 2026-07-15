from __future__ import annotations

import re
from datetime import date

import pytest

from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.office_panel import OfficePageContext, OfficePanel
from catering_system.ui.office_panel_dashboard import (
    DashboardUi,
    render_arbeitszentrale,
)


def _view(*, truncated: bool = False) -> dict[str, object]:
    return {
        "attention": {
            "neue_anfragen": 1,
            "druck_fehlt": 1,
            "nicht_wirksam": 1,
            "versand_blockiert": 1,
            "storniert": 0,
        },
        "week": {
            "iso_year": 2026,
            "iso_week": 42,
            "entries": [
                {
                    "order_id": "order-real-001",
                    "event_date": "2026-10-13",
                    "time_window_text": "12:00–14:00",
                    "location_text": "Vorhandener Ort",
                    "guest_count_estimate": 24,
                }
            ],
            "total_count": 2 if truncated else 1,
            "truncated": truncated,
        },
        "neue_anfragen_top": [
            {
                "inquiry_id": "inquiry-real-001",
                "event_date": "2026-10-20",
                "created_at": "2026-10-01T10:00:00+00:00",
                "updated_at": "2026-10-01T10:00:00+00:00",
                "inquiry_source": "email",
                "crm_stage": "Neue Anfrage",
                "time_window_text": "abends",
                "location_text": "Bestehender Ort",
                "guest_count_estimate": None,
                "planning_mode": "caterer_suggestion",
                "call_verification_required": False,
                "call_verification_status": "not_required",
                "next_action": "convert",
            }
        ],
        "auftraege_top": [
            {
                "order_id": "order-real-001",
                "source_inquiry_id": "inquiry-real-001",
                "created_at": "2026-10-01T10:00:00+00:00",
                "updated_at": "2026-10-01T10:00:00+00:00",
                "candidate_order_version_id": "version-real-001",
                "effective_order_version_id": None,
                "cancelled_at": None,
                "blocker_reason": "no_effective_version",
                "next_action": {
                    "action": "print-confirm",
                    "order_version_id": "version-real-001",
                },
            }
        ],
    }


def _ui(
    *,
    callbacks: list[dict] | None = None,
    callback_error: str | None = None,
) -> DashboardUi:
    return DashboardUi(
        context=OfficePageContext(csrf_token="csrf-real"),
        command_fields=lambda _expect: (
            '<input type="hidden" name="_command_id" value="command-real">'
        ),
        callbacks=callbacks,
        callback_error=callback_error,
        kiosk_url="",
        today=date(2026, 10, 13),
    )


def test_dashboard_uses_queue_view_without_demo_content() -> None:
    page = render_arbeitszentrale(_view(), ui=_ui(callbacks=[]))

    assert "Heute im Büro" in page
    assert "Vorhandener Ort" in page
    assert "Bestehender Ort" in page
    assert "Auftrag order-re" in page
    assert "Silberlöffel Event Catering Service" in page
    assert "Möbel &amp; Mehr" not in page
    assert "Hanseatic Consulting" not in page
    assert "040 12345" not in page
    assert "<script" not in page


def test_callback_empty_and_unavailable_are_visually_distinct() -> None:
    empty = render_arbeitszentrale(_view(), ui=_ui(callbacks=[]))
    unavailable = render_arbeitszentrale(
        _view(),
        ui=_ui(callbacks=None, callback_error="connection refused"),
    )

    assert "0 offen" in empty
    assert "Keine offenen Rückrufe" in empty
    assert "Dienst nicht erreichbar" not in empty
    assert "Dienst nicht erreichbar" in unavailable
    assert "0 offen" not in unavailable
    assert "connection refused" not in unavailable


def test_dashboard_preserves_csrf_and_remote_command_fields() -> None:
    page = render_arbeitszentrale(_view(), ui=_ui(callbacks=[]))
    forms = re.findall(r"<form.*?</form>", page)

    assert len(forms) == 2
    assert all('name="_csrf_token" value="csrf-real"' in form for form in forms)
    assert all('name="_command_id" value="command-real"' in form for form in forms)
    assert 'action="/inquiry/inquiry-real-001/convert"' in page
    assert 'action="/order/order-real-001/print-confirm"' in page


def test_dashboard_reports_truncated_week_truthfully() -> None:
    page = render_arbeitszentrale(_view(truncated=True), ui=_ui(callbacks=[]))

    assert "Ansicht unvollständig" in page
    assert "1 von 2 Aufträgen" in page


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
    assert '<div class="dashboard-page-header">' not in legacy
    assert "Heute im Büro" in v2
    assert "Realer Testort" in v2


def test_unknown_ui_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="ui_version"):
        OfficePanel(
            InMemoryInquiryRepository(),
            InMemoryOrderRepository(),
            ui_version="unknown",
        )

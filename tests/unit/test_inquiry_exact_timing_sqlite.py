from __future__ import annotations

from datetime import date, time

from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService


def test_sqlite_inquiry_exact_timing_round_trip_and_update(tmp_path) -> None:
    db = tmp_path / "core.db"
    repo = SQLiteInquiryRepository(db)
    service = InquiryService(repo)

    inquiry = service.create_inquiry(
        event_date=date(2026, 9, 15),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="legacy historical text",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        event_start_local=time(18, 0),
        delivery_time_local=time(16, 30),
    )
    inquiry_id = inquiry.inquiry_id
    repo.close()

    reopened = SQLiteInquiryRepository(db)
    stored = reopened.get_by_id(inquiry_id)
    assert stored is not None
    assert stored.event_start_local == time(18, 0)
    assert stored.delivery_time_local == time(16, 30)
    assert stored.time_window_text == "legacy historical text"

    updated = InquiryService(reopened).update_inquiry(
        inquiry_id,
        event_start_local=time(19, 15),
        delivery_time_local=time(17, 0),
    )
    assert updated.event_start_local == time(19, 15)
    assert updated.delivery_time_local == time(17, 0)
    assert updated.time_window_text == "legacy historical text"
    reopened.close()

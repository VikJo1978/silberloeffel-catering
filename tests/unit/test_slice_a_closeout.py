"""Slice A closeout package — §8 / HubSpot boundary / events."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from catering_system.domain.inquiry import CALL_VERIFICATION_STATUSES, CRM_PIPELINE, PLANNING_MODES
from catering_system.domain.slice_a_events import CustomerCallVerified, InquiryCreated, InquiryUpdated
from catering_system.integration.hubspot_office_intake import (
    HUBSPOT_PRIVATE_APP_TOKEN_ENV,
    HubSpotOfficeInquiryNoop,
    HubSpotOfficeCredentials,
)
from catering_system.intake.external_secure_intake_layer import normalize_public_wix_inquiry_payload
from catering_system.repositories.in_memory_inquiry_repository import InMemoryInquiryRepository
from catering_system.services.inquiry_service import InquiryService


def test_normalize_public_wix_strips_text_fields() -> None:
    raw = {
        "event_date": date(2026, 7, 1),
        "time_window_text": "  abends  ",
        "location_text": " Berlin ",
    }
    out = normalize_public_wix_inquiry_payload(raw)
    assert out["time_window_text"] == "abends"
    assert out["location_text"] == "Berlin"


def test_hubspot_token_only_from_env_name_documented() -> None:
    assert HUBSPOT_PRIVATE_APP_TOKEN_ENV == "HUBSPOT_PRIVATE_APP_TOKEN"
    assert HubSpotOfficeCredentials.private_app_token_from_env() is None or isinstance(
        HubSpotOfficeCredentials.private_app_token_from_env(), str
    )


def test_hubspot_noop_sync_runs() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = svc.create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="x",
        location_text="y",
        guest_count_estimate=None,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
    )
    HubSpotOfficeInquiryNoop().sync_inquiry_from_core(q)


def test_event_sink_create_and_update_and_verify() -> None:
    seen: list[object] = []
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo, event_sink=seen.append)
    q = svc.create_inquiry(
        event_date=date(2026, 9, 1),
        inquiry_source="phone",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="a",
        location_text="b",
        guest_count_estimate=10,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=True,
        call_verification_status=CALL_VERIFICATION_STATUSES[1],
    )
    assert seen[0] == InquiryCreated(inquiry_id=q.inquiry_id)
    svc.update_inquiry(q.inquiry_id, time_window_text="evening")
    assert seen[1] == InquiryUpdated(inquiry_id=q.inquiry_id)
    svc.verify_customer_by_call(q.inquiry_id)
    assert seen[2] == InquiryUpdated(inquiry_id=q.inquiry_id)
    assert seen[3] == CustomerCallVerified(inquiry_id=q.inquiry_id)

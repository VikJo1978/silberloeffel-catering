"""Unit tests — HubSpot HTTP client (INTEGRATION_DEPLOYMENT_EXECUTION_PACK_V1 §2). No live network."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.integration.hubspot_office_intake import (
    HUBSPOT_PRIVATE_APP_TOKEN_ENV,
    HubSpotOfficeInquiryPort,
)
from catering_system.integration.hubspot_office_intake_http import (
    HUBSPOT_API_BASE,
    HUBSPOT_INQUIRY_OBJECT_PATH,
    HubSpotOfficeInquiryHttp,
    inquiry_to_hubspot_properties,
)


def _sample_inquiry() -> Inquiry:
    now = datetime.now(timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="wix_form",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
    )


def test_missing_token_raises_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HUBSPOT_PRIVATE_APP_TOKEN_ENV, raising=False)
    with pytest.raises(ValueError, match=HUBSPOT_PRIVATE_APP_TOKEN_ENV):
        HubSpotOfficeInquiryHttp(transport=lambda *a: b"")


def test_sync_sends_documented_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HUBSPOT_PRIVATE_APP_TOKEN_ENV, "test-token")
    calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def fake_transport(url: str, method: str, headers: dict[str, str], body: bytes) -> bytes:
        calls.append((url, method, headers, body))
        return b"{}"

    client = HubSpotOfficeInquiryHttp(transport=fake_transport)
    assert isinstance(client, HubSpotOfficeInquiryPort)
    inquiry = _sample_inquiry()
    client.sync_inquiry_from_core(inquiry)

    assert len(calls) == 1
    url, method, headers, body = calls[0]
    assert url == f"{HUBSPOT_API_BASE}{HUBSPOT_INQUIRY_OBJECT_PATH}"
    assert method == "POST"
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["Content-Type"] == "application/json"
    payload = json.loads(body)
    assert payload == {"properties": inquiry_to_hubspot_properties(inquiry)}


def test_property_mapping_mirrors_frozen_inquiry() -> None:
    inquiry = _sample_inquiry()
    props = inquiry_to_hubspot_properties(inquiry)
    assert props["core_inquiry_id"] == inquiry.inquiry_id
    assert props["core_crm_stage"] == inquiry.crm_stage  # plain text, no invented stage ids
    assert props["core_event_date"] == "2026-10-01"
    assert props["core_guest_count"] == "25"
    assert props["dealname"] == "Anfrage 2026-10-01 Hamburg"
    assert all(isinstance(v, str) for v in props.values())


def test_property_mapping_handles_missing_guest_count() -> None:
    inquiry = _sample_inquiry()
    from dataclasses import replace

    props = inquiry_to_hubspot_properties(replace(inquiry, guest_count_estimate=None))
    assert props["core_guest_count"] == ""


def test_token_never_appears_in_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HUBSPOT_PRIVATE_APP_TOKEN_ENV, "super-secret")
    seen: list[bytes] = []
    client = HubSpotOfficeInquiryHttp(
        transport=lambda url, m, h, body: seen.append(body) or b"{}"
    )
    client.sync_inquiry_from_core(_sample_inquiry())
    assert b"super-secret" not in seen[0]

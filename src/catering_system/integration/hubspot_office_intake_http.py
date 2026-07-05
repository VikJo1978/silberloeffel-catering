"""HubSpot office-facing HTTP client — INTEGRATION_DEPLOYMENT_EXECUTION_PACK_V1 §1.

Implements the existing HubSpotOfficeInquiryPort with stdlib urllib. Transport
is injectable so unit tests never touch the network. Token comes strictly from
the process environment (HUBSPOT_PRIVATE_APP_TOKEN) — never from a caller
parameter that could be fed from browser input.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable
from typing import Any

from catering_system.domain.inquiry import Inquiry
from catering_system.integration.hubspot_office_intake import (
    HUBSPOT_PRIVATE_APP_TOKEN_ENV,
    HubSpotOfficeCredentials,
)

_log = logging.getLogger(__name__)

HUBSPOT_API_BASE = "https://api.hubapi.com"
# Office-facing CRM visibility object. MVP pushes deals whose properties mirror
# the Core inquiry; pipeline/stage id mapping is HubSpot-portal configuration,
# not domain logic, so crm_stage travels as plain text.
HUBSPOT_INQUIRY_OBJECT_PATH = "/crm/v3/objects/deals"

# Transport signature: (url, method, headers, body) -> response body bytes.
Transport = Callable[[str, str, dict[str, str], bytes], bytes]


def inquiry_to_hubspot_properties(inquiry: Inquiry) -> dict[str, str]:
    """Explicit, flat property mapping; the frozen inquiry stays the source of truth."""
    return {
        "dealname": f"Anfrage {inquiry.event_date.isoformat()} {inquiry.location_text}".strip(),
        "core_inquiry_id": inquiry.inquiry_id,
        "core_crm_stage": inquiry.crm_stage,
        "core_inquiry_source": inquiry.inquiry_source,
        "core_event_date": inquiry.event_date.isoformat(),
        "core_time_window": inquiry.time_window_text,
        "core_location": inquiry.location_text,
        "core_guest_count": (
            str(inquiry.guest_count_estimate) if inquiry.guest_count_estimate is not None else ""
        ),
        "core_planning_mode": inquiry.planning_mode,
        "core_call_verification_status": inquiry.call_verification_status,
    }


def _urllib_transport(url: str, method: str, headers: dict[str, str], body: bytes) -> bytes:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


class HubSpotOfficeInquiryHttp:
    """Office-facing push of Core Inquiry state into HubSpot (CRM visibility, not kitchen truth)."""

    def __init__(self, *, transport: Transport | None = None) -> None:
        token = HubSpotOfficeCredentials.private_app_token_from_env()
        if not token:
            raise ValueError(
                f"HubSpot office intake requires {HUBSPOT_PRIVATE_APP_TOKEN_ENV} in the "
                "process environment; use HubSpotOfficeInquiryNoop where a no-op is intended"
            )
        self._token = token
        self._transport = transport if transport is not None else _urllib_transport

    def sync_inquiry_from_core(self, inquiry: Inquiry) -> None:
        payload: dict[str, Any] = {"properties": inquiry_to_hubspot_properties(inquiry)}
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        url = f"{HUBSPOT_API_BASE}{HUBSPOT_INQUIRY_OBJECT_PATH}"
        self._transport(url, "POST", headers, body)
        _log.info("hubspot sync_inquiry_from_core inquiry_id=%s", inquiry.inquiry_id)

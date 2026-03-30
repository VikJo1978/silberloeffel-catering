"""HubSpot office-facing inquiry baseline — Slice A (pack §3.1, §8.3, §11).

HubSpot Private App tokens and API calls MUST live server-side or in trusted office
automation only. No browser code in this repository loads HubSpot secrets; the
browser never receives a path to embed those secrets (§11 HubSpot exposure rule).
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from catering_system.domain.inquiry import Inquiry


HUBSPOT_PRIVATE_APP_TOKEN_ENV = "HUBSPOT_PRIVATE_APP_TOKEN"


@runtime_checkable
class HubSpotOfficeInquiryPort(Protocol):
    """Office-facing sync of Core Inquiry state into HubSpot (CRM visibility, not kitchen truth)."""

    def sync_inquiry_from_core(self, inquiry: Inquiry) -> None:
        """Push or update HubSpot-side inquiry representation from Core inquiry."""
        ...


class HubSpotOfficeCredentials:
    """Secrets sourced only from process environment — never from browser or untrusted input."""

    @staticmethod
    def private_app_token_from_env() -> str | None:
        return os.environ.get(HUBSPOT_PRIVATE_APP_TOKEN_ENV)


class HubSpotOfficeInquiryNoop(HubSpotOfficeInquiryPort):
    """Baseline stub: boundary exists; real HTTP is deferred to deployment wiring."""

    def sync_inquiry_from_core(self, inquiry: Inquiry) -> None:
        _ = inquiry
        return None

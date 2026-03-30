"""External Secure Intake Layer — Slice A baseline (SLICE_A_EXECUTION_PACK_V1 §8).

This module is the explicit Python-side contract for the frozen architectural role.
Production may place validation/proxy logic in a Cloudflare Worker; Core receives
payloads only after this boundary (public browser → Worker → office/Core), never
with HubSpot private credentials in the browser.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class ExternalSecureIntakeLayerPort(Protocol):
    """Receives external inquiry-shaped input, normalizes, forwards toward Core."""

    def normalize_public_inquiry_payload(
        self, raw: Mapping[str, Any]
    ) -> dict[str, Any]: ...


def normalize_public_wix_inquiry_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate/sanitize/minimally normalize before wix_form adapter (§8.2).

    Does not add secrets; strips user-controlled text fields; copies to a new dict.
    """
    out: dict[str, Any] = dict(raw)
    for key in ("time_window_text", "location_text"):
        v = out.get(key)
        if isinstance(v, str):
            out[key] = v.strip()
    return out

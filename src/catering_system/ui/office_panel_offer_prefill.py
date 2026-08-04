"""Read-only Inquiry -> configurator offer-prefill handoff."""

from __future__ import annotations

import base64
import json
from urllib.parse import urlsplit, urlunsplit

from catering_system.domain.inquiry import Inquiry
from catering_system.intake.intake_contact import labelled_intake_context

OFFER_PREFILL_SCHEMA_VERSION = "core_inquiry_offer_prefill_v1"
_FRAGMENT_KEY = "core-inquiry"
_HANDOFF_FRAGMENT_KEY = "core-handoff"
_MAX_SHORT_TEXT = 500
_MAX_REMARKS = 4000


def normalize_configurator_url(raw: str) -> str:
    """Validate the optional office-configured target; empty keeps the feature dormant."""
    value = raw.strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("CONFIGURATOR_URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("CONFIGURATOR_URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("CONFIGURATOR_URL must not contain query or fragment data")
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _clip(value: str | None, limit: int = _MAX_SHORT_TEXT) -> str:
    return (value or "").strip()[:limit]


def _contact_prefill_value(
    structured_value: str | None, labelled_fallback: str | None
) -> str:
    """Prefer the Inquiry's structured customer fact; retain legacy intake fallback."""
    return _clip(structured_value) or _clip(labelled_fallback)


def offer_prefill_payload(inquiry: Inquiry) -> dict[str, object]:
    """Build proposal-phase copy only; this performs no Core write."""
    labelled, remaining = labelled_intake_context(inquiry.intake_message)
    customer = inquiry.customer_snapshot
    context_parts = []
    if inquiry.intake_subject:
        context_parts.append(f"Betreff: {_clip(inquiry.intake_subject, 1000)}")
    if labelled.get("Wunsch"):
        context_parts.append(f"Wunsch: {_clip(labelled['Wunsch'], 2000)}")
    if remaining:
        context_parts.append(_clip("\n".join(remaining), 2000))
    if inquiry.intake_summary:
        context_parts.append(f"Zusammenfassung: {_clip(inquiry.intake_summary, 1000)}")
    remarks = _clip("\n\n".join(context_parts), _MAX_REMARKS)

    return {
        "schema_version": OFFER_PREFILL_SCHEMA_VERSION,
        "source": "silberloeffel-core",
        "inquiry_id": inquiry.inquiry_id,
        "transfer": {
            "planning": {
                "persons": inquiry.guest_count_estimate,
                "budget": None,
                "budgetEnabled": False,
                "desiredModules": [],
                "dietaryRequirements": "",
                "eventType": _clip(labelled.get("Veranstaltungsart")),
                "serviceStyle": "",
            },
            "orderContextPrefill": {
                "companyName": _contact_prefill_value(
                    customer.company_name if customer is not None else None,
                    labelled.get("Firma"),
                ),
                "contactPerson": _contact_prefill_value(
                    customer.contact_name if customer is not None else None,
                    labelled.get("Name"),
                ),
                "email": _contact_prefill_value(
                    customer.email if customer is not None else None,
                    labelled.get("E-Mail"),
                ),
                "phone": _contact_prefill_value(
                    customer.phone if customer is not None else None,
                    labelled.get("Telefon"),
                ),
                "eventDate": inquiry.event_date.isoformat(),
                "eventTime": _clip(inquiry.time_window_text),
                "location": _clip(inquiry.location_text),
                "billingAddress": "",
                "remarks": remarks,
            },
        },
    }


def build_offer_prefill_url(configurator_url: str, inquiry: Inquiry) -> str:
    base_url = normalize_configurator_url(configurator_url)
    if not base_url:
        return ""
    raw = json.dumps(
        offer_prefill_payload(inquiry),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{base_url}#{_FRAGMENT_KEY}={encoded}"


def build_configurator_handoff_url(configurator_url: str, code: str) -> str:
    base_url = normalize_configurator_url(configurator_url)
    if not base_url:
        return ""
    return f"{base_url}#{_HANDOFF_FRAGMENT_KEY}={code}"

"""Preliminary commercial guidance for incomplete catering event facts.

A Richtangebot is deliberately not a normal Offer. It may carry fuzzy date/time
and guest-count information and must remain explicitly non-binding until the
missing event facts are clarified and a normal Inquiry/Offer can be created.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Literal

RichtangebotStatus = Literal["DRAFT", "SUPERSEDED", "CLOSED"]
RICHTANGEBOT_STATUSES = frozenset({"DRAFT", "SUPERSEDED", "CLOSED"})

DEFAULT_RICHTANGEBOT_DISCLAIMER = (
    "Dieses unverbindliche Richtangebot dient ausschließlich zur ersten Budget- "
    "und Leistungsorientierung. Preise, Verfügbarkeit und Leistungsumfang stehen "
    "unter dem Vorbehalt der finalen Termin-, Zeit-, Gästezahl- und Leistungsabstimmung. "
    "Ein verbindliches Angebot erstellen wir nach Klärung der noch offenen Angaben."
)

_MAX_TEXT = 20_000
_MAX_SHORT_TEXT = 500
_MAX_GUEST_COUNT = 2_000
_MAX_BUDGET_CENTS = 100_000_000


@dataclass(frozen=True)
class Richtangebot:
    richtangebot_id: str
    source_call_id: str
    created_at: datetime
    updated_at: datetime
    contact_name: str = ""
    caller_phone: str = ""
    email: str = ""
    event_type: str = ""
    event_date: date | None = None
    event_date_text: str = ""
    event_start: time | None = None
    event_time_text: str = ""
    guest_count: int | None = None
    guest_count_min: int | None = None
    guest_count_max: int | None = None
    location: str = ""
    budget_per_person_cents: int | None = None
    budget_total_cents: int | None = None
    customer_request: str = ""
    disclaimer: str = DEFAULT_RICHTANGEBOT_DISCLAIMER
    status: RichtangebotStatus = "DRAFT"


def validate_richtangebot(value: Richtangebot) -> Richtangebot:
    rid = _uuid4(value.richtangebot_id, "richtangebot_id")
    source_call_id = _uuid4(value.source_call_id, "source_call_id")
    created_at = _utc_datetime(value.created_at, "created_at")
    updated_at = _utc_datetime(value.updated_at, "updated_at")
    if updated_at < created_at:
        raise ValueError("updated_at must not be earlier than created_at")

    contact_name = _text(value.contact_name, _MAX_SHORT_TEXT)
    caller_phone = _text(value.caller_phone, _MAX_SHORT_TEXT)
    email = _text(value.email, _MAX_SHORT_TEXT)
    event_type = _text(value.event_type, _MAX_SHORT_TEXT)
    event_date_text = _text(value.event_date_text, _MAX_SHORT_TEXT)
    event_time_text = _text(value.event_time_text, _MAX_SHORT_TEXT)
    location = _text(value.location, _MAX_SHORT_TEXT)
    customer_request = _text(value.customer_request, _MAX_TEXT)
    disclaimer = _required_text(value.disclaimer, "disclaimer", _MAX_TEXT)

    if value.event_start is not None:
        if not isinstance(value.event_start, time):
            raise TypeError("event_start must be time or null")
        if value.event_start.tzinfo is not None:
            raise ValueError("event_start must be local wall-clock time")

    guest_count = _guest(value.guest_count, "guest_count")
    guest_min = _guest(value.guest_count_min, "guest_count_min")
    guest_max = _guest(value.guest_count_max, "guest_count_max")
    if guest_count is not None and (guest_min is not None or guest_max is not None):
        raise ValueError("exact guest_count cannot be combined with a guest range")
    if (guest_min is None) != (guest_max is None):
        raise ValueError("guest_count_min and guest_count_max must be set together")
    if guest_min is not None and guest_max is not None and guest_min > guest_max:
        raise ValueError("guest_count_min must not exceed guest_count_max")

    budget_pp = _budget(value.budget_per_person_cents, "budget_per_person_cents")
    budget_total = _budget(value.budget_total_cents, "budget_total_cents")

    if value.status not in RICHTANGEBOT_STATUSES:
        raise ValueError("invalid Richtangebot status")

    # It is a commercial orientation, so at least one customer contact route and
    # one event/commercial fact must exist. Missing exactness is allowed; absence
    # of all useful facts is not.
    if not (contact_name or caller_phone or email):
        raise ValueError("Richtangebot requires customer contact context")
    if not any(
        (
            event_type,
            value.event_date,
            event_date_text,
            value.event_start,
            event_time_text,
            guest_count,
            guest_min,
            location,
            budget_pp,
            budget_total,
            customer_request,
        )
    ):
        raise ValueError("Richtangebot requires at least one event or commercial fact")

    return replace(
        value,
        richtangebot_id=rid,
        source_call_id=source_call_id,
        contact_name=contact_name,
        caller_phone=caller_phone,
        email=email,
        event_type=event_type,
        event_date_text=event_date_text,
        event_time_text=event_time_text,
        location=location,
        customer_request=customer_request,
        disclaimer=disclaimer,
        guest_count=guest_count,
        guest_count_min=guest_min,
        guest_count_max=guest_max,
        budget_per_person_cents=budget_pp,
        budget_total_cents=budget_total,
    )


def _uuid4(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID string") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{field} must be a canonical UUID4 string")
    return value


def _utc_datetime(value: datetime, field: str) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")
    return value


def _text(value: object, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("text field must be a string")
    return value.strip()[:max_len]


def _required_text(value: object, field: str, max_len: int) -> str:
    text = _text(value, max_len)
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


def _guest(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int or null")
    if not 1 <= value <= _MAX_GUEST_COUNT:
        raise ValueError(f"{field} must be between 1 and {_MAX_GUEST_COUNT}")
    return value


def _budget(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int or null")
    if not 0 <= value <= _MAX_BUDGET_CENTS:
        raise ValueError(f"{field} is outside the accepted range")
    return value

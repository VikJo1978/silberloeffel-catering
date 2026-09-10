"""Parsing and normalization for STRATO Smart-Telefonassistent summary mail.

The outer mail format is parsed deterministically. Semantic fields from the
free-text summary are accepted separately from an LLM and validated here so
missing values stay missing instead of being invented by transport code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

_STRATO_FIELDS = ("Anrufer", "Name", "Telefonnummer", "Betreff", "Zusammenfassung", "ID")
_MAX_GUEST_COUNT = 2000


@dataclass(frozen=True)
class StratoSummaryMail:
    caller: str
    name: str
    phone: str
    subject: str
    summary: str
    strato_id: str
    raw_text: str


@dataclass(frozen=True)
class StructuredCallFacts:
    email: str = ""
    event_type: str = ""
    event_date: date | None = None
    event_period: str = ""
    event_start: time | None = None
    guest_count: int | None = None
    location: str = ""
    budget_per_person_cents: int | None = None
    fulfillment_mode: str = "UNKNOWN"
    customer_request: str = ""
    callback_requested: bool | None = None
    callback_date: date | None = None
    callback_time: time | None = None


def parse_strato_summary_mail(raw_text: str) -> StratoSummaryMail:
    if not isinstance(raw_text, str):
        raise TypeError("raw_text must be a string")
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise ValueError("STRATO mail is empty")

    values: dict[str, str] = {}
    current: str | None = None
    buffers: dict[str, list[str]] = {field: [] for field in _STRATO_FIELDS}
    field_pattern = re.compile(
        r"^(Anrufer|Name|Telefonnummer|Betreff|Zusammenfassung|ID)\s*:\s*(.*)$",
        re.IGNORECASE,
    )
    canonical = {field.lower(): field for field in _STRATO_FIELDS}

    for line in text.split("\n"):
        match = field_pattern.match(line.strip())
        if match:
            current = canonical[match.group(1).lower()]
            buffers[current].append(match.group(2).strip())
            continue
        if current is not None:
            buffers[current].append(line.rstrip())

    for field, lines in buffers.items():
        values[field] = "\n".join(lines).strip()

    summary = values["Zusammenfassung"]
    strato_id = values["ID"]
    if not summary:
        raise ValueError("STRATO mail has no Zusammenfassung")
    if not strato_id:
        raise ValueError("STRATO mail has no ID")

    caller = values["Anrufer"]
    phone = values["Telefonnummer"] or caller
    return StratoSummaryMail(
        caller=caller,
        name=values["Name"],
        phone=_normalize_phone(phone),
        subject=values["Betreff"],
        summary=summary,
        strato_id=strato_id,
        raw_text=text,
    )


def structured_call_facts_from_mapping(raw: Mapping[str, Any]) -> StructuredCallFacts:
    if not isinstance(raw, Mapping):
        raise TypeError("structured call facts must be a mapping")

    return StructuredCallFacts(
        email=_text(raw.get("email")),
        event_type=_text(raw.get("event_type")),
        event_date=_optional_date(raw.get("event_date"), "event_date"),
        event_period=_text(raw.get("event_period")),
        event_start=_optional_time(raw.get("event_start"), "event_start"),
        guest_count=_optional_guest_count(raw.get("guest_count")),
        location=_text(raw.get("location")),
        budget_per_person_cents=_optional_budget_cents(
            raw.get("budget_per_person")
            if "budget_per_person" in raw
            else raw.get("budget_per_person_cents"),
            already_cents="budget_per_person" not in raw,
        ),
        fulfillment_mode=_fulfillment(raw.get("fulfillment_mode")),
        customer_request=_text(raw.get("customer_request")),
        callback_requested=_optional_bool(
            raw.get("callback_requested"), "callback_requested"
        ),
        callback_date=_optional_date(raw.get("callback_date"), "callback_date"),
        callback_time=_optional_time(raw.get("callback_time"), "callback_time"),
    )


def llm_extraction_contract() -> dict[str, object]:
    """Small JSON contract suitable for any strict JSON-capable LLM client."""
    return {
        "email": None,
        "event_type": None,
        "event_date": None,
        "event_period": None,
        "event_start": None,
        "guest_count": None,
        "location": None,
        "budget_per_person": None,
        "fulfillment_mode": "UNKNOWN",
        "customer_request": None,
        "callback_requested": None,
        "callback_date": None,
        "callback_time": None,
    }


def _normalize_phone(value: str) -> str:
    compact = re.sub(r"[\s,;./()\-]+", "", value.strip())
    return compact if re.fullmatch(r"\+?\d+", compact) else value.strip()


def _text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("text fact must be string or null")
    return value.strip()


def _optional_date(value: object, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{field} must be ISO date string or null")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc


def _optional_time(value: object, field: str) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        if value.tzinfo is not None:
            raise ValueError(f"{field} must be local time without timezone")
        return value.replace(second=0, microsecond=0)
    if not isinstance(value, str):
        raise TypeError(f"{field} must be HH:MM string or null")
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field} must use HH:MM") from exc
    if parsed.tzinfo is not None:
        raise ValueError(f"{field} must be local time without timezone")
    return parsed.replace(second=0, microsecond=0)


def _optional_guest_count(value: object) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise TypeError("guest_count must be integer or null")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("guest_count must be integer or null") from exc
    if not (1 <= count <= _MAX_GUEST_COUNT):
        raise ValueError(f"guest_count must be between 1 and {_MAX_GUEST_COUNT}")
    return count


def _optional_budget_cents(value: object, *, already_cents: bool) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise TypeError("budget must be numeric or null")
    try:
        amount = Decimal(str(value).replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("budget must be numeric") from exc
    if amount < 0:
        raise ValueError("budget must not be negative")
    if already_cents:
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _fulfillment(value: object) -> str:
    if value in (None, ""):
        return "UNKNOWN"
    if not isinstance(value, str):
        raise TypeError("fulfillment_mode must be string or null")
    normalized = value.strip().upper()
    if normalized not in {"UNKNOWN", "DELIVERY", "PICKUP"}:
        raise ValueError("fulfillment_mode must be UNKNOWN, DELIVERY or PICKUP")
    return normalized


def _optional_bool(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be bool or null")
    return value

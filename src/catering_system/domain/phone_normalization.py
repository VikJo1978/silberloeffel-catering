"""Canonical Core phone normalization for identity matching."""

from __future__ import annotations

_PRIVATE_CALLER_MARKERS = frozenset(
    {
        "anonymous",
        "anonym",
        "unbekannt",
        "unterdruckt",
        "unterdrückt",
        "withheld",
        "private",
        "anonyme",
        "anonymus",
    }
)


def normalize_phone(raw: str | None) -> str:
    """Return canonical E.164-style phone or empty string when not parseable."""
    value = (raw or "").strip()
    if not value:
        return ""
    plus = value.startswith("+")
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return ""
    if plus:
        return f"+{digits}"
    if digits.startswith("00"):
        return f"+{digits[2:]}"
    if digits.startswith("0"):
        return f"+49{digits[1:]}"
    return digits


def is_private_or_anonymous_caller(raw: str | None) -> bool:
    value = (raw or "").strip()
    if not value or value in {"-", "--"}:
        return True
    collapsed = "".join(ch for ch in value.casefold() if ch.isalnum())
    return collapsed in _PRIVATE_CALLER_MARKERS


def normalize_phone_for_contact_point(raw: str | None) -> str:
    """Normalize a phone for PhoneContactPoint persistence and exact lookup."""
    if is_private_or_anonymous_caller(raw):
        raise ValueError("private or anonymous caller is not a phone number")
    normalized = normalize_phone(raw)
    if not normalized:
        raise ValueError("phone number is empty or invalid")
    return normalized

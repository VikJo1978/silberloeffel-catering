"""Explicit customer gastronomic preferences.

This module stores only preferences deliberately recorded by a customer or an
Office operator. Inferred recommendation hints and order-history facts belong
to separate models and must never be persisted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

PreferenceSource = Literal["customer_stated", "office_recorded"]
PREFERENCE_SOURCES: tuple[PreferenceSource, ...] = (
    "customer_stated",
    "office_recorded",
)
PREFERENCE_SOURCE_SET: frozenset[str] = frozenset(PREFERENCE_SOURCES)

PreferenceKind = Literal[
    "dietary_preference",
    "operational_requirement",
    "service_style",
    "spice_level",
    "favorite_dish",
    "disliked_dish",
    "budget_style",
    "gastronomic_note",
]
PREFERENCE_KINDS: tuple[PreferenceKind, ...] = (
    "dietary_preference",
    "operational_requirement",
    "service_style",
    "spice_level",
    "favorite_dish",
    "disliked_dish",
    "budget_style",
    "gastronomic_note",
)
PREFERENCE_KIND_SET: frozenset[str] = frozenset(PREFERENCE_KINDS)

MAX_PREFERENCE_VALUE_LENGTH = 1000


@dataclass(frozen=True)
class CustomerGastronomicPreference:
    preference_id: str
    customer_id: str
    kind: PreferenceKind
    value: str
    source: PreferenceSource
    created_at: datetime
    updated_at: datetime


def validate_preference_source(value: str) -> PreferenceSource:
    if value not in PREFERENCE_SOURCE_SET:
        raise ValueError(
            "preference source must be explicit and one of "
            f"{sorted(PREFERENCE_SOURCE_SET)}, got {value!r}"
        )
    return cast(PreferenceSource, value)


def validate_preference_kind(value: str) -> PreferenceKind:
    if value not in PREFERENCE_KIND_SET:
        raise ValueError(
            "preference kind must be one of "
            f"{sorted(PREFERENCE_KIND_SET)}, got {value!r}"
        )
    return cast(PreferenceKind, value)


def validate_preference_value(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("preference value must not be empty")
    if len(text) > MAX_PREFERENCE_VALUE_LENGTH:
        raise ValueError(
            f"preference value must be at most {MAX_PREFERENCE_VALUE_LENGTH} characters"
        )
    if text != value:
        raise ValueError("preference value must already be trimmed")
    return value


def _require_aware_timestamp(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def validate_customer_gastronomic_preference(
    preference: CustomerGastronomicPreference,
) -> CustomerGastronomicPreference:
    if not preference.preference_id.strip():
        raise ValueError("preference_id must not be empty")
    if not preference.customer_id.strip():
        raise ValueError("customer_id must not be empty")
    validate_preference_kind(preference.kind)
    validate_preference_value(preference.value)
    validate_preference_source(preference.source)
    _require_aware_timestamp("created_at", preference.created_at)
    _require_aware_timestamp("updated_at", preference.updated_at)
    if preference.updated_at < preference.created_at:
        raise ValueError("updated_at must not be earlier than created_at")
    return preference

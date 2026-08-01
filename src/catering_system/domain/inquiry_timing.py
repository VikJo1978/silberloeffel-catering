"""Canonical inquiry/offer timing fields and evaluation rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

TimingFinding = Literal[
    "DELIVERY_DATE_MISSING",
    "DELIVERY_WINDOW_START_MISSING",
    "DELIVERY_WINDOW_END_MISSING",
    "EVENT_START_MISSING",
    "LEGACY_TIME_UNRESOLVED",
    "DELIVERY_WINDOW_INVALID",
    "DELIVERY_AFTER_EVENT_START",
    "DELIVERY_GAP_TOO_SHORT",
]

_LOCAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")
_LOCAL_TIME_RE = re.compile(r"^\d{2}:\d{2}\Z")
_OVERRIDEABLE_FINDINGS = frozenset(
    {
        "DELIVERY_DATE_MISSING",
        "DELIVERY_WINDOW_START_MISSING",
        "DELIVERY_WINDOW_END_MISSING",
        "EVENT_START_MISSING",
        "LEGACY_TIME_UNRESOLVED",
        "DELIVERY_AFTER_EVENT_START",
        "DELIVERY_GAP_TOO_SHORT",
    }
)


def _validate_bool_guard(value: object, field: str) -> None:
    if isinstance(value, bool):
        raise ValueError(f"{field} must not be a boolean")


def validate_local_date_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a YYYY-MM-DD string")
    if not _LOCAL_DATE_RE.fullmatch(value):
        raise ValueError(f"{field} must be a YYYY-MM-DD string")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a real YYYY-MM-DD date") from exc
    return value


def validate_optional_local_date_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    _validate_bool_guard(value, field)
    return validate_local_date_text(value, field)


def validate_local_time_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a HH:MM string")
    if not _LOCAL_TIME_RE.fullmatch(value):
        raise ValueError(f"{field} must be a HH:MM string")
    try:
        time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a real HH:MM time") from exc
    return value


def validate_optional_local_time_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    _validate_bool_guard(value, field)
    return validate_local_time_text(value, field)


def validate_optional_acknowledged_by(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > 200:
        raise ValueError(f"{field} exceeds length limit")
    return trimmed


def normalize_legacy_time_window_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > 500:
        raise ValueError(f"{field} exceeds length limit")
    return trimmed


@dataclass(frozen=True)
class TimingEvaluation:
    findings: tuple[TimingFinding, ...]

    @property
    def requires_acknowledgement(self) -> bool:
        return any(finding in _OVERRIDEABLE_FINDINGS for finding in self.findings)

    @property
    def has_invalid_window(self) -> bool:
        return "DELIVERY_WINDOW_INVALID" in self.findings


def evaluate_timing(
    *,
    event_date: date,
    delivery_date_local: str | None,
    delivery_window_start_local: str | None,
    delivery_window_end_local: str | None,
    event_start_local: str | None,
    legacy_time_window_text: str | None,
) -> TimingEvaluation:
    findings: list[TimingFinding] = []
    if delivery_date_local is None:
        findings.append("DELIVERY_DATE_MISSING")
    if delivery_window_start_local is None:
        findings.append("DELIVERY_WINDOW_START_MISSING")
    if delivery_window_end_local is None:
        findings.append("DELIVERY_WINDOW_END_MISSING")
    if event_start_local is None:
        findings.append("EVENT_START_MISSING")
    if legacy_time_window_text is not None:
        findings.append("LEGACY_TIME_UNRESOLVED")

    if (
        delivery_date_local is None
        or delivery_window_start_local is None
        or delivery_window_end_local is None
        or event_start_local is None
    ):
        return TimingEvaluation(findings=tuple(findings))

    delivery_date = date.fromisoformat(delivery_date_local)
    delivery_start = time.fromisoformat(delivery_window_start_local)
    delivery_end = time.fromisoformat(delivery_window_end_local)
    event_start = time.fromisoformat(event_start_local)
    delivery_start_at = datetime.combine(delivery_date, delivery_start)
    delivery_end_at = datetime.combine(delivery_date, delivery_end)
    event_start_at = datetime.combine(event_date, event_start)

    if delivery_start_at > delivery_end_at:
        findings.append("DELIVERY_WINDOW_INVALID")
        return TimingEvaluation(findings=tuple(findings))

    if delivery_end_at > event_start_at:
        findings.append("DELIVERY_AFTER_EVENT_START")
    gap = event_start_at - delivery_end_at
    if timedelta(0) <= gap < timedelta(minutes=30):
        findings.append("DELIVERY_GAP_TOO_SHORT")
    return TimingEvaluation(findings=tuple(findings))


def timing_acknowledgement_is_valid(
    evaluation: TimingEvaluation,
    *,
    acknowledged_at: datetime | None,
    acknowledged_by: str | None,
) -> bool:
    if evaluation.has_invalid_window:
        return False
    if not evaluation.requires_acknowledgement:
        return True
    return acknowledged_at is not None and acknowledged_by is not None


def timing_fields_changed(
    *,
    time_window_text_before: str,
    time_window_text_after: str,
    delivery_date_local_before: str | None,
    delivery_date_local_after: str | None,
    delivery_window_start_local_before: str | None,
    delivery_window_start_local_after: str | None,
    delivery_window_end_local_before: str | None,
    delivery_window_end_local_after: str | None,
    event_start_local_before: str | None,
    event_start_local_after: str | None,
    legacy_time_window_text_before: str | None,
    legacy_time_window_text_after: str | None,
) -> bool:
    return (
        time_window_text_before != time_window_text_after
        or delivery_date_local_before != delivery_date_local_after
        or delivery_window_start_local_before != delivery_window_start_local_after
        or delivery_window_end_local_before != delivery_window_end_local_after
        or event_start_local_before != event_start_local_after
        or legacy_time_window_text_before != legacy_time_window_text_after
    )

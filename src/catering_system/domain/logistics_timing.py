"""Canonical local time-window primitives for logistics planning.

Legacy display strings are deliberately outside this module.  A machine-usable
window exists only when its structured values were explicitly supplied.
"""

from __future__ import annotations

from datetime import date, time


def validate_optional_local_time(value: time | None, *, label: str) -> None:
    """Validate one explicit local wall-clock fact without inventing a window."""
    if value is not None and value.tzinfo is not None:
        raise ValueError(f"{label} must use local wall-clock time without tzinfo")


def validate_optional_local_window(
    starts_at: time | None,
    ends_at: time | None,
    *,
    label: str,
) -> None:
    if (starts_at is None) != (ends_at is None):
        raise ValueError(f"{label} requires both start and end")
    if starts_at is None:
        return
    assert ends_at is not None
    if starts_at.tzinfo is not None or ends_at.tzinfo is not None:
        raise ValueError(f"{label} must use local wall-clock times without tzinfo")
    if starts_at >= ends_at:
        raise ValueError(f"{label} start must be before end")


def validate_optional_service_window(
    service_date: date | None,
    starts_at: time | None,
    ends_at: time | None,
    *,
    label: str,
) -> None:
    present = (service_date is not None, starts_at is not None, ends_at is not None)
    if any(present) and not all(present):
        raise ValueError(f"{label} requires date, start and end together")
    validate_optional_local_window(starts_at, ends_at, label=label)

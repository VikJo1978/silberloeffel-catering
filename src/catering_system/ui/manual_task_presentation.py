"""Shared presentation rules for system-derived and manual Office tasks."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from urllib.parse import quote, unquote

_PRIORITY_RANK = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
_PRIORITY_LABEL = {"HIGH": "Hoch", "NORMAL": "Normal", "LOW": "Niedrig"}
_SYSTEM_CATEGORY_RANK = {
    "verify": 0,
    "order_print": 1,
    "order_effective": 2,
    "convert_accepted": 3,
    "payment": 4,
    "prepare_offer": 5,
    "prepare_next_version": 6,
    "manual": 7,
}
_SUBJECT_PERMISSION = {
    "CONTACT": "customers.view",
    "INQUIRY": "inquiries.view",
    "OFFER": "offers.view",
    "ORDER": "orders.view",
}


def priority_label(priority: str) -> str:
    return _PRIORITY_LABEL.get(priority, "Normal")


def system_task_priority(row: dict[str, object]) -> str:
    if str(row.get("urgency", "")) in {"overdue", "urgent"}:
        return "HIGH"
    category = str(row.get("category", ""))
    if category in {"verify", "order_print"}:
        return "HIGH"
    if category in {"order_effective", "convert_accepted", "payment"}:
        return "NORMAL"
    return "LOW"


def task_sort_key(row: dict[str, object]) -> tuple[int, datetime, int, datetime, str]:
    priority = str(row.get("priority", "NORMAL"))
    return (
        _PRIORITY_RANK.get(priority, _PRIORITY_RANK["NORMAL"]),
        _as_datetime(row.get("due_at"), maximum=True),
        _SYSTEM_CATEGORY_RANK.get(str(row.get("category", "manual")), 99),
        _as_datetime(row.get("opened_at") or row.get("created_at"), maximum=False),
        str(row.get("task_id", "")),
    )


def sort_task_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(rows, key=task_sort_key)


def make_subject_reference(subject_type: str, subject_key: str) -> str:
    if subject_type not in _SUBJECT_PERMISSION:
        raise ValueError("invalid manual task subject type")
    if not subject_key:
        raise ValueError("manual task subject key is required")
    return f"{subject_type}:{quote(subject_key, safe='')}"


def parse_subject_reference(value: str) -> tuple[str, str | None]:
    raw = value.strip()
    if not raw:
        return "NONE", None
    subject_type, separator, encoded_key = raw.partition(":")
    if not separator or subject_type not in _SUBJECT_PERMISSION or not encoded_key:
        raise ValueError("invalid manual task subject reference")
    subject_key = unquote(encoded_key)
    if not subject_key:
        raise ValueError("invalid manual task subject reference")
    return subject_type, subject_key


def subject_permission(subject_type: str) -> str | None:
    return _SUBJECT_PERMISSION.get(subject_type)


def _as_datetime(value: object | None, *, maximum: bool) -> datetime:
    if value is None or value == "":
        return (
            datetime.max.replace(tzinfo=UTC)
            if maximum
            else datetime.min.replace(tzinfo=UTC)
        )
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(value), time.min, tzinfo=UTC)
            except ValueError:
                return (
                    datetime.max.replace(tzinfo=UTC)
                    if maximum
                    else datetime.min.replace(tzinfo=UTC)
                )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return (
        datetime.max.replace(tzinfo=UTC)
        if maximum
        else datetime.min.replace(tzinfo=UTC)
    )

"""Persisted STRATO AI telephone call inbox facts.

A call is deliberately not an Inquiry. It is a pre-inquiry office inbox item
that may later be converted into an Inquiry, a manual task, linked to an
existing business object, or simply marked done.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Literal

from catering_system.domain.inquiry import FulfillmentMode, validate_fulfillment_mode

AiTelefonCallStatus = Literal["NEW", "PROCESSED", "DONE"]
AI_TELEFON_CALL_STATUSES: tuple[AiTelefonCallStatus, ...] = (
    "NEW",
    "PROCESSED",
    "DONE",
)
AI_TELEFON_CALL_STATUS_SET = frozenset(AI_TELEFON_CALL_STATUSES)

AiTelefonCallResultType = Literal["INQUIRY", "TASK", "LINKED"]
AI_TELEFON_CALL_RESULT_TYPES: tuple[AiTelefonCallResultType, ...] = (
    "INQUIRY",
    "TASK",
    "LINKED",
)
AI_TELEFON_CALL_RESULT_TYPE_SET = frozenset(AI_TELEFON_CALL_RESULT_TYPES)

AiTelefonCallLinkedType = Literal["ORDER", "INQUIRY", "OFFER", "CONTACT"]
AI_TELEFON_CALL_LINKED_TYPES: tuple[AiTelefonCallLinkedType, ...] = (
    "ORDER",
    "INQUIRY",
    "OFFER",
    "CONTACT",
)
AI_TELEFON_CALL_LINKED_TYPE_SET = frozenset(AI_TELEFON_CALL_LINKED_TYPES)

_MAX_SHORT_TEXT = 500
_MAX_SUMMARY = 10000
_MAX_RAW_MESSAGE = 30000
_MAX_EXTERNAL_ID = 500
_MAX_GUEST_COUNT = 2000
_MAX_BUDGET_CENTS = 10_000_000


@dataclass(frozen=True)
class AiTelefonCall:
    call_id: str
    strato_id: str
    gmail_message_id: str
    caller_phone: str
    contact_name: str
    email: str
    subject: str
    summary: str
    raw_message: str
    event_type: str = ""
    event_date: date | None = None
    event_period: str = ""
    event_start: time | None = None
    guest_count: int | None = None
    location: str = ""
    budget_per_person_cents: int | None = None
    fulfillment_mode: FulfillmentMode = "UNKNOWN"
    customer_request: str = ""
    callback_requested: bool | None = None
    callback_date: date | None = None
    callback_time: time | None = None
    status: AiTelefonCallStatus = "NEW"
    result_type: AiTelefonCallResultType | None = None
    result_id: str | None = None
    linked_type: AiTelefonCallLinkedType | None = None
    linked_id: str | None = None
    received_at: datetime | None = None
    processed_at: datetime | None = None
    updated_at: datetime | None = None


def validate_ai_telefon_call_status(value: str) -> AiTelefonCallStatus:
    if value not in AI_TELEFON_CALL_STATUS_SET:
        raise ValueError(
            f"status must be one of {sorted(AI_TELEFON_CALL_STATUS_SET)}, got {value!r}"
        )
    return value


def validate_ai_telefon_call_result_type(value: str) -> AiTelefonCallResultType:
    if value not in AI_TELEFON_CALL_RESULT_TYPE_SET:
        raise ValueError(
            "result_type must be one of "
            f"{sorted(AI_TELEFON_CALL_RESULT_TYPE_SET)}, got {value!r}"
        )
    return value


def validate_ai_telefon_call_linked_type(value: str) -> AiTelefonCallLinkedType:
    if value not in AI_TELEFON_CALL_LINKED_TYPE_SET:
        raise ValueError(
            "linked_type must be one of "
            f"{sorted(AI_TELEFON_CALL_LINKED_TYPE_SET)}, got {value!r}"
        )
    return value


def validate_ai_telefon_call(call: AiTelefonCall) -> AiTelefonCall:
    call_id = _uuid4(call.call_id, "call_id")
    strato_id = _required_text(call.strato_id, "strato_id", _MAX_EXTERNAL_ID)
    gmail_message_id = _required_text(
        call.gmail_message_id, "gmail_message_id", _MAX_EXTERNAL_ID
    )
    caller_phone = _optional_text(call.caller_phone, _MAX_SHORT_TEXT)
    contact_name = _optional_text(call.contact_name, _MAX_SHORT_TEXT)
    email = _optional_text(call.email, _MAX_SHORT_TEXT)
    subject = _optional_text(call.subject, _MAX_SHORT_TEXT)
    summary = _required_text(call.summary, "summary", _MAX_SUMMARY)
    raw_message = _optional_text(call.raw_message, _MAX_RAW_MESSAGE)
    event_type = _optional_text(call.event_type, _MAX_SHORT_TEXT)
    event_period = _optional_text(call.event_period, _MAX_SHORT_TEXT)
    location = _optional_text(call.location, _MAX_SHORT_TEXT)
    customer_request = _optional_text(call.customer_request, _MAX_SUMMARY)
    fulfillment_mode = validate_fulfillment_mode(call.fulfillment_mode)
    status = validate_ai_telefon_call_status(call.status)

    if call.guest_count is not None:
        if isinstance(call.guest_count, bool) or not isinstance(call.guest_count, int):
            raise TypeError("guest_count must be int or null")
        if not (1 <= call.guest_count <= _MAX_GUEST_COUNT):
            raise ValueError(f"guest_count must be between 1 and {_MAX_GUEST_COUNT}")
    if call.budget_per_person_cents is not None:
        if isinstance(call.budget_per_person_cents, bool) or not isinstance(
            call.budget_per_person_cents, int
        ):
            raise TypeError("budget_per_person_cents must be int or null")
        if not (0 <= call.budget_per_person_cents <= _MAX_BUDGET_CENTS):
            raise ValueError("budget_per_person_cents is outside the accepted range")
    if call.callback_requested is not None and not isinstance(
        call.callback_requested, bool
    ):
        raise TypeError("callback_requested must be bool or null")

    _optional_local_time(call.event_start, "event_start")
    _optional_local_time(call.callback_time, "callback_time")
    received_at = _utc_datetime(call.received_at, "received_at")
    updated_at = _utc_datetime(call.updated_at, "updated_at")
    processed_at = _optional_utc_datetime(call.processed_at, "processed_at")
    if updated_at < received_at:
        raise ValueError("updated_at must not be earlier than received_at")
    if processed_at is not None and processed_at < received_at:
        raise ValueError("processed_at must not be earlier than received_at")

    result_type = None
    result_id = call.result_id
    linked_type = call.linked_type
    linked_id = call.linked_id
    if call.result_type is not None:
        result_type = validate_ai_telefon_call_result_type(call.result_type)
        if result_id is None:
            raise ValueError("result_id is required when result_type is set")
        result_id = _uuid4(result_id, "result_id")
    elif result_id is not None:
        raise ValueError("result_type is required when result_id is set")

    if linked_type is not None:
        linked_type = validate_ai_telefon_call_linked_type(linked_type)
        if linked_id is None:
            raise ValueError("linked_id is required when linked_type is set")
        linked_id = _uuid4(linked_id, "linked_id")
    elif linked_id is not None:
        raise ValueError("linked_type is required when linked_id is set")

    if status == "NEW" and (
        result_type is not None or linked_type is not None or processed_at is not None
    ):
        raise ValueError("NEW call cannot already contain a processing result")
    if status == "PROCESSED" and processed_at is None:
        raise ValueError("PROCESSED call requires processed_at")

    return replace(
        call,
        call_id=call_id,
        strato_id=strato_id,
        gmail_message_id=gmail_message_id,
        caller_phone=caller_phone,
        contact_name=contact_name,
        email=email,
        subject=subject,
        summary=summary,
        raw_message=raw_message,
        event_type=event_type,
        event_period=event_period,
        location=location,
        customer_request=customer_request,
        fulfillment_mode=fulfillment_mode,
        status=status,
        result_type=result_type,
        result_id=result_id,
        linked_type=linked_type,
        linked_id=linked_id,
        received_at=received_at,
        processed_at=processed_at,
        updated_at=updated_at,
    )


def _required_text(value: object, field: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text[:max_len]


def _optional_text(value: object, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("text field must be a string")
    return value.strip()[:max_len]


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


def _utc_datetime(value: datetime | None, field: str) -> datetime:
    if value is None:
        raise ValueError(f"{field} is required")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")
    return value


def _optional_utc_datetime(value: datetime | None, field: str) -> datetime | None:
    if value is None:
        return None
    return _utc_datetime(value, field)


def _optional_local_time(value: time | None, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, time):
        raise TypeError(f"{field} must be time or null")
    if value.tzinfo is not None:
        raise ValueError(f"{field} must be a local wall-clock time without timezone")

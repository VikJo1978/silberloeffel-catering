"""Internal employee chat domain objects for staff-only MVP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

ChatThreadType = Literal["DIRECT", "GROUP"]
ChatReferenceType = Literal["ORDER", "INQUIRY", "CONTACT"]

CHAT_THREAD_TYPES: tuple[ChatThreadType, ...] = ("DIRECT", "GROUP")
CHAT_REFERENCE_TYPES: tuple[ChatReferenceType, ...] = ("ORDER", "INQUIRY", "CONTACT")
CHAT_THREAD_TYPE_SET: frozenset[str] = frozenset(CHAT_THREAD_TYPES)
CHAT_REFERENCE_TYPE_SET: frozenset[str] = frozenset(CHAT_REFERENCE_TYPES)
MAX_CHAT_TITLE_LENGTH = 200
MAX_CHAT_MESSAGE_BODY_LENGTH = 20000


@dataclass(frozen=True)
class ChatThread:
    thread_id: str
    thread_type: ChatThreadType
    title: str | None
    created_by_employee_id: str
    created_at: datetime


@dataclass(frozen=True)
class ChatParticipant:
    thread_id: str
    employee_id: str
    joined_at: datetime
    last_read_message_id: str | None = None


@dataclass(frozen=True)
class ChatMessage:
    message_id: str
    thread_id: str
    author_employee_id: str
    body: str
    reply_to_message_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class ChatMessageMention:
    message_id: str
    employee_id: str


@dataclass(frozen=True)
class ChatMessageReference:
    message_id: str
    reference_type: ChatReferenceType
    reference_id: str


@dataclass(frozen=True)
class ChatMessageBundle:
    message: ChatMessage
    mentions: tuple[ChatMessageMention, ...] = ()
    references: tuple[ChatMessageReference, ...] = ()


@dataclass(frozen=True)
class ChatThreadSummary:
    thread: ChatThread
    participants: tuple[ChatParticipant, ...]
    latest_message: ChatMessage | None
    unread_count: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def validate_chat_thread_type(value: str) -> ChatThreadType:
    if value not in CHAT_THREAD_TYPE_SET:
        raise ValueError(
            f"thread_type must be one of {sorted(CHAT_THREAD_TYPE_SET)}, got {value!r}"
        )
    return cast(ChatThreadType, value)


def validate_chat_reference_type(value: str) -> ChatReferenceType:
    if value not in CHAT_REFERENCE_TYPE_SET:
        raise ValueError(
            "reference_type must be one of "
            f"{sorted(CHAT_REFERENCE_TYPE_SET)}, got {value!r}"
        )
    return cast(ChatReferenceType, value)


def normalize_chat_title(
    value: str | None, *, thread_type: ChatThreadType
) -> str | None:
    if thread_type == "DIRECT":
        if value is not None and value.strip():
            raise ValueError("DIRECT chat title must be empty")
        return None
    if not isinstance(value, str):
        raise TypeError("GROUP chat title is required")
    title = value.strip()
    if not title:
        raise ValueError("GROUP chat title must not be empty")
    if len(title) > MAX_CHAT_TITLE_LENGTH:
        raise ValueError(f"title must be at most {MAX_CHAT_TITLE_LENGTH} characters")
    return title


def normalize_chat_body(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("body must be a string")
    body = value.strip()
    if len(body) > MAX_CHAT_MESSAGE_BODY_LENGTH:
        raise ValueError(
            f"body must be at most {MAX_CHAT_MESSAGE_BODY_LENGTH} characters"
        )
    return body


def validate_message_content(body: str, reference_count: int) -> None:
    if body or reference_count > 0:
        return
    raise ValueError("message requires non-empty body or at least one reference")

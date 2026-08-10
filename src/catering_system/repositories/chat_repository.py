"""Repository contract for internal employee chat."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.chat import (
    ChatMessage,
    ChatMessageBundle,
    ChatMessageMention,
    ChatMessageReference,
    ChatParticipant,
    ChatThread,
    ChatThreadSummary,
)


class ChatRepository(Protocol):
    def create_thread(
        self,
        thread: ChatThread,
        participants: tuple[ChatParticipant, ...],
        *,
        direct_pair: tuple[str, str] | None = None,
    ) -> None: ...

    def get_thread(self, thread_id: str) -> ChatThread | None: ...

    def find_direct_thread(
        self, employee_a_id: str, employee_b_id: str
    ) -> ChatThread | None: ...

    def list_participants(self, thread_id: str) -> tuple[ChatParticipant, ...]: ...

    def is_participant(self, thread_id: str, employee_id: str) -> bool: ...

    def add_message(
        self,
        message: ChatMessage,
        *,
        mentions: tuple[ChatMessageMention, ...] = (),
        references: tuple[ChatMessageReference, ...] = (),
    ) -> None: ...

    def get_message(self, message_id: str) -> ChatMessage | None: ...

    def list_messages(
        self, thread_id: str, *, limit: int = 100
    ) -> tuple[ChatMessageBundle, ...]: ...

    def mark_read(
        self, thread_id: str, employee_id: str, last_read_message_id: str | None
    ) -> None: ...

    def list_thread_summaries_for_employee(
        self, employee_id: str
    ) -> tuple[ChatThreadSummary, ...]: ...

    def unread_count_for_thread(self, thread_id: str, employee_id: str) -> int: ...

    def total_unread_count(self, employee_id: str) -> int: ...

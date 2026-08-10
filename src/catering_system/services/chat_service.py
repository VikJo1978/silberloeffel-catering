"""Application service for internal employee chat."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Protocol

from catering_system.domain.chat import (
    ChatMessage,
    ChatMessageBundle,
    ChatMessageMention,
    ChatMessageReference,
    ChatParticipant,
    ChatReferenceType,
    ChatThread,
    ChatThreadSummary,
    normalize_chat_body,
    normalize_chat_title,
    utc_now,
    validate_chat_reference_type,
    validate_message_content,
)
from catering_system.domain.contact_profile import ContactProfile
from catering_system.domain.employee_auth import AuthenticatedEmployee, EmployeeAccount
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.order import Order
from catering_system.repositories.chat_repository import ChatRepository
from catering_system.repositories.contact_profile_repository import (
    ContactProfileRepository,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.order_repository import OrderRepository

_CHAT_VIEW = "chat.view"
_CHAT_SEND = "chat.send"
_CHAT_CREATE = "chat.create"


class ChatAccessDenied(Exception):
    pass


class ChatNotFoundError(Exception):
    pass


class ChatReferenceNotFoundError(Exception):
    pass


class EmployeeAccountLookup(Protocol):
    def get_account_by_id(self, account_id: str) -> EmployeeAccount | None: ...


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        employee_accounts: EmployeeAccountLookup,
        *,
        orders: OrderRepository | None = None,
        inquiries: InquiryRepository | None = None,
        contacts: ContactProfileRepository | None = None,
    ) -> None:
        self._repository = repository
        self._employees = employee_accounts
        self._orders = orders
        self._inquiries = inquiries
        self._contacts = contacts

    def create_direct_thread(
        self, actor: AuthenticatedEmployee, other_employee_id: str
    ) -> ChatThread:
        self._require(actor, _CHAT_CREATE)
        actor_id = actor.account.id
        other_id = other_employee_id.strip()
        if actor_id == other_id:
            raise ValueError("DIRECT chat requires two distinct employees")
        self._require_active_employee(actor_id)
        self._require_active_employee(other_id)
        existing = self._repository.find_direct_thread(actor_id, other_id)
        if existing is not None:
            return existing
        now = utc_now()
        thread = ChatThread(
            thread_id=str(uuid.uuid4()),
            thread_type="DIRECT",
            title=None,
            created_by_employee_id=actor_id,
            created_at=now,
        )
        participants = (
            ChatParticipant(thread.thread_id, actor_id, now),
            ChatParticipant(thread.thread_id, other_id, now),
        )
        try:
            self._repository.create_thread(
                thread, participants, direct_pair=(actor_id, other_id)
            )
        except sqlite3.IntegrityError:
            replay = self._repository.find_direct_thread(actor_id, other_id)
            if replay is not None:
                return replay
            raise
        return thread

    def create_group_thread(
        self,
        actor: AuthenticatedEmployee,
        *,
        title: str,
        participant_employee_ids: tuple[str, ...],
    ) -> ChatThread:
        self._require(actor, _CHAT_CREATE)
        actor_id = actor.account.id
        normalized_title = normalize_chat_title(title, thread_type="GROUP")
        participant_ids = self._unique_participant_ids(
            (actor_id, *participant_employee_ids)
        )
        if len(participant_ids) < 2:
            raise ValueError("GROUP chat requires at least two participants")
        for employee_id in participant_ids:
            self._require_active_employee(employee_id)
        now = utc_now()
        thread = ChatThread(
            thread_id=str(uuid.uuid4()),
            thread_type="GROUP",
            title=normalized_title,
            created_by_employee_id=actor_id,
            created_at=now,
        )
        participants = tuple(
            ChatParticipant(thread.thread_id, employee_id, now)
            for employee_id in participant_ids
        )
        self._repository.create_thread(thread, participants)
        return thread

    def list_threads(
        self, actor: AuthenticatedEmployee
    ) -> tuple[ChatThreadSummary, ...]:
        self._require(actor, _CHAT_VIEW)
        return self._repository.list_thread_summaries_for_employee(actor.account.id)

    def list_messages(
        self, actor: AuthenticatedEmployee, thread_id: str, *, limit: int = 100
    ) -> tuple[ChatMessageBundle, ...]:
        self._require_thread_access(actor, thread_id, _CHAT_VIEW)
        return self._repository.list_messages(thread_id, limit=limit)

    def send_message(
        self,
        actor: AuthenticatedEmployee,
        thread_id: str,
        *,
        body: str,
        reply_to_message_id: str | None = None,
        mention_employee_ids: tuple[str, ...] = (),
        references: tuple[tuple[str, str], ...] = (),
    ) -> ChatMessage:
        self._require_thread_access(actor, thread_id, _CHAT_SEND)
        thread = self._require_thread(thread_id)
        normalized_body = normalize_chat_body(body)
        normalized_references = self._references_for_message("pending", references)
        validate_message_content(normalized_body, len(normalized_references))

        if reply_to_message_id is not None:
            reply = self._repository.get_message(reply_to_message_id)
            if reply is None or reply.thread_id != thread.thread_id:
                raise ValueError("reply target must belong to the same thread")

        participant_ids = {
            participant.employee_id
            for participant in self._repository.list_participants(thread.thread_id)
        }
        mentions = self._mentions_for_message(
            "pending", mention_employee_ids, participant_ids
        )
        message_id = str(uuid.uuid4())
        message = ChatMessage(
            message_id=message_id,
            thread_id=thread.thread_id,
            author_employee_id=actor.account.id,
            body=normalized_body,
            reply_to_message_id=reply_to_message_id,
            created_at=utc_now(),
        )
        self._repository.add_message(
            message,
            mentions=tuple(
                ChatMessageMention(message_id, mention.employee_id)
                for mention in mentions
            ),
            references=tuple(
                ChatMessageReference(message_id, ref.reference_type, ref.reference_id)
                for ref in normalized_references
            ),
        )
        return message

    def mark_read(
        self,
        actor: AuthenticatedEmployee,
        thread_id: str,
        *,
        last_read_message_id: str | None,
    ) -> None:
        self._require_thread_access(actor, thread_id, _CHAT_VIEW)
        if last_read_message_id is not None:
            message = self._repository.get_message(last_read_message_id)
            if message is None or message.thread_id != thread_id:
                raise ValueError("last_read_message_id must belong to the thread")
        self._repository.mark_read(thread_id, actor.account.id, last_read_message_id)

    def total_unread_count(self, actor: AuthenticatedEmployee) -> int:
        self._require(actor, _CHAT_VIEW)
        return self._repository.total_unread_count(actor.account.id)

    def _require_thread_access(
        self, actor: AuthenticatedEmployee, thread_id: str, permission_code: str
    ) -> None:
        self._require(actor, permission_code)
        if self._repository.get_thread(thread_id) is None:
            raise ChatNotFoundError(thread_id)
        if not self._repository.is_participant(thread_id, actor.account.id):
            raise ChatAccessDenied("employee is not a chat participant")

    def _require(self, actor: AuthenticatedEmployee, permission_code: str) -> None:
        if not actor.application_access_allowed:
            raise ChatAccessDenied("employee application access is disabled")
        if permission_code not in actor.effective_permissions:
            raise ChatAccessDenied(f"missing permission {permission_code}")

    def _require_thread(self, thread_id: str) -> ChatThread:
        thread = self._repository.get_thread(thread_id)
        if thread is None:
            raise ChatNotFoundError(thread_id)
        return thread

    def _require_active_employee(self, employee_id: str) -> EmployeeAccount:
        account = self._employees.get_account_by_id(employee_id)
        if account is None or not account.is_active:
            raise ValueError("employee_id must reference an active EmployeeAccount")
        return account

    def _mentions_for_message(
        self,
        message_id: str,
        employee_ids: tuple[str, ...],
        participant_ids: set[str],
    ) -> tuple[ChatMessageMention, ...]:
        mentions: list[ChatMessageMention] = []
        seen: set[str] = set()
        for raw_employee_id in employee_ids:
            employee_id = raw_employee_id.strip()
            if employee_id in seen:
                continue
            if employee_id not in participant_ids:
                raise ValueError("mentioned employee must be a thread participant")
            self._require_active_employee(employee_id)
            seen.add(employee_id)
            mentions.append(ChatMessageMention(message_id, employee_id))
        return tuple(mentions)

    def _references_for_message(
        self, message_id: str, references: tuple[tuple[str, str], ...]
    ) -> tuple[ChatMessageReference, ...]:
        normalized: list[ChatMessageReference] = []
        seen: set[tuple[ChatReferenceType, str]] = set()
        for raw_type, raw_id in references:
            reference_type = validate_chat_reference_type(raw_type)
            reference_id = raw_id.strip()
            if not reference_id:
                raise ValueError("reference_id is required")
            key = (reference_type, reference_id)
            if key in seen:
                continue
            self._require_reference(reference_type, reference_id)
            seen.add(key)
            normalized.append(
                ChatMessageReference(message_id, reference_type, reference_id)
            )
        return tuple(normalized)

    def _require_reference(
        self, reference_type: ChatReferenceType, reference_id: str
    ) -> Order | Inquiry | ContactProfile:
        if reference_type == "ORDER":
            if self._orders is None:
                raise ChatReferenceNotFoundError(reference_id)
            order = self._orders.get_order(reference_id)
            if order is None:
                raise ChatReferenceNotFoundError(reference_id)
            return order
        if reference_type == "INQUIRY":
            if self._inquiries is None:
                raise ChatReferenceNotFoundError(reference_id)
            inquiry = self._inquiries.get_by_id(reference_id)
            if inquiry is None:
                raise ChatReferenceNotFoundError(reference_id)
            return inquiry
        if self._contacts is None:
            raise ChatReferenceNotFoundError(reference_id)
        contact = self._contacts.get_profile(reference_id)
        if contact is None:
            raise ChatReferenceNotFoundError(reference_id)
        return contact

    @staticmethod
    def _unique_participant_ids(employee_ids: tuple[str, ...]) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()
        for raw_employee_id in employee_ids:
            employee_id = raw_employee_id.strip()
            if not employee_id or employee_id in seen:
                continue
            seen.add(employee_id)
            result.append(employee_id)
        return tuple(result)

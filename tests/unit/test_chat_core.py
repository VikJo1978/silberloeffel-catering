"""Unit tests for internal employee chat PR1 core."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from catering_system.domain.chat import (
    ChatMessage,
    ChatMessageReference,
    ChatParticipant,
    ChatThread,
)
from catering_system.domain.contact_profile import ContactProfile
from catering_system.domain.employee_auth import (
    PERMISSION_SET,
    AuthenticatedEmployee,
    EmployeeAccount,
    EmployeeSession,
    role_ceiling,
    role_default_grants,
)
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.order import Order
from catering_system.repositories.sqlite_chat_repository import SQLiteChatRepository
from catering_system.repositories.sqlite_contact_profile_repository import (
    SQLiteContactProfileRepository,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.chat_service import (
    ChatAccessDenied,
    ChatReferenceNotFoundError,
    ChatService,
)


class _OrderLookup:
    def __init__(self, order: Order | None = None) -> None:
        self.order = order

    def get_order(self, order_id: str) -> Order | None:
        if self.order is None or self.order.order_id != order_id:
            return None
        return self.order


class _InquiryLookup:
    def __init__(self, inquiry: Inquiry | None = None) -> None:
        self.inquiry = inquiry

    def get_by_id(self, inquiry_id: str) -> Inquiry | None:
        if self.inquiry is None or self.inquiry.inquiry_id != inquiry_id:
            return None
        return self.inquiry


def _now() -> datetime:
    return datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _account(account_id: str, display_name: str) -> EmployeeAccount:
    now = _now()
    return EmployeeAccount(
        id=account_id,
        username=display_name.casefold(),
        email=None,
        display_name=display_name,
        password_hash="hash",
        role="USER",
        is_active=True,
        must_change_password=False,
        created_at=now,
        updated_at=now,
        deactivated_at=None,
        last_login_at=None,
        auth_version=1,
    )


def _actor(
    account: EmployeeAccount, permissions: frozenset[str]
) -> AuthenticatedEmployee:
    now = _now()
    return AuthenticatedEmployee(
        account=account,
        session=EmployeeSession(
            id=f"session-{account.id}",
            account_id=account.id,
            token_hash="token",
            csrf_token_hash="csrf",
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
            revoked_at=None,
            revoked_reason=None,
            auth_version=account.auth_version,
        ),
        application_access_allowed=True,
        effective_permissions=permissions,
    )


def _chat_world(
    tmp_path: Path,
) -> tuple[
    SQLiteChatRepository,
    SQLiteEmployeeAuthRepository,
    SQLiteContactProfileRepository,
    EmployeeAccount,
    EmployeeAccount,
    EmployeeAccount,
]:
    db = tmp_path / "chat.db"
    employees = SQLiteEmployeeAuthRepository(db)
    viktor = _account("00000000-0000-4000-8000-000000000001", "Viktor")
    anna = _account("00000000-0000-4000-8000-000000000002", "Anna")
    lena = _account("00000000-0000-4000-8000-000000000003", "Lena")
    for account in (viktor, anna, lena):
        employees.add_account(account)
        employees.set_explicit_permissions(account.id, set(role_default_grants("USER")))
    contacts = SQLiteContactProfileRepository(db)
    chat = SQLiteChatRepository(db)
    return chat, employees, contacts, viktor, anna, lena


def test_chat_permissions_are_registered() -> None:
    assert {"chat.view", "chat.send", "chat.create"} <= PERMISSION_SET
    assert {"chat.view", "chat.send", "chat.create"} <= role_default_grants("USER")
    assert {"chat.view", "chat.send", "chat.create"} <= role_default_grants("ADMIN")
    assert "chat.view" in role_default_grants("SUPERADMIN")
    assert not {"chat.view", "chat.send", "chat.create"}.intersection(
        role_default_grants("VIEWER")
    )
    assert {"chat.view", "chat.send", "chat.create"} <= role_ceiling("USER")
    assert {"chat.view", "chat.send", "chat.create"} <= role_ceiling("ADMIN")
    assert "chat.view" in role_ceiling("VIEWER")
    assert "chat.send" not in role_ceiling("VIEWER")
    assert "chat.create" not in role_ceiling("VIEWER")


def test_direct_thread_is_reused_for_employee_pair(tmp_path: Path) -> None:
    chat, employees, contacts, viktor, anna, _lena = _chat_world(tmp_path)
    service = ChatService(chat, employees, contacts=contacts)
    actor = _actor(viktor, frozenset({"chat.create", "chat.view", "chat.send"}))
    reverse_actor = _actor(anna, frozenset({"chat.create", "chat.view", "chat.send"}))

    first = service.create_direct_thread(actor, anna.id)
    second = service.create_direct_thread(actor, anna.id)
    reverse = service.create_direct_thread(reverse_actor, viktor.id)

    assert second.thread_id == first.thread_id
    assert reverse.thread_id == first.thread_id
    assert first.thread_type == "DIRECT"
    assert first.title is None
    assert {p.employee_id for p in chat.list_participants(first.thread_id)} == {
        viktor.id,
        anna.id,
    }


def test_direct_thread_rejects_self_chat(tmp_path: Path) -> None:
    chat, employees, contacts, viktor, _anna, _lena = _chat_world(tmp_path)
    service = ChatService(chat, employees, contacts=contacts)
    actor = _actor(viktor, frozenset({"chat.create"}))

    with pytest.raises(ValueError, match="distinct"):
        service.create_direct_thread(actor, viktor.id)


def test_group_thread_requires_title_and_two_participants(tmp_path: Path) -> None:
    chat, employees, contacts, viktor, anna, lena = _chat_world(tmp_path)
    service = ChatService(chat, employees, contacts=contacts)
    actor = _actor(viktor, frozenset({"chat.create"}))

    with pytest.raises(ValueError, match="title"):
        service.create_group_thread(
            actor, title=" ", participant_employee_ids=(anna.id,)
        )
    with pytest.raises(ValueError, match="at least two"):
        service.create_group_thread(actor, title="Team", participant_employee_ids=())

    thread = service.create_group_thread(
        actor, title="Team", participant_employee_ids=(anna.id,)
    )
    assert thread.thread_type == "GROUP"
    assert thread.title == "Team"
    assert {
        participant.employee_id
        for participant in chat.list_participants(thread.thread_id)
    } == {
        viktor.id,
        anna.id,
    }

    deduped = service.create_group_thread(
        actor, title="Team 2", participant_employee_ids=(viktor.id, anna.id, anna.id)
    )
    assert {
        participant.employee_id
        for participant in chat.list_participants(deduped.thread_id)
    } == {
        viktor.id,
        anna.id,
    }
    assert lena.id not in {
        participant.employee_id
        for participant in chat.list_participants(deduped.thread_id)
    }


def test_only_participants_can_be_mentioned(tmp_path: Path) -> None:
    chat, employees, contacts, viktor, anna, lena = _chat_world(tmp_path)
    service = ChatService(chat, employees, contacts=contacts)
    actor = _actor(viktor, frozenset({"chat.create", "chat.send", "chat.view"}))
    thread = service.create_direct_thread(actor, anna.id)

    with pytest.raises(ValueError, match="participant"):
        service.send_message(
            actor,
            thread.thread_id,
            body="@Lena bitte pruefen",
            mention_employee_ids=(lena.id,),
        )

    message = service.send_message(
        actor,
        thread.thread_id,
        body="@Anna bitte pruefen",
        mention_employee_ids=(anna.id,),
    )
    bundle = chat.list_messages(thread.thread_id)[0]
    assert bundle.message.message_id == message.message_id
    assert [mention.employee_id for mention in bundle.mentions] == [anna.id]


def test_invalid_mention_leaves_no_partial_message(tmp_path: Path) -> None:
    chat, employees, contacts, viktor, anna, lena = _chat_world(tmp_path)
    service = ChatService(chat, employees, contacts=contacts)
    actor = _actor(viktor, frozenset({"chat.create", "chat.send", "chat.view"}))
    thread = service.create_direct_thread(actor, anna.id)

    with pytest.raises(ValueError, match="participant"):
        service.send_message(
            actor,
            thread.thread_id,
            body="Bitte pruefen",
            mention_employee_ids=(lena.id,),
        )

    assert chat.list_messages(thread.thread_id) == ()


def test_reply_target_must_be_in_same_thread(tmp_path: Path) -> None:
    chat, employees, contacts, viktor, anna, lena = _chat_world(tmp_path)
    service = ChatService(chat, employees, contacts=contacts)
    actor = _actor(viktor, frozenset({"chat.create", "chat.send", "chat.view"}))
    first = service.create_direct_thread(actor, anna.id)
    second = service.create_direct_thread(actor, lena.id)
    original = service.send_message(actor, first.thread_id, body="Bitte pruefen")

    with pytest.raises(ValueError, match="same thread"):
        service.send_message(
            actor,
            second.thread_id,
            body="Ja",
            reply_to_message_id=original.message_id,
        )

    reply = service.send_message(
        actor, first.thread_id, body="Ja", reply_to_message_id=original.message_id
    )
    assert chat.get_message(reply.message_id).reply_to_message_id == original.message_id


def test_reference_only_message_is_valid_and_reference_must_exist(
    tmp_path: Path,
) -> None:
    chat, employees, contacts, viktor, anna, _lena = _chat_world(tmp_path)
    contact = ContactProfile(
        contact_profile_id="00000000-0000-4000-8000-000000000099",
        display_name="Muller",
        email=None,
        phone=None,
        created_at=_now(),
        updated_at=_now(),
    )
    contacts.create_profile(contact)
    service = ChatService(chat, employees, contacts=contacts)
    actor = _actor(viktor, frozenset({"chat.create", "chat.send", "chat.view"}))
    thread = service.create_direct_thread(actor, anna.id)

    with pytest.raises(ValueError, match="non-empty body"):
        service.send_message(actor, thread.thread_id, body="   ")
    with pytest.raises(ValueError, match="non-empty body"):
        service.send_message(
            actor, thread.thread_id, body="   ", mention_employee_ids=(anna.id,)
        )

    message = service.send_message(
        actor,
        thread.thread_id,
        body="   ",
        references=(("CONTACT", contact.contact_profile_id),),
    )
    bundle = chat.list_messages(thread.thread_id)[0]
    assert bundle.message.message_id == message.message_id
    assert bundle.message.body == ""
    assert bundle.references == (
        ChatMessageReference(message.message_id, "CONTACT", contact.contact_profile_id),
    )


def test_order_and_inquiry_references_are_validated(tmp_path: Path) -> None:
    chat, employees, contacts, viktor, anna, _lena = _chat_world(tmp_path)
    order = Order(
        order_id="00000000-0000-4000-8000-000000000201",
        source_inquiry_id="00000000-0000-4000-8000-000000000301",
        created_at=_now(),
        updated_at=_now(),
    )
    inquiry = Inquiry(
        inquiry_id=order.source_inquiry_id,
        event_date=_now().date(),
        created_at=_now(),
        updated_at=_now(),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittag",
        location_text="Berlin",
        guest_count_estimate=26,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    service = ChatService(
        chat,
        employees,
        orders=_OrderLookup(order),  # type: ignore[arg-type]
        inquiries=_InquiryLookup(inquiry),  # type: ignore[arg-type]
        contacts=contacts,
    )
    actor = _actor(viktor, frozenset({"chat.create", "chat.send", "chat.view"}))
    thread = service.create_direct_thread(actor, anna.id)

    service.send_message(
        actor,
        thread.thread_id,
        body="",
        references=(("ORDER", order.order_id), ("INQUIRY", inquiry.inquiry_id)),
    )

    with pytest.raises(ChatReferenceNotFoundError):
        service.send_message(
            actor,
            thread.thread_id,
            body="",
            references=(("ORDER", "00000000-0000-4000-8000-000000000999"),),
        )
    assert len(chat.list_messages(thread.thread_id)) == 1


def test_invalid_reference_with_mentions_leaves_no_partial_message(
    tmp_path: Path,
) -> None:
    chat, employees, contacts, viktor, anna, _lena = _chat_world(tmp_path)
    service = ChatService(chat, employees, orders=_OrderLookup(), contacts=contacts)
    actor = _actor(viktor, frozenset({"chat.create", "chat.send", "chat.view"}))
    thread = service.create_direct_thread(actor, anna.id)

    with pytest.raises(ChatReferenceNotFoundError):
        service.send_message(
            actor,
            thread.thread_id,
            body="Bitte pruefen",
            mention_employee_ids=(anna.id,),
            references=(("ORDER", "00000000-0000-4000-8000-000000000999"),),
        )

    assert chat.list_messages(thread.thread_id) == ()


def test_non_participant_cannot_read_or_send(tmp_path: Path) -> None:
    chat, employees, contacts, viktor, anna, lena = _chat_world(tmp_path)
    service = ChatService(chat, employees, contacts=contacts)
    viktor_actor = _actor(viktor, frozenset({"chat.create", "chat.send", "chat.view"}))
    lena_actor = _actor(lena, frozenset({"chat.send", "chat.view"}))
    thread = service.create_direct_thread(viktor_actor, anna.id)

    with pytest.raises(ChatAccessDenied):
        service.list_messages(lena_actor, thread.thread_id)
    with pytest.raises(ChatAccessDenied):
        service.send_message(lena_actor, thread.thread_id, body="heimlich")


def test_unread_uses_last_read_message_position_for_identical_timestamps(
    tmp_path: Path,
) -> None:
    chat, _employees, _contacts, viktor, anna, _lena = _chat_world(tmp_path)
    created_at = _now()
    thread = ChatThread(
        thread_id="00000000-0000-4000-8000-000000000401",
        thread_type="DIRECT",
        title=None,
        created_by_employee_id=viktor.id,
        created_at=created_at,
    )
    chat.create_thread(
        thread,
        (
            ChatParticipant(thread.thread_id, viktor.id, created_at),
            ChatParticipant(thread.thread_id, anna.id, created_at),
        ),
        direct_pair=(viktor.id, anna.id),
    )
    chat.add_message(
        ChatMessage("a", thread.thread_id, anna.id, "eins", None, created_at)
    )
    chat.add_message(
        ChatMessage("b", thread.thread_id, anna.id, "zwei", None, created_at)
    )

    assert chat.unread_count_for_thread(thread.thread_id, viktor.id) == 2
    chat.mark_read(thread.thread_id, viktor.id, "a")
    assert chat.unread_count_for_thread(thread.thread_id, viktor.id) == 1
    chat.mark_read(thread.thread_id, viktor.id, "b")
    assert chat.unread_count_for_thread(thread.thread_id, viktor.id) == 0


def test_mark_read_changes_only_current_participant_and_rejects_cross_thread_marker(
    tmp_path: Path,
) -> None:
    chat, employees, contacts, viktor, anna, lena = _chat_world(tmp_path)
    service = ChatService(chat, employees, contacts=contacts)
    viktor_actor = _actor(viktor, frozenset({"chat.create", "chat.send", "chat.view"}))
    first = service.create_direct_thread(viktor_actor, anna.id)
    second = service.create_direct_thread(viktor_actor, lena.id)
    first_message = service.send_message(viktor_actor, first.thread_id, body="eins")
    second_message = service.send_message(viktor_actor, second.thread_id, body="zwei")

    service.mark_read(
        viktor_actor,
        first.thread_id,
        last_read_message_id=first_message.message_id,
    )
    participants = {
        participant.employee_id: participant
        for participant in chat.list_participants(first.thread_id)
    }
    assert participants[viktor.id].last_read_message_id == first_message.message_id
    assert participants[anna.id].last_read_message_id is None

    with pytest.raises(ValueError, match="belong to the thread"):
        service.mark_read(
            viktor_actor,
            first.thread_id,
            last_read_message_id=second_message.message_id,
        )


def test_sqlite_rejects_non_participant_mentions_and_message_updates(
    tmp_path: Path,
) -> None:
    chat, _employees, _contacts, viktor, anna, lena = _chat_world(tmp_path)
    created_at = _now()
    thread = ChatThread(
        thread_id="00000000-0000-4000-8000-000000000501",
        thread_type="DIRECT",
        title=None,
        created_by_employee_id=viktor.id,
        created_at=created_at,
    )
    chat.create_thread(
        thread,
        (
            ChatParticipant(thread.thread_id, viktor.id, created_at),
            ChatParticipant(thread.thread_id, anna.id, created_at),
        ),
        direct_pair=(viktor.id, anna.id),
    )
    message = ChatMessage("m1", thread.thread_id, viktor.id, "Hallo", None, created_at)
    chat.add_message(message)

    with pytest.raises(sqlite3.IntegrityError, match="not a participant"):
        chat._conn.execute(
            "INSERT INTO chat_message_mentions (message_id, employee_id) VALUES (?, ?)",
            (message.message_id, lena.id),
        )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        chat._conn.execute(
            "UPDATE chat_messages SET body = ? WHERE message_id = ?",
            ("Geaendert", message.message_id),
        )

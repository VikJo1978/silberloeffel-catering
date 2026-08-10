from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
import uuid
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest

from catering_system.domain.contact_profile import ContactProfile
from catering_system.repositories.sqlite_contact_profile_repository import (
    SQLiteContactProfileRepository,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.employee_auth_service import EmployeeAuthService
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.remote_core_client import RemoteCoreClient, RemoteCoreError
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content
from tests.helpers.order_seed import seed_order

_TOKEN = "test-office-api-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_NOW = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)


def _start_api_server(db: Path) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        from catering_system.ui.office_api import create_office_api_server

        server = create_office_api_server(
            str(db),
            _TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
            employee_auth_now=lambda: _NOW,
        )
        ready.put(server)
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return server, thread, f"http://{host!s}:{int(port)}"


def _seed_auth(db: Path) -> dict[str, str]:
    repo = SQLiteEmployeeAuthRepository(db)
    service = EmployeeAuthService(repo, now=lambda: _NOW)
    service.bootstrap_superadmin(
        username="chat.admin",
        display_name="Chat Admin",
        password="TempPassw0rd!",
    )
    initial = service.authenticate(username="chat.admin", password="TempPassw0rd!")
    service.change_password(
        service.authenticate_session(initial.session_token),
        current_password="TempPassw0rd!",
        new_password="ChangedPassw0rd!",
    )
    admin_session = service.authenticate(
        username="chat.admin", password="ChangedPassw0rd!"
    ).session_token
    admin_actor = service.authenticate_session(admin_session)
    viktor = service.create_account(
        admin_actor,
        username="chat.viktor",
        display_name="Viktor",
        password="ViktorPassw0rd!",
        role="USER",
        must_change_password=False,
    )
    anna = service.create_account(
        admin_actor,
        username="chat.anna",
        display_name="Anna",
        password="AnnaPassw0rd!",
        role="USER",
        must_change_password=False,
    )
    lena = service.create_account(
        admin_actor,
        username="chat.lena",
        display_name="Lena",
        password="LenaPassw0rd!",
        role="USER",
        must_change_password=False,
    )
    viewer = service.create_account(
        admin_actor,
        username="chat.viewer",
        display_name="Viewer",
        password="ViewerPassw0rd!",
        role="VIEWER",
        must_change_password=False,
    )
    service.create_account(
        admin_actor,
        username="chat.send.only",
        display_name="Chat Send Only",
        password="ChatSendPassw0rd!",
        role="USER",
        explicit_permissions={"chat.send"},
        must_change_password=False,
    )
    service.create_account(
        admin_actor,
        username="chat.no.orders",
        display_name="Chat No Orders",
        password="NoOrdersPassw0rd!",
        role="USER",
        explicit_permissions={"chat.send", "inquiries.view", "customers.view"},
        must_change_password=False,
    )
    service.create_account(
        admin_actor,
        username="chat.no.inquiries",
        display_name="Chat No Inquiries",
        password="NoInquiriesPassw0rd!",
        role="USER",
        explicit_permissions={"chat.send", "orders.view", "customers.view"},
        must_change_password=False,
    )
    service.create_account(
        admin_actor,
        username="chat.no.customers",
        display_name="Chat No Customers",
        password="NoCustomersPassw0rd!",
        role="USER",
        explicit_permissions={"chat.send", "orders.view", "inquiries.view"},
        must_change_password=False,
    )
    service.create_account(
        admin_actor,
        username="chat.create.only",
        display_name="Chat Create Only",
        password="ChatCreatePassw0rd!",
        role="USER",
        explicit_permissions={"chat.create"},
        must_change_password=False,
    )
    inactive = service.create_account(
        admin_actor,
        username="chat.inactive",
        display_name="Inactive Chat User",
        password="InactivePassw0rd!",
        role="USER",
        must_change_password=False,
    )
    service.deactivate_account(admin_actor, inactive.id)
    sessions = {
        "viktor_session": service.authenticate(
            username="chat.viktor", password="ViktorPassw0rd!"
        ).session_token,
        "anna_session": service.authenticate(
            username="chat.anna", password="AnnaPassw0rd!"
        ).session_token,
        "lena_session": service.authenticate(
            username="chat.lena", password="LenaPassw0rd!"
        ).session_token,
        "viewer_session": service.authenticate(
            username="chat.viewer", password="ViewerPassw0rd!"
        ).session_token,
        "chat_send_only_session": service.authenticate(
            username="chat.send.only", password="ChatSendPassw0rd!"
        ).session_token,
        "chat_send_no_orders_session": service.authenticate(
            username="chat.no.orders", password="NoOrdersPassw0rd!"
        ).session_token,
        "chat_send_no_inquiries_session": service.authenticate(
            username="chat.no.inquiries", password="NoInquiriesPassw0rd!"
        ).session_token,
        "chat_send_no_customers_session": service.authenticate(
            username="chat.no.customers", password="NoCustomersPassw0rd!"
        ).session_token,
        "chat_create_only_session": service.authenticate(
            username="chat.create.only", password="ChatCreatePassw0rd!"
        ).session_token,
    }
    repo.close()
    return {
        "viktor_id": viktor.id,
        "anna_id": anna.id,
        "lena_id": lena.id,
        "viewer_id": viewer.id,
        "inactive_id": inactive.id,
        **sessions,
    }


def _seed_entities(db: Path) -> dict[str, str]:
    inquiries = SQLiteInquiryRepository(db)
    orders = SQLiteOrderRepository(db)
    inquiry = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 15),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=26,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="mueller@example.com",
        contact_phone="+49301234567",
        company_name="Mueller GmbH",
        contact_name="Marta Mueller",
    )
    order, _version = seed_order(orders, inquiry)
    profiles = SQLiteContactProfileRepository(db)
    contact_id = str(uuid.uuid4())
    profiles.create_profile(
        ContactProfile(
            contact_profile_id=contact_id,
            display_name="Marta Mueller",
            email="mueller@example.com",
            phone="+49301234567",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    inquiries.close()
    orders.close()
    profiles.close()
    return {
        "inquiry_id": inquiry.inquiry_id,
        "order_id": order.order_id,
        "contact_profile_id": contact_id,
    }


@pytest.fixture()
def chat_api(tmp_path: Path):
    db = tmp_path / "core.db"
    ids = {**_seed_auth(db), **_seed_entities(db)}
    server, thread, base = _start_api_server(db)
    try:
        yield base, ids
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert thread.is_alive() is False


def _headers(session_token: str) -> dict[str, str]:
    return {**_AUTH, "X-Employee-Session": session_token}


def _post(
    url: str,
    *,
    headers: dict[str, str],
    args: dict[str, object] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(
        {"command_id": str(uuid.uuid4()), "expect": {}, "args": args or {}}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _get(url: str, *, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _direct(base: str, ids: dict[str, str]) -> str:
    status, body = _post(
        f"{base}/office/v1/chat/threads",
        headers=_headers(ids["viktor_session"]),
        args={"thread_type": "DIRECT", "participant_employee_ids": [ids["anna_id"]]},
    )
    assert status == 201
    return str(body["thread"]["thread_id"])


def test_direct_duplicate_is_order_independent_and_actor_is_session_bound(
    chat_api,
) -> None:
    base, ids = chat_api
    first = _direct(base, ids)
    status, duplicate = _post(
        f"{base}/office/v1/chat/threads",
        headers=_headers(ids["anna_session"]),
        args={"thread_type": "DIRECT", "participant_employee_ids": [ids["viktor_id"]]},
    )
    assert status == 200
    assert duplicate["thread"]["thread_id"] == first

    status, spoof = _post(
        f"{base}/office/v1/chat/threads/{first}/messages",
        headers=_headers(ids["viktor_session"]),
        args={
            "body": "spoof",
            "author_employee_id": ids["lena_id"],
        },
    )
    assert status == 400
    assert spoof["error"] == "invalid_request"


def test_send_message_atomicity_and_message_validity(chat_api) -> None:
    base, ids = chat_api
    thread_id = _direct(base, ids)
    headers = _headers(ids["viktor_session"])
    url = f"{base}/office/v1/chat/threads/{thread_id}/messages"

    status, body = _post(
        url,
        headers=headers,
        args={
            "body": "   ",
            "mention_employee_ids": [ids["anna_id"]],
            "references": [],
        },
    )
    assert status == 422
    assert body["error"] == "invalid_chat_message"

    status, body = _post(
        url,
        headers=headers,
        args={"body": "hi", "mention_employee_ids": [ids["lena_id"]]},
    )
    assert status == 422
    assert body["error"] == "invalid_chat_mention"

    status, body = _post(
        url,
        headers=headers,
        args={
            "body": "hi",
            "references": [
                {"reference_type": "ORDER", "reference_id": str(uuid.uuid4())}
            ],
        },
    )
    assert status == 422
    assert body["error"] == "invalid_chat_reference"

    status, detail = _get(
        f"{base}/office/v1/chat/threads/{thread_id}",
        headers=headers,
    )
    assert status == 200
    assert detail["messages"] == []

    status, sent = _post(
        url,
        headers=headers,
        args={
            "body": "",
            "references": [
                {
                    "reference_type": "CONTACT",
                    "reference_id": ids["contact_profile_id"],
                }
            ],
        },
    )
    assert status == 201
    assert sent["message"]["body"] == ""
    assert sent["message"]["references"] == [
        {"reference_type": "CONTACT", "reference_id": ids["contact_profile_id"]}
    ]


def test_membership_and_read_marker_are_enforced(chat_api) -> None:
    base, ids = chat_api
    first_thread = _direct(base, ids)
    second_status, second_body = _post(
        f"{base}/office/v1/chat/threads",
        headers=_headers(ids["viktor_session"]),
        args={"thread_type": "DIRECT", "participant_employee_ids": [ids["lena_id"]]},
    )
    assert second_status == 201
    second_thread = str(second_body["thread"]["thread_id"])

    status, _body = _get(
        f"{base}/office/v1/chat/threads/{first_thread}",
        headers=_headers(ids["lena_session"]),
    )
    assert status == 404
    status, _body = _post(
        f"{base}/office/v1/chat/threads/{first_thread}/messages",
        headers=_headers(ids["lena_session"]),
        args={"body": "no"},
    )
    assert status == 404

    status, first_message = _post(
        f"{base}/office/v1/chat/threads/{first_thread}/messages",
        headers=_headers(ids["viktor_session"]),
        args={"body": "first"},
    )
    assert status == 201
    status, second_message = _post(
        f"{base}/office/v1/chat/threads/{second_thread}/messages",
        headers=_headers(ids["viktor_session"]),
        args={"body": "second"},
    )
    assert status == 201

    status, body = _post(
        f"{base}/office/v1/chat/threads/{first_thread}/read",
        headers=_headers(ids["anna_session"]),
        args={"last_read_message_id": second_message["message"]["message_id"]},
    )
    assert status == 422
    assert body["error"] == "invalid_chat_message"

    status, _body = _post(
        f"{base}/office/v1/chat/threads/{first_thread}/read",
        headers=_headers(ids["anna_session"]),
        args={"last_read_message_id": first_message["message"]["message_id"]},
    )
    assert status == 200

    status, anna_detail = _get(
        f"{base}/office/v1/chat/threads/{first_thread}",
        headers=_headers(ids["anna_session"]),
    )
    assert status == 200
    assert (
        anna_detail["current_participant"]["last_read_message_id"]
        == first_message["message"]["message_id"]
    )
    status, viktor_detail = _get(
        f"{base}/office/v1/chat/threads/{first_thread}",
        headers=_headers(ids["viktor_session"]),
    )
    assert status == 200
    assert viktor_detail["current_participant"]["last_read_message_id"] is None


def test_search_picker_participants_and_rbac(chat_api) -> None:
    base, ids = chat_api
    thread_id = _direct(base, ids)
    _post(
        f"{base}/office/v1/chat/threads/{thread_id}/messages",
        headers=_headers(ids["viktor_session"]),
        args={"body": "secret-mueller"},
    )

    status, results = _get(
        f"{base}/office/v1/chat/search?q=secret-mueller",
        headers=_headers(ids["anna_session"]),
    )
    assert status == 200
    assert [row["thread"]["thread_id"] for row in results["results"]] == [thread_id]

    status, results = _get(
        f"{base}/office/v1/chat/search?q=secret-mueller",
        headers=_headers(ids["lena_session"]),
    )
    assert status == 200
    assert results["results"] == []

    status, participants = _get(
        f"{base}/office/v1/chat/threads/{thread_id}/participants?q=Len",
        headers=_headers(ids["viktor_session"]),
    )
    assert status == 200
    assert participants["participants"] == []

    status, contacts = _get(
        f"{base}/office/v1/chat/entity-search?q=Mueller&type=CONTACT",
        headers=_headers(ids["viktor_session"]),
    )
    assert status == 200
    assert contacts["results"][0]["reference_id"] == ids["contact_profile_id"]
    assert contacts["results"][0]["meta"] == {
        "contact_profile_id": ids["contact_profile_id"]
    }

    status, body = _post(
        f"{base}/office/v1/chat/threads",
        headers=_headers(ids["viewer_session"]),
        args={"thread_type": "DIRECT", "participant_employee_ids": [ids["anna_id"]]},
    )
    assert status == 403
    assert body["error"] == "forbidden"


def test_entity_picker_requires_target_entity_view_permission(chat_api) -> None:
    base, ids = chat_api
    cases = [
        ("ORDER", "chat_send_no_orders_session"),
        ("INQUIRY", "chat_send_no_inquiries_session"),
        ("CONTACT", "chat_send_no_customers_session"),
    ]
    for reference_type, session_key in cases:
        status, body = _get(
            f"{base}/office/v1/chat/entity-search?q=Mueller&type={reference_type}",
            headers=_headers(ids[session_key]),
        )
        assert status == 403
        assert body == {"error": "forbidden"}

    status, body = _get(
        f"{base}/office/v1/chat/entity-search?q=Mueller&type=CONTACT",
        headers=_headers(ids["chat_send_only_session"]),
    )
    assert status == 403
    assert body == {"error": "forbidden"}


def test_chat_employee_picker_is_minimal_active_and_requires_create(chat_api) -> None:
    base, ids = chat_api
    status, body = _get(
        f"{base}/office/v1/chat/employees?q=chat",
        headers=_headers(ids["chat_create_only_session"]),
    )
    assert status == 200
    employees = body["employees"]
    assert employees
    assert all(set(row) == {"employee_id", "display_name"} for row in employees)
    assert ids["inactive_id"] not in {row["employee_id"] for row in employees}
    assert "Inactive Chat User" not in {row["display_name"] for row in employees}
    assert [row["display_name"] for row in employees] == sorted(
        row["display_name"] for row in employees
    )
    serialized = json.dumps(body)
    for forbidden in (
        "username",
        "role",
        "permissions",
        "password",
        "session",
        "must_change_password",
    ):
        assert forbidden not in serialized

    status, body = _get(
        f"{base}/office/v1/chat/employees?q=chat",
        headers=_headers(ids["viewer_session"]),
    )
    assert status == 403
    assert body == {"error": "forbidden"}


def test_chat_search_does_not_reveal_inaccessible_title_participants_or_reference(
    chat_api,
) -> None:
    base, ids = chat_api
    status, created = _post(
        f"{base}/office/v1/chat/threads",
        headers=_headers(ids["viktor_session"]),
        args={
            "thread_type": "GROUP",
            "title": "secret-title-leak-check",
            "participant_employee_ids": [ids["lena_id"]],
        },
    )
    assert status == 201
    thread_id = str(created["thread"]["thread_id"])
    status, sent = _post(
        f"{base}/office/v1/chat/threads/{thread_id}/messages",
        headers=_headers(ids["viktor_session"]),
        args={
            "body": "secret-body-leak-check",
            "references": [
                {
                    "reference_type": "CONTACT",
                    "reference_id": ids["contact_profile_id"],
                }
            ],
        },
    )
    assert status == 201
    assert sent["message"]["references"][0]["reference_id"] == ids["contact_profile_id"]

    for query in (
        "secret-title-leak-check",
        "secret-body-leak-check",
        "Lena",
        "Marta Mueller",
        ids["contact_profile_id"],
    ):
        status, results = _get(
            f"{base}/office/v1/chat/search?q={quote(query)}",
            headers=_headers(ids["anna_session"]),
        )
        assert status == 200
        assert results["results"] == []


def test_remote_core_client_chat_methods_preserve_shapes(chat_api) -> None:
    base, ids = chat_api
    client = RemoteCoreClient(base, _TOKEN)
    thread = client.create_chat_thread(
        employee_session_token=ids["viktor_session"],
        thread_type="DIRECT",
        participant_employee_ids=[ids["anna_id"]],
    )
    message = client.send_chat_message(
        str(thread["thread_id"]),
        employee_session_token=ids["viktor_session"],
        body="@Anna",
        mention_employee_ids=[ids["anna_id"]],
        references=[
            {"reference_type": "INQUIRY", "reference_id": ids["inquiry_id"]},
        ],
    )
    reply = client.send_chat_message(
        str(thread["thread_id"]),
        employee_session_token=ids["anna_session"],
        body="ok",
        reply_to_message_id=str(message["message_id"]),
    )
    detail = client.get_chat_thread(
        str(thread["thread_id"]), employee_session_token=ids["viktor_session"]
    )
    employees = client.search_chat_employees(
        employee_session_token=ids["viktor_session"], q="Anna"
    )
    messages = cast(list[dict[str, Any]], detail["messages"])
    assert employees == [{"employee_id": ids["anna_id"], "display_name": "Anna"}]
    assert messages[0]["mentions"][0]["employee_id"] == ids["anna_id"]
    assert messages[0]["references"][0]["reference_id"] == ids["inquiry_id"]
    assert messages[1]["reply_to_message_id"] == reply["reply_to_message_id"]

    with pytest.raises(RemoteCoreError) as exc:
        client.search_chat_entities(
            employee_session_token=ids["viewer_session"],
            q="Mueller",
            reference_type="CONTACT",
        )
    assert exc.value.status == 403


def test_remote_core_client_rejects_malformed_chat_response() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            payload = json.dumps({"threads": [{"thread": {}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        client = RemoteCoreClient(f"http://{host!s}:{int(port)}", _TOKEN)
        with pytest.raises(RemoteCoreError) as exc:
            client.list_chat_threads(employee_session_token="session")
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

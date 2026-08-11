from __future__ import annotations

import queue
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import EmployeeAuthService
from catering_system.ui.employee_auth_http import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from catering_system.ui.office_api import create_office_api_server
from catering_system.ui.office_panel import create_office_panel_server
from catering_system.ui.office_panel_chat import render_chat_detail
from catering_system.ui.office_panel_views import OfficePageContext
from catering_system.ui.remote_core_client import RemoteCoreClient
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content

_API_TOKEN = "test-office-api-token"
_NOW = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)


@dataclass(frozen=True)
class PanelChatWorld:
    panel_base: str
    api_base: str
    api_server: HTTPServer
    api_thread: threading.Thread
    panel_server: HTTPServer
    panel_thread: threading.Thread
    client: RemoteCoreClient
    viktor_id: str
    viktor_session: str
    viktor_csrf: str
    anna_id: str
    anna_session: str


def _run_server(factory) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        server = factory()
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
    first = service.authenticate(username="chat.admin", password="TempPassw0rd!")
    service.change_password(
        service.authenticate_session(first.session_token),
        current_password="TempPassw0rd!",
        new_password="ChangedPassw0rd!",
    )
    admin = service.authenticate(username="chat.admin", password="ChangedPassw0rd!")
    actor = service.authenticate_session(admin.session_token)
    viktor = service.create_account(
        actor,
        username="chat.viktor",
        display_name="Viktor",
        password="ViktorPassw0rd!",
        role="USER",
        must_change_password=False,
    )
    anna = service.create_account(
        actor,
        username="chat.anna",
        display_name="Anna",
        password="AnnaPassw0rd!",
        role="USER",
        must_change_password=False,
    )
    inactive = service.create_account(
        actor,
        username="chat.inactive",
        display_name="Inactive Chat User",
        password="InactivePassw0rd!",
        role="USER",
        must_change_password=False,
    )
    service.deactivate_account(actor, inactive.id)
    viktor_login = service.authenticate(
        username="chat.viktor", password="ViktorPassw0rd!"
    )
    anna_login = service.authenticate(username="chat.anna", password="AnnaPassw0rd!")
    return {
        "viktor_id": viktor.id,
        "viktor_session": viktor_login.session_token,
        "viktor_csrf": viktor_login.csrf_token,
        "anna_id": anna.id,
        "anna_session": anna_login.session_token,
    }


@pytest.fixture()
def chat_panel_world(tmp_path: Path):
    db = tmp_path / "chat-panel.db"
    ids = _seed_auth(db)
    api_server, api_thread, api_base = _run_server(
        lambda: create_office_api_server(
            str(db),
            _API_TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
            employee_auth_now=lambda: _NOW,
        )
    )
    remote = RemoteCoreClient(api_base, _API_TOKEN)
    panel_connection = sqlite3.connect(str(db), check_same_thread=False)
    panel_auth = EmployeeAuthService(
        SQLiteEmployeeAuthRepository.from_connection(panel_connection),
        now=lambda: _NOW,
    )
    panel_server, panel_thread, panel_base = _run_server(
        lambda: create_office_panel_server(
            InMemoryInquiryRepository(),
            InMemoryOrderRepository(),
            "shared-office-password",
            host="127.0.0.1",
            port=0,
            remote=remote,
            auth_mode="employee",
            auth_service=panel_auth,
            secure_cookie=False,
            ui_version="v2",
        )
    )
    yield PanelChatWorld(
        panel_base=panel_base,
        api_base=api_base,
        api_server=api_server,
        api_thread=api_thread,
        panel_server=panel_server,
        panel_thread=panel_thread,
        client=remote,
        **ids,
    )
    for server, thread in (
        (panel_server, panel_thread),
        (api_server, api_thread),
    ):
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    panel_connection.close()


def _cookie(world: PanelChatWorld) -> str:
    return (
        f"{SESSION_COOKIE_NAME}={world.viktor_session}; "
        f"{CSRF_COOKIE_NAME}={world.viktor_csrf}"
    )


def _request(
    world: PanelChatWorld,
    path: str,
    *,
    method: str = "GET",
    data: dict[str, str] | list[tuple[str, str]] | None = None,
) -> tuple[int, str, str]:
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        f"{world.panel_base}{path}",
        data=body,
        method=method,
        headers={"Cookie": _cookie(world)},
    )
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.geturl(), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.geturl(), exc.read().decode("utf-8")


def _hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    assert match, f"missing hidden field {name}"
    return match.group(1)


def _form(html: str, *, method: str, action: str) -> str:
    match = re.search(
        rf'<form[^>]*method="{re.escape(method)}"[^>]*action="{re.escape(action)}"[^>]*>.*?</form>',
        html,
        flags=re.DOTALL,
    )
    assert match, f"missing {method} form {action}"
    return match.group(0)


def _render_message_body(body: str) -> str:
    return render_chat_detail(
        {
            "thread": {
                "thread_id": "thread-1",
                "thread_type": "DIRECT",
                "title": None,
            },
            "participants": [
                {"employee_id": "viktor", "display_name": "Viktor"},
                {"employee_id": "anna", "display_name": "Anna"},
            ],
            "messages": [
                {
                    "message_id": "message-1",
                    "thread_id": "thread-1",
                    "author_display_name": "Anna",
                    "body": body,
                    "created_at": "2026-08-10T08:00:00+00:00",
                    "reply_to_message_id": None,
                    "mentions": [],
                    "references": [],
                }
            ],
        },
        context=OfficePageContext(employee_account_id="viktor"),
        read_command_fields="",
        send_command_fields="",
        participant_results=[],
        mention_q="",
        entity_results=[],
        reference_q="",
        reference_type="ORDER",
        reply_to_message_id="",
    )


def test_chat_message_body_linkifies_http_and_https_urls() -> None:
    html = _render_message_body(
        "Docs https://example.test/a?x=1&y=2 and http://intranet.test/path."
    )

    assert (
        '<a href="https://example.test/a?x=1&amp;y=2" '
        'target="_blank" rel="noopener noreferrer">'
        "https://example.test/a?x=1&amp;y=2</a>"
    ) in html
    assert (
        '<a href="http://intranet.test/path" '
        'target="_blank" rel="noopener noreferrer">'
        "http://intranet.test/path</a>."
    ) in html


def test_chat_message_body_escapes_text_and_ignores_unsafe_schemes() -> None:
    html = _render_message_body(
        '5 < 7 & <script>alert("x")</script> javascript:alert(1) data:text/html,payload'
    )

    assert "5 &lt; 7 &amp; &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "javascript:alert(1)" in html
    assert "data:text/html,payload" in html
    assert "<script>" not in html
    assert 'href="javascript:' not in html
    assert 'href="data:' not in html


def test_chat_nav_list_badge_and_search_use_remote_client(
    chat_panel_world: PanelChatWorld,
) -> None:
    thread = chat_panel_world.client.create_chat_thread(
        employee_session_token=chat_panel_world.viktor_session,
        thread_type="DIRECT",
        participant_employee_ids=[chat_panel_world.anna_id],
    )
    chat_panel_world.client.send_chat_message(
        str(thread["thread_id"]),
        employee_session_token=chat_panel_world.anna_session,
        body="Bitte Angebot prüfen",
    )

    status, _url, html = _request(chat_panel_world, "/chat?q=Angebot")

    assert status == 200
    assert "Nachrichten" in html
    assert "Anna" in html
    assert "Bitte Angebot prüfen" in html
    assert '<span class="badge">1</span>' in html
    assert "Suchbegriff eingeben." not in html


def test_chat_detail_get_does_not_mark_read_but_explicit_post_does(
    chat_panel_world: PanelChatWorld,
) -> None:
    thread = chat_panel_world.client.create_chat_thread(
        employee_session_token=chat_panel_world.viktor_session,
        thread_type="DIRECT",
        participant_employee_ids=[chat_panel_world.anna_id],
    )
    message = chat_panel_world.client.send_chat_message(
        str(thread["thread_id"]),
        employee_session_token=chat_panel_world.anna_session,
        body="Neue Nachricht",
    )

    status, _url, html = _request(chat_panel_world, f"/chat/{thread['thread_id']}")
    unread_after_get = chat_panel_world.client.list_chat_threads(
        employee_session_token=chat_panel_world.viktor_session
    )[0]["unread_count"]

    assert status == 200
    assert "Gelesen markieren" in html
    assert unread_after_get == 1

    status, url, _html = _request(
        chat_panel_world,
        f"/chat/{thread['thread_id']}/read",
        method="POST",
        data={
            "_csrf_token": chat_panel_world.viktor_csrf,
            "_command_id": _hidden(html, "_command_id"),
            "last_read_message_id": str(message["message_id"]),
        },
    )
    unread_after_post = chat_panel_world.client.list_chat_threads(
        employee_session_token=chat_panel_world.viktor_session
    )[0]["unread_count"]

    assert status == 200
    assert url.endswith(f"/chat/{thread['thread_id']}")
    assert unread_after_post == 0


def test_chat_create_uses_minimal_employee_picker_and_no_sensitive_fields(
    chat_panel_world: PanelChatWorld,
) -> None:
    status, _url, html = _request(chat_panel_world, "/chat/new?q=Anna")

    assert status == 200
    assert "Anna" in html
    assert "chat.anna" not in html
    assert "role" not in html.lower()
    assert "permission" not in html.lower()
    assert "Inactive Chat User" not in html
    assert html.count('name="participant_employee_id"') == 1

    search_form = _form(html, method="get", action="/chat/new")
    create_form = _form(html, method="post", action="/chat/threads")
    assert 'name="q"' in search_form
    assert 'name="participant_employee_id"' not in search_form
    assert 'name="participant_employee_id"' in create_form

    status, url, _html = _request(
        chat_panel_world,
        "/chat/threads",
        method="POST",
        data=[
            ("_csrf_token", chat_panel_world.viktor_csrf),
            ("_command_id", _hidden(html, "_command_id")),
            ("thread_type", "DIRECT"),
            ("participant_employee_id", chat_panel_world.anna_id),
            ("title", ""),
        ],
    )

    assert status == 200
    assert "/chat/" in url


def test_chat_send_form_has_no_actor_field_and_uses_session_identity(
    chat_panel_world: PanelChatWorld,
) -> None:
    thread = chat_panel_world.client.create_chat_thread(
        employee_session_token=chat_panel_world.viktor_session,
        thread_type="DIRECT",
        participant_employee_ids=[chat_panel_world.anna_id],
    )
    status, _url, html = _request(
        chat_panel_world,
        f"/chat/{thread['thread_id']}?mention_q=Anna",
    )

    assert status == 200
    assert 'name="author_employee_id"' not in html
    assert 'name="actor_employee_id"' not in html
    assert 'name="employee_id"' not in html

    status, _url, _html = _request(
        chat_panel_world,
        f"/chat/{thread['thread_id']}/messages",
        method="POST",
        data=[
            ("_csrf_token", chat_panel_world.viktor_csrf),
            ("_command_id", _hidden(html, "_command_id")),
            ("body", "@Anna erledigt"),
            ("mention_employee_id", chat_panel_world.anna_id),
        ],
    )
    detail = chat_panel_world.client.get_chat_thread(
        str(thread["thread_id"]),
        employee_session_token=chat_panel_world.viktor_session,
    )
    messages = detail["messages"]

    assert status == 200
    assert messages[-1]["author_employee_id"] == chat_panel_world.viktor_id
    assert messages[-1]["mentions"][0]["employee_id"] == chat_panel_world.anna_id

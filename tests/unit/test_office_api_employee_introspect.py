"""Core Office API employee-session introspection contract (AUTH-2E1)."""

from __future__ import annotations

import socket
import json
import queue
import threading
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.domain.employee_auth import PERMISSION_SET
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import EmployeeAuthService
from catering_system.ui.office_api_employee_introspect import (
    EMPLOYEE_INTROSPECT_PATH,
    perform_employee_introspection,
    validate_introspection_request_body,
)
from catering_system.ui.office_api_service_auth import (
    IntrospectionServiceTokenConfigError,
    OfficeApiServiceAuth,
    parse_introspection_service_tokens,
    read_introspection_service_tokens_from_env,
)
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content

_PANEL_TOKEN = "test-office-api-token"
_CONFIGURATOR_TOKEN = "test-configurator-introspect-token"
_INTROSPECT_PATH = EMPLOYEE_INTROSPECT_PATH
_PANEL_AUTH = {"Authorization": f"Bearer {_PANEL_TOKEN}"}
_CONFIGURATOR_AUTH = {
    "Authorization": f"Bearer {_CONFIGURATOR_TOKEN}",
}


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _start_api_server(
    db: Path,
    *,
    introspection_tokens: dict[str, str] | None = None,
    employee_auth_now: Callable[[], datetime] | None = None,
) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        from catering_system.ui.office_api import create_office_api_server

        server = create_office_api_server(
            str(db),
            _PANEL_TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
            introspection_service_tokens=(
                {"configurator": _CONFIGURATOR_TOKEN}
                if introspection_tokens is None
                else introspection_tokens
            ),
            employee_auth_now=employee_auth_now,
        )
        ready.put(server)
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


def _auth_service(
    db: Path, clock: Clock
) -> tuple[EmployeeAuthService, SQLiteEmployeeAuthRepository]:
    repo = SQLiteEmployeeAuthRepository(db)
    service = EmployeeAuthService(repo, now=clock.now)
    service.bootstrap_superadmin(
        username="super.admin",
        display_name="Super Admin",
        password="TempPassw0rd!",
        metadata={"seed": "test"},
    )
    return service, repo


def _ready_session(
    service: EmployeeAuthService,
    *,
    username: str = "super.admin",
    password: str = "TempPassw0rd!",
) -> tuple[str, object]:
    login = service.authenticate(username=username, password=password)
    service.change_password(
        service.authenticate_session(login.session_token),
        current_password=password,
        new_password="ChangedTemp1!",
    )
    relogin = service.authenticate(username=username, password="ChangedTemp1!")
    return relogin.session_token, relogin


@pytest.fixture()
def introspect_api(tmp_path: Path):
    clock = Clock(datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    db = tmp_path / f"introspect-{uuid.uuid4().hex}.sqlite3"
    auth_service, repo = _auth_service(db, clock)
    server, thread, base = _start_api_server(
        db,
        employee_auth_now=clock.now,
    )
    yield {
        "base": base,
        "db": db,
        "clock": clock,
        "auth_service": auth_service,
        "repo": repo,
    }
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert thread.is_alive() is False
    repo.close()


def _introspect_post(
    base: str,
    *,
    headers: dict[str, str] | None = None,
    session_token: str | None = None,
    body: bytes | None = b"",
) -> tuple[int, dict, dict]:
    all_headers = dict(_CONFIGURATOR_AUTH)
    if headers is not None:
        all_headers.update(headers)
    if session_token is not None:
        all_headers["X-Employee-Session"] = session_token
    req = urllib.request.Request(
        f"{base}{_INTROSPECT_PATH}",
        data=body,
        headers=all_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}"), dict(exc.headers)


def _introspect_raw_post(base: str, raw_request: bytes) -> tuple[int, dict]:
    host_port = base.removeprefix("http://")
    host, port_text = host_port.split(":", 1)
    port = int(port_text)
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(raw_request)
        chunks: list[bytes] = []
        while True:
            part = sock.recv(4096)
            if not part:
                break
            chunks.append(part)
    raw_response = b"".join(chunks)
    header_block, _body = raw_response.split(b"\r\n\r\n", 1)
    status_line = header_block.split(b"\r\n", 1)[0]
    status = int(status_line.split(b" ", 2)[1])
    body_start = raw_response.find(b"\r\n\r\n") + 4
    payload = json.loads(raw_response[body_start:].decode() or "{}")
    return status, payload


def _introspect_post_header_list(
    base: str,
    header_items: list[tuple[str, str]],
    *,
    body: bytes = b"",
) -> tuple[int, dict]:
    header_lines = "".join(f"{name}: {value}\r\n" for name, value in header_items)
    raw_request = (
        f"POST {_INTROSPECT_PATH} HTTP/1.0\r\n"
        f"{header_lines}"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n"
    ).encode("utf-8") + body
    return _introspect_raw_post(base, raw_request)


def test_missing_bearer_returns_401(introspect_api) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Authorization": ""},
    )
    assert status == 401
    assert body == {"error": "unauthorized"}


def test_invalid_bearer_returns_401(introspect_api) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert status == 401
    assert body == {"error": "unauthorized"}


def test_office_panel_bearer_returns_403(introspect_api) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers=_PANEL_AUTH,
    )
    assert status == 403
    assert body == {"error": "forbidden"}


@pytest.mark.parametrize(
    "extra_headers",
    [
        {"Content-Length": "12"},
        {"Content-Length": "not-a-number"},
        {"Transfer-Encoding": "chunked"},
    ],
    ids=["non_empty_body", "invalid_content_length", "chunked_body"],
)
def test_missing_bearer_returns_401_before_body_validation(
    introspect_api, extra_headers: dict[str, str]
) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Authorization": "Bearer wrong-token", **extra_headers},
        body=b'{"account_id":"x"}'
        if extra_headers.get("Content-Length") == "12"
        else b"",
    )
    assert status == 401
    assert body == {"error": "unauthorized"}


@pytest.mark.parametrize(
    "session_token",
    ["not valid!", "a" * 300],
    ids=["malformed_session", "oversized_session"],
)
def test_missing_bearer_returns_401_before_session_validation(
    introspect_api, session_token: str
) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Authorization": "Bearer wrong-token"},
        session_token=session_token,
    )
    assert status == 401
    assert body == {"error": "unauthorized"}


def test_missing_bearer_with_client_identity_body_returns_401(introspect_api) -> None:
    payload = json.dumps(
        {"account_id": str(uuid.uuid4()), "effective_permissions": ["offers.prepare"]}
    ).encode("utf-8")
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Authorization": "Bearer wrong-token"},
        body=payload,
    )
    assert status == 401
    assert body == {"error": "unauthorized"}


def test_missing_session_header_returns_unauthenticated(introspect_api) -> None:
    status, body, headers = _introspect_post(introspect_api["base"])
    assert status == 200
    assert body == {
        "authenticated": False,
        "application_access_allowed": False,
        "principal": None,
    }
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert "Access-Control-Allow-Origin" not in headers


def test_empty_session_header_returns_unauthenticated(introspect_api) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token="   ",
    )
    assert status == 200
    assert body["authenticated"] is False
    assert body["principal"] is None


def test_malformed_session_header_returns_400(introspect_api) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token="not valid token!",
    )
    assert status == 400
    assert body == {"error": "invalid_request"}


def test_oversized_session_header_returns_400(introspect_api) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token="a" * 300,
    )
    assert status == 400
    assert body == {"error": "invalid_request"}


def test_valid_superadmin_session_returns_permissions(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    session_token, _login = _ready_session(service)
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token=session_token,
    )
    assert status == 200
    assert body["authenticated"] is True
    assert body["application_access_allowed"] is True
    principal = body["principal"]
    assert isinstance(principal, dict)
    assert principal["role"] == "SUPERADMIN"
    assert principal["effective_permissions"] == sorted(PERMISSION_SET)
    assert "session" not in json.dumps(body)
    assert "csrf" not in json.dumps(body).lower()
    assert "email" not in principal


def test_viewer_session_returns_view_permissions_only(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    superadmin_token, _super_login = _ready_session(service)
    superadmin = service.authenticate_session(superadmin_token)
    viewer = service.create_account(
        superadmin,
        username="viewer.user",
        display_name="Viewer User",
        password="ViewerTemp1!",
        role="VIEWER",
        explicit_permissions={"inquiries.view"},
    )
    login = service.authenticate(username=viewer.username, password="ViewerTemp1!")
    service.change_password(
        service.authenticate_session(login.session_token),
        current_password="ViewerTemp1!",
        new_password="ViewerChanged1!",
    )
    relogin = service.authenticate(username=viewer.username, password="ViewerChanged1!")
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token=relogin.session_token,
    )
    assert status == 200
    principal = body["principal"]
    assert principal["role"] == "VIEWER"
    assert principal["effective_permissions"] == ["inquiries.view"]


def test_must_change_password_blocks_application_access(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    login = service.authenticate(username="super.admin", password="TempPassw0rd!")
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token=login.session_token,
    )
    assert status == 200
    assert body["authenticated"] is True
    assert body["application_access_allowed"] is False
    assert body["principal"]["effective_permissions"] == []


def test_expired_session_returns_unauthenticated(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    clock: Clock = introspect_api["clock"]
    session_token, _login = _ready_session(service)
    clock.value = clock.value + timedelta(hours=13)
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token=session_token,
    )
    assert status == 200
    assert body["authenticated"] is False


def test_revoked_session_returns_unauthenticated(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    session_token, _login = _ready_session(service)
    employee = service.authenticate_session(session_token)
    service.logout(employee)
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token=session_token,
    )
    assert status == 200
    assert body["authenticated"] is False


def test_deactivated_employee_returns_unauthenticated(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    superadmin_token, _super_login = _ready_session(service)
    superadmin = service.authenticate_session(superadmin_token)
    worker = service.create_account(
        superadmin,
        username="worker.user",
        display_name="Worker User",
        password="WorkerTemp1!",
        role="USER",
    )
    login = service.authenticate(username=worker.username, password="WorkerTemp1!")
    service.change_password(
        service.authenticate_session(login.session_token),
        current_password="WorkerTemp1!",
        new_password="WorkerChanged1!",
    )
    relogin = service.authenticate(username=worker.username, password="WorkerChanged1!")
    service.deactivate_account(superadmin, worker.id)
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token=relogin.session_token,
    )
    assert status == 200
    assert body["authenticated"] is False


def test_auth_version_mismatch_returns_unauthenticated(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    session_token, _login = _ready_session(service)
    employee = service.authenticate_session(session_token)
    service.change_password(
        employee,
        current_password="ChangedTemp1!",
        new_password="AnotherTemp1!",
    )
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token=session_token,
    )
    assert status == 200
    assert body["authenticated"] is False


def test_permission_change_reflected_without_new_session(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    superadmin_token, _super_login = _ready_session(service)
    superadmin = service.authenticate_session(superadmin_token)
    worker = service.create_account(
        superadmin,
        username="worker.user",
        display_name="Worker User",
        password="WorkerTemp1!",
        role="USER",
        explicit_permissions={"inquiries.view"},
    )
    login = service.authenticate(username=worker.username, password="WorkerTemp1!")
    service.change_password(
        service.authenticate_session(login.session_token),
        current_password="WorkerTemp1!",
        new_password="WorkerChanged1!",
    )
    relogin = service.authenticate(username=worker.username, password="WorkerChanged1!")
    session_token = relogin.session_token

    _status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token=session_token,
    )
    assert body["principal"]["effective_permissions"] == ["inquiries.view"]

    service.set_account_permissions(
        superadmin,
        worker.id,
        {"offers.view", "inquiries.view"},
    )
    _status, body, _headers = _introspect_post(
        introspect_api["base"],
        session_token=session_token,
    )
    assert sorted(body["principal"]["effective_permissions"]) == [
        "inquiries.view",
        "offers.view",
    ]


def test_request_body_with_client_identity_is_rejected(introspect_api) -> None:
    payload = json.dumps({"account_id": str(uuid.uuid4())}).encode("utf-8")
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        body=payload,
    )
    assert status == 400
    assert body == {"error": "invalid_request"}


def test_chunked_transfer_encoding_rejected_after_service_auth(
    introspect_api,
) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Transfer-Encoding": "chunked"},
    )
    assert status == 400
    assert body == {"error": "invalid_request"}


def test_duplicate_session_headers_rejected(introspect_api) -> None:
    status, body = _introspect_post_header_list(
        introspect_api["base"],
        [
            ("Authorization", f"Bearer {_CONFIGURATOR_TOKEN}"),
            ("X-Employee-Session", "valid-session-token"),
            ("X-Employee-Session", "other-session-token"),
        ],
    )
    assert status == 400
    assert body == {"error": "invalid_request"}


def test_introspection_endpoint_fail_closed_without_configured_clients(
    tmp_path: Path,
) -> None:
    db = tmp_path / f"introspect-dormant-{uuid.uuid4().hex}.sqlite3"
    SQLiteEmployeeAuthRepository(db).close()
    server, thread, base = _start_api_server(db, introspection_tokens={})
    try:
        status, body, _headers = _introspect_post(base)
        assert status == 401
        assert body == {"error": "unauthorized"}
        req = urllib.request.Request(
            f"{base}/office/v1/queue",
            headers=_PANEL_AUTH,
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_cookie_header_does_not_authenticate(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    session_token, _login = _ready_session(service)
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Cookie": f"sl_employee_session={session_token}"},
    )
    assert status == 200
    assert body["authenticated"] is False


def test_basic_auth_does_not_substitute_session_header(introspect_api) -> None:
    import base64

    basic = base64.b64encode(b"office:secret").decode()
    status, _body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Authorization": f"Basic {basic}"},
    )
    assert status == 401


def test_introspection_does_not_mutate_session_state(introspect_api) -> None:
    service: EmployeeAuthService = introspect_api["auth_service"]
    repo: SQLiteEmployeeAuthRepository = introspect_api["repo"]
    session_token, login = _ready_session(service)
    session_before = repo.get_session_by_token_hash(login.session.token_hash)
    assert session_before is not None
    before_seen = session_before.last_seen_at
    before_expires = session_before.expires_at
    audit_before = repo.list_audit_events()

    for _ in range(3):
        status, body, _headers = _introspect_post(
            introspect_api["base"],
            session_token=session_token,
        )
        assert status == 200
        assert body["authenticated"] is True

    session_after = repo.get_session_by_token_hash(login.session.token_hash)
    assert session_after is not None
    assert session_after.last_seen_at == before_seen
    assert session_after.expires_at == before_expires
    assert repo.list_audit_events() == audit_before


def test_get_method_not_allowed(introspect_api) -> None:
    req = urllib.request.Request(
        f"{introspect_api['base']}{_INTROSPECT_PATH}",
        headers=_CONFIGURATOR_AUTH,
        method="GET",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 405
    body = json.loads(exc_info.value.read().decode())
    assert body == {"error": "method_not_allowed"}


def test_existing_office_api_routes_unchanged(introspect_api) -> None:
    req = urllib.request.Request(
        f"{introspect_api['base']}/office/v1/queue",
        headers=_PANEL_AUTH,
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200


def test_bearer_with_empty_token_returns_401(introspect_api) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Authorization": "Bearer "},
    )
    assert status == 401
    assert body == {"error": "unauthorized"}


def test_invalid_content_length_header_returns_400(introspect_api) -> None:
    status, body, _headers = _introspect_post(
        introspect_api["base"],
        headers={"Content-Length": "not-a-number"},
    )
    assert status == 400
    assert body == {"error": "invalid_request"}


def test_read_introspection_service_tokens_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON", raising=False)
    assert (
        read_introspection_service_tokens_from_env(office_panel_token="panel-token")
        == {}
    )
    monkeypatch.setenv(
        "EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON",
        '{"configurator":"secret-token"}',
    )
    assert read_introspection_service_tokens_from_env(
        office_panel_token="panel-token"
    ) == {"configurator": "secret-token"}


def test_parse_introspection_service_tokens_rejects_invalid_config() -> None:
    with pytest.raises(IntrospectionServiceTokenConfigError, match="valid JSON"):
        parse_introspection_service_tokens("{", office_panel_token="panel")
    with pytest.raises(IntrospectionServiceTokenConfigError, match="JSON object"):
        parse_introspection_service_tokens("[]", office_panel_token="panel")
    with pytest.raises(IntrospectionServiceTokenConfigError, match="client id"):
        parse_introspection_service_tokens('{"": "token"}', office_panel_token="panel")
    with pytest.raises(IntrospectionServiceTokenConfigError, match="token must"):
        parse_introspection_service_tokens(
            '{"configurator": ""}', office_panel_token="panel"
        )
    with pytest.raises(IntrospectionServiceTokenConfigError, match="non-empty string"):
        parse_introspection_service_tokens(
            '{"configurator": 1}', office_panel_token="panel"
        )
    with pytest.raises(IntrospectionServiceTokenConfigError, match="OFFICE_API_TOKEN"):
        parse_introspection_service_tokens(
            '{"configurator": "panel"}', office_panel_token="panel"
        )
    with pytest.raises(IntrospectionServiceTokenConfigError, match="duplicate"):
        parse_introspection_service_tokens(
            '{"a": "same-token", "b": "same-token"}',
            office_panel_token="panel",
        )


def test_ambiguous_bearer_matching_office_and_introspection_returns_403(
    tmp_path: Path,
) -> None:
    auth = OfficeApiServiceAuth(
        office_panel_token="shared-token",
        introspection_clients={"configurator": "shared-token"},
    )
    assert auth.authenticate_introspection("Bearer shared-token").outcome == "ambiguous"
    service = EmployeeAuthService(SQLiteEmployeeAuthRepository(tmp_path / "ambig.db"))
    status, _response, error = perform_employee_introspection(
        service_auth=auth,
        authorization="Bearer shared-token",
        content_length=None,
        transfer_encoding=None,
        session_header_values=None,
        employee_auth=service,
    )
    assert status == 403
    assert error == "forbidden"


def test_service_auth_helpers(tmp_path: Path) -> None:
    auth = OfficeApiServiceAuth(
        office_panel_token="panel-token",
        introspection_clients={"configurator": "cfg-token"},
    )
    assert auth.authenticate_introspection(None).outcome == "missing"
    assert auth.authenticate_introspection("Basic x").outcome == "missing"
    assert auth.authenticate_introspection("Bearer panel-token").outcome == "forbidden"
    assert auth.authenticate_introspection("Bearer cfg-token").outcome == "allowed"
    assert (
        auth.authenticate_introspection("Bearer cfg-token").client_id == "configurator"
    )
    assert auth.authenticate_introspection("Bearer unknown").outcome == "invalid"
    assert (
        validate_introspection_request_body(content_length=None, transfer_encoding=None)
        is False
    )
    assert (
        validate_introspection_request_body(content_length="0", transfer_encoding=None)
        is False
    )
    assert (
        validate_introspection_request_body(content_length="12", transfer_encoding=None)
        is True
    )
    assert (
        validate_introspection_request_body(
            content_length="bad", transfer_encoding=None
        )
        is True
    )
    assert (
        validate_introspection_request_body(
            content_length=None, transfer_encoding="chunked"
        )
        is True
    )

    db = tmp_path / "helper.db"
    service = EmployeeAuthService(SQLiteEmployeeAuthRepository(db))
    status, response, error = perform_employee_introspection(
        service_auth=auth,
        authorization="Bearer cfg-token",
        content_length=None,
        transfer_encoding=None,
        session_header_values=None,
        employee_auth=service,
    )
    assert status == 200
    assert error is None
    assert response is not None
    assert response.authenticated is False


def test_resolve_session_for_introspection_skips_last_seen(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    repo = SQLiteEmployeeAuthRepository(tmp_path / "core.db")
    service = EmployeeAuthService(repo, now=clock.now)
    service.bootstrap_superadmin(
        username="super.admin",
        display_name="Super Admin",
        password="TempPassw0rd!",
        metadata={"seed": "test"},
    )
    login = service.authenticate(username="super.admin", password="TempPassw0rd!")
    session = repo.get_session_by_token_hash(login.session.token_hash)
    assert session is not None
    first_seen = session.last_seen_at
    clock.value = clock.value + timedelta(minutes=6)
    resolved = service.resolve_session_for_introspection(login.session_token)
    assert resolved is not None
    session = repo.get_session_by_token_hash(login.session.token_hash)
    assert session is not None
    assert session.last_seen_at == first_seen


def test_resolve_session_for_introspection_does_not_revoke_expired(
    tmp_path: Path,
) -> None:
    clock = Clock(datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    repo = SQLiteEmployeeAuthRepository(tmp_path / "core.db")
    service = EmployeeAuthService(repo, now=clock.now)
    service.bootstrap_superadmin(
        username="super.admin",
        display_name="Super Admin",
        password="TempPassw0rd!",
        metadata={"seed": "test"},
    )
    login = service.authenticate(username="super.admin", password="TempPassw0rd!")
    clock.value = clock.value + timedelta(hours=13)
    assert service.resolve_session_for_introspection(login.session_token) is None
    session = repo.get_session_by_token_hash(login.session.token_hash)
    assert session is not None
    assert session.revoked_at is None

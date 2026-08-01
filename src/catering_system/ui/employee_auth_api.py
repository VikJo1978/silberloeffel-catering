"""Cookie-session employee authentication API for AUTH_RBAC_V1.

Production rollout still requires a private HTTPS reverse-proxy origin so the
session cookie can be Secure and same-origin for both Office Panel and
Configurator. This module provides the Core-side contract only.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from catering_system.repositories.bootstrap_employee_auth_schema import (
    bootstrap_employee_auth_schema,
)
from catering_system.repositories.core_transaction import open_core_connection
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import (
    AuthenticationError,
    AuthorizationError,
    CsrfValidationError,
    EmployeeAuthService,
)
from catering_system.ui.employee_auth_account_api import (
    dispatch_account_route,
    parse_accounts_route,
)
from catering_system.ui.employee_auth_http import (
    bearer_token_from_headers,
    clear_cookie_header,
    session_cookie_header,
    session_token_from_headers,
)

_MAX_BODY_BYTES = 16 * 1024


def _read_service_tokens_from_env() -> dict[str, str]:
    raw = __import__("os").environ.get("EMPLOYEE_AUTH_SERVICE_TOKENS_JSON", "")
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise SystemExit("EMPLOYEE_AUTH_SERVICE_TOKENS_JSON must be a JSON object")
    tokens: dict[str, str] = {}
    for key, value in parsed.items():
        if isinstance(key, str) and isinstance(value, str) and value:
            tokens[key] = value
    return tokens


def _strict_json(raw: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("invalid JSON")
    return parsed


def make_employee_auth_handler(
    service: EmployeeAuthService, *, secure_cookie: bool = True
) -> type[BaseHTTPRequestHandler]:
    class EmployeeAuthHandler(BaseHTTPRequestHandler):
        server_version = "EmployeeAuth/1.0"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def _json(
            self,
            status: int,
            payload: dict[str, object],
            *,
            cookie_header: str | None = None,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if cookie_header is not None:
                self.send_header("Set-Cookie", cookie_header)
            self.end_headers()
            self.wfile.write(body)

        def _empty(self, status: int, *, cookie_header: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            if cookie_header is not None:
                self.send_header("Set-Cookie", cookie_header)
            self.end_headers()

        def _read_json_body(self) -> dict[str, object]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid content length") from exc
            if length <= 0 or length > _MAX_BODY_BYTES:
                raise ValueError("invalid content length")
            if (
                self.headers.get("Content-Type", "").split(";")[0].strip()
                != "application/json"
            ):
                raise ValueError("unsupported content type")
            return _strict_json(self.rfile.read(length))

        def _employee(self):
            session_token = session_token_from_headers(self.headers)
            if session_token is None:
                raise AuthenticationError("missing session")
            return service.authenticate_session(session_token)

        def _employee_with_access(self):
            employee = self._employee()
            if not employee.application_access_allowed:
                raise AuthorizationError("password change required")
            return employee

        def _csrf(self, employee) -> None:
            token = self.headers.get("X-CSRF-Token", "")
            service.validate_csrf(employee.session, token)

        def _dispatch_accounts(self, *, method: str, body: dict[str, object] | None):
            try:
                employee = self._employee_with_access()
            except CsrfValidationError:
                self._json(403, {"error": "forbidden"})
                return
            except AuthorizationError:
                self._json(403, {"error": "forbidden"})
                return
            except AuthenticationError:
                self._json(401, {"error": "unauthorized"})
                return
            if method != "GET":
                try:
                    self._csrf(employee)
                except CsrfValidationError:
                    self._json(403, {"error": "forbidden"})
                    return
            handled = dispatch_account_route(
                service,
                method=method,
                path=self.path.split("?", 1)[0],
                employee=employee,
                body=body,
                respond=lambda status, payload: self._json(status, payload),
            )
            if not handled:
                self.send_error(404)

        def do_GET(self) -> None:  # noqa: N802
            if parse_accounts_route(self.path.split("?", 1)[0])[0]:
                self._dispatch_accounts(method="GET", body=None)
                return
            if self.path == "/auth/me":
                try:
                    employee = self._employee()
                except AuthenticationError:
                    self._json(401, {"error": "unauthorized"})
                    return
                session_token = session_token_from_headers(self.headers)
                assert session_token is not None
                self._json(
                    200,
                    {
                        "account": {
                            "id": employee.account.id,
                            "username": employee.account.username,
                            "email": employee.account.email,
                            "display_name": employee.account.display_name,
                            "role": employee.account.role,
                            "is_active": employee.account.is_active,
                            "must_change_password": employee.account.must_change_password,
                        },
                        "application_access_allowed": employee.application_access_allowed,
                        "effective_permissions": sorted(employee.effective_permissions),
                        "session": {
                            "id": employee.session.id,
                            "expires_at": employee.session.expires_at.isoformat(),
                        },
                    },
                )
                return
            if self.path == "/auth/introspect":
                session_token = session_token_from_headers(self.headers)
                bearer_token = bearer_token_from_headers(self.headers)
                introspection = service.introspect(
                    session_token=session_token, bearer_token=bearer_token
                )
                payload: dict[str, object] = {
                    "kind": introspection.kind,
                    "authenticated": introspection.authenticated,
                    "application_access_allowed": introspection.application_access_allowed,
                }
                if introspection.account is not None:
                    payload["account"] = {
                        "id": introspection.account.id,
                        "username": introspection.account.username,
                        "display_name": introspection.account.display_name,
                        "role": introspection.account.role,
                        "must_change_password": introspection.account.must_change_password,
                    }
                    payload["effective_permissions"] = sorted(
                        introspection.effective_permissions
                    )
                if introspection.service_id is not None:
                    payload["service_id"] = introspection.service_id
                self._json(200, payload)
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            if parse_accounts_route(self.path.split("?", 1)[0])[0]:
                try:
                    body = self._read_json_body()
                except ValueError:
                    self._json(400, {"error": "invalid_request"})
                    return
                self._dispatch_accounts(method="POST", body=body)
                return
            if self.path == "/auth/login":
                try:
                    body = self._read_json_body()
                    result = service.authenticate(
                        username=str(body.get("username", "")),
                        password=str(body.get("password", "")),
                    )
                except ValueError:
                    self._json(400, {"error": "invalid_request"})
                    return
                except AuthenticationError:
                    self._json(401, {"error": "invalid_credentials"})
                    return
                self._json(
                    200,
                    {
                        "account": {
                            "id": result.account.id,
                            "username": result.account.username,
                            "email": result.account.email,
                            "display_name": result.account.display_name,
                            "role": result.account.role,
                            "is_active": result.account.is_active,
                            "must_change_password": result.account.must_change_password,
                        },
                        "application_access_allowed": result.application_access_allowed,
                        "effective_permissions": sorted(result.effective_permissions),
                        "csrf_token": result.csrf_token,
                        "session": {
                            "id": result.session.id,
                            "expires_at": result.session.expires_at.isoformat(),
                        },
                    },
                    cookie_header=session_cookie_header(
                        result.session_token, secure=secure_cookie
                    ),
                )
                return
            if self.path == "/auth/logout":
                try:
                    employee = self._employee()
                    self._csrf(employee)
                    service.logout(employee)
                except CsrfValidationError:
                    self._json(403, {"error": "forbidden"})
                    return
                except AuthenticationError:
                    self._json(401, {"error": "unauthorized"})
                    return
                self._empty(
                    204,
                    cookie_header=clear_cookie_header(
                        "sl_employee_session",
                        secure=secure_cookie,
                        http_only=True,
                    ),
                )
                return
            if self.path == "/auth/password/change":
                try:
                    employee = self._employee()
                    self._csrf(employee)
                    body = self._read_json_body()
                    service.change_password(
                        employee,
                        current_password=str(body.get("current_password", "")),
                        new_password=str(body.get("new_password", "")),
                    )
                except CsrfValidationError:
                    self._json(403, {"error": "forbidden"})
                    return
                except ValueError:
                    self._json(400, {"error": "invalid_request"})
                    return
                except AuthenticationError:
                    self._json(401, {"error": "unauthorized"})
                    return
                self._empty(
                    204,
                    cookie_header=clear_cookie_header(
                        "sl_employee_session",
                        secure=secure_cookie,
                        http_only=True,
                    ),
                )
                return
            self.send_error(404)

        def do_PUT(self) -> None:  # noqa: N802
            if parse_accounts_route(self.path.split("?", 1)[0])[0]:
                try:
                    body = self._read_json_body()
                except ValueError:
                    self._json(400, {"error": "invalid_request"})
                    return
                self._dispatch_accounts(method="PUT", body=body)
                return
            self.send_error(404)

        def do_PATCH(self) -> None:  # noqa: N802
            if parse_accounts_route(self.path.split("?", 1)[0])[0]:
                try:
                    body = self._read_json_body()
                except ValueError:
                    self._json(400, {"error": "invalid_request"})
                    return
                self._dispatch_accounts(method="PATCH", body=body)
                return
            self.send_error(404)

    return EmployeeAuthHandler


def create_employee_auth_server(
    db_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8085,
    secure_cookie: bool = True,
    service_tokens: dict[str, str] | None = None,
) -> HTTPServer:
    connection = open_core_connection(db_path)
    bootstrap_employee_auth_schema(connection)
    repository = SQLiteEmployeeAuthRepository.from_connection(connection)
    service = EmployeeAuthService(
        repository,
        service_tokens=service_tokens,
    )
    return HTTPServer(
        (host, port),
        make_employee_auth_handler(service, secure_cookie=secure_cookie),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Employee auth API (AUTH_RBAC_V1)")
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8085)
    parser.add_argument(
        "--allow-insecure-cookie",
        action="store_true",
        help="Allow non-Secure employee session cookies for local HTTP development only",
    )
    args = parser.parse_args()
    server = create_employee_auth_server(
        args.db,
        host=args.host,
        port=args.port,
        secure_cookie=not args.allow_insecure_cookie,
        service_tokens=_read_service_tokens_from_env(),
    )
    print(f"Employee auth API on http://{args.host}:{args.port}/auth/")
    server.serve_forever()


if __name__ == "__main__":
    main()

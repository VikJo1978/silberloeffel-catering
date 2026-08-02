"""AUTH-2D5: Office Panel catalog mutations and Rückruf resolve authorization."""

from __future__ import annotations

import base64
import http.cookiejar
import json
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from catering_system.domain.catalog import CatalogDish
from catering_system.domain.employee_auth import (
    PERMISSION_REGISTRY,
    PERMISSION_SET,
    ROLE_DEFAULT_GRANTS,
    VIEW_PERMISSION_SET,
    effective_permissions,
    ensure_permissions_within_role,
    role_ceiling,
    validate_permission_code,
)
from catering_system.repositories.in_memory_catalog_repository import (
    InMemoryCatalogRepository,
)
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
from catering_system.ui.office_panel import create_office_panel_server
from catering_system.ui.office_panel_authz import DYNAMIC_CATALOG_UPDATE_AUTH
from catering_system.ui.office_panel_http import csrf_token_for_password
from catering_system.ui.office_panel_settings_users import PERMISSION_LABELS

_GERMAN_FORBIDDEN = "Ihre Berechtigung reicht für diese Aktion nicht aus."
_GERMAN_CSRF = "Ungültiger oder fehlender CSRF-Sicherheitstoken."
_MODERN_ID = "11111111-1111-4111-8111-111111111111"
_INACTIVE_ID = "22222222-2222-4222-8222-222222222222"
_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
_AUERSWALD_ITEMS = [
    {
        "call_id": "07.07.26|09:00:00|+491234",
        "date": "07.07.26",
        "time": "09:00:00",
        "duration": "00:00:12",
        "phone": "01234",
        "normalized_phone": "+491234",
        "contact_found": False,
        "contact_name": "Unbekannt",
        "contact_url": "",
        "reason": "Nicht angenommen",
    }
]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class PanelHarness:
    base: str
    server: object
    thread: threading.Thread
    service: EmployeeAuthService
    repo: SQLiteEmployeeAuthRepository
    password: str
    catalog: InMemoryCatalogRepository | None = None


def _auth_header(password: str) -> str:
    return "Basic " + base64.b64encode(f"office:{password}".encode()).decode()


def _cookie_value(jar: http.cookiejar.CookieJar, name: str) -> str:
    for cookie in jar:
        if cookie.name == name:
            return cookie.value
    raise AssertionError(f"missing cookie {name}")


def _csrf(jar: http.cookiejar.CookieJar) -> str:
    return _cookie_value(jar, "sl_employee_csrf")


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    jar: http.cookiejar.CookieJar | None = None,
) -> tuple[int, str, str, object]:
    cookie_jar = jar if jar is not None else http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        _NoRedirect,
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    payload = None
    if data is not None:
        payload = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        f"{base}{path}",
        data=payload,
        method=method,
    )
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with opener.open(request) as response:
            return (
                response.status,
                response.url,
                response.read().decode("utf-8"),
                response.headers,
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.geturl(), exc.read().decode("utf-8"), exc.headers


def _csrf_from(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]*)"', html)
    assert match, "page is missing the _csrf_token hidden field"
    return match.group(1)


def _expect_updated_at_from(html: str) -> str:
    match = re.search(r'name="_expect_updated_at" value="([^"]+)"', html)
    assert match, "page is missing the _expect_updated_at hidden field"
    return match.group(1)


def _seed_catalog() -> InMemoryCatalogRepository:
    catalog = InMemoryCatalogRepository()
    catalog.insert_dish_if_absent(
        CatalogDish(
            dish_id=_MODERN_ID,
            name="Bruschetta",
            description="Beschreibung",
            composition="Zusammensetzung",
            notes="Hinweise",
            current_unit_net_cents=290,
            allergens=("A",),
            active=True,
            created_at=_NOW,
            updated_at=_NOW,
            category="fingerfood",
            pricing_unit="stueck",
            vat_rate_percent=7,
        )
    )
    catalog.insert_dish_if_absent(
        CatalogDish(
            dish_id=_INACTIVE_ID,
            name="Altes Gericht",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=500,
            allergens=(),
            active=False,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    return catalog


def _create_panel(
    tmp_path: Path,
    *,
    auth_mode: str,
    password: str = "shared-office-password",
    catalog: InMemoryCatalogRepository | None = None,
    auerswald_url: str | None = None,
) -> PanelHarness:
    db = tmp_path / "core.db"
    connection = sqlite3.connect(str(db), check_same_thread=False)
    repo = SQLiteEmployeeAuthRepository.from_connection(connection)
    service = EmployeeAuthService(
        repo, now=lambda: datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    )
    service.bootstrap_superadmin(
        username="viktor.admin",
        display_name="Viktor Johanson",
        password="TempPassw0rd!",
        metadata={"seed": "office-panel"},
    )
    kwargs: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 0,
        "auth_mode": auth_mode,
        "auth_service": service,
        "secure_cookie": False,
        "ui_version": "v2",
    }
    if catalog is not None:
        kwargs["catalog_repo"] = catalog
    if auerswald_url is not None:
        kwargs["auerswald_url"] = auerswald_url
        kwargs["auerswald_user"] = "office"
        kwargs["auerswald_password"] = "secret"
    server = create_office_panel_server(
        InMemoryInquiryRepository(),
        InMemoryOrderRepository(),
        password,
        **kwargs,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return PanelHarness(
        base=f"http://{host}:{port}",
        server=server,
        thread=thread,
        service=service,
        repo=repo,
        password=password,
        catalog=catalog,
    )


def _shutdown(panel: PanelHarness) -> None:
    panel.server.shutdown()
    panel.server.server_close()
    panel.thread.join(timeout=5)
    panel.repo.close()


def _login(
    panel: PanelHarness, *, username: str, password: str
) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    status, _url, _body, _headers = _request(
        panel.base,
        "/login",
        method="POST",
        data={"username": username, "password": password, "next": "/"},
        jar=jar,
    )
    assert status == 303
    return jar


def _ready_superadmin(panel: PanelHarness) -> http.cookiejar.CookieJar:
    jar = _login(panel, username="viktor.admin", password="TempPassw0rd!")
    employee = panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    panel.service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    return _login(panel, username="viktor.admin", password="ChangedTemp1!")


def _create_employee(
    panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    *,
    username: str,
    password: str,
    role: str,
    permissions: frozenset[str] | None = None,
) -> str:
    super_employee = panel.service.authenticate_session(
        _cookie_value(super_jar, "sl_employee_session")
    )
    account = panel.service.create_account(
        super_employee,
        username=username,
        display_name=username,
        password=password,
        role=role,
        explicit_permissions=set(permissions) if permissions is not None else None,
        must_change_password=False,
    )
    return account.id


def _employee_jar(
    panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    *,
    username: str,
    password: str = "ReaderTemp1!",
    permissions: frozenset[str],
) -> http.cookiejar.CookieJar:
    _create_employee(
        panel,
        super_jar,
        username=username,
        password=password,
        role="USER",
        permissions=permissions,
    )
    return _login(panel, username=username, password=password)


def _assert_post_forbidden(
    panel: PanelHarness,
    path: str,
    *,
    jar: http.cookiejar.CookieJar | None = None,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    patch_target: str | None = None,
) -> None:
    with ExitStack() as stack:
        mock = None
        if patch_target is not None:
            mock = stack.enter_context(patch(patch_target, autospec=True))
        status, _url, body, _headers = _request(
            panel.base,
            path,
            method="POST",
            data=data,
            headers=headers,
            jar=jar,
        )
    assert status == 403
    assert _GERMAN_FORBIDDEN in body
    if mock is not None:
        mock.assert_not_called()


def _make_auerswald_stub(resolved: list[str]) -> HTTPServer:
    class StubHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/missed-board.json"):
                remaining = [
                    it for it in _AUERSWALD_ITEMS if it["call_id"] not in resolved
                ]
                payload = json.dumps({"items": remaining}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/missed/resolve":
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode()
                params = urllib.parse.parse_qs(body)
                call_id = params.get("call_id", [""])[0]
                resolved.append(call_id)
                self.send_response(204)
                self.end_headers()
            else:
                self.send_error(404)

    return HTTPServer(("127.0.0.1", 0), StubHandler)


def _valid_create_fields(csrf: str, **overrides: str) -> dict[str, str]:
    fields = {
        "_csrf_token": csrf,
        "name": "Neues Gericht",
        "description": "Beschreibung",
        "composition": "Zusammensetzung",
        "notes": "Hinweise",
        "category": "warme_speisen",
        "pricing_unit": "per_person",
        "price_net": "12,50",
        "vat_rate_percent": "19",
        "allergen_A": "1",
    }
    fields.update(overrides)
    return fields


def _update_fields_from_edit(edit_html: str, **overrides: str) -> dict[str, str]:
    fields = {
        "_csrf_token": _csrf_from(edit_html),
        "_expect_updated_at": _expect_updated_at_from(edit_html),
        "name": "Bruschetta",
        "description": "Beschreibung",
        "composition": "Zusammensetzung",
        "notes": "Hinweise",
        "price_net": "2,90",
        "allergen_A": "1",
    }
    fields.update(overrides)
    return fields


@pytest.fixture()
def employee_panel(tmp_path: Path) -> PanelHarness:
    panel = _create_panel(tmp_path, auth_mode="employee", catalog=_seed_catalog())
    yield panel
    _shutdown(panel)


@pytest.fixture()
def migration_panel(tmp_path: Path) -> PanelHarness:
    panel = _create_panel(tmp_path, auth_mode="migration", catalog=_seed_catalog())
    yield panel
    _shutdown(panel)


@pytest.fixture()
def super_jar(employee_panel: PanelHarness) -> http.cookiejar.CookieJar:
    return _ready_superadmin(employee_panel)


@pytest.fixture()
def rueckruf_panel(tmp_path: Path) -> tuple[PanelHarness, list[str], HTTPServer]:
    resolved: list[str] = []
    stub = _make_auerswald_stub(resolved)
    stub_thread = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_thread.start()
    stub_host, stub_port = stub.server_address[:2]
    panel = _create_panel(
        tmp_path,
        auth_mode="employee",
        auerswald_url=f"http://{stub_host}:{stub_port}",
    )
    yield panel, resolved, stub
    _shutdown(panel)
    stub.shutdown()
    stub.server_close()
    stub_thread.join(timeout=5)


# --- registry ----------------------------------------------------------------


def test_queue_resolve_permission_registered_once() -> None:
    assert PERMISSION_REGISTRY.count("queue.resolve") == 1
    assert "queue.resolve" in PERMISSION_SET
    assert validate_permission_code("queue.resolve") == "queue.resolve"
    assert PERMISSION_LABELS["queue.resolve"] == "Rückrufe erledigen"


def test_queue_resolve_role_ceilings_and_defaults() -> None:
    assert "queue.resolve" in role_ceiling("ADMIN")
    assert "queue.resolve" in role_ceiling("USER")
    assert "queue.resolve" not in VIEW_PERMISSION_SET
    with pytest.raises(ValueError, match="permissions exceed VIEWER ceiling"):
        ensure_permissions_within_role("VIEWER", {"queue.resolve"})
    assert "queue.resolve" in ROLE_DEFAULT_GRANTS["ADMIN"]
    assert "queue.resolve" in ROLE_DEFAULT_GRANTS["USER"]
    assert "queue.resolve" not in ROLE_DEFAULT_GRANTS["VIEWER"]
    assert effective_permissions("USER", {"queue.resolve"}) == frozenset(
        {"queue.resolve"}
    )


# --- Rückruf -----------------------------------------------------------------


def test_rueckruf_view_without_resolve_hides_button_but_shows_list(
    rueckruf_panel: tuple[PanelHarness, list[str], HTTPServer],
    super_jar: http.cookiejar.CookieJar,
) -> None:
    panel, _resolved, _stub = rueckruf_panel
    jar = _employee_jar(
        panel,
        super_jar,
        username="queue.view.only",
        permissions=frozenset({"queue.view"}),
    )
    status, _url, body, _headers = _request(panel.base, "/rueckruf", jar=jar)
    assert status == 200
    assert "01234" in body
    assert "Erledigt" not in body
    assert 'action="/rueckruf/resolve"' not in body


def test_rueckruf_resolve_allowed_with_queue_resolve(
    rueckruf_panel: tuple[PanelHarness, list[str], HTTPServer],
    super_jar: http.cookiejar.CookieJar,
) -> None:
    panel, resolved, _stub = rueckruf_panel
    jar = _employee_jar(
        panel,
        super_jar,
        username="queue.resolver",
        permissions=frozenset({"queue.view", "queue.resolve"}),
    )
    _status, _url, body, _headers = _request(panel.base, "/rueckruf", jar=jar)
    assert "Erledigt" in body
    status, _url, _body, _headers = _request(
        panel.base,
        "/rueckruf/resolve",
        method="POST",
        data={
            "_csrf_token": _csrf(jar),
            "call_id": _AUERSWALD_ITEMS[0]["call_id"],
        },
        jar=jar,
    )
    assert status == 303
    assert resolved == [_AUERSWALD_ITEMS[0]["call_id"]]


def test_rueckruf_resolve_denied_without_queue_resolve(
    rueckruf_panel: tuple[PanelHarness, list[str], HTTPServer],
    super_jar: http.cookiejar.CookieJar,
) -> None:
    panel, resolved, _stub = rueckruf_panel
    jar = _employee_jar(
        panel,
        super_jar,
        username="queue.view.denied",
        permissions=frozenset({"queue.view"}),
    )
    _assert_post_forbidden(
        panel,
        "/rueckruf/resolve",
        jar=jar,
        data={
            "_csrf_token": _csrf(jar),
            "call_id": _AUERSWALD_ITEMS[0]["call_id"],
        },
        patch_target="catering_system.integration.auerswald_sync.resolve_missed_call",
    )
    assert resolved == []


def test_rueckruf_resolve_anonymous_redirects_to_login(
    rueckruf_panel: tuple[PanelHarness, list[str], HTTPServer],
) -> None:
    panel, _resolved, _stub = rueckruf_panel
    status, url, _body, _headers = _request(
        panel.base,
        "/rueckruf/resolve",
        method="POST",
        data={"call_id": "x", "_csrf_token": "bad"},
    )
    assert status == 303
    assert "/login" in url


def test_rueckruf_resolve_employee_basic_headers_do_not_bypass(
    rueckruf_panel: tuple[PanelHarness, list[str], HTTPServer],
    super_jar: http.cookiejar.CookieJar,
) -> None:
    panel, resolved, _stub = rueckruf_panel
    jar = _employee_jar(
        panel,
        super_jar,
        username="queue.view.basic",
        permissions=frozenset({"queue.view"}),
    )
    _assert_post_forbidden(
        panel,
        "/rueckruf/resolve",
        jar=jar,
        headers={"Authorization": _auth_header(panel.password)},
        data={
            "_csrf_token": _csrf(jar),
            "call_id": _AUERSWALD_ITEMS[0]["call_id"],
        },
        patch_target="catering_system.integration.auerswald_sync.resolve_missed_call",
    )
    assert resolved == []


def test_rueckruf_resolve_migration_basic_still_works(
    tmp_path: Path,
) -> None:
    resolved: list[str] = []
    stub = _make_auerswald_stub(resolved)
    stub_thread = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_thread.start()
    stub_host, stub_port = stub.server_address[:2]
    password = "shared-office-password"
    panel = _create_panel(
        tmp_path,
        auth_mode="migration",
        password=password,
        auerswald_url=f"http://{stub_host}:{stub_port}",
    )
    csrf = csrf_token_for_password(password)
    try:
        status, _url, _body, _headers = _request(
            panel.base,
            "/rueckruf/resolve",
            method="POST",
            data={
                "_csrf_token": csrf,
                "call_id": _AUERSWALD_ITEMS[0]["call_id"],
            },
            headers={"Authorization": _auth_header(password)},
        )
        assert status == 303
        assert resolved == [_AUERSWALD_ITEMS[0]["call_id"]]
    finally:
        _shutdown(panel)
        stub.shutdown()
        stub.server_close()
        stub_thread.join(timeout=5)


def test_viewer_role_default_has_no_queue_resolve() -> None:
    assert "queue.resolve" not in ROLE_DEFAULT_GRANTS["VIEWER"]
    assert "queue.resolve" not in effective_permissions("VIEWER", frozenset())


# --- catalog create ----------------------------------------------------------


def test_catalog_create_success_with_both_permissions(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.creator",
        permissions=frozenset({"catalog.edit", "prices.edit"}),
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        "/gerichte/new",
        jar=jar,
    )
    assert status == 200
    fields = _valid_create_fields(_csrf(jar))
    before = len(employee_panel.catalog.list_dishes())  # type: ignore[union-attr]
    status, _url, _body, _headers = _request(
        employee_panel.base,
        "/gerichte/new",
        method="POST",
        data=fields,
        jar=jar,
    )
    assert status == 303
    assert len(employee_panel.catalog.list_dishes()) == before + 1  # type: ignore[union-attr]


def test_catalog_create_denied_with_catalog_edit_only(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.only",
        permissions=frozenset({"catalog.edit", "catalog.view"}),
    )
    before = len(employee_panel.catalog.list_dishes())  # type: ignore[union-attr]
    _assert_post_forbidden(
        employee_panel,
        "/gerichte/new",
        jar=jar,
        data=_valid_create_fields(_csrf(jar)),
        patch_target="catering_system.ui.office_panel.OfficePanel.create_catalog_dish",
    )
    assert len(employee_panel.catalog.list_dishes()) == before  # type: ignore[union-attr]
    status, _url, body, _headers = _request(
        employee_panel.base, "/gerichte/new", jar=jar
    )
    assert status == 403


def test_catalog_create_denied_with_prices_edit_only(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="prices.only",
        permissions=frozenset({"prices.edit", "catalog.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        "/gerichte/new",
        jar=jar,
        data=_valid_create_fields(_csrf(jar)),
        patch_target="catering_system.ui.office_panel.OfficePanel.create_catalog_dish",
    )
    status, _url, body, _headers = _request(
        employee_panel.base, "/gerichte", jar=jar
    )
    assert status == 200
    assert 'href="/gerichte/new"' not in body


def test_catalog_create_ui_hidden_without_full_permission_set(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.edit.nav",
        permissions=frozenset({"catalog.view", "catalog.edit"}),
    )
    status, _url, body, _headers = _request(
        employee_panel.base, "/gerichte", jar=jar
    )
    assert status == 200
    assert 'href="/gerichte/new"' not in body


# --- metadata update ---------------------------------------------------------


def test_catalog_metadata_update_with_catalog_edit_only(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="metadata.editor",
        permissions=frozenset({"catalog.view", "catalog.edit"}),
    )
    _status, _url, edit, _headers = _request(
        employee_panel.base, f"/gerichte/{_MODERN_ID}/edit", jar=jar
    )
    status, _url, _body, _headers = _request(
        employee_panel.base,
        f"/gerichte/{_MODERN_ID}/update",
        method="POST",
        data=_update_fields_from_edit(edit, name="Bruschetta Neu"),
        jar=jar,
    )
    assert status == 303
    dish = employee_panel.catalog.get_dish(_MODERN_ID)  # type: ignore[union-attr]
    assert dish.name == "Bruschetta Neu"
    assert dish.current_unit_net_cents == 290


def test_catalog_metadata_drift_denied_with_prices_edit_only(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="price.only.meta",
        permissions=frozenset({"catalog.view", "prices.edit"}),
    )
    _status, _url, edit, _headers = _request(
        employee_panel.base, f"/gerichte/{_MODERN_ID}/edit", jar=jar
    )
    before = employee_panel.catalog.get_dish(_MODERN_ID)  # type: ignore[union-attr]
    _assert_post_forbidden(
        employee_panel,
        f"/gerichte/{_MODERN_ID}/update",
        jar=jar,
        data=_update_fields_from_edit(edit, name="Tampered Name"),
        patch_target="catering_system.ui.office_panel.OfficePanel.update_catalog_dish",
    )
    after = employee_panel.catalog.get_dish(_MODERN_ID)  # type: ignore[union-attr]
    assert after.name == before.name


# --- price update ------------------------------------------------------------


def test_catalog_price_update_with_prices_edit_only(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="price.editor",
        permissions=frozenset({"catalog.view", "prices.edit"}),
    )
    _status, _url, edit, _headers = _request(
        employee_panel.base, f"/gerichte/{_MODERN_ID}/edit", jar=jar
    )
    status, _url, _body, _headers = _request(
        employee_panel.base,
        f"/gerichte/{_MODERN_ID}/update",
        method="POST",
        data=_update_fields_from_edit(edit, price_net="3,50"),
        jar=jar,
    )
    assert status == 303
    dish = employee_panel.catalog.get_dish(_MODERN_ID)  # type: ignore[union-attr]
    assert dish.current_unit_net_cents == 350
    assert dish.name == "Bruschetta"


def test_catalog_price_drift_denied_with_catalog_edit_only(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="metadata.only.price",
        permissions=frozenset({"catalog.view", "catalog.edit"}),
    )
    _status, _url, edit, _headers = _request(
        employee_panel.base, f"/gerichte/{_MODERN_ID}/edit", jar=jar
    )
    before = employee_panel.catalog.get_dish(_MODERN_ID)  # type: ignore[union-attr]
    _assert_post_forbidden(
        employee_panel,
        f"/gerichte/{_MODERN_ID}/update",
        jar=jar,
        data=_update_fields_from_edit(edit, price_net="9,99"),
        patch_target="catering_system.ui.office_panel.OfficePanel.update_catalog_dish",
    )
    after = employee_panel.catalog.get_dish(_MODERN_ID)  # type: ignore[union-attr]
    assert after.current_unit_net_cents == before.current_unit_net_cents


def test_catalog_combined_update_requires_both_permissions(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.full",
        permissions=frozenset(
            {"catalog.view", "catalog.edit", "prices.edit"}
        ),
    )
    _status, _url, edit, _headers = _request(
        employee_panel.base, f"/gerichte/{_MODERN_ID}/edit", jar=jar
    )
    status, _url, _body, _headers = _request(
        employee_panel.base,
        f"/gerichte/{_MODERN_ID}/update",
        method="POST",
        data=_update_fields_from_edit(
            edit, name="Bruschetta Deluxe", price_net="4,20"
        ),
        jar=jar,
    )
    assert status == 303
    dish = employee_panel.catalog.get_dish(_MODERN_ID)  # type: ignore[union-attr]
    assert dish.name == "Bruschetta Deluxe"
    assert dish.current_unit_net_cents == 420


def test_catalog_combined_drift_denied_with_prices_edit_only(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="price.only.combo",
        permissions=frozenset({"catalog.view", "prices.edit"}),
    )
    _status, _url, edit, _headers = _request(
        employee_panel.base, f"/gerichte/{_MODERN_ID}/edit", jar=jar
    )
    before = employee_panel.catalog.get_dish(_MODERN_ID)  # type: ignore[union-attr]
    _assert_post_forbidden(
        employee_panel,
        f"/gerichte/{_MODERN_ID}/update",
        jar=jar,
        data=_update_fields_from_edit(
            edit, name="Tampered", price_net="4,20"
        ),
        patch_target="catering_system.ui.office_panel.OfficePanel.update_catalog_dish",
    )
    after = employee_panel.catalog.get_dish(_MODERN_ID)  # type: ignore[union-attr]
    assert after.name == before.name
    assert after.current_unit_net_cents == before.current_unit_net_cents


# --- activate/deactivate -----------------------------------------------------


def test_catalog_activate_allowed_with_catalog_edit(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.activator",
        permissions=frozenset({"catalog.view", "catalog.edit"}),
    )
    _status, _url, detail, _headers = _request(
        employee_panel.base, f"/gerichte/{_INACTIVE_ID}", jar=jar
    )
    status, _url, _body, _headers = _request(
        employee_panel.base,
        f"/gerichte/{_INACTIVE_ID}/activate",
        method="POST",
        data={
            "_csrf_token": _csrf(jar),
            "_expect_updated_at": _expect_updated_at_from(detail),
        },
        jar=jar,
    )
    assert status == 303
    assert employee_panel.catalog.get_dish(_INACTIVE_ID).active is True  # type: ignore[union-attr]


def test_catalog_activate_denied_without_catalog_edit(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.viewer.activate",
        permissions=frozenset({"catalog.view"}),
    )
    _status, _url, detail, _headers = _request(
        employee_panel.base, f"/gerichte/{_INACTIVE_ID}", jar=jar
    )
    _assert_post_forbidden(
        employee_panel,
        f"/gerichte/{_INACTIVE_ID}/activate",
        jar=jar,
        data={
            "_csrf_token": _csrf(jar),
            "_expect_updated_at": _expect_updated_at_from(detail),
        },
        patch_target=(
            "catering_system.ui.office_panel.OfficePanel.set_catalog_dish_active"
        ),
    )
    assert employee_panel.catalog.get_dish(_INACTIVE_ID).active is False  # type: ignore[union-attr]


def test_catalog_activate_controls_hidden_without_catalog_edit(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.viewer.controls",
        permissions=frozenset({"catalog.view"}),
    )
    status, _url, body, _headers = _request(
        employee_panel.base, f"/gerichte/{_MODERN_ID}", jar=jar
    )
    assert status == 200
    assert "Aktivieren" not in body
    assert "Deaktivieren" not in body


# --- boundary/order ----------------------------------------------------------


def test_catalog_update_invalid_csrf_skips_mutation(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.csrf",
        permissions=frozenset(
            {"catalog.view", "catalog.edit", "prices.edit"}
        ),
    )
    _status, _url, edit, _headers = _request(
        employee_panel.base, f"/gerichte/{_MODERN_ID}/edit", jar=jar
    )
    fields = _update_fields_from_edit(edit, name="CSRF Block")
    fields["_csrf_token"] = "invalid"
    with patch(
        "catering_system.ui.office_panel.OfficePanel.update_catalog_dish",
        autospec=True,
    ) as update_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
            f"/gerichte/{_MODERN_ID}/update",
            method="POST",
            data=fields,
            jar=jar,
        )
    assert status == 403
    assert _GERMAN_CSRF in body
    update_mock.assert_not_called()


def test_auth2d5_post_routes_are_explicitly_mapped(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.view.only",
        permissions=frozenset({"catalog.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        "/gerichte/new",
        jar=jar,
        data=_valid_create_fields(_csrf(jar)),
        patch_target="catering_system.ui.office_panel.OfficePanel.create_catalog_dish",
    )
    _assert_post_forbidden(
        employee_panel,
        f"/gerichte/{_MODERN_ID}/activate",
        jar=jar,
        data={"_csrf_token": _csrf(jar), "_expect_updated_at": _NOW.isoformat()},
        patch_target=(
            "catering_system.ui.office_panel.OfficePanel.set_catalog_dish_active"
        ),
    )
    assert DYNAMIC_CATALOG_UPDATE_AUTH is not None


def test_alternative_catalog_post_urls_do_not_bypass_gate(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="catalog.bypass",
        permissions=frozenset({"catalog.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        f"/gerichte/{_MODERN_ID}/update",
        jar=jar,
        data={"_csrf_token": _csrf(jar), "name": "x"},
        patch_target="catering_system.ui.office_panel.OfficePanel.update_catalog_dish",
    )


def test_unmapped_catalog_post_returns_404(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _ready_superadmin(employee_panel)
    with patch(
        "catering_system.ui.office_panel.OfficePanel.update_catalog_dish",
        autospec=True,
    ) as update_mock:
        status, _url, _body, _headers = _request(
            employee_panel.base,
            f"/gerichte/{_MODERN_ID}/unknown-action",
            method="POST",
            data={"_csrf_token": _csrf(jar)},
            jar=jar,
        )
    assert status == 404
    update_mock.assert_not_called()


def test_login_logout_password_change_still_work(
    employee_panel: PanelHarness,
) -> None:
    jar = _ready_superadmin(employee_panel)
    status, _url, _body, _headers = _request(
        employee_panel.base,
        "/logout",
        method="POST",
        data={"_csrf_token": _csrf(jar)},
        jar=jar,
    )
    assert status == 303
    status, _url, _body, _headers = _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={
            "username": "viktor.admin",
            "password": "ChangedTemp1!",
            "next": "/",
        },
    )
    assert status == 303

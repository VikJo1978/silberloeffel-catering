"""Office panel catalog pages."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest

from catering_system.domain.catalog import CatalogDish
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.in_memory_catalog_repository import (
    InMemoryCatalogRepository,
)
from catering_system.ui.office_panel import create_office_panel_server

from catering_system.ui.office_panel_http import csrf_token_for_password

_PASSWORD = "test-pw"
_CSRF_TOKEN = csrf_token_for_password(_PASSWORD)
_DISH_ID = "11111111-1111-4111-8111-111111111111"
_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def _auth_header() -> str:
    import base64

    return "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()


@pytest.fixture()
def catalog_panel():
    catalog = InMemoryCatalogRepository()
    catalog.insert_dish_if_absent(
        CatalogDish(
            dish_id=_DISH_ID,
            name='Schnitzel <test>',
            description="Beschreibung",
            composition="Zusammensetzung",
            notes=None,
            current_unit_net_cents=850,
            allergens=("A", "C", "G"),
            active=True,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    server = create_office_panel_server(
        InMemoryInquiryRepository(),
        InMemoryOrderRepository(),
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        catalog_repo=catalog,
        ui_version="v2",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()


def _get(url: str) -> tuple[int, str]:
    import urllib.request

    req = urllib.request.Request(url)
    req.add_header("Authorization", _auth_header())
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")


def _post(url: str, fields: dict[str, str]) -> tuple[int, str]:
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", _auth_header())
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")


def test_gerichte_list_renders(catalog_panel: str) -> None:
    status, body = _get(f"{catalog_panel}/gerichte")
    assert status == 200
    assert "Gerichte" in body
    assert "Schnitzel" in body
    assert "8,50 €" in body
    assert "<script" not in body
    assert "&lt;test&gt;" in body


def test_gericht_detail_renders_and_escapes(catalog_panel: str) -> None:
    status, body = _get(f"{catalog_panel}/gerichte/{_DISH_ID}")
    assert status == 200
    assert "Beschreibung" in body
    assert "Zusammensetzung" in body
    assert "Preisänderungen:" in body
    assert "noch keine" in body
    assert "8,50 €" in body
    assert "Bearbeiten" in body


def test_gericht_edit_form_renders(catalog_panel: str) -> None:
    status, body = _get(f"{catalog_panel}/gerichte/{_DISH_ID}/edit")
    assert status == 200
    assert "Speichern" in body
    assert 'name="allergen_A"' in body
    assert 'name="price_net"' in body
    assert 'name="_expect_updated_at"' in body


def test_gericht_update_post_success(catalog_panel: str) -> None:
    _status, edit_html = _get(f"{catalog_panel}/gerichte/{_DISH_ID}/edit")
    import re

    updated_at = re.search(
        r'name="_expect_updated_at" value="([^"]+)"',
        edit_html,
    ).group(1)
    status, _body = _post(
        f"{catalog_panel}/gerichte/{_DISH_ID}/update",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_expect_updated_at": updated_at,
            "name": "Schnitzel Wiener Art",
            "description": "Neu",
            "composition": "mit Gurken",
            "notes": "",
            "price_net": "9,00",
            "allergen_A": "1",
            "allergen_G": "1",
            "active": "1",
            "effective_from": "2026-08-01",
        },
    )
    assert status == 200
    status, detail = _get(f"{catalog_panel}/gerichte/{_DISH_ID}")
    assert status == 200
    assert "Schnitzel Wiener Art" in detail
    assert "9,00 €" in detail
    assert "Preisänderungen:" in detail
    assert "8,50 €" in detail
    assert "noch keine" not in detail

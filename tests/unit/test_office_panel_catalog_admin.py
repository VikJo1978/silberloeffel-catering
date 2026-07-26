"""CATALOG_ADMIN_PANEL_V1: /gerichte administration surface.

Covers the list's new columns/search/filter, the create form, the separate
Aktivieren/Deaktivieren commands and their optimistic-concurrency token, and
the German error handling — all driven through the real HTTP handler so the
CSRF check and routing are exercised the way a browser would.
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

import pytest

from catering_system.domain.catalog import CatalogDish
from catering_system.repositories.in_memory_catalog_repository import (
    InMemoryCatalogRepository,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.ui.office_panel import create_office_panel_server
from catering_system.ui.office_panel_http import csrf_token_for_password

_PASSWORD = "test-pw"
_CSRF_TOKEN = csrf_token_for_password(_PASSWORD)
_MODERN_ID = "11111111-1111-4111-8111-111111111111"
_LEGACY_ID = "22222222-2222-4222-8222-222222222222"
_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def _auth_header() -> str:
    import base64

    return "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()


@pytest.fixture()
def catalog_world():
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
    # Legacy row: created before CATALOG_ADMIN_COMPLETION_V1A, so all three
    # new columns are NULL and must not break any page.
    catalog.insert_dish_if_absent(
        CatalogDish(
            dish_id=_LEGACY_ID,
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
    yield f"http://{host}:{port}", catalog
    server.shutdown()
    server.server_close()


def _get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", _auth_header())
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _post(url: str, fields: dict[str, str]) -> tuple[int, str]:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", _auth_header())
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _csrf_from(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]*)"', html)
    assert match, "page is missing the _csrf_token hidden field"
    return match.group(1)


def _expect_updated_at_from(html: str) -> str:
    match = re.search(r'name="_expect_updated_at" value="([^"]+)"', html)
    assert match, "page is missing the _expect_updated_at hidden field"
    return match.group(1)


def _valid_create_fields(**overrides: str) -> dict[str, str]:
    fields = {
        "_csrf_token": _CSRF_TOKEN,
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


# --- list: columns, legacy NULLs, search, filter -------------------------


def test_list_shows_new_columns(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte")
    assert status == 200
    for header in ("Kategorie", "Preiseinheit", "Netto-Preis", "MwSt", "Allergene"):
        assert header in body
    assert "fingerfood" in body
    assert "Stück" in body
    assert "7 %" in body
    assert "2,90 €" in body
    assert "Aktiv" in body
    assert "Neues Gericht anlegen" in body


def test_list_renders_legacy_null_fields_without_failing(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte")
    assert status == 200
    assert "Altes Gericht" in body
    assert "–" in body


def test_detail_and_edit_render_legacy_null_fields(catalog_world) -> None:
    base, _catalog = catalog_world
    status, detail = _get(f"{base}/gerichte/{_LEGACY_ID}")
    assert status == 200
    assert "Kategorie" in detail
    assert "–" in detail
    status, edit = _get(f"{base}/gerichte/{_LEGACY_ID}/edit")
    assert status == 200
    assert "–" in edit


def test_list_search_by_name(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte?q=Bruschetta")
    assert status == 200
    assert "Bruschetta" in body
    assert "Altes Gericht" not in body


def test_list_search_without_match_shows_empty_notice(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte?q=GibtEsNicht")
    assert status == 200
    assert "Keine Gerichte gefunden." in body


def test_list_filter_active(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte?status=active")
    assert status == 200
    assert "Bruschetta" in body
    assert "Altes Gericht" not in body


def test_list_filter_inactive(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte?status=inactive")
    assert status == 200
    assert "Altes Gericht" in body
    assert "Bruschetta" not in body


def test_list_unknown_filter_falls_back_to_all(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte?status=bogus")
    assert status == 200
    assert "Bruschetta" in body
    assert "Altes Gericht" in body


# --- create form ---------------------------------------------------------


def test_get_create_form(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte/new")
    assert status == 200
    for field in (
        'name="name"',
        'name="description"',
        'name="composition"',
        'name="notes"',
        'name="category"',
        'name="pricing_unit"',
        'name="price_net"',
        'name="vat_rate_percent"',
        'name="allergen_A"',
        'name="allergen_N"',
    ):
        assert field in body
    assert '<option value="7"' in body
    assert '<option value="19"' in body
    assert _csrf_from(body) == _CSRF_TOKEN


def test_create_success_redirects_to_detail(catalog_world) -> None:
    base, catalog = catalog_world
    status, body = _post(
        f"{base}/gerichte/new", _valid_create_fields(name="Lachstatar")
    )
    assert status == 200
    created = [d for d in catalog.list_dishes() if d.name == "Lachstatar"]
    assert len(created) == 1
    dish = created[0]
    assert dish.category == "warme_speisen"
    assert dish.pricing_unit == "per_person"
    assert dish.vat_rate_percent == 19
    assert dish.allergens == ("A",)
    # followed the redirect to *this* dish's detail page, not back to the list
    assert f"/gerichte/{dish.dish_id}/edit" in body
    assert "Lachstatar" in body
    assert "Aktivieren" in body


def test_created_dish_is_inactive(catalog_world) -> None:
    base, catalog = catalog_world
    _status, _body = _post(f"{base}/gerichte/new", _valid_create_fields())
    dish = next(d for d in catalog.list_dishes() if d.name == "Neues Gericht")
    assert dish.active is False


@pytest.mark.parametrize(
    "raw,expected_cents",
    [
        ("12,50", 1250),
        ("12.50", 1250),
        ("12,5", 1250),
        ("12.5", 1250),
        ("12", 1200),
        ("0", 0),
        ("0,00", 0),
        ("12,50 €", 1250),
    ],
)
def test_create_accepts_valid_price_formats(
    catalog_world, raw: str, expected_cents: int
) -> None:
    base, catalog = catalog_world
    _status, _body = _post(
        f"{base}/gerichte/new",
        _valid_create_fields(name=f"Preis {raw}", price_net=raw),
    )
    dish = next(d for d in catalog.list_dishes() if d.name == f"Preis {raw}")
    assert dish.current_unit_net_cents == expected_cents


@pytest.mark.parametrize(
    "raw",
    [
        "1.999",
        "12,505",
        "12,999",
        "-5,00",
        "-1",
        "",
        "   ",
        "abc",
        "1e3",
        "12,5,0",
        "1.000,50",
        "12,",
        "12.",
        ",50",
    ],
)
def test_create_rejects_imprecise_or_malformed_price(catalog_world, raw: str) -> None:
    """CATALOG_ADMIN_PANEL_V1 review fix: a third decimal used to be quantized
    away silently, storing a price nobody typed (1.999 -> 2,00 €). Anything
    that is not a plain amount with at most two decimals is now refused, and
    no dish is created."""
    base, catalog = catalog_world
    before = len(catalog.list_dishes())
    status, body = _post(
        f"{base}/gerichte/new",
        _valid_create_fields(name="Ungueltiger Preis", price_net=raw),
    )
    assert status == 400
    assert "Nachkommastellen" in body or "ungültig" in body
    assert len(catalog.list_dishes()) == before
    assert all(d.name != "Ungueltiger Preis" for d in catalog.list_dishes())


@pytest.mark.parametrize("raw", ["1.999", "12,505", "-5,00", "abc", ""])
def test_edit_rejects_imprecise_price_and_keeps_old_value(
    catalog_world, raw: str
) -> None:
    """The same rule guards the pre-existing edit form — a rejected save must
    leave the stored price exactly as it was."""
    base, catalog = catalog_world
    _status, edit = _get(f"{base}/gerichte/{_MODERN_ID}/edit")
    before = catalog.get_dish(_MODERN_ID).current_unit_net_cents
    status, _body = _post(
        f"{base}/gerichte/{_MODERN_ID}/update",
        {
            "_csrf_token": _csrf_from(edit),
            "_expect_updated_at": _expect_updated_at_from(edit),
            "name": "Bruschetta",
            "description": "",
            "composition": "",
            "notes": "",
            "price_net": raw,
        },
    )
    assert status == 400
    assert catalog.get_dish(_MODERN_ID).current_unit_net_cents == before


@pytest.mark.parametrize(
    "overrides,expected_status",
    [
        # Form/price parsing never reaches the domain -> 400.
        ({"price_net": "keine-zahl"}, 400),
        ({"price_net": ""}, 400),
        # The domain rejected the value -> 422.
        ({"category": "Fingerfood"}, 422),
        ({"category": ""}, 422),
        ({"vat_rate_percent": "5"}, 422),
        ({"vat_rate_percent": ""}, 422),
        ({"pricing_unit": "kilogramm"}, 422),
        ({"name": ""}, 422),
    ],
    ids=[
        "price-not-a-number",
        "price-empty",
        "category-uppercase",
        "category-empty",
        "vat-not-allowed",
        "vat-empty",
        "pricing-unit-unknown",
        "name-empty",
    ],
)
def test_create_rejects_invalid_input(
    catalog_world, overrides: dict, expected_status: int
) -> None:
    """CATALOG_ADMIN_PANEL_V1 review fix: a malformed price and a value the
    domain refuses are different failures and must not share a status."""
    base, catalog = catalog_world
    before = len(catalog.list_dishes())
    status, body = _post(f"{base}/gerichte/new", _valid_create_fields(**overrides))
    assert status == expected_status
    assert "ungültig" in body
    assert len(catalog.list_dishes()) == before


def test_create_rejected_form_keeps_submitted_values(catalog_world) -> None:
    base, _catalog = catalog_world
    _status, body = _post(
        f"{base}/gerichte/new",
        _valid_create_fields(name="Behalten", price_net="kaputt"),
    )
    assert 'value="Behalten"' in body


def test_create_without_csrf_token_is_rejected(catalog_world) -> None:
    base, catalog = catalog_world
    before = len(catalog.list_dishes())
    fields = _valid_create_fields()
    del fields["_csrf_token"]
    status, _body = _post(f"{base}/gerichte/new", fields)
    assert status == 403
    assert len(catalog.list_dishes()) == before


def test_create_with_wrong_csrf_token_is_rejected(catalog_world) -> None:
    base, catalog = catalog_world
    before = len(catalog.list_dishes())
    status, _body = _post(
        f"{base}/gerichte/new", _valid_create_fields(_csrf_token="falsch")
    )
    assert status == 403
    assert len(catalog.list_dishes()) == before


# --- activate / deactivate ----------------------------------------------


def test_detail_offers_deactivate_for_active_dish(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte/{_MODERN_ID}")
    assert status == 200
    assert "Deaktivieren" in body
    assert "Aktivieren" not in body
    assert _csrf_from(body) == _CSRF_TOKEN
    assert _expect_updated_at_from(body)


def test_detail_offers_activate_for_inactive_dish(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte/{_LEGACY_ID}")
    assert status == 200
    assert "Aktivieren" in body


def test_activate_success(catalog_world) -> None:
    base, catalog = catalog_world
    _status, detail = _get(f"{base}/gerichte/{_LEGACY_ID}")
    status, _body = _post(
        f"{base}/gerichte/{_LEGACY_ID}/activate",
        {
            "_csrf_token": _csrf_from(detail),
            "_expect_updated_at": _expect_updated_at_from(detail),
        },
    )
    assert status == 200
    assert catalog.get_dish(_LEGACY_ID).active is True


def test_deactivate_success(catalog_world) -> None:
    base, catalog = catalog_world
    _status, detail = _get(f"{base}/gerichte/{_MODERN_ID}")
    status, _body = _post(
        f"{base}/gerichte/{_MODERN_ID}/deactivate",
        {
            "_csrf_token": _csrf_from(detail),
            "_expect_updated_at": _expect_updated_at_from(detail),
        },
    )
    assert status == 200
    assert catalog.get_dish(_MODERN_ID).active is False


def test_activate_with_stale_updated_at_is_rejected(catalog_world) -> None:
    base, catalog = catalog_world
    stale = _NOW.isoformat()
    _status, detail = _get(f"{base}/gerichte/{_LEGACY_ID}")
    _post(
        f"{base}/gerichte/{_LEGACY_ID}/activate",
        {
            "_csrf_token": _csrf_from(detail),
            "_expect_updated_at": _expect_updated_at_from(detail),
        },
    )
    assert catalog.get_dish(_LEGACY_ID).active is True
    # second command still carries the *original* token
    status, body = _post(
        f"{base}/gerichte/{_LEGACY_ID}/deactivate",
        {"_csrf_token": _CSRF_TOKEN, "_expect_updated_at": stale},
    )
    assert status == 409
    assert "zwischenzeitlich geändert" in body
    assert catalog.get_dish(_LEGACY_ID).active is True


def test_activate_without_csrf_token_leaves_dish_unchanged(catalog_world) -> None:
    base, catalog = catalog_world
    status, _body = _post(
        f"{base}/gerichte/{_LEGACY_ID}/activate",
        {"_expect_updated_at": _NOW.isoformat()},
    )
    assert status == 403
    assert catalog.get_dish(_LEGACY_ID).active is False


def test_status_command_on_missing_dish_reports_not_found(catalog_world) -> None:
    base, _catalog = catalog_world
    missing = "33333333-3333-4333-8333-333333333333"
    status, body = _post(
        f"{base}/gerichte/{missing}/activate",
        {"_csrf_token": _CSRF_TOKEN, "_expect_updated_at": _NOW.isoformat()},
    )
    assert status == 404
    assert "nicht gefunden" in body


# --- existing edit form keeps working -----------------------------------


def test_edit_form_has_no_active_checkbox(catalog_world) -> None:
    base, _catalog = catalog_world
    status, body = _get(f"{base}/gerichte/{_MODERN_ID}/edit")
    assert status == 200
    assert 'name="active"' not in body
    # status is still visible, just not editable here
    assert "Status" in body
    assert "Status ändern" in body


def test_edit_form_shows_creation_fields_read_only(catalog_world) -> None:
    base, _catalog = catalog_world
    _status, body = _get(f"{base}/gerichte/{_MODERN_ID}/edit")
    assert "fingerfood" in body
    assert "Stück" in body
    assert "7 %" in body
    assert 'name="category"' not in body
    assert 'name="pricing_unit"' not in body
    assert 'name="vat_rate_percent"' not in body


def test_edit_update_still_saves_and_keeps_status(catalog_world) -> None:
    """The Aktiv checkbox is gone, so `active` is carried forward from the
    dish's current state — a plain save must never silently deactivate."""
    base, catalog = catalog_world
    _status, edit = _get(f"{base}/gerichte/{_MODERN_ID}/edit")
    status, _body = _post(
        f"{base}/gerichte/{_MODERN_ID}/update",
        {
            "_csrf_token": _csrf_from(edit),
            "_expect_updated_at": _expect_updated_at_from(edit),
            "name": "Bruschetta Classica",
            "description": "Neu",
            "composition": "Tomaten",
            "notes": "",
            "price_net": "3,10",
            "allergen_A": "1",
        },
    )
    assert status == 200
    dish = catalog.get_dish(_MODERN_ID)
    assert dish.name == "Bruschetta Classica"
    assert dish.current_unit_net_cents == 310
    assert dish.active is True
    # creation-time fields survive an edit untouched
    assert dish.category == "fingerfood"
    assert dish.pricing_unit == "stueck"
    assert dish.vat_rate_percent == 7


def test_edit_update_on_inactive_dish_keeps_it_inactive(catalog_world) -> None:
    base, catalog = catalog_world
    _status, edit = _get(f"{base}/gerichte/{_LEGACY_ID}/edit")
    status, _body = _post(
        f"{base}/gerichte/{_LEGACY_ID}/update",
        {
            "_csrf_token": _csrf_from(edit),
            "_expect_updated_at": _expect_updated_at_from(edit),
            "name": "Altes Gericht",
            "description": "",
            "composition": "",
            "notes": "",
            "price_net": "5,00",
        },
    )
    assert status == 200
    assert catalog.get_dish(_LEGACY_ID).active is False


def test_edit_update_with_stale_token_leaves_dish_unchanged(catalog_world) -> None:
    base, catalog = catalog_world
    _status, edit = _get(f"{base}/gerichte/{_MODERN_ID}/edit")
    token = _expect_updated_at_from(edit)
    _post(
        f"{base}/gerichte/{_MODERN_ID}/update",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_expect_updated_at": token,
            "name": "Erste Änderung",
            "description": "",
            "composition": "",
            "notes": "",
            "price_net": "2,90",
        },
    )
    status, body = _post(
        f"{base}/gerichte/{_MODERN_ID}/update",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_expect_updated_at": token,
            "name": "Darf nicht gespeichert werden",
            "description": "",
            "composition": "",
            "notes": "",
            "price_net": "9,99",
        },
    )
    assert status == 409
    assert "zwischenzeitlich geändert" in body
    assert catalog.get_dish(_MODERN_ID).name == "Erste Änderung"


# --- server-side status filter (applied before the 100-row limit) --------


@pytest.fixture()
def large_catalog_world():
    """120 active dishes sorted ahead of 3 inactive ones — the shape that
    exposed the original bug: a page limit of 100 is filled entirely by
    active rows, so any filtering done after the read cannot see the
    inactive ones at all."""
    catalog = InMemoryCatalogRepository()
    for index in range(120):
        catalog.insert_dish_if_absent(
            CatalogDish(
                dish_id=f"{index:08d}-1111-4111-8111-111111111111",
                name=f"Aktiv {index:03d}",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=100,
                allergens=(),
                active=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
    for index in range(3):
        catalog.insert_dish_if_absent(
            CatalogDish(
                dish_id=f"9999{index:04d}-2222-4222-8222-222222222222",
                name=f"Zzz Inaktiv {index}",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=100,
                allergens=(),
                active=False,
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
    yield f"http://{host}:{port}", catalog
    server.shutdown()
    server.server_close()


def test_inactive_filter_finds_dishes_beyond_the_first_page(
    large_catalog_world,
) -> None:
    """The regression itself: Inaktiv must return the real inactive dishes,
    not an empty page produced by filtering 100 already-fetched active rows."""
    base, _catalog = large_catalog_world
    status, body = _get(f"{base}/gerichte?status=inactive")
    assert status == 200
    assert body.count("Zzz Inaktiv") == 3
    assert "Keine Gerichte gefunden." not in body
    assert "Aktiv 0" not in body


def test_active_filter_returns_only_active_up_to_the_limit(
    large_catalog_world,
) -> None:
    base, body = large_catalog_world[0], None
    status, body = _get(f"{base}/gerichte?status=active")
    assert status == 200
    assert body.count("Öffnen") == 100
    assert "Zzz Inaktiv" not in body


def test_all_filter_applies_no_status_filter(large_catalog_world) -> None:
    base, _catalog = large_catalog_world
    status, body = _get(f"{base}/gerichte?status=all")
    assert status == 200
    assert body.count("Öffnen") == 100


def test_search_combines_with_inactive_filter(large_catalog_world) -> None:
    base, _catalog = large_catalog_world
    status, body = _get(f"{base}/gerichte?q=Zzz&status=inactive")
    assert status == 200
    assert body.count("Zzz Inaktiv") == 3
    assert "Aktiv 0" not in body


def test_search_combines_with_active_filter(large_catalog_world) -> None:
    base, _catalog = large_catalog_world
    status, body = _get(f"{base}/gerichte?q=Zzz&status=active")
    assert status == 200
    assert "Keine Gerichte gefunden." in body


def test_limit_warning_shown_when_page_is_full(large_catalog_world) -> None:
    base, _catalog = large_catalog_world
    _status, body = _get(f"{base}/gerichte?status=active")
    assert "Die Liste ist auf 100 Gerichte begrenzt." in body
    assert "Bitte verwenden Sie die Suche" in body


def test_limit_warning_absent_below_the_limit(large_catalog_world) -> None:
    base, _catalog = large_catalog_world
    _status, body = _get(f"{base}/gerichte?status=inactive")
    assert "auf 100 Gerichte begrenzt" not in body


def test_limit_warning_absent_on_small_catalog(catalog_world) -> None:
    base, _catalog = catalog_world
    _status, body = _get(f"{base}/gerichte")
    assert "auf 100 Gerichte begrenzt" not in body

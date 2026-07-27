"""REMOTE_CATALOG_PRICE_HISTORY_CONTRACT_FIX_V1 — issue #37.

`RemoteCoreClient.catalog_dish_detail` used to reject every dish that had
ever had its price changed: the Office API emits nine keys per price-history
entry, the client's `_exact()` allowed seven. A dish opened fine until the
first price edit and then returned 502 invalid_response.

These tests pin the real contract from both ends — unit tests against the
exact payload shape, and an integration test through a real Office API
server so the client can never again drift from what Core actually sends.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from catering_system.domain.catalog import CatalogDishCreatePayload
from catering_system.ui.office_api import create_office_api_server
from catering_system.ui.remote_core_client import RemoteCoreClient, RemoteCoreError
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content

_TOKEN = "test-remote-token"
_API_TOKEN = "test-remote-api-token"


def _serve(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[str, HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _json_handler(payload: dict[str, object]) -> type[BaseHTTPRequestHandler]:
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    return Handler


def _history_entry(dish_id: str, **overrides: object) -> dict[str, object]:
    """Exactly what views._price_history_shape emits — all nine keys."""
    entry: dict[str, object] = {
        "entry_id": str(uuid.uuid4()),
        "dish_id": dish_id,
        "old_unit_net_cents": 1250,
        "new_unit_net_cents": 1200,
        "old_price_display": "12,50 €",
        "new_price_display": "12,00 €",
        "changed_at": "2026-07-16T10:00:00+02:00",
        "changed_by": "office",
        "effective_from": "2026-07-16",
    }
    entry.update(overrides)
    return entry


def _detail(dish_id: str, history: list[dict[str, object]]) -> dict[str, object]:
    return {
        "dish_id": dish_id,
        "name": "Fingerfood",
        "current_unit_net_cents": 1200,
        "price_display": "12,00 €",
        "allergens": ["A"],
        "allergen_labels": ["Gluten"],
        "active": True,
        "category": "fingerfood",
        "pricing_unit": "stueck",
        "vat_rate_percent": 7,
        "description": "Desc",
        "composition": "Comp",
        "notes": None,
        "created_at": "2026-07-14T10:00:00+02:00",
        "updated_at": "2026-07-16T10:00:00+02:00",
        "price_history": history,
    }


def _parse(payload: dict[str, object], dish_id: str) -> dict[str, object] | None:
    url, server = _serve(_json_handler(payload))
    try:
        return RemoteCoreClient(url, _TOKEN).catalog_dish_detail(dish_id)
    finally:
        server.shutdown()
        server.server_close()


# --- accepted shapes -----------------------------------------------------


def test_detail_without_price_history_is_accepted() -> None:
    dish_id = str(uuid.uuid4())
    parsed = _parse(_detail(dish_id, []), dish_id)
    assert parsed is not None
    assert parsed["price_history"] == []


def test_detail_with_one_price_history_entry_is_accepted() -> None:
    """The exact case issue #37 rejected."""
    dish_id = str(uuid.uuid4())
    parsed = _parse(_detail(dish_id, [_history_entry(dish_id)]), dish_id)
    assert parsed is not None
    assert len(parsed["price_history"]) == 1


def test_detail_with_several_price_history_entries_is_accepted() -> None:
    dish_id = str(uuid.uuid4())
    history = [
        _history_entry(dish_id, old_unit_net_cents=1250, new_unit_net_cents=1200),
        _history_entry(dish_id, old_unit_net_cents=1200, new_unit_net_cents=990),
        _history_entry(dish_id, old_unit_net_cents=990, new_unit_net_cents=1500),
    ]
    parsed = _parse(_detail(dish_id, history), dish_id)
    assert parsed is not None
    assert len(parsed["price_history"]) == 3


def test_display_strings_are_preserved_verbatim() -> None:
    """The client reads the API's rendering; it must not recompute or
    normalise it, or two formatters would silently drift apart."""
    dish_id = str(uuid.uuid4())
    entry = _history_entry(
        dish_id, old_price_display="12,50 €", new_price_display="9,90 €"
    )
    parsed = _parse(_detail(dish_id, [entry]), dish_id)
    assert parsed is not None
    returned = parsed["price_history"][0]
    assert returned["old_price_display"] == "12,50 €"
    assert returned["new_price_display"] == "9,90 €"


def test_first_entry_without_previous_price_is_accepted() -> None:
    """old_unit_net_cents and old_price_display are both nullable and null
    together — a dish whose history starts with no previous price."""
    dish_id = str(uuid.uuid4())
    entry = _history_entry(dish_id, old_unit_net_cents=None, old_price_display=None)
    parsed = _parse(_detail(dish_id, [entry]), dish_id)
    assert parsed is not None
    assert parsed["price_history"][0]["old_price_display"] is None


def test_null_effective_from_is_accepted() -> None:
    dish_id = str(uuid.uuid4())
    parsed = _parse(
        _detail(dish_id, [_history_entry(dish_id, effective_from=None)]), dish_id
    )
    assert parsed is not None


# --- still fail-closed ---------------------------------------------------


def test_unknown_extra_key_is_rejected() -> None:
    dish_id = str(uuid.uuid4())
    entry = _history_entry(dish_id)
    entry["surprise_field"] = "x"
    with pytest.raises(RemoteCoreError) as exc:
        _parse(_detail(dish_id, [entry]), dish_id)
    assert exc.value.code == "invalid_response"


@pytest.mark.parametrize(
    "missing",
    [
        "entry_id",
        "dish_id",
        "old_unit_net_cents",
        "new_unit_net_cents",
        "old_price_display",
        "new_price_display",
        "changed_at",
        "changed_by",
        "effective_from",
    ],
)
def test_missing_required_key_is_rejected(missing: str) -> None:
    dish_id = str(uuid.uuid4())
    entry = _history_entry(dish_id)
    del entry[missing]
    with pytest.raises(RemoteCoreError) as exc:
        _parse(_detail(dish_id, [entry]), dish_id)
    assert exc.value.code == "invalid_response"


@pytest.mark.parametrize(
    "field,value",
    [
        ("new_price_display", 1200),
        ("new_price_display", None),
        ("old_price_display", 1250),
        ("changed_by", 42),
        ("entry_id", "not-a-uuid"),
        ("new_unit_net_cents", "1200"),
        ("new_unit_net_cents", -1),
        ("old_unit_net_cents", "1250"),
        ("changed_at", "2026-07-16T10:00:00"),  # naive, no timezone
        ("changed_at", "nonsense"),
        ("effective_from", "16.07.2026"),
    ],
)
def test_wrong_field_type_is_rejected(field: str, value: object) -> None:
    dish_id = str(uuid.uuid4())
    with pytest.raises(RemoteCoreError) as exc:
        _parse(_detail(dish_id, [_history_entry(dish_id, **{field: value})]), dish_id)
    assert exc.value.code == "invalid_response"


def test_entry_for_a_different_dish_is_rejected() -> None:
    dish_id = str(uuid.uuid4())
    entry = _history_entry(dish_id)
    entry["dish_id"] = str(uuid.uuid4())
    with pytest.raises(RemoteCoreError) as exc:
        _parse(_detail(dish_id, [entry]), dish_id)
    assert exc.value.code == "invalid_response"


@pytest.mark.parametrize(
    "overrides",
    [
        {"old_unit_net_cents": None},  # display still set
        {"old_price_display": None},  # cents still set
    ],
)
def test_half_null_previous_price_is_rejected(overrides: dict) -> None:
    """Only one of the pair null means the response contradicts itself."""
    dish_id = str(uuid.uuid4())
    with pytest.raises(RemoteCoreError) as exc:
        _parse(_detail(dish_id, [_history_entry(dish_id, **overrides)]), dish_id)
    assert exc.value.code == "invalid_response"


# --- integration through a real Office API server ------------------------


@pytest.fixture()
def core(tmp_path: Path):
    ready: queue.Queue = queue.Queue()

    def run() -> None:
        server = create_office_api_server(
            str(tmp_path / "core.db"),
            _API_TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
        )
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=10)
    host, port = server.server_address[:2]
    yield RemoteCoreClient(f"http://{host}:{port}", _API_TOKEN)
    server.shutdown()
    server.server_close()


def test_real_remote_flow_after_price_change_is_not_502(core: RemoteCoreClient) -> None:
    """End to end against Core: create a dish, change its price, read the
    detail back through RemoteCoreClient. This is the flow that produced
    502 invalid_response in production-shaped remote mode (issue #37)."""
    core.begin_request({})
    dish = core.catalog_dish_write_service.create_dish(
        CatalogDishCreatePayload(
            name="Preisverlauf",
            category="fingerfood",
            pricing_unit="stueck",
            current_unit_net_cents=1250,
            vat_rate_percent=7,
        )
    )

    core.begin_request({})
    detail = core.catalog_dish_detail(dish.dish_id)
    assert detail is not None
    assert detail["price_history"] == []

    core.begin_request({})
    core.update_catalog_dish(
        dish.dish_id,
        args={
            "name": "Preisverlauf",
            "description": None,
            "composition": None,
            "notes": None,
            "current_unit_net_cents": 1200,
            "allergens": [],
            "active": False,
        },
        expected_updated_at=dish.updated_at.isoformat(),
    )

    core.begin_request({})
    detail = core.catalog_dish_detail(dish.dish_id)
    assert detail is not None
    history = detail["price_history"]
    assert len(history) == 1
    entry = history[0]
    assert entry["old_unit_net_cents"] == 1250
    assert entry["new_unit_net_cents"] == 1200
    # display strings come from Core, not recomputed here
    assert entry["old_price_display"] == "12,50 €"
    assert entry["new_price_display"] == "12,00 €"


def test_real_remote_repeated_price_changes_accumulate(core: RemoteCoreClient) -> None:
    core.begin_request({})
    dish = core.catalog_dish_write_service.create_dish(
        CatalogDishCreatePayload(
            name="Mehrfach",
            category="fingerfood",
            pricing_unit="stueck",
            current_unit_net_cents=1250,
            vat_rate_percent=7,
        )
    )
    expected = dish.updated_at.isoformat()
    for price in (1200, 990, 1500):
        core.begin_request({})
        core.update_catalog_dish(
            dish.dish_id,
            args={
                "name": "Mehrfach",
                "description": None,
                "composition": None,
                "notes": None,
                "current_unit_net_cents": price,
                "allergens": [],
                "active": False,
            },
            expected_updated_at=expected,
        )
        core.begin_request({})
        detail = core.catalog_dish_detail(dish.dish_id)
        assert detail is not None
        expected = str(detail["updated_at"])
    assert len(detail["price_history"]) == 3


def test_real_remote_update_without_price_change_has_no_history_entry(
    core: RemoteCoreClient,
) -> None:
    """The other side of the optional key: an edit that leaves the price
    alone returns no price_history_entry_id, and must still be accepted."""
    core.begin_request({})
    dish = core.catalog_dish_write_service.create_dish(
        CatalogDishCreatePayload(
            name="Ohne Preisaenderung",
            category="fingerfood",
            pricing_unit="stueck",
            current_unit_net_cents=1250,
            vat_rate_percent=7,
        )
    )
    core.begin_request({})
    result = core.update_catalog_dish(
        dish.dish_id,
        args={
            "name": "Ohne Preisaenderung neu",
            "description": None,
            "composition": None,
            "notes": None,
            "current_unit_net_cents": 1250,
            "allergens": [],
            "active": False,
        },
        expected_updated_at=dish.updated_at.isoformat(),
    )
    assert result["price_changed"] is False
    assert "price_history_entry_id" not in result

    core.begin_request({})
    detail = core.catalog_dish_detail(dish.dish_id)
    assert detail is not None
    assert detail["price_history"] == []


def test_real_remote_price_change_returns_history_entry_id(
    core: RemoteCoreClient,
) -> None:
    core.begin_request({})
    dish = core.catalog_dish_write_service.create_dish(
        CatalogDishCreatePayload(
            name="Mit Preisaenderung",
            category="fingerfood",
            pricing_unit="stueck",
            current_unit_net_cents=1250,
            vat_rate_percent=7,
        )
    )
    core.begin_request({})
    result = core.update_catalog_dish(
        dish.dish_id,
        args={
            "name": "Mit Preisaenderung",
            "description": None,
            "composition": None,
            "notes": None,
            "current_unit_net_cents": 1500,
            "allergens": [],
            "active": False,
        },
        expected_updated_at=dish.updated_at.isoformat(),
    )
    assert result["price_changed"] is True
    assert uuid.UUID(str(result["price_history_entry_id"])).version == 4

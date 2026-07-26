"""CATALOG_ADMIN_REMOTE_CLIENT_V1: RemoteCoreClient catalog write coverage.

create_catalog_dish/activate_catalog_dish/deactivate_catalog_dish each issue
a write command against the existing minimal Office API response, then
re-read the full detail and construct a strictly-validated CatalogDish — the
same pattern proven for reads in test_remote_core_client_reads.py, applied to
the new write paths and the _RemoteCatalogDishWriteService facade.
"""

from __future__ import annotations

import inspect
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from catering_system.domain.catalog import CatalogDish, CatalogDishCreatePayload
from catering_system.services.catalog_dish_write_service import CatalogDishWriteService
from catering_system.ui.remote_core_client import (
    RemoteCoreClient,
    RemoteCoreError,
    _RemoteCatalogDishWriteService,
)

_TOKEN = "test-remote-token"
_DISH_ID = str(uuid.uuid4())
_UPDATED_AT = "2026-07-14T10:00:00+02:00"


def _serve(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[str, HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _write_json(
    handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]
) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _detail_payload(dish_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "dish_id": dish_id,
        "name": "Fingerfood",
        "current_unit_net_cents": 290,
        "price_display": "2,90 EUR",
        "allergens": ["A"],
        "allergen_labels": ["Gluten"],
        "active": False,
        "category": "fingerfood",
        "pricing_unit": "stueck",
        "vat_rate_percent": 7,
        "description": "Desc",
        "composition": "Comp",
        "notes": "Notes",
        "created_at": _UPDATED_AT,
        "updated_at": _UPDATED_AT,
        "price_history": [],
    }
    payload.update(overrides)
    return payload


def _command_then_detail_handler(
    *,
    command_path: str,
    command_status: int,
    command_response: dict[str, object] | None = None,
    command_error: str | None = None,
    detail_response: dict[str, object] | None = None,
    captured: dict[str, object] | None = None,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            assert self.path == command_path
            length = int(self.headers["Content-Length"])
            request = json.loads(self.rfile.read(length))
            if captured is not None:
                captured["args"] = request["args"]
                captured["command_id"] = request["command_id"]
                captured["expect"] = request["expect"]
            if command_error is not None:
                _write_json(self, command_status, {"error": command_error})
                return
            body = dict(command_response or {})
            body["command_id"] = request["command_id"]
            _write_json(self, command_status, body)

        def do_GET(self) -> None:  # noqa: N802
            if detail_response is None:
                self.send_error(500)
                return
            _write_json(self, 200, detail_response)

        def log_message(self, *_args: object) -> None:
            pass

    return Handler


# --- create_catalog_dish -----------------------------------------------


def test_create_catalog_dish_success() -> None:
    handler_cls = _command_then_detail_handler(
        command_path="/office/v1/catalog/dishes",
        command_status=201,
        command_response={
            "dish_id": _DISH_ID,
            "active": False,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID),
    )
    url, server = _serve(handler_cls)
    try:
        dish = RemoteCoreClient(url, _TOKEN).create_catalog_dish(
            name="Fingerfood",
            category="fingerfood",
            pricing_unit="stueck",
            current_unit_net_cents=290,
            vat_rate_percent=7,
        )
        assert isinstance(dish, CatalogDish)
        assert dish.dish_id == _DISH_ID
        assert dish.active is False
        assert dish.category == "fingerfood"
        assert dish.pricing_unit == "stueck"
        assert dish.vat_rate_percent == 7
    finally:
        server.shutdown()
        server.server_close()


def test_create_catalog_dish_request_payload_strictness() -> None:
    captured: dict[str, object] = {}
    handler_cls = _command_then_detail_handler(
        command_path="/office/v1/catalog/dishes",
        command_status=201,
        command_response={
            "dish_id": _DISH_ID,
            "active": False,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID),
        captured=captured,
    )
    url, server = _serve(handler_cls)
    try:
        RemoteCoreClient(url, _TOKEN).create_catalog_dish(
            name="Fingerfood",
            category="fingerfood",
            pricing_unit="stueck",
            current_unit_net_cents=290,
            vat_rate_percent=7,
            description="Desc",
            allergens=("A", "C"),
        )
        args = captured["args"]
        assert args == {
            "name": "Fingerfood",
            "category": "fingerfood",
            "pricing_unit": "stueck",
            "current_unit_net_cents": 290,
            "vat_rate_percent": 7,
            "description": "Desc",
            "composition": None,
            "notes": None,
            "allergens": ["A", "C"],
        }
        assert captured["expect"] == {}
    finally:
        server.shutdown()
        server.server_close()


def test_create_catalog_dish_cannot_set_dish_id_or_active() -> None:
    """Requirement #6: the client method has no dish_id/active parameter at
    all — the server always mints dish_id and always starts inactive."""
    params = inspect.signature(RemoteCoreClient.create_catalog_dish).parameters
    assert "dish_id" not in params
    assert "active" not in params


def test_create_catalog_dish_validation_error_mapping() -> None:
    handler_cls = _command_then_detail_handler(
        command_path="/office/v1/catalog/dishes",
        command_status=422,
        command_error="validation_error",
    )
    url, server = _serve(handler_cls)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).create_catalog_dish(
                name="",
                category="fingerfood",
                pricing_unit="stueck",
                current_unit_net_cents=290,
                vat_rate_percent=7,
            )
        assert exc.value.status == 422
        assert exc.value.code == "validation_error"
    finally:
        server.shutdown()
        server.server_close()


def test_create_catalog_dish_already_exists_mapping() -> None:
    handler_cls = _command_then_detail_handler(
        command_path="/office/v1/catalog/dishes",
        command_status=409,
        command_error="already_exists",
    )
    url, server = _serve(handler_cls)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).create_catalog_dish(
                name="Fingerfood",
                category="fingerfood",
                pricing_unit="stueck",
                current_unit_net_cents=290,
                vat_rate_percent=7,
            )
        assert exc.value.status == 409
        assert exc.value.code == "already_exists"
    finally:
        server.shutdown()
        server.server_close()


def test_create_catalog_dish_rejects_unknown_response_key() -> None:
    handler_cls = _command_then_detail_handler(
        command_path="/office/v1/catalog/dishes",
        command_status=201,
        command_response={
            "dish_id": _DISH_ID,
            "active": False,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID, unexpected_field="surprise"),
    )
    url, server = _serve(handler_cls)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).create_catalog_dish(
                name="Fingerfood",
                category="fingerfood",
                pricing_unit="stueck",
                current_unit_net_cents=290,
                vat_rate_percent=7,
            )
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_create_catalog_dish_rejects_invalid_pricing_unit_in_response() -> None:
    handler_cls = _command_then_detail_handler(
        command_path="/office/v1/catalog/dishes",
        command_status=201,
        command_response={
            "dish_id": _DISH_ID,
            "active": False,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID, pricing_unit="kg"),
    )
    url, server = _serve(handler_cls)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).create_catalog_dish(
                name="Fingerfood",
                category="fingerfood",
                pricing_unit="stueck",
                current_unit_net_cents=290,
                vat_rate_percent=7,
            )
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_create_catalog_dish_rejects_invalid_category_in_response() -> None:
    handler_cls = _command_then_detail_handler(
        command_path="/office/v1/catalog/dishes",
        command_status=201,
        command_response={
            "dish_id": _DISH_ID,
            "active": False,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID, category="Fingerfood"),
    )
    url, server = _serve(handler_cls)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).create_catalog_dish(
                name="Fingerfood",
                category="fingerfood",
                pricing_unit="stueck",
                current_unit_net_cents=290,
                vat_rate_percent=7,
            )
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_create_catalog_dish_rejects_invalid_vat_rate_in_response() -> None:
    handler_cls = _command_then_detail_handler(
        command_path="/office/v1/catalog/dishes",
        command_status=201,
        command_response={
            "dish_id": _DISH_ID,
            "active": False,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID, vat_rate_percent=21),
    )
    url, server = _serve(handler_cls)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).create_catalog_dish(
                name="Fingerfood",
                category="fingerfood",
                pricing_unit="stueck",
                current_unit_net_cents=290,
                vat_rate_percent=7,
            )
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_create_catalog_dish_accepts_null_legacy_fields() -> None:
    """A freshly created dish always has category/pricing_unit/vat set, but
    the same detail-conversion path is shared with legacy NULL rows (proven
    already for reads) — construction must not require these fields."""
    handler_cls = _command_then_detail_handler(
        command_path="/office/v1/catalog/dishes",
        command_status=201,
        command_response={
            "dish_id": _DISH_ID,
            "active": False,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(
            _DISH_ID, category=None, pricing_unit=None, vat_rate_percent=None
        ),
    )
    url, server = _serve(handler_cls)
    try:
        dish = RemoteCoreClient(url, _TOKEN).create_catalog_dish(
            name="Fingerfood",
            category="fingerfood",
            pricing_unit="stueck",
            current_unit_net_cents=290,
            vat_rate_percent=7,
        )
        assert dish.category is None
        assert dish.pricing_unit is None
        assert dish.vat_rate_percent is None
    finally:
        server.shutdown()
        server.server_close()


# --- activate_catalog_dish / deactivate_catalog_dish --------------------


def test_activate_catalog_dish_success() -> None:
    handler_cls = _command_then_detail_handler(
        command_path=f"/office/v1/catalog/dishes/{_DISH_ID}/activate",
        command_status=200,
        command_response={
            "dish_id": _DISH_ID,
            "active": True,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID, active=True),
    )
    url, server = _serve(handler_cls)
    try:
        dish = RemoteCoreClient(url, _TOKEN).activate_catalog_dish(
            _DISH_ID, expected_updated_at=_UPDATED_AT
        )
        assert dish.active is True
    finally:
        server.shutdown()
        server.server_close()


def test_deactivate_catalog_dish_success() -> None:
    handler_cls = _command_then_detail_handler(
        command_path=f"/office/v1/catalog/dishes/{_DISH_ID}/deactivate",
        command_status=200,
        command_response={
            "dish_id": _DISH_ID,
            "active": False,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID, active=False),
    )
    url, server = _serve(handler_cls)
    try:
        dish = RemoteCoreClient(url, _TOKEN).deactivate_catalog_dish(
            _DISH_ID, expected_updated_at=_UPDATED_AT
        )
        assert dish.active is False
    finally:
        server.shutdown()
        server.server_close()


def test_activate_catalog_dish_sends_expect_updated_at() -> None:
    captured: dict[str, object] = {}
    handler_cls = _command_then_detail_handler(
        command_path=f"/office/v1/catalog/dishes/{_DISH_ID}/activate",
        command_status=200,
        command_response={
            "dish_id": _DISH_ID,
            "active": True,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID, active=True),
        captured=captured,
    )
    url, server = _serve(handler_cls)
    try:
        RemoteCoreClient(url, _TOKEN).activate_catalog_dish(
            _DISH_ID, expected_updated_at=_UPDATED_AT
        )
        assert captured["args"] == {}
        assert captured["expect"] == {"updated_at": _UPDATED_AT}
    finally:
        server.shutdown()
        server.server_close()


def test_activate_catalog_dish_stale_updated_at_maps_to_409() -> None:
    handler_cls = _command_then_detail_handler(
        command_path=f"/office/v1/catalog/dishes/{_DISH_ID}/activate",
        command_status=409,
        command_error="stale_state",
    )
    url, server = _serve(handler_cls)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).activate_catalog_dish(
                _DISH_ID, expected_updated_at=_UPDATED_AT
            )
        assert exc.value.status == 409
        assert exc.value.code == "stale_state"
    finally:
        server.shutdown()
        server.server_close()


def test_deactivate_catalog_dish_missing_dish_maps_to_404() -> None:
    handler_cls = _command_then_detail_handler(
        command_path=f"/office/v1/catalog/dishes/{_DISH_ID}/deactivate",
        command_status=404,
        command_error="not_found",
    )
    url, server = _serve(handler_cls)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).deactivate_catalog_dish(
                _DISH_ID, expected_updated_at=_UPDATED_AT
            )
        assert exc.value.status == 404
        assert exc.value.code == "not_found"
    finally:
        server.shutdown()
        server.server_close()


def test_activate_catalog_dish_repeated_call_is_idempotent() -> None:
    """A second activate against an already-active dish is still a 200 with
    active=True — the server-side no-op path — and the client must accept it
    exactly like the first call, not treat it as an error."""
    handler_cls = _command_then_detail_handler(
        command_path=f"/office/v1/catalog/dishes/{_DISH_ID}/activate",
        command_status=200,
        command_response={
            "dish_id": _DISH_ID,
            "active": True,
            "updated_at": _UPDATED_AT,
        },
        detail_response=_detail_payload(_DISH_ID, active=True),
    )
    url, server = _serve(handler_cls)
    try:
        client = RemoteCoreClient(url, _TOKEN)
        first = client.activate_catalog_dish(_DISH_ID, expected_updated_at=_UPDATED_AT)
        second = client.activate_catalog_dish(_DISH_ID, expected_updated_at=_UPDATED_AT)
        assert first.active is True
        assert second.active is True
    finally:
        server.shutdown()
        server.server_close()


# --- _RemoteCatalogDishWriteService facade -------------------------------


def test_facade_create_calls_client_create_catalog_dish() -> None:
    client = RemoteCoreClient("http://127.0.0.1:8084", _TOKEN)
    recorded: dict[str, object] = {}

    def fake_create(**kwargs: Any) -> CatalogDish:
        recorded.update(kwargs)
        return _detail_dish()

    client.create_catalog_dish = fake_create  # type: ignore[method-assign]
    payload = CatalogDishCreatePayload(
        name="Fingerfood",
        category="fingerfood",
        pricing_unit="stueck",
        current_unit_net_cents=290,
        vat_rate_percent=7,
        allergens=("A",),
    )
    result = client.catalog_dish_write_service.create_dish(payload)
    assert result is not None
    assert recorded["name"] == "Fingerfood"
    assert recorded["category"] == "fingerfood"
    assert recorded["pricing_unit"] == "stueck"
    assert recorded["current_unit_net_cents"] == 290
    assert recorded["vat_rate_percent"] == 7
    assert recorded["allergens"] == ("A",)
    assert "command_id" in recorded


def test_facade_activate_calls_client_activate_catalog_dish() -> None:
    client = RemoteCoreClient("http://127.0.0.1:8084", _TOKEN)
    recorded: dict[str, object] = {}

    def fake_activate(
        dish_id: str, *, expected_updated_at: str, command_id: str | None = None
    ) -> CatalogDish:
        recorded["dish_id"] = dish_id
        recorded["expected_updated_at"] = expected_updated_at
        return _detail_dish(active=True)

    client.activate_catalog_dish = fake_activate  # type: ignore[method-assign]
    result = client.catalog_dish_write_service.activate_dish(
        _DISH_ID, expected_updated_at=_UPDATED_AT
    )
    assert result.active is True
    assert recorded["dish_id"] == _DISH_ID
    assert recorded["expected_updated_at"] == _UPDATED_AT


def test_facade_deactivate_calls_client_deactivate_catalog_dish() -> None:
    client = RemoteCoreClient("http://127.0.0.1:8084", _TOKEN)
    recorded: dict[str, object] = {}

    def fake_deactivate(
        dish_id: str, *, expected_updated_at: str, command_id: str | None = None
    ) -> CatalogDish:
        recorded["dish_id"] = dish_id
        recorded["expected_updated_at"] = expected_updated_at
        return _detail_dish(active=False)

    client.deactivate_catalog_dish = fake_deactivate  # type: ignore[method-assign]
    result = client.catalog_dish_write_service.deactivate_dish(
        _DISH_ID, expected_updated_at=_UPDATED_AT
    )
    assert result.active is False
    assert recorded["dish_id"] == _DISH_ID
    assert recorded["expected_updated_at"] == _UPDATED_AT


def _detail_dish(*, active: bool = False) -> CatalogDish:
    from datetime import UTC, datetime

    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    return CatalogDish(
        dish_id=_DISH_ID,
        name="Fingerfood",
        description=None,
        composition=None,
        notes=None,
        current_unit_net_cents=290,
        allergens=("A",),
        active=active,
        created_at=now,
        updated_at=now,
        category="fingerfood",
        pricing_unit="stueck",
        vat_rate_percent=7,
    )


_DIRECT_TO_REMOTE_METHOD_NAMES = {
    "create_dish": "create_dish",
    "activate_dish": "activate_dish",
    "deactivate_dish": "deactivate_dish",
    # update()/update_dish() is a separate, pre-existing naming mismatch —
    # out of scope for this fix, tracked but not aligned here.
    "update_dish": "update",
}

_REMOTE_SHORT_ALIASES_REMOVED = ("create", "activate", "deactivate")


def test_direct_and_remote_catalog_dish_write_service_interfaces_have_parity() -> None:
    """Requirement #8: every write operation the direct-mode service exposes
    has an identically-named remote-mode facade method, so future Office
    Panel code never has to branch by method name depending on mode.
    update()/update_dish() remains a known, separately-scoped exception."""
    for direct_name, remote_name in _DIRECT_TO_REMOTE_METHOD_NAMES.items():
        assert hasattr(CatalogDishWriteService, direct_name)
        assert hasattr(_RemoteCatalogDishWriteService, remote_name)


def test_remote_catalog_dish_write_service_has_no_short_aliases() -> None:
    """CATALOG_ADMIN_REMOTE_CLIENT_V1 interface fix: create/activate/deactivate
    must not exist alongside create_dish/activate_dish/deactivate_dish — the
    old short names must be gone, not merely supplemented."""
    for short_name in _REMOTE_SHORT_ALIASES_REMOVED:
        assert not hasattr(_RemoteCatalogDishWriteService, short_name)

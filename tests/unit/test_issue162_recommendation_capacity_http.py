from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
from datetime import date
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

from catering_system.services.recommendation_capacity_service import (
    RecommendationCapacityRow,
)
from catering_system.ui.office_api import OfficeApi, create_office_api_server
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content

_TOKEN = "test-office-api-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_EVENT_DATE = date(2026, 8, 31)


def _start_server(db_path: Path) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        server = create_office_api_server(
            str(db_path),
            _TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
        )
        ready.put(server)
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


def _get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


@pytest.fixture()
def capacity_api(tmp_path: Path):  # noqa: ANN201
    server, thread, base_url = _start_server(tmp_path / "core.db")
    yield base_url
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert thread.is_alive() is False


def test_recommendation_capacity_requires_bearer_and_date(capacity_api: str) -> None:
    path = "/office/v1/recommendation-capacity"

    status, body = _get(f"{capacity_api}{path}?date=2026-08-31", {})
    assert status == 401
    assert body == {"error": "unauthorized"}

    status, body = _get(f"{capacity_api}{path}", _AUTH)
    assert status == 400
    assert body == {"error": "invalid_request"}

    status, body = _get(f"{capacity_api}{path}?date=not-a-date", _AUTH)
    assert status == 400
    assert body == {"error": "invalid_request"}


def test_recommendation_capacity_returns_pii_free_shape(capacity_api: str) -> None:
    status, body = _get(
        f"{capacity_api}/office/v1/recommendation-capacity?date=2026-08-31",
        _AUTH,
    )

    assert status == 200
    assert body == {"event_date": "2026-08-31", "rows": []}


def test_office_api_shapes_capacity_rows_without_full_initialization() -> None:
    api = OfficeApi.__new__(OfficeApi)
    api.recommendation_capacity_service = Mock()
    api.recommendation_capacity_service.list_for_date.return_value = (
        RecommendationCapacityRow("dish-a", True, 35),
        RecommendationCapacityRow("dish-b", False, 100, "CAPACITY_UNSET"),
    )

    assert api.recommendation_capacity(_EVENT_DATE) == {
        "event_date": "2026-08-31",
        "rows": [
            {
                "catalog_item_id": "dish-a",
                "feasible": True,
                "overload_penalty": 35,
                "reason_code": None,
            },
            {
                "catalog_item_id": "dish-b",
                "feasible": False,
                "overload_penalty": 100,
                "reason_code": "CAPACITY_UNSET",
            },
        ],
    }

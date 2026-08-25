from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.domain.customer_identity import CustomerIdentity
from catering_system.repositories.sqlite_customer_identity_repository import (
    SQLiteCustomerIdentityRepository,
)

_TOKEN = "test-office-api-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_NOW = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)


def _seed_customer(db: Path, customer_id: str = "customer-1") -> None:
    repo = SQLiteCustomerIdentityRepository(db)
    repo.add(
        CustomerIdentity(
            customer_id=customer_id,
            display_name="Testkunde",
            company_name=None,
            status="active",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    repo.close()


def _start_api_server(db: Path) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        from catering_system.ui.office_api import create_office_api_server

        server = create_office_api_server(
            str(db),
            _TOKEN,
            "127.0.0.1",
            0,
        )
        ready.put(server)
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


@pytest.fixture()
def preference_api(tmp_path: Path):
    db = tmp_path / "core.db"
    _seed_customer(db)
    _seed_customer(db, "customer-2")
    server, thread, base = _start_api_server(db)
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert thread.is_alive() is False


def _get(url: str) -> tuple[int, dict[str, object]]:
    req = urllib.request.Request(url, headers=_AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _post(
    url: str,
    *,
    args: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    body = json.dumps(
        {
            "command_id": str(uuid.uuid4()),
            "expect": {},
            "args": args or {},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**_AUTH, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def test_office_can_create_list_update_and_delete_explicit_preference(
    preference_api: str,
) -> None:
    base = preference_api
    root = f"{base}/office/v1/customers/customer-1/gastronomic-preferences"

    status, created = _post(
        f"{root}/create",
        args={
            "kind": "favorite_dish",
            "value": "Mini-Frikadellen",
            "source": "customer_stated",
        },
    )
    assert status == 201
    preference = created["preference"]
    assert isinstance(preference, dict)
    preference_id = preference["preference_id"]
    assert preference["customer_id"] == "customer-1"
    assert preference["source"] == "customer_stated"

    status, listed = _get(root)
    assert status == 200
    assert listed["customer_id"] == "customer-1"
    assert listed["preferences"] == [preference]

    status, updated = _post(
        f"{root}/{preference_id}/update",
        args={
            "kind": "disliked_dish",
            "value": "Leber",
            "source": "office_recorded",
        },
    )
    assert status == 200
    updated_preference = updated["preference"]
    assert isinstance(updated_preference, dict)
    assert updated_preference["preference_id"] == preference_id
    assert updated_preference["customer_id"] == "customer-1"
    assert updated_preference["created_at"] == preference["created_at"]
    assert updated_preference["source"] == "office_recorded"

    status, deleted = _post(f"{root}/{preference_id}/delete")
    assert status == 200
    assert deleted["deleted_preference_id"] == preference_id
    assert isinstance(deleted["command_id"], str)

    status, listed = _get(root)
    assert status == 200
    assert listed["preferences"] == []


def test_missing_customer_is_404_for_read_and_create(preference_api: str) -> None:
    base = preference_api
    root = f"{base}/office/v1/customers/missing/gastronomic-preferences"

    status, body = _get(root)
    assert status == 404
    assert body == {"error": "customer_not_found"}

    status, body = _post(
        f"{root}/create",
        args={
            "kind": "favorite_dish",
            "value": "Mini-Frikadellen",
            "source": "customer_stated",
        },
    )
    assert status == 404
    assert body == {"error": "customer_not_found"}


def test_inferred_source_is_rejected_and_cross_customer_access_is_hidden(
    preference_api: str,
) -> None:
    base = preference_api
    root = f"{base}/office/v1/customers/customer-1/gastronomic-preferences"

    status, body = _post(
        f"{root}/create",
        args={
            "kind": "favorite_dish",
            "value": "Mini-Frikadellen",
            "source": "inferred",
        },
    )
    assert status == 422
    assert body == {"error": "invalid_gastronomic_preference"}

    status, created = _post(
        f"{root}/create",
        args={
            "kind": "service_style",
            "value": "Buffet",
            "source": "office_recorded",
        },
    )
    assert status == 201
    preference = created["preference"]
    assert isinstance(preference, dict)
    preference_id = preference["preference_id"]

    other_root = f"{base}/office/v1/customers/customer-2/gastronomic-preferences"
    status, body = _post(
        f"{other_root}/{preference_id}/update",
        args={
            "kind": "service_style",
            "value": "Fingerfood",
            "source": "office_recorded",
        },
    )
    assert status == 404
    assert body == {"error": "gastronomic_preference_not_found"}

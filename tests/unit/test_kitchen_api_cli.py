from __future__ import annotations

import sys

import pytest

from catering_system.ui import kitchen_api


class _FakeServer:
    def __init__(self) -> None:
        self.served = False
        self.closed = False

    def serve_forever(self) -> None:
        self.served = True

    def server_close(self) -> None:
        self.closed = True


class _FakeApi:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_main_requires_agent_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KITCHEN_PRINT_AGENT_TOKEN", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["kitchen_api", "--db", "/tmp/core.db", "--host", "127.0.0.1", "--port", "8086"],
    )

    with pytest.raises(SystemExit, match="KITCHEN_PRINT_AGENT_TOKEN is required"):
        kitchen_api.main()


def test_main_runs_server_with_cli_args(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _FakeServer()
    api = _FakeApi()
    captured: dict[str, object] = {}

    def fake_create(
        db_path: str,
        token: str,
        host: str,
        port: int,
    ) -> tuple[_FakeServer, _FakeApi]:
        captured.update(
            db_path=db_path,
            token=token,
            host=host,
            port=port,
        )
        return server, api

    monkeypatch.setenv("KITCHEN_PRINT_AGENT_TOKEN", "test-token")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "kitchen_api",
            "--db",
            "/srv/core.db",
            "--host",
            "127.0.0.1",
            "--port",
            "8086",
        ],
    )
    monkeypatch.setattr(kitchen_api, "create_kitchen_api_server", fake_create)

    kitchen_api.main()

    assert captured == {
        "db_path": "/srv/core.db",
        "token": "test-token",
        "host": "127.0.0.1",
        "port": 8086,
    }
    assert server.served is True
    assert server.closed is True
    assert api.closed is True

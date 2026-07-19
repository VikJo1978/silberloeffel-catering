from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from catering_system.integration import auerswald_sync


class FakeResp:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _fetch_with_payload(payload: bytes):
    with patch("urllib.request.urlopen", return_value=FakeResp(payload)):
        return auerswald_sync.fetch_missed_board("http://sync", "u", "p")


def test_fetch_missed_board_empty_items_list() -> None:
    items, error = _fetch_with_payload(json.dumps({"items": []}).encode())
    assert error is None
    assert items == []


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"items": None}),
        json.dumps({}),
        json.dumps({"items": "bad"}),
        json.dumps({"items": 42}),
        json.dumps(["not", "object"]),
        json.dumps("not-object"),
        b"{not-json",
    ],
)
def test_fetch_missed_board_malformed_payload_is_failure(payload) -> None:
    if isinstance(payload, str):
        payload = payload.encode()
    items, error = _fetch_with_payload(payload)
    assert items is None
    assert error is not None


def test_fetch_rueckruf_count_malformed_board_is_none() -> None:
    with patch.object(
        auerswald_sync,
        "fetch_missed_board",
        return_value=(None, "invalid items in missed-board response"),
    ):
        assert auerswald_sync.fetch_rueckruf_count("http://sync", "u", "p") is None


def test_count_open_missed_calls_empty_board_is_zero() -> None:
    with patch.object(
        auerswald_sync,
        "fetch_missed_board",
        return_value=([], None),
    ):
        assert auerswald_sync.count_open_missed_calls("http://sync", "u", "p") == 0


def test_fetch_rueckruf_count_empty_board_is_zero_not_none() -> None:
    with patch.object(
        auerswald_sync,
        "fetch_missed_board",
        return_value=([], None),
    ):
        assert auerswald_sync.fetch_rueckruf_count("http://sync", "u", "p") == 0


def test_fetch_rueckruf_count_error_is_none() -> None:
    with patch.object(
        auerswald_sync,
        "fetch_missed_board",
        return_value=(None, "timeout"),
    ):
        assert auerswald_sync.fetch_rueckruf_count("http://sync", "u", "p") is None


def test_fetch_missed_board_null_items_not_empty_queue() -> None:
    items, error = _fetch_with_payload(json.dumps({"items": None}).encode())
    assert items is None
    assert error is not None
    assert items != []


def test_fetch_missed_board_missing_items_key_not_empty_queue() -> None:
    items, error = _fetch_with_payload(json.dumps({}).encode())
    assert items is None
    assert error is not None


import urllib.error


def test_fetch_missed_board_transport_error_is_failure() -> None:
    with patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("network down")
    ):
        items, error = auerswald_sync.fetch_missed_board("http://sync", "u", "p")
    assert items is None
    assert error is not None


def test_fetch_missed_board_valid_non_empty_list_unchanged() -> None:
    payload = {
        "items": [
            {"call_id": "01.01.26|10:00:00|01710000000", "reason": "Nicht angenommen"}
        ]
    }
    items, error = _fetch_with_payload(json.dumps(payload).encode())
    assert error is None
    assert items == payload["items"]

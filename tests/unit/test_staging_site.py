from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from catering_system.ui.staging_site import (
    SubmissionRateLimiter,
    create_staging_server,
    validate_staging_payload,
)


@pytest.fixture()
def staging_server(tmp_path: Path):
    db_path = tmp_path / "staging.db"
    server = create_staging_server(db_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}", db_path
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


_VALID = {
    "event_date": "2027-03-14",
    "time_window_text": "18:00–23:00",
    "location_text": "Hamburg",
    "guest_count_estimate": "42",
    "company": "Testbetrieb",
    "name": "Erika Test",
    "email": "erika@example.test",
    "phone": "",
    "event_type": "Business Event",
    "message": "Nur eine Testanfrage.",
    "website": "",
}


def _post(base: str, payload: object) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"{base}/api/inquiries",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_landing_page_and_health_are_served_with_security_headers(
    staging_server,
) -> None:
    base, _db_path = staging_server
    with urllib.request.urlopen(f"{base}/") as response:
        page = response.read().decode()
        assert response.status == 200
        assert "Silberlöffel" in page
        assert "inquiry-form" in page
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]

    with urllib.request.urlopen(f"{base}/healthz") as response:
        assert json.loads(response.read()) == {
            "status": "ok",
            "environment": "staging",
        }


def test_valid_submission_is_stored_only_in_staging_database(staging_server) -> None:
    base, db_path = staging_server
    status, body = _post(base, _VALID)
    assert status == 201
    assert body["accepted"] is True
    assert body["environment"] == "staging"

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT event_date, guest_count_estimate, name, email "
            "FROM staging_inquiries"
        ).fetchone()
        tables = {
            item[0]
            for item in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert row == ("2027-03-14", 42, "Erika Test", "erika@example.test")
    assert tables == {"staging_inquiries"}


@pytest.mark.parametrize(
    "replacement",
    [
        {"event_date": "not-a-date"},
        {"name": ""},
        {"email": "", "phone": ""},
        {"email": "invalid"},
        {"guest_count_estimate": 0},
        {"guest_count_estimate": True},
        {"website": "spam.example"},
    ],
)
def test_invalid_submissions_are_rejected(staging_server, replacement) -> None:
    base, db_path = staging_server
    status, body = _post(base, {**_VALID, **replacement})
    assert status == 400
    assert "error" in body
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM staging_inquiries"
        ).fetchone() == (0,)


def test_private_submission_list_is_not_exposed(staging_server) -> None:
    base, _db_path = staging_server
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(f"{base}/api/inquiries")
    assert error.value.code == 404


def test_wrong_content_type_and_large_body_are_rejected(staging_server) -> None:
    base, _db_path = staging_server
    wrong_type = urllib.request.Request(
        f"{base}/api/inquiries", data=b"{}", method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(wrong_type)
    assert error.value.code == 415

    too_large = urllib.request.Request(
        f"{base}/api/inquiries",
        data=b"x" * 16_385,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(too_large)
    assert error.value.code == 413


def test_rate_limiter_expires_old_hits() -> None:
    limiter = SubmissionRateLimiter(limit=2, window_seconds=10)
    assert limiter.allow("client", now=100)
    assert limiter.allow("client", now=101)
    assert not limiter.allow("client", now=102)
    assert limiter.allow("client", now=111)


def test_payload_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="object"):
        validate_staging_payload([])

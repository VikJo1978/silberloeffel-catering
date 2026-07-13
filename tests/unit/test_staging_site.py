from __future__ import annotations

import json
import socket
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.ui.staging_site import (
    CoreIntakeClient,
    CoreIntakeForwardError,
    SubmissionRateLimiter,
    create_staging_server,
    is_loopback_client,
    validate_core_intake_url,
    validate_staging_payload,
)
from catering_system.ui.website_intake_endpoint import create_website_intake_server


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
            "core_forwarding": False,
        }


def test_valid_submission_is_stored_only_in_staging_database(staging_server) -> None:
    base, db_path = staging_server
    status, body = _post(base, _VALID)
    assert status == 201
    assert body["accepted"] is True
    assert body["environment"] == "staging"
    assert body["forwarded_to_core"] is False

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
        {"guest_count_estimate": 2001},
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


def test_admin_page_is_loopback_only_and_escapes_stored_text(staging_server) -> None:
    base, _db_path = staging_server
    status, _body = _post(
        base,
        {**_VALID, "name": "<script>alert(1)</script>", "message": "A & B"},
    )
    assert status == 201

    with urllib.request.urlopen(f"{base}/admin") as response:
        page = response.read().decode()

    assert response.status == 200
    assert "Staging-Anfragen" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "A &amp; B" in page
    assert "<script>alert(1)</script>" not in page


@pytest.mark.parametrize(
    ("address", "expected"),
    [("127.0.0.1", True), ("::1", True), ("185.16.60.69", False), ("bad", False)],
)
def test_loopback_client_classification(address: str, expected: bool) -> None:
    assert is_loopback_client(address) is expected


def test_stalled_client_does_not_block_other_visitors(staging_server) -> None:
    base, _db_path = staging_server
    host, port_text = base.removeprefix("http://").split(":")
    stalled_client = socket.create_connection((host, int(port_text)), timeout=1)
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=1) as response:
            assert response.status == 200
    finally:
        stalled_client.close()


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


def test_submission_id_is_namespaced_and_strict() -> None:
    inquiry = validate_staging_payload({**_VALID, "submission_id": "retry_42"})
    assert inquiry["submission_id"] == "vps-staging-retry_42"

    with pytest.raises(ValueError, match="submission_id"):
        validate_staging_payload({**_VALID, "submission_id": "bad/id"})


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:18083/intake/website-form",
        "http://185.16.60.69:18083/intake/website-form",
        "http://127.0.0.1:18083/wrong",
        "http://127.0.0.1:18083/intake/website-form?debug=1",
        "http://user@127.0.0.1:18083/intake/website-form",
    ],
)
def test_core_intake_url_must_be_exact_loopback(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        validate_core_intake_url(url)


def test_forwarding_creates_one_core_inquiry_and_one_local_audit_row(
    tmp_path: Path,
) -> None:
    core_repository = InMemoryInquiryRepository()
    core_server = create_website_intake_server(
        core_repository, "forward-test-token", host="127.0.0.1", port=0
    )
    core_thread = threading.Thread(target=core_server.serve_forever, daemon=True)
    core_thread.start()
    core_host, core_port = core_server.server_address[:2]
    client = CoreIntakeClient(
        f"http://{core_host}:{core_port}/intake/website-form",
        "forward-test-token",
    )
    local_db = tmp_path / "forwarding.db"
    staging_server = create_staging_server(
        local_db, host="127.0.0.1", port=0, core_intake_client=client
    )
    staging_thread = threading.Thread(target=staging_server.serve_forever, daemon=True)
    staging_thread.start()
    staging_host, staging_port = staging_server.server_address[:2]
    base = f"http://{staging_host}:{staging_port}"
    payload = {**_VALID, "submission_id": "same-browser-attempt"}
    try:
        first_status, first_body = _post(base, payload)
        second_status, second_body = _post(base, payload)
        with urllib.request.urlopen(f"{base}/healthz") as response:
            health = json.loads(response.read())
    finally:
        staging_server.shutdown()
        staging_thread.join(timeout=2)
        staging_server.server_close()
        core_server.shutdown()
        core_thread.join(timeout=2)
        core_server.server_close()

    assert first_status == second_status == 202
    assert first_body["forwarded_to_core"] is True
    assert second_body["submission_id"] == first_body["submission_id"]
    assert health["core_forwarding"] is True
    inquiries = core_repository.list_all()
    assert len(inquiries) == 1
    assert inquiries[0].intake_external_ref == "vps-staging-same-browser-attempt"
    with sqlite3.connect(local_db) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM staging_inquiries"
        ).fetchone() == (1,)


def test_failed_core_forward_is_502_and_is_not_saved_locally(tmp_path: Path) -> None:
    class FailingClient:
        def forward(self, inquiry: dict[str, object]) -> None:
            raise CoreIntakeForwardError("expected test failure")

    db_path = tmp_path / "failed-forward.db"
    server = create_staging_server(
        db_path,
        host="127.0.0.1",
        port=0,
        core_intake_client=FailingClient(),  # type: ignore[arg-type]
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status, body = _post(f"http://{host}:{port}", _VALID)
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert status == 502
    assert body == {"error": "Core intake temporarily unavailable"}
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM staging_inquiries"
        ).fetchone() == (0,)

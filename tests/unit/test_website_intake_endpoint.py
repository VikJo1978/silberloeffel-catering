"""Unit tests — website intake receiver (WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1).

Live-socket HTTP, same pattern as test_office_panel.py. This receiver has
exactly one route and one job: create an Inquiry via website_form_adapter,
nothing else — every test here is either proving that job works correctly
or proving nothing beyond it is reachable.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.ui.website_intake_endpoint import create_website_intake_server

_TOKEN = "test-website-intake-token"
_D = date(2026, 9, 20)


@pytest.fixture()
def server():
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    srv = create_website_intake_server(inquiry_repo, _TOKEN, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address[:2]
    yield f"http://{host}:{port}", inquiry_repo, order_repo
    srv.shutdown()
    srv.server_close()


def _post(
    base: str, payload: dict | str, *, token: str | None = _TOKEN
) -> tuple[int, dict, bytes]:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    req = urllib.request.Request(
        f"{base}/intake/website-form",
        data=body.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {}
        return exc.code, parsed, raw


_VALID_PAYLOAD = {
    "event_date": "2026-09-20",
    "guest_count_estimate": 15,
    "location_text": "Musterstraße 1, München",
    "time_window_text": "abends",
    "company": "Musterfirma GmbH",
    "event_type": "Firmenfeier",
    "phone": "0151 2345678",
    "email": "info@musterfirma.de",
    "message": "Bitte Rückruf vor Lieferung.",
    "submission_id": "web-42",
}


def test_valid_post_creates_exactly_one_inquiry(server) -> None:
    base, inquiry_repo, order_repo = server
    status, body, _raw = _post(base, _VALID_PAYLOAD)
    assert status == 202
    assert body["accepted"] is True
    assert "inquiry_id" in body

    inquiries = inquiry_repo.list_all()
    assert len(inquiries) == 1
    q = inquiries[0]
    assert q.inquiry_id == body["inquiry_id"]
    assert q.inquiry_source == "website_form"
    assert q.event_date == _D
    assert q.guest_count_estimate == 15
    assert q.location_text == "Musterstraße 1, München"
    assert q.time_window_text == "abends"
    assert q.intake_subject == "Musterfirma GmbH — Firmenfeier"
    assert "Telefon: 0151 2345678" in q.intake_message
    assert "E-Mail: info@musterfirma.de" in q.intake_message
    assert "Wunsch: Bitte Rückruf vor Lieferung." in q.intake_message
    assert q.intake_external_ref == "web-42"
    assert order_repo.list_orders() == []


def test_response_sets_security_headers(server) -> None:
    base, _inquiry_repo, _order_repo = server
    request = urllib.request.Request(
        f"{base}/intake/website-form",
        data=json.dumps(_VALID_PAYLOAD).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_TOKEN}",
        },
    )
    with urllib.request.urlopen(request) as response:
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Content-Security-Policy"] == "default-src 'none'"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_response_does_not_echo_contact_details(server) -> None:
    base, _inquiry_repo, _order_repo = server
    _status, _body, raw = _post(base, _VALID_PAYLOAD)
    text = raw.decode("utf-8")
    assert "0151 2345678" not in text
    assert "info@musterfirma.de" not in text
    assert "Bitte Rückruf" not in text
    assert "Musterfirma GmbH" not in text


def test_missing_token_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    status, body, _raw = _post(base, _VALID_PAYLOAD, token=None)
    assert status == 401
    assert body["error"] == "unauthorized"
    assert inquiry_repo.list_all() == []


def test_wrong_token_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    status, body, _raw = _post(base, _VALID_PAYLOAD, token="wrong-token")
    assert status == 401
    assert inquiry_repo.list_all() == []


def test_wrong_method_rejected(server) -> None:
    base, _inquiry_repo, _order_repo = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(
            urllib.request.Request(
                f"{base}/intake/website-form",
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
        )
    assert exc.value.code == 405


def test_wrong_path_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    req = urllib.request.Request(
        f"{base}/some/other/path",
        data=json.dumps(_VALID_PAYLOAD).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_TOKEN}",
        },
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 404
    assert inquiry_repo.list_all() == []


def test_invalid_json_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    status, body, _raw = _post(base, "{not json")
    assert status == 400
    assert body["error"] == "invalid JSON"
    assert inquiry_repo.list_all() == []


def test_missing_event_date_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "event_date"}
    status, body, _raw = _post(base, payload)
    assert status == 400
    assert body["error"] == "invalid website_form payload"
    assert inquiry_repo.list_all() == []


def test_guest_count_out_of_range_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    payload = {**_VALID_PAYLOAD, "guest_count_estimate": 2001}
    status, _body, _raw = _post(base, payload)
    assert status == 400
    assert inquiry_repo.list_all() == []


def test_guest_count_zero_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    payload = {**_VALID_PAYLOAD, "guest_count_estimate": 0}
    status, _body, _raw = _post(base, payload)
    assert status == 400
    assert inquiry_repo.list_all() == []


def test_non_object_json_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    status, body, _raw = _post(base, "[1, 2, 3]")
    assert status == 400
    assert body["error"] == "invalid payload"
    assert inquiry_repo.list_all() == []


def test_unsupported_content_type_rejected(server) -> None:
    base, _inquiry_repo, order_repo = server
    req = urllib.request.Request(
        f"{base}/intake/website-form",
        data=b"not json at all",
        method="POST",
        headers={"Content-Type": "text/plain", "Authorization": f"Bearer {_TOKEN}"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 415
    assert order_repo.list_orders() == []


def test_minimal_payload_creates_inquiry_without_optional_fields(server) -> None:
    base, inquiry_repo, order_repo = server
    status, body, _raw = _post(base, {"event_date": "2026-09-20"})
    assert status == 202
    q = inquiry_repo.get_by_id(body["inquiry_id"])
    assert q is not None
    assert q.inquiry_source == "website_form"
    assert q.intake_subject is None
    assert order_repo.list_orders() == []


def test_no_order_or_orderversion_path_touched(server) -> None:
    base, _inquiry_repo, order_repo = server
    _post(base, _VALID_PAYLOAD)
    assert order_repo.list_orders() == []
    assert order_repo._versions == {}  # noqa: SLF001 — no public "list all versions" method


# -- idempotency (WEBSITE_FORM_INTAKE_IDEMPOTENCY_PACK_V1) ------------------


def test_first_post_with_submission_id_creates_one_inquiry(server) -> None:
    base, inquiry_repo, _order_repo = server
    status, body, _raw = _post(base, _VALID_PAYLOAD)
    assert status == 202
    assert len(inquiry_repo.list_all()) == 1
    assert inquiry_repo.list_all()[0].intake_external_ref == "web-42"


def test_retry_same_submission_id_returns_same_inquiry_id(server) -> None:
    base, inquiry_repo, _order_repo = server
    _status1, body1, _raw1 = _post(base, _VALID_PAYLOAD)
    status2, body2, _raw2 = _post(base, _VALID_PAYLOAD)
    assert status2 == 202
    assert body2["accepted"] is True
    assert body2["inquiry_id"] == body1["inquiry_id"]
    assert len(inquiry_repo.list_all()) == 1


def test_duplicate_insert_race_returns_existing_inquiry() -> None:
    class LookupRaceRepository(InMemoryInquiryRepository):
        hide_next_match = False

        def find_by_source_and_external_ref(
            self, inquiry_source: str, intake_external_ref: str
        ):
            if self.hide_next_match:
                self.hide_next_match = False
                return None
            return super().find_by_source_and_external_ref(
                inquiry_source, intake_external_ref
            )

    inquiry_repo = LookupRaceRepository()
    srv = create_website_intake_server(inquiry_repo, _TOKEN, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        _status1, body1, _raw1 = _post(base, _VALID_PAYLOAD)
        inquiry_repo.hide_next_match = True
        status2, body2, _raw2 = _post(base, _VALID_PAYLOAD)
    finally:
        srv.shutdown()
        srv.server_close()

    assert status2 == 202
    assert body2["inquiry_id"] == body1["inquiry_id"]
    assert len(inquiry_repo.list_all()) == 1


def test_retry_with_different_payload_same_submission_id_still_no_duplicate(
    server,
) -> None:
    """Even if the retried payload's other fields differ slightly (e.g. a
    Worker resending with an updated timestamp elsewhere), matching
    submission_id alone is enough to short-circuit — no adapter call, no
    second Inquiry."""
    base, inquiry_repo, _order_repo = server
    _status1, body1, _raw1 = _post(base, _VALID_PAYLOAD)
    retried = {**_VALID_PAYLOAD, "message": "Ein anderer Text als beim ersten Mal."}
    status2, body2, _raw2 = _post(base, retried)
    assert status2 == 202
    assert body2["inquiry_id"] == body1["inquiry_id"]
    assert len(inquiry_repo.list_all()) == 1
    # the stored Inquiry keeps its original message — retry never re-ran the adapter
    assert (
        inquiry_repo.list_all()[0].intake_message
        != "Ein anderer Text als beim ersten Mal."
    )


def test_missing_submission_id_can_create_multiple_inquiries(server) -> None:
    base, inquiry_repo, _order_repo = server
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "submission_id"}
    _post(base, payload)
    _post(base, payload)
    assert len(inquiry_repo.list_all()) == 2


def test_empty_submission_id_can_create_multiple_inquiries(server) -> None:
    base, inquiry_repo, _order_repo = server
    payload = {**_VALID_PAYLOAD, "submission_id": ""}
    _post(base, payload)
    _post(base, payload)
    assert len(inquiry_repo.list_all()) == 2


def test_duplicate_path_creates_no_order_or_orderversion(server) -> None:
    base, _inquiry_repo, order_repo = server
    _post(base, _VALID_PAYLOAD)
    _post(base, _VALID_PAYLOAD)  # the duplicate/idempotent-replay request
    assert order_repo.list_orders() == []
    assert order_repo._versions == {}  # noqa: SLF001

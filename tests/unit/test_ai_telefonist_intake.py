from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date, time

import pytest

from catering_system.intake.ai_telefonist_adapter import intake_from_ai_telefonist
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.inquiry_repository import (
    DuplicateExternalReferenceError,
)
from catering_system.repositories.sqlite_inquiry_repository import SQLiteInquiryRepository
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.ai_telefonist_intake_endpoint import (
    create_ai_telefonist_intake_server,
)

_TOKEN = "test-ai-telefonist-token"
_D = date(2026, 10, 10)

_VALID = {
    "submission_id": "strato-call-001",
    "contact_name": "Anna Becker",
    "company_name": "Hanse Event GmbH",
    "phone": "+494055512345",
    "email": "anna@hanse-event.de",
    "event_date": "2026-10-10",
    "event_start": "18:30",
    "guest_count": 80,
    "location": "Hamburg-Altona",
    "event_type": "Firmenfeier",
    "fulfillment_mode": "DELIVERY",
    "customer_request": "Vegetarische Auswahl und Dessertgläser.",
}


@pytest.fixture()
def server():
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    srv = create_ai_telefonist_intake_server(
        inquiry_repo, _TOKEN, host="127.0.0.1", port=0
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address[:2]
    yield f"http://{host}:{port}", inquiry_repo, order_repo
    srv.shutdown()
    srv.server_close()


def _post(
    base: str,
    payload: dict | str,
    *,
    token: str | None = _TOKEN,
) -> tuple[int, dict, bytes]:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    request = urllib.request.Request(
        f"{base}/intake/ai-telefonist",
        data=body.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return response.status, json.loads(raw), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {}
        return exc.code, parsed, raw


def test_adapter_maps_strato_call_to_ai_telefonist_inquiry() -> None:
    repo = InMemoryInquiryRepository()
    service = InquiryService(repo)
    q = intake_from_ai_telefonist(
        service,
        {
            **_VALID,
            "event_date": _D,
            "event_start": time(18, 30),
        },
    )

    assert q.inquiry_source == "ai_telefonist"
    assert q.crm_stage == "Neue Anfrage"
    assert q.event_date == _D
    assert q.event_start_local == time(18, 30)
    assert q.time_window_text == "ab 18:30 Uhr"
    assert q.guest_count_estimate == 80
    assert q.location_text == "Hamburg-Altona"
    assert q.fulfillment_mode == "DELIVERY"
    assert q.call_verification_required is True
    assert q.call_verification_status == "pending"
    assert q.intake_external_ref == "strato-call-001"
    assert q.intake_subject == "Hanse Event GmbH — Firmenfeier"
    assert q.customer_snapshot is not None
    assert q.customer_snapshot.contact_name == "Anna Becker"
    assert q.customer_snapshot.company_name == "Hanse Event GmbH"
    assert q.customer_snapshot.email == "anna@hanse-event.de"
    assert q.customer_snapshot.phone == "+494055512345"
    assert "Wunsch: Vegetarische Auswahl" in (q.intake_message or "")


@pytest.mark.parametrize(
    "missing",
    ["submission_id", "contact_name", "phone", "event_date", "guest_count"],
)
def test_adapter_required_fields(missing: str) -> None:
    repo = InMemoryInquiryRepository()
    service = InquiryService(repo)
    payload = {
        **_VALID,
        "event_date": _D,
        "event_start": time(18, 30),
    }
    del payload[missing]
    with pytest.raises((ValueError, TypeError)):
        intake_from_ai_telefonist(service, payload)
    assert repo.list_all() == []


def test_adapter_email_is_optional() -> None:
    repo = InMemoryInquiryRepository()
    service = InquiryService(repo)
    payload = {
        **_VALID,
        "event_date": _D,
        "event_start": time(18, 30),
    }
    del payload["email"]
    q = intake_from_ai_telefonist(service, payload)
    assert q.customer_snapshot is not None
    assert q.customer_snapshot.email is None
    assert q.customer_snapshot.phone == "+494055512345"


def test_valid_http_post_creates_only_one_inquiry(server) -> None:
    base, inquiry_repo, order_repo = server
    status, body, raw = _post(base, _VALID)

    assert status == 202
    assert body["accepted"] is True
    assert len(inquiry_repo.list_all()) == 1
    q = inquiry_repo.get_by_id(body["inquiry_id"])
    assert q is not None
    assert q.inquiry_source == "ai_telefonist"
    assert q.event_start_local == time(18, 30)
    assert order_repo.list_orders() == []

    response_text = raw.decode("utf-8")
    assert "Anna Becker" not in response_text
    assert "+494055512345" not in response_text
    assert "anna@hanse-event.de" not in response_text


def test_retry_same_submission_id_is_idempotent(server) -> None:
    base, inquiry_repo, _order_repo = server
    first_status, first, _ = _post(base, _VALID)
    second_status, second, _ = _post(
        base,
        {**_VALID, "customer_request": "geänderter Retry-Text"},
    )

    assert first_status == 202
    assert second_status == 202
    assert first["inquiry_id"] == second["inquiry_id"]
    assert len(inquiry_repo.list_all()) == 1


def test_missing_or_wrong_token_is_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    status, body, _ = _post(base, _VALID, token=None)
    assert status == 401
    assert body == {"error": "unauthorized"}
    status, body, _ = _post(base, _VALID, token="wrong")
    assert status == 401
    assert body == {"error": "unauthorized"}
    assert inquiry_repo.list_all() == []


def test_invalid_json_and_wrong_path_are_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    status, body, _ = _post(base, "{broken")
    assert status == 400
    assert body == {"error": "invalid JSON"}

    request = urllib.request.Request(
        f"{base}/other",
        data=json.dumps(_VALID).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_TOKEN}",
        },
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request)
    assert exc.value.code == 404
    assert inquiry_repo.list_all() == []


def test_invalid_business_payload_creates_nothing(server) -> None:
    base, inquiry_repo, order_repo = server
    status, body, _ = _post(base, {**_VALID, "guest_count": 0})
    assert status == 400
    assert body == {"error": "invalid ai_telefonist payload"}
    assert inquiry_repo.list_all() == []
    assert order_repo.list_orders() == []


def test_non_json_content_type_is_rejected(server) -> None:
    base, inquiry_repo, _order_repo = server
    request = urllib.request.Request(
        f"{base}/intake/ai-telefonist",
        data=b"abc",
        method="POST",
        headers={
            "Content-Type": "text/plain",
            "Authorization": f"Bearer {_TOKEN}",
        },
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request)
    assert exc.value.code == 415
    assert inquiry_repo.list_all() == []


def test_response_security_headers(server) -> None:
    base, _inquiry_repo, _order_repo = server
    request = urllib.request.Request(
        f"{base}/intake/ai-telefonist",
        data=json.dumps(_VALID).encode("utf-8"),
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


def test_sqlite_ai_telefonist_submission_id_is_unique(tmp_path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    service = InquiryService(repo)
    payload = {
        **_VALID,
        "event_date": _D,
        "event_start": time(18, 30),
    }
    first = intake_from_ai_telefonist(service, payload)
    assert repo.find_by_source_and_external_ref(
        "ai_telefonist", "strato-call-001"
    ) == first

    with pytest.raises(DuplicateExternalReferenceError):
        intake_from_ai_telefonist(service, payload)
    assert len(repo.list_all()) == 1
    repo.close()


def test_same_external_ref_is_allowed_for_other_source(tmp_path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    service = InquiryService(repo)
    ai_payload = {
        **_VALID,
        "event_date": _D,
        "event_start": time(18, 30),
    }
    intake_from_ai_telefonist(service, ai_payload)
    website = service.create_inquiry(
        event_date=_D,
        inquiry_source="website_form",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=True,
        call_verification_status="pending",
        intake_external_ref="strato-call-001",
        contact_email="web@example.test",
        contact_phone="+49405550000",
    )
    assert website.inquiry_source == "website_form"
    assert len(repo.list_all()) == 2
    repo.close()

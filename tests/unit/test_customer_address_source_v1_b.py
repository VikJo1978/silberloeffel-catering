"""CUSTOMER_ADDRESS_SOURCE_V1-B — preservation + write API (slices 1–2)."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.inquiry_contact_completeness import (
    complete_inquiry_contact_information,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot,
    customer_address_to_mapping,
    customer_snapshot_to_mapping,
    set_inquiry_customer_addresses,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService

_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
_INVOICE = CustomerAddress(
    street="Bürostraße 1",
    postal_code="20095",
    city="Hamburg",
    country="DE",
)
_DELIVERY = CustomerAddress(
    street="Eventplatz 9",
    postal_code="20457",
    city="Hamburg",
    country="DE",
)
_API_TOKEN = "customer-addresses-test-token"
_API_AUTH = {"Authorization": f"Bearer {_API_TOKEN}"}


def _inquiry(snapshot: InquiryCustomerSnapshot | None) -> Inquiry:
    return Inquiry(
        inquiry_id="99999999-9999-4999-8999-999999999999",
        event_date=date(2026, 8, 20),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        created_at=_NOW,
        updated_at=_NOW,
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        customer_snapshot=snapshot,
    )


def _addressed_snapshot() -> InquiryCustomerSnapshot:
    return InquiryCustomerSnapshot(
        company_name="ACME",
        contact_name="Anna",
        phone="+49301234567",
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )


def test_contact_completion_preserves_addresses_and_mode() -> None:
    inquiry = _inquiry(_addressed_snapshot())
    updated = complete_inquiry_contact_information(
        inquiry, email="Nachtrag@Example.com"
    )
    assert updated.customer_snapshot is not None
    assert updated.customer_snapshot.email == "nachtrag@example.com"
    assert updated.customer_snapshot.phone == "+49301234567"
    assert updated.customer_snapshot.invoice_address == _INVOICE
    assert updated.customer_snapshot.delivery_address == _DELIVERY
    assert updated.customer_snapshot.delivery_address_mode == "SEPARATE"
    assert updated.customer_snapshot.company_name == "ACME"
    assert updated.customer_snapshot.contact_name == "Anna"


def test_set_addresses_same_as_invoice_clears_delivery() -> None:
    inquiry = _inquiry(
        InquiryCustomerSnapshot(
            contact_name="Anna",
            phone="+49301",
            invoice_address=_INVOICE,
            delivery_address=_DELIVERY,
            delivery_address_mode="SEPARATE",
        )
    )
    updated = set_inquiry_customer_addresses(
        inquiry,
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,  # ignored
        delivery_address_mode="SAME_AS_INVOICE",
    )
    assert updated.customer_snapshot is not None
    assert updated.customer_snapshot.delivery_address_mode == "SAME_AS_INVOICE"
    assert updated.customer_snapshot.delivery_address is None
    assert updated.customer_snapshot.invoice_address == _INVOICE
    assert updated.customer_snapshot.phone == "+49301"


def test_set_addresses_unknown_clears_delivery() -> None:
    inquiry = _inquiry(_addressed_snapshot())
    updated = set_inquiry_customer_addresses(
        inquiry,
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="UNKNOWN",
    )
    assert updated.customer_snapshot is not None
    assert updated.customer_snapshot.delivery_address is None
    assert updated.customer_snapshot.delivery_address_mode == "UNKNOWN"


def test_set_addresses_separate_requires_delivery() -> None:
    with pytest.raises(ValueError, match="SEPARATE mode requires delivery_address"):
        set_inquiry_customer_addresses(
            _inquiry(InquiryCustomerSnapshot(contact_name="Anna")),
            invoice_address=_INVOICE,
            delivery_address=None,
            delivery_address_mode="SEPARATE",
        )


def test_set_addresses_preserves_contact_fields() -> None:
    inquiry = _inquiry(
        InquiryCustomerSnapshot(
            company_name="ACME",
            contact_name="Anna",
            email="a@b.de",
            phone="+49301",
        )
    )
    updated = set_inquiry_customer_addresses(
        inquiry,
        invoice_address=_INVOICE,
        delivery_address=None,
        delivery_address_mode="SAME_AS_INVOICE",
    )
    snap = updated.customer_snapshot
    assert snap is not None
    assert snap.company_name == "ACME"
    assert snap.contact_name == "Anna"
    assert snap.email == "a@b.de"
    assert snap.phone == "+49301"


def test_service_round_trip_sqlite(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    service = InquiryService(repo)
    created = service.create_inquiry(
        inquiry_source="manual",
        contact_phone="+49301234567",
        contact_name="Anna",
        **_create_kwargs(),
    )
    updated = service.set_inquiry_customer_addresses(
        created.inquiry_id,
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    loaded = repo.get_by_id(created.inquiry_id)
    assert loaded is not None
    assert loaded.customer_snapshot == updated.customer_snapshot
    assert loaded.customer_snapshot is not None
    assert loaded.customer_snapshot.delivery_address_mode == "SEPARATE"
    completed = service.complete_inquiry_contact_information(
        created.inquiry_id, email="a@b.de"
    )
    assert completed.customer_snapshot is not None
    assert completed.customer_snapshot.invoice_address == _INVOICE
    assert completed.customer_snapshot.delivery_address == _DELIVERY
    assert completed.customer_snapshot.delivery_address_mode == "SEPARATE"
    repo.close()


# --- API ---------------------------------------------------------------------


def _create_kwargs() -> dict[str, object]:
    return {
        "event_date": date(2026, 8, 20),
        "crm_stage": "Neue Anfrage",
        "customer_linkage": {},
        "time_window_text": "mittags",
        "location_text": "Hamburg",
        "guest_count_estimate": 20,
        "planning_mode": "caterer_suggestion",
        "call_verification_required": False,
        "call_verification_status": "not_required",
    }


def _api_seed(db_path: Path) -> dict[str, str]:
    repo = SQLiteInquiryRepository(db_path)
    service = InquiryService(repo)
    inquiry = service.create_inquiry(
        inquiry_source="manual",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
        contact_name="Anna",
        **_create_kwargs(),
    )
    repo.close()
    return {
        "inquiry_id": inquiry.inquiry_id,
        "updated_at": inquiry.updated_at.isoformat(),
    }


@pytest.fixture()
def addresses_api(tmp_path: Path):
    from catering_system.ui.office_api import create_office_api_server
    from tests.helpers.offer_pdf_static_content import (
        fake_offer_pdf_static_content,
    )

    db = tmp_path / "core.db"
    ids = _api_seed(db)
    ready: queue.Queue = queue.Queue()

    def run() -> None:
        server = create_office_api_server(
            str(db),
            _API_TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
        )
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}", ids
    server.shutdown()
    server.server_close()


def _api_get(url: str):  # noqa: ANN202
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers=_API_AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _api_set_addresses(
    base: str,
    inquiry_id: str,
    *,
    args: dict,
    expect: dict,
    headers: dict | None = None,
):  # noqa: ANN202
    import urllib.error
    import urllib.request

    body = json.dumps(
        {"command_id": str(uuid.uuid4()), "expect": expect, "args": args}
    ).encode()
    all_headers = {"Content-Type": "application/json"}
    all_headers.update(headers if headers is not None else _API_AUTH)
    req = urllib.request.Request(
        f"{base}/office/v1/inquiries/{inquiry_id}/customer-addresses",
        data=body,
        headers=all_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _payload(
    *,
    mode: str,
    invoice: CustomerAddress | None = _INVOICE,
    delivery: CustomerAddress | None = None,
) -> dict[str, object]:
    return {
        "invoice_address": customer_address_to_mapping(invoice),
        "delivery_address": customer_address_to_mapping(delivery),
        "delivery_address_mode": mode,
    }


def test_api_customer_addresses_separate_success(addresses_api) -> None:
    base, ids = addresses_api
    status, body = _api_set_addresses(
        base,
        ids["inquiry_id"],
        args=_payload(mode="SEPARATE", delivery=_DELIVERY),
        expect={"updated_at": ids["updated_at"]},
    )
    assert status == 200
    assert body["customer_snapshot"]["delivery_address_mode"] == "SEPARATE"
    assert body["customer_snapshot"]["delivery_address"] == customer_address_to_mapping(
        _DELIVERY
    )
    status, detail = _api_get(f"{base}/office/v1/inquiries/{ids['inquiry_id']}")
    assert status == 200
    assert detail["customer_snapshot"] == body["customer_snapshot"]


def test_api_customer_addresses_same_as_invoice_stores_null_delivery(
    addresses_api,
) -> None:
    base, ids = addresses_api
    status, body = _api_set_addresses(
        base,
        ids["inquiry_id"],
        args=_payload(mode="SAME_AS_INVOICE", delivery=_DELIVERY),
        expect={"updated_at": ids["updated_at"]},
    )
    assert status == 200
    snap = body["customer_snapshot"]
    assert snap["delivery_address_mode"] == "SAME_AS_INVOICE"
    assert snap["delivery_address"] is None
    assert snap["invoice_address"] == customer_address_to_mapping(_INVOICE)


def test_api_customer_addresses_separate_missing_delivery_422(addresses_api) -> None:
    base, ids = addresses_api
    status, body = _api_set_addresses(
        base,
        ids["inquiry_id"],
        args=_payload(mode="SEPARATE", delivery=None),
        expect={"updated_at": ids["updated_at"]},
    )
    assert (status, body["error"]) == (422, "invalid_customer_addresses")


def test_api_customer_addresses_invalid_mode_422(addresses_api) -> None:
    base, ids = addresses_api
    status, body = _api_set_addresses(
        base,
        ids["inquiry_id"],
        args=_payload(mode="OTHER"),
        expect={"updated_at": ids["updated_at"]},
    )
    assert (status, body["error"]) == (422, "invalid_customer_addresses")


def test_api_customer_addresses_unknown_inquiry_404(addresses_api) -> None:
    base, _ids = addresses_api
    status, body = _api_set_addresses(
        base,
        str(uuid.uuid4()),
        args=_payload(mode="UNKNOWN"),
        expect={"updated_at": "2026-07-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (404, "not_found")


def test_api_customer_addresses_stale_409(addresses_api) -> None:
    base, ids = addresses_api
    status, body = _api_set_addresses(
        base,
        ids["inquiry_id"],
        args=_payload(mode="UNKNOWN"),
        expect={"updated_at": "2020-01-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (409, "stale_state")


def test_api_customer_addresses_missing_arg_key_400(addresses_api) -> None:
    base, ids = addresses_api
    status, body = _api_set_addresses(
        base,
        ids["inquiry_id"],
        args={
            "invoice_address": customer_address_to_mapping(_INVOICE),
            "delivery_address_mode": "UNKNOWN",
        },
        expect={"updated_at": ids["updated_at"]},
    )
    assert (status, body["error"]) == (400, "invalid_request")


def test_mapping_shape_stable_after_write() -> None:
    inquiry = set_inquiry_customer_addresses(
        _inquiry(InquiryCustomerSnapshot(contact_name="Anna")),
        invoice_address=_INVOICE,
        delivery_address=None,
        delivery_address_mode="SAME_AS_INVOICE",
    )
    mapped = customer_snapshot_to_mapping(inquiry.customer_snapshot)
    assert mapped is not None
    assert set(mapped) == {
        "company_name",
        "contact_name",
        "email",
        "phone",
        "invoice_address",
        "delivery_address",
        "delivery_address_mode",
    }

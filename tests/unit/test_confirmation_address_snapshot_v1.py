"""CONFIRMATION_ADDRESS_SNAPSHOT_V1 — schema 2 address facts + legacy schema 1."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerAddress,
)
from catering_system.domain.inquiry_customer_snapshot import (
    set_inquiry_customer_addresses,
)
from catering_system.domain.order_confirmation_document import (
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
)
from catering_system.services.order_confirmation_document_hash import (
    compute_document_hash,
    snapshot_hash_payload,
)
from catering_system.services.order_confirmation_document_preview import (
    build_preview,
    preview_to_json,
    render_preview_html,
)
from catering_system.services.order_confirmation_document_serialization import (
    snapshot_from_canonical_json,
    snapshot_to_canonical_json,
)
from catering_system.ui import office_api_views as views
from tests.unit.test_order_confirmation_document import _effective_order, _services

# Golden legacy schema-1 canonical JSON (no address keys). Hash captured on
# origin/main before CONFIRMATION_ADDRESS_SNAPSHOT_V1 — must remain stable.
_LEGACY_V1_CANONICAL_JSON = (
    '{"created_at":"2026-01-15T12:00:00+00:00","created_by":"fixture",'
    '"document_hash":"sha256:e8a0f371e92b8cf417ddce34919cd4ab3d60174c4386d37ac379603196f5a31b",'
    '"document_reference":"AB-TEST-V1",'
    '"document_snapshot_id":"11111111-1111-4111-8111-111111111111",'
    '"document_warnings":["DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE"],'
    '"event_date":"2026-06-01","gross_total_cents":1190,"guest_count_estimate":40,'
    '"location_text":"Hamburg","net_total_cents":1000,'
    '"offer_id":"44444444-4444-4444-8444-444444444444",'
    '"offer_version_id":"55555555-5555-4555-8555-555555555555",'
    '"order_id":"22222222-2222-4222-8222-222222222222",'
    '"order_version_id":"33333333-3333-4333-8333-333333333333",'
    '"payment_customer_visible_text":"Rechnung","payment_method":"RECHNUNG",'
    '"planning_mode":"caterer_suggestion",'
    '"positions":[{"composition":"Comp","description":"Desc","gross_cents":1190,'
    '"kind":"MENU","name":"Buffet Classic","net_total_cents":1000,'
    '"position_id":"pos-1","quantity":"40","related_position_id":null,'
    '"unit_label":"Pers.","unit_net_cents":1000,"vat_cents":190,'
    '"vat_rate_percent":19}],'
    '"recipient_company":"Analytical Engines",'
    '"recipient_email":"ada@example.invalid","recipient_name":"Ada Lovelace",'
    '"recipient_phone":"+490000","recipient_status":"ready","schema_version":1,'
    '"time_window_text":"10:00–14:00",'
    '"vat_buckets":[{"base_net_cents":1000,"rate_percent":19,"vat_cents":190}],'
    '"vat_total_cents":190}'
)
_LEGACY_V1_DOCUMENT_HASH = (
    "sha256:e8a0f371e92b8cf417ddce34919cd4ab3d60174c4386d37ac379603196f5a31b"
)

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


def _set_inquiry_addresses(
    inquiries: object,
    order: object,
    *,
    invoice: CustomerAddress | None,
    delivery: CustomerAddress | None,
    mode: str,
) -> None:
    inquiry = inquiries.get_by_id(order.source_inquiry_id)  # type: ignore[attr-defined]
    assert inquiry is not None
    inquiries.update(  # type: ignore[attr-defined]
        set_inquiry_customer_addresses(
            inquiry,
            invoice_address=invoice,
            delivery_address=delivery,
            delivery_address_mode=mode,
        )
    )


def test_a_same_as_invoice_persists_effective_delivery() -> None:
    orders, _offers, inquiries, documents, service, _core, _offer = _services()
    order, version = _effective_order(
        (orders, _offers, inquiries, documents, service, _core, _offer)
    )
    _set_inquiry_addresses(
        inquiries, order, invoice=_INVOICE, delivery=None, mode="SAME_AS_INVOICE"
    )
    snapshot = service.prepare_snapshot(
        order.order_id, version.order_version_id, "office-panel"
    )
    assert snapshot.schema_version == SCHEMA_VERSION_V2
    assert snapshot.invoice_address == _INVOICE
    assert snapshot.delivery_address == _INVOICE
    assert snapshot.delivery_address_differs is False
    assert WARNING_DELIVERY_ADDRESS_DIFFERS not in snapshot.document_warnings
    preview = build_preview(snapshot)
    assert preview.address_facts_stored is True
    assert preview.invoice_address == {
        "street": "Bürostraße 1",
        "postal_code": "20095",
        "city": "Hamburg",
        "country": "DE",
    }
    assert preview.delivery_address == preview.invoice_address
    assert preview.delivery_address_differs is False


def test_b_separate_persists_differs_warning() -> None:
    orders, _offers, inquiries, documents, service, _core, _offer = _services()
    order, version = _effective_order(
        (orders, _offers, inquiries, documents, service, _core, _offer)
    )
    _set_inquiry_addresses(
        inquiries,
        order,
        invoice=_INVOICE,
        delivery=_DELIVERY,
        mode="SEPARATE",
    )
    snapshot = service.prepare_snapshot(
        order.order_id, version.order_version_id, "office-panel"
    )
    assert snapshot.schema_version == SCHEMA_VERSION_V2
    assert snapshot.invoice_address == _INVOICE
    assert snapshot.delivery_address == _DELIVERY
    assert snapshot.delivery_address_differs is True
    assert WARNING_DELIVERY_ADDRESS_DIFFERS in snapshot.document_warnings
    payload = json.loads(snapshot_to_canonical_json(snapshot))
    assert payload["delivery_address_differs"] is True
    assert WARNING_DELIVERY_ADDRESS_DIFFERS in payload["document_warnings"]


def test_c_persisted_addresses_immutable_after_inquiry_change() -> None:
    orders, _offers, inquiries, documents, service, _core, _offer = _services()
    order, version = _effective_order(
        (orders, _offers, inquiries, documents, service, _core, _offer)
    )
    _set_inquiry_addresses(
        inquiries, order, invoice=_INVOICE, delivery=None, mode="SAME_AS_INVOICE"
    )
    snapshot = service.prepare_snapshot(
        order.order_id, version.order_version_id, "office-panel"
    )
    before_canonical = snapshot_to_canonical_json(snapshot)
    before_preview = preview_to_json(build_preview(snapshot))

    changed = CustomerAddress(
        street="Neue Straße 99",
        postal_code="22765",
        city="Hamburg",
        country="DE",
    )
    _set_inquiry_addresses(
        inquiries,
        order,
        invoice=changed,
        delivery=_DELIVERY,
        mode="SEPARATE",
    )
    loaded = service.get_snapshot(order.order_id, snapshot.document_snapshot_id)
    assert snapshot_to_canonical_json(loaded) == before_canonical
    assert preview_to_json(build_preview(loaded)) == before_preview
    assert loaded.invoice_address == _INVOICE
    assert loaded.delivery_address == _INVOICE
    assert loaded.delivery_address_differs is False


def test_d_replay_returns_same_address_facts_without_rewrite() -> None:
    orders, _offers, inquiries, documents, service, _core, _offer = _services()
    order, version = _effective_order(
        (orders, _offers, inquiries, documents, service, _core, _offer)
    )
    _set_inquiry_addresses(
        inquiries,
        order,
        invoice=_INVOICE,
        delivery=_DELIVERY,
        mode="SEPARATE",
    )
    first = service.prepare_snapshot(
        order.order_id, version.order_version_id, "office-panel"
    )
    assert len(documents._by_id) == 1
    second = service.prepare_snapshot(
        order.order_id, version.order_version_id, "office-panel"
    )
    assert second.document_snapshot_id == first.document_snapshot_id
    assert second.document_hash == first.document_hash
    assert second.invoice_address == first.invoice_address
    assert second.delivery_address == first.delivery_address
    assert second.delivery_address_differs == first.delivery_address_differs
    assert len(documents._by_id) == 1


def test_e_legacy_schema_1_explicit_not_stored_and_stable_hash() -> None:
    payload = json.loads(_LEGACY_V1_CANONICAL_JSON)
    assert "invoice_address" not in payload
    assert "delivery_address" not in payload
    assert "delivery_address_differs" not in payload

    loaded = snapshot_from_canonical_json(_LEGACY_V1_CANONICAL_JSON)
    assert loaded.schema_version == SCHEMA_VERSION_V1
    assert loaded.address_facts_stored is False
    assert loaded.invoice_address is None
    assert loaded.delivery_address is None
    assert loaded.delivery_address_differs is None  # NOT_STORED, not false
    assert loaded.document_hash == _LEGACY_V1_DOCUMENT_HASH
    assert compute_document_hash(loaded) == _LEGACY_V1_DOCUMENT_HASH
    assert "invoice_address" not in snapshot_hash_payload(loaded)
    assert "delivery_address" not in snapshot_hash_payload(loaded)
    assert "delivery_address_differs" not in snapshot_hash_payload(loaded)

    roundtrip = snapshot_to_canonical_json(loaded)
    assert json.loads(roundtrip) == payload
    assert "invoice_address" not in json.loads(roundtrip)

    preview = build_preview(loaded)
    assert preview.address_facts_stored is False
    assert preview.invoice_address is None
    assert preview.delivery_address is None
    assert preview.delivery_address_differs is None
    preview_json = preview_to_json(preview)
    assert preview_json["address_facts_stored"] is False
    assert preview_json["delivery_address_differs"] is None


def test_f_boundary_no_offer_or_inquiry_in_persisted_preview_path() -> None:
    root = Path(__file__).resolve().parents[2]
    service_text = (
        root / "src/catering_system/services/order_confirmation_document_service.py"
    ).read_text(encoding="utf-8")
    preview_text = (
        root / "src/catering_system/services/order_confirmation_document_preview.py"
    ).read_text(encoding="utf-8")
    assert "OfferRepository" not in service_text
    assert "OfferRepository" not in preview_text
    assert "InquiryRepository" not in preview_text
    assert "CustomerDocumentProjectionService" not in preview_text
    assert "build_customer_document_recipient" not in preview_text
    sig = inspect.signature(build_preview)
    assert list(sig.parameters) == ["snapshot", "watermark"]


def test_g_api_preview_shape_exposes_address_contract_keys() -> None:
    orders, _offers, inquiries, documents, service, _core, _offer = _services()
    order, version = _effective_order(
        (orders, _offers, inquiries, documents, service, _core, _offer)
    )
    _set_inquiry_addresses(
        inquiries,
        order,
        invoice=_INVOICE,
        delivery=_DELIVERY,
        mode="SEPARATE",
    )
    snapshot = service.prepare_snapshot(
        order.order_id, version.order_version_id, "office-panel"
    )
    shape = views.confirmation_document_preview_shape(build_preview(snapshot))
    required = {
        "schema_version",
        "address_facts_stored",
        "invoice_address",
        "delivery_address",
        "delivery_address_differs",
        "document_warnings",
        "title",
        "positions",
        "watermark",
    }
    assert required.issubset(shape)
    assert shape["schema_version"] == SCHEMA_VERSION_V2
    assert shape["address_facts_stored"] is True
    assert shape["delivery_address_differs"] is True
    assert WARNING_DELIVERY_ADDRESS_DIFFERS in shape["document_warnings"]


def test_unknown_mode_persists_nullable_projection_values() -> None:
    orders, _offers, inquiries, documents, service, _core, _offer = _services()
    order, version = _effective_order(
        (orders, _offers, inquiries, documents, service, _core, _offer)
    )
    _set_inquiry_addresses(
        inquiries, order, invoice=_INVOICE, delivery=None, mode="UNKNOWN"
    )
    snapshot = service.prepare_snapshot(
        order.order_id, version.order_version_id, "office-panel"
    )
    assert snapshot.schema_version == SCHEMA_VERSION_V2
    assert snapshot.invoice_address == _INVOICE
    assert snapshot.delivery_address is None
    assert snapshot.delivery_address_differs is False
    # JSON contract unchanged: null delivery + differs=false from CDP.
    preview = build_preview(snapshot)
    assert preview.delivery_address is None
    assert preview.delivery_address_differs is False
    html = render_preview_html(preview)
    assert "Lieferadresse nicht festgelegt" in html
    assert "weicht ab: nein" not in html
    assert "weicht ab: ja" not in html


def _schema2_payload_from_legacy(**overrides: object) -> dict[str, object]:
    payload = json.loads(_LEGACY_V1_CANONICAL_JSON)
    payload["schema_version"] = SCHEMA_VERSION_V2
    payload["document_warnings"] = []
    payload["invoice_address"] = {
        "street": "Bürostraße 1",
        "postal_code": "20095",
        "city": "Hamburg",
        "country": "DE",
    }
    payload["delivery_address"] = None
    payload["delivery_address_differs"] = False
    payload.update(overrides)
    return payload


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def test_schema2_rejects_missing_invoice_address_key() -> None:
    payload = _schema2_payload_from_legacy()
    del payload["invoice_address"]
    with pytest.raises(ValueError, match="schema 2 snapshot requires"):
        snapshot_from_canonical_json(_dumps(payload))


def test_schema2_rejects_missing_delivery_address_key() -> None:
    payload = _schema2_payload_from_legacy()
    del payload["delivery_address"]
    with pytest.raises(ValueError, match="schema 2 snapshot requires"):
        snapshot_from_canonical_json(_dumps(payload))


def test_schema2_rejects_missing_delivery_address_differs_key() -> None:
    payload = _schema2_payload_from_legacy()
    del payload["delivery_address_differs"]
    with pytest.raises(ValueError, match="schema 2 snapshot requires"):
        snapshot_from_canonical_json(_dumps(payload))


def test_schema2_rejects_null_delivery_address_differs() -> None:
    payload = _schema2_payload_from_legacy(delivery_address_differs=None)
    with pytest.raises(ValueError, match="delivery_address_differs must be a bool"):
        snapshot_from_canonical_json(_dumps(payload))


def test_schema2_rejects_malformed_address_object() -> None:
    payload = _schema2_payload_from_legacy(invoice_address={"street": "only"})
    with pytest.raises(ValueError, match="address object keys must be exactly"):
        snapshot_from_canonical_json(_dumps(payload))


def test_schema2_rejects_unsupported_schema_version() -> None:
    payload = _schema2_payload_from_legacy(schema_version=3)
    with pytest.raises(ValueError, match="unsupported order confirmation document"):
        snapshot_from_canonical_json(_dumps(payload))


def test_same_as_invoice_html_may_show_differs_nein() -> None:
    orders, _offers, inquiries, documents, service, _core, _offer = _services()
    order, version = _effective_order(
        (orders, _offers, inquiries, documents, service, _core, _offer)
    )
    _set_inquiry_addresses(
        inquiries, order, invoice=_INVOICE, delivery=None, mode="SAME_AS_INVOICE"
    )
    snapshot = service.prepare_snapshot(
        order.order_id, version.order_version_id, "office-panel"
    )
    html = render_preview_html(build_preview(snapshot))
    assert "Lieferadresse nicht festgelegt" not in html
    assert "weicht ab: nein" in html
    assert "Bürostraße 1" in html

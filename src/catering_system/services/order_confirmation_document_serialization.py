"""JSON serialization for OrderConfirmationDocumentSnapshot persistence."""

from __future__ import annotations

import json
from datetime import date, datetime

from catering_system.domain.inquiry import validate_planning_mode
from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentPosition,
    OrderConfirmationDocumentSnapshot,
    OrderConfirmationVatBucket,
    RecipientStatus,
    SCHEMA_VERSION,
)
from catering_system.domain.order_payment_reminder import validate_payment_method


def snapshot_to_canonical_json(snapshot: OrderConfirmationDocumentSnapshot) -> str:
    payload = _snapshot_payload(snapshot)
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def snapshot_from_canonical_json(raw: str) -> OrderConfirmationDocumentSnapshot:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("confirmation document snapshot JSON must be an object")
    positions_raw = payload.get("positions")
    buckets_raw = payload.get("vat_buckets")
    if not isinstance(positions_raw, list) or not isinstance(buckets_raw, list):
        raise ValueError("confirmation document snapshot JSON is incomplete")
    return OrderConfirmationDocumentSnapshot(
        document_snapshot_id=str(payload["document_snapshot_id"]),
        order_id=str(payload["order_id"]),
        order_version_id=str(payload["order_version_id"]),
        offer_id=str(payload["offer_id"]),
        offer_version_id=str(payload["offer_version_id"]),
        document_reference=str(payload["document_reference"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        created_by=str(payload["created_by"]),
        recipient_name=_optional_str(payload.get("recipient_name")),
        recipient_email=_optional_str(payload.get("recipient_email")),
        recipient_company=_optional_str(payload.get("recipient_company")),
        recipient_phone=_optional_str(payload.get("recipient_phone")),
        recipient_status=_recipient_status(payload.get("recipient_status")),
        event_date=date.fromisoformat(str(payload["event_date"])),
        time_window_text=str(payload["time_window_text"]),
        location_text=str(payload["location_text"]),
        guest_count_estimate=_optional_int(payload.get("guest_count_estimate")),
        planning_mode=validate_planning_mode(str(payload["planning_mode"])),
        positions=tuple(_position(item) for item in positions_raw),
        vat_buckets=tuple(_bucket(item) for item in buckets_raw),
        net_total_cents=int(payload["net_total_cents"]),
        vat_total_cents=int(payload["vat_total_cents"]),
        gross_total_cents=int(payload["gross_total_cents"]),
        payment_method=validate_payment_method(str(payload["payment_method"])),
        payment_customer_visible_text=str(payload["payment_customer_visible_text"]),
        document_hash=str(payload["document_hash"]),
        schema_version=int(payload.get("schema_version", SCHEMA_VERSION)),
        document_warnings=_document_warnings(payload.get("document_warnings")),
    )


def _snapshot_payload(snapshot: OrderConfirmationDocumentSnapshot) -> dict[str, object]:
    return {
        "document_snapshot_id": snapshot.document_snapshot_id,
        "order_id": snapshot.order_id,
        "order_version_id": snapshot.order_version_id,
        "offer_id": snapshot.offer_id,
        "offer_version_id": snapshot.offer_version_id,
        "document_reference": snapshot.document_reference,
        "created_at": snapshot.created_at.isoformat(),
        "created_by": snapshot.created_by,
        "recipient_name": snapshot.recipient_name,
        "recipient_email": snapshot.recipient_email,
        "recipient_company": snapshot.recipient_company,
        "recipient_phone": snapshot.recipient_phone,
        "recipient_status": snapshot.recipient_status,
        "event_date": snapshot.event_date.isoformat(),
        "time_window_text": snapshot.time_window_text,
        "location_text": snapshot.location_text,
        "guest_count_estimate": snapshot.guest_count_estimate,
        "planning_mode": snapshot.planning_mode,
        "positions": [
            {
                "position_id": position.position_id,
                "kind": position.kind,
                "name": position.name,
                "description": position.description,
                "composition": position.composition,
                "quantity": position.quantity,
                "unit_label": position.unit_label,
                "unit_net_cents": position.unit_net_cents,
                "net_total_cents": position.net_total_cents,
                "vat_rate_percent": position.vat_rate_percent,
                "vat_cents": position.vat_cents,
                "gross_cents": position.gross_cents,
                "related_position_id": position.related_position_id,
            }
            for position in snapshot.positions
        ],
        "vat_buckets": [
            {
                "rate_percent": bucket.rate_percent,
                "base_net_cents": bucket.base_net_cents,
                "vat_cents": bucket.vat_cents,
            }
            for bucket in snapshot.vat_buckets
        ],
        "net_total_cents": snapshot.net_total_cents,
        "vat_total_cents": snapshot.vat_total_cents,
        "gross_total_cents": snapshot.gross_total_cents,
        "payment_method": snapshot.payment_method,
        "payment_customer_visible_text": snapshot.payment_customer_visible_text,
        "document_hash": snapshot.document_hash,
        "schema_version": snapshot.schema_version,
        "document_warnings": list(snapshot.document_warnings),
    }


def _position(raw: object) -> OrderConfirmationDocumentPosition:
    if not isinstance(raw, dict):
        raise ValueError("position must be an object")
    return OrderConfirmationDocumentPosition(
        position_id=str(raw["position_id"]),
        kind=str(raw["kind"]),
        name=str(raw["name"]),
        unit_net_cents=int(raw["unit_net_cents"]),
        net_total_cents=int(raw["net_total_cents"]),
        vat_rate_percent=int(raw["vat_rate_percent"]),
        vat_cents=int(raw["vat_cents"]),
        gross_cents=int(raw["gross_cents"]),
        related_position_id=_optional_str(raw.get("related_position_id")),
        description=_optional_str(raw.get("description")),
        composition=_optional_str(raw.get("composition")),
        quantity=_optional_str(raw.get("quantity")),
        unit_label=_optional_str(raw.get("unit_label")),
    )


def _bucket(raw: object) -> OrderConfirmationVatBucket:
    if not isinstance(raw, dict):
        raise ValueError("vat bucket must be an object")
    return OrderConfirmationVatBucket(
        rate_percent=int(raw["rate_percent"]),
        base_net_cents=int(raw["base_net_cents"]),
        vat_cents=int(raw["vat_cents"]),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("invalid integer")
    return value


def _recipient_status(value: object) -> RecipientStatus:
    if value == "ready":
        return "ready"
    if value == "missing":
        return "missing"
    raise ValueError("invalid recipient_status")


def _document_warnings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("document_warnings must be a list")
    return tuple(str(item) for item in value)

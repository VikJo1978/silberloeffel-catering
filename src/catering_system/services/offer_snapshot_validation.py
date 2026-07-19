"""Validate incoming OfferSnapshot V1/V2 envelopes before Core persistence."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, cast

from catering_system.domain.catalog import validate_allergen_codes
from catering_system.domain.inquiry import validate_planning_mode
from catering_system.domain.offer_snapshot import (
    CURRENCY,
    MAX_EMAIL_LEN,
    MAX_LONG_TEXT_LEN,
    MAX_PAYLOAD_BYTES,
    MAX_POSITIONS_PER_VARIANT,
    MAX_SHORT_TEXT_LEN,
    MAX_VARIANTS,
    MIN_POSITIONS_PER_VARIANT,
    MIN_VARIANTS,
    SCHEMA_VERSION,
    SCHEMA_VERSION_V2,
    SOURCE,
    OfferSnapshotCalculator,
    OfferSnapshotCustomerText,
    OfferSnapshotEvent,
    OfferSnapshotPaymentTerms,
    OfferSnapshotPosition,
    OfferSnapshotRecipient,
    OfferSnapshotV1,
    OfferSnapshotV2,
    OfferSnapshotVariant,
    OfferSnapshotVariantTotals,
    SnapshotPositionKind,
    SnapshotQuantityMode,
    _POSITION_KINDS,
    _QUANTITY_MODES,
    _QUANTITY_RE,
    _SNAPSHOT_HASH_RE,
    _VAT_RATES,
    compute_snapshot_hash,
)
from catering_system.domain.order_payment_reminder import validate_payment_method

_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "source",
        "source_draft_id",
        "inquiry_id",
        "snapshot_id",
        "snapshot_hash",
        "snapshot_created_at",
        "valid_until",
        "currency",
        "recipient",
        "event",
        "customer_text",
        "payment_terms",
        "calculator",
        "variants",
    }
)
_RECIPIENT_KEYS = frozenset({"company_name", "contact_name", "email", "postal_address"})
_EVENT_KEYS = frozenset(
    {
        "event_date",
        "time_window_text",
        "location_text",
        "guest_count",
        "planning_mode",
    }
)
_CUSTOMER_TEXT_KEYS = frozenset({"title", "introduction", "notes"})
_PAYMENT_TERMS_KEYS = frozenset({"method", "customer_visible_text"})
_CALCULATOR_KEYS = frozenset(
    {"name", "calculator_revision", "catalog_revision", "tax_revision"}
)
_VARIANT_KEYS = frozenset({"variant_id", "label", "description", "positions", "totals"})
_POSITION_KEYS = frozenset(
    {
        "position_id",
        "kind",
        "catalog_item_id",
        "name",
        "description",
        "composition",
        "quantity_mode",
        "quantity",
        "unit_label",
        "unit_net_cents",
        "net_total_cents",
        "vat_rate_percent",
        "vat_amount_cents",
        "gross_total_cents",
        "notes",
        "related_position_id",
    }
)
_POSITION_KEYS_V2 = _POSITION_KEYS | frozenset({"allergens", "vegan", "vegetarian"})
_TOTALS_KEYS = frozenset(
    {
        "net_cents",
        "vat_7_base_cents",
        "vat_7_amount_cents",
        "vat_19_base_cents",
        "vat_19_amount_cents",
        "gross_cents",
    }
)


def validate_offer_snapshot_bytes(raw: bytes) -> OfferSnapshotV1 | OfferSnapshotV2:
    """Parse UTF-8 JSON bytes and validate an OfferSnapshot V1 envelope."""
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("snapshot payload exceeds size limit")
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid snapshot JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("snapshot envelope must be a JSON object")
    return validate_offer_snapshot(payload)


def validate_offer_snapshot(
    payload: dict[str, object],
) -> OfferSnapshotV1 | OfferSnapshotV2:
    """Validate a parsed OfferSnapshot envelope and verify its content hash."""
    _reject_unknown_keys(payload, _ENVELOPE_KEYS, "envelope")
    schema_version = _require_exact_str(payload.get("schema_version"), "schema_version")
    if schema_version not in (SCHEMA_VERSION, SCHEMA_VERSION_V2):
        raise ValueError("invalid schema_version")
    v2 = schema_version == SCHEMA_VERSION_V2
    source = _require_exact_str(payload.get("source"), "source")
    if source != SOURCE:
        raise ValueError("invalid source")
    inquiry_id = _require_uuid(payload.get("inquiry_id"), "inquiry_id")
    snapshot_id = _require_uuid(payload.get("snapshot_id"), "snapshot_id")
    snapshot_hash = _require_snapshot_hash(payload.get("snapshot_hash"))
    snapshot_created_at = _require_utc_datetime(
        payload.get("snapshot_created_at"), "snapshot_created_at"
    )
    valid_until = _require_date(payload.get("valid_until"), "valid_until")
    currency = _require_exact_str(payload.get("currency"), "currency")
    if currency != CURRENCY:
        raise ValueError("invalid currency")
    recipient = _parse_recipient(_require_object(payload.get("recipient"), "recipient"))
    event = _parse_event(_require_object(payload.get("event"), "event"))
    customer_text = _parse_customer_text(
        _require_object(payload.get("customer_text"), "customer_text")
    )
    payment_terms = _parse_payment_terms(
        _require_object(payload.get("payment_terms"), "payment_terms")
    )
    calculator = _parse_calculator(
        _require_object(payload.get("calculator"), "calculator")
    )
    variants = _parse_variants(
        _require_list(payload.get("variants"), "variants"), event, v2=v2
    )
    source_draft_id = _optional_short_text(
        payload.get("source_draft_id"), "source_draft_id"
    )

    computed_hash = compute_snapshot_hash(payload)
    if snapshot_hash != computed_hash:
        raise ValueError("snapshot_hash mismatch")

    snapshot = OfferSnapshotV2(
        schema_version=schema_version,
        source=source,
        source_draft_id=source_draft_id,
        inquiry_id=inquiry_id,
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
        snapshot_created_at=snapshot_created_at,
        valid_until=valid_until,
        currency=currency,
        recipient=recipient,
        event=event,
        customer_text=customer_text,
        payment_terms=payment_terms,
        calculator=calculator,
        variants=variants,
    )
    if v2:
        return snapshot
    return OfferSnapshotV1(
        schema_version=snapshot.schema_version,
        source=snapshot.source,
        source_draft_id=snapshot.source_draft_id,
        inquiry_id=snapshot.inquiry_id,
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.snapshot_hash,
        snapshot_created_at=snapshot.snapshot_created_at,
        valid_until=snapshot.valid_until,
        currency=snapshot.currency,
        recipient=snapshot.recipient,
        event=snapshot.event,
        customer_text=snapshot.customer_text,
        payment_terms=snapshot.payment_terms,
        calculator=snapshot.calculator,
        variants=snapshot.variants,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_unknown_keys(
    payload: dict[str, object], allowed: frozenset[str], label: str
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown {label} field")


def _require_object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _require_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _require_exact_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _require_short_text(value: object, field: str) -> str:
    text = _require_exact_str(value, field).strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > MAX_SHORT_TEXT_LEN:
        raise ValueError(f"{field} exceeds length limit")
    return text


def _optional_short_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    text = _require_exact_str(value, field).strip()
    if not text:
        return None
    if len(text) > MAX_SHORT_TEXT_LEN:
        raise ValueError(f"{field} exceeds length limit")
    return text


def _optional_long_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    text = _require_exact_str(value, field)
    if len(text) > MAX_LONG_TEXT_LEN:
        raise ValueError(f"{field} exceeds length limit")
    return text


def _require_long_text(value: object, field: str) -> str:
    text = _require_exact_str(value, field)
    if len(text) > MAX_LONG_TEXT_LEN:
        raise ValueError(f"{field} exceeds length limit")
    return text


def _require_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID string") from exc
    if parsed.version != 4:
        raise ValueError(f"{field} must be a UUID4 string")
    return str(parsed)


def _require_catalog_item_id(value: object, field: str) -> str:
    """Catalog dish_id may be UUID v5 (seed from items.json slug) — not only v4."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID string") from exc
    if parsed.version not in {4, 5}:
        raise ValueError(f"{field} must be a UUID string")
    return str(parsed)


def _require_snapshot_hash(value: object) -> str:
    if not isinstance(value, str) or not _SNAPSHOT_HASH_RE.fullmatch(value):
        raise ValueError("snapshot_hash must be a lowercase sha256 digest")
    return value


def _require_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _require_utc_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a timezone-aware UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware UTC timestamp") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be a timezone-aware UTC timestamp")
    return parsed


def _require_cents(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be integer euro cents")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _require_vat_rate(value: object, field: str) -> Literal[7, 19]:
    cents = _require_cents(value, field)
    if cents not in _VAT_RATES:
        raise ValueError("vat_rate_percent must be 7 or 19")
    return cast(Literal[7, 19], cents)


def _require_quantity(value: object, field: str) -> str:
    text = _require_exact_str(value, field)
    if not _QUANTITY_RE.fullmatch(text):
        raise ValueError(f"{field} must be a positive decimal string")
    if text == "0":
        raise ValueError(f"{field} must be a positive decimal string")
    return text


def _parse_recipient(payload: dict[str, object]) -> OfferSnapshotRecipient:
    _reject_unknown_keys(payload, _RECIPIENT_KEYS, "recipient")
    company_name = _require_exact_str(payload.get("company_name"), "company_name")
    contact_name = _require_exact_str(payload.get("contact_name"), "contact_name")
    if not company_name.strip() and not contact_name.strip():
        raise ValueError("recipient requires company_name or contact_name")
    if len(company_name) > MAX_SHORT_TEXT_LEN or len(contact_name) > MAX_SHORT_TEXT_LEN:
        raise ValueError("recipient name exceeds length limit")
    email = _require_exact_str(payload.get("email"), "email")
    if len(email) > MAX_EMAIL_LEN:
        raise ValueError("email exceeds length limit")
    postal_address = _require_exact_str(payload.get("postal_address"), "postal_address")
    if len(postal_address) > MAX_SHORT_TEXT_LEN:
        raise ValueError("postal_address exceeds length limit")
    return OfferSnapshotRecipient(
        company_name=company_name,
        contact_name=contact_name,
        email=email,
        postal_address=postal_address,
    )


def _parse_event(payload: dict[str, object]) -> OfferSnapshotEvent:
    _reject_unknown_keys(payload, _EVENT_KEYS, "event")
    guest_count_value = payload.get("guest_count")
    guest_count: int | None
    if guest_count_value is None:
        guest_count = None
    elif isinstance(guest_count_value, int) and not isinstance(guest_count_value, bool):
        if guest_count_value < 1:
            raise ValueError("guest_count must be a positive integer")
        guest_count = guest_count_value
    else:
        raise ValueError("guest_count must be a positive integer or null")
    return OfferSnapshotEvent(
        event_date=_require_date(payload.get("event_date"), "event_date"),
        time_window_text=_require_short_text(
            payload.get("time_window_text"), "time_window_text"
        ),
        location_text=_require_short_text(
            payload.get("location_text"), "location_text"
        ),
        guest_count=guest_count,
        planning_mode=validate_planning_mode(
            _require_exact_str(payload.get("planning_mode"), "planning_mode")
        ),
    )


def _parse_customer_text(payload: dict[str, object]) -> OfferSnapshotCustomerText:
    _reject_unknown_keys(payload, _CUSTOMER_TEXT_KEYS, "customer_text")
    return OfferSnapshotCustomerText(
        title=_require_short_text(payload.get("title"), "title"),
        introduction=_require_long_text(payload.get("introduction"), "introduction"),
        notes=_require_long_text(payload.get("notes"), "notes"),
    )


def _parse_payment_terms(payload: dict[str, object]) -> OfferSnapshotPaymentTerms:
    _reject_unknown_keys(payload, _PAYMENT_TERMS_KEYS, "payment_terms")
    return OfferSnapshotPaymentTerms(
        method=validate_payment_method(
            _require_exact_str(payload.get("method"), "payment_terms.method")
        ),
        customer_visible_text=_require_long_text(
            payload.get("customer_visible_text"), "payment_terms.customer_visible_text"
        ),
    )


def _parse_calculator(payload: dict[str, object]) -> OfferSnapshotCalculator:
    _reject_unknown_keys(payload, _CALCULATOR_KEYS, "calculator")
    return OfferSnapshotCalculator(
        name=_require_short_text(payload.get("name"), "calculator.name"),
        calculator_revision=_require_short_text(
            payload.get("calculator_revision"), "calculator.calculator_revision"
        ),
        catalog_revision=_require_short_text(
            payload.get("catalog_revision"), "calculator.catalog_revision"
        ),
        tax_revision=_require_short_text(
            payload.get("tax_revision"), "calculator.tax_revision"
        ),
    )


def _parse_variants(
    items: list[object], event: OfferSnapshotEvent, *, v2: bool = False
) -> tuple[OfferSnapshotVariant, ...]:
    if not MIN_VARIANTS <= len(items) <= MAX_VARIANTS:
        raise ValueError("variant count exceeds limit")
    variant_ids: set[str] = set()
    variants: list[OfferSnapshotVariant] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("variant must be an object")
        variant = _parse_variant(item, event, label=f"variants[{index}]", v2=v2)
        if variant.variant_id in variant_ids:
            raise ValueError("variant_id must be unique within snapshot")
        variant_ids.add(variant.variant_id)
        variants.append(variant)
    return tuple(variants)


def _parse_variant(
    payload: dict[str, object],
    event: OfferSnapshotEvent,
    *,
    label: str,
    v2: bool = False,
) -> OfferSnapshotVariant:
    _reject_unknown_keys(payload, _VARIANT_KEYS, label)
    positions = _parse_positions(
        _require_list(payload.get("positions"), f"{label}.positions"),
        event,
        label=f"{label}.positions",
        v2=v2,
    )
    totals = _parse_totals(
        _require_object(payload.get("totals"), f"{label}.totals"), label
    )
    _validate_variant_arithmetic(positions, totals)
    return OfferSnapshotVariant(
        variant_id=_require_uuid(payload.get("variant_id"), f"{label}.variant_id"),
        label=_require_short_text(payload.get("label"), f"{label}.label"),
        description=_require_long_text(
            payload.get("description"), f"{label}.description"
        ),
        positions=positions,
        totals=totals,
    )


def _parse_totals(payload: dict[str, object], label: str) -> OfferSnapshotVariantTotals:
    _reject_unknown_keys(payload, _TOTALS_KEYS, f"{label}.totals")
    return OfferSnapshotVariantTotals(
        net_cents=_require_cents(payload.get("net_cents"), f"{label}.totals.net_cents"),
        vat_7_base_cents=_require_cents(
            payload.get("vat_7_base_cents"), f"{label}.totals.vat_7_base_cents"
        ),
        vat_7_amount_cents=_require_cents(
            payload.get("vat_7_amount_cents"), f"{label}.totals.vat_7_amount_cents"
        ),
        vat_19_base_cents=_require_cents(
            payload.get("vat_19_base_cents"), f"{label}.totals.vat_19_base_cents"
        ),
        vat_19_amount_cents=_require_cents(
            payload.get("vat_19_amount_cents"), f"{label}.totals.vat_19_amount_cents"
        ),
        gross_cents=_require_cents(
            payload.get("gross_cents"), f"{label}.totals.gross_cents"
        ),
    )


def _parse_positions(
    items: list[object],
    event: OfferSnapshotEvent,
    *,
    label: str,
    v2: bool = False,
) -> tuple[OfferSnapshotPosition, ...]:
    if not MIN_POSITIONS_PER_VARIANT <= len(items) <= MAX_POSITIONS_PER_VARIANT:
        raise ValueError("position count exceeds limit")
    position_ids: set[str] = set()
    positions: list[OfferSnapshotPosition] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("position must be an object")
        position = _parse_position(item, label=f"{label}[{index}]", v2=v2)
        if position.position_id in position_ids:
            raise ValueError("position_id must be unique within variant")
        position_ids.add(position.position_id)
        positions.append(position)
    by_id = {position.position_id: position for position in positions}
    for position in positions:
        if position.quantity_mode == "per_person" and event.guest_count is None:
            raise ValueError("quantity_mode=per_person requires event.guest_count")
        if position.kind == "surcharge":
            if position.related_position_id is None:
                raise ValueError("surcharge requires related_position_id")
            base = by_id.get(position.related_position_id)
            if base is None or base.kind != "catalog":
                raise ValueError("surcharge must reference a catalog position")
            if position.vat_rate_percent != base.vat_rate_percent:
                raise ValueError(
                    "surcharge must use the same VAT rate as its base position"
                )
        elif position.related_position_id is not None:
            raise ValueError("related_position_id is only valid for surcharges")
        _validate_position_arithmetic(position, event)
    return tuple(positions)


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _validate_position_arithmetic(
    position: OfferSnapshotPosition, event: OfferSnapshotEvent
) -> None:
    effective_quantity = Decimal(position.quantity)
    if position.quantity_mode == "per_person":
        if event.guest_count is None:
            raise ValueError("quantity_mode=per_person requires event.guest_count")
        effective_quantity *= Decimal(event.guest_count)

    expected_net = _round_half_up(Decimal(position.unit_net_cents) * effective_quantity)
    if position.net_total_cents != expected_net:
        raise ValueError("offer snapshot position net total mismatch")

    expected_vat = _round_half_up(
        Decimal(position.net_total_cents)
        * Decimal(position.vat_rate_percent)
        / Decimal(100)
    )
    if position.vat_amount_cents != expected_vat:
        raise ValueError("offer snapshot position VAT mismatch")

    if (
        position.gross_total_cents
        != position.net_total_cents + position.vat_amount_cents
    ):
        raise ValueError("offer snapshot position gross total mismatch")


def _validate_variant_arithmetic(
    positions: tuple[OfferSnapshotPosition, ...],
    totals: OfferSnapshotVariantTotals,
) -> None:
    net_cents = sum(position.net_total_cents for position in positions)
    vat_7_positions = tuple(
        position for position in positions if position.vat_rate_percent == 7
    )
    vat_19_positions = tuple(
        position for position in positions if position.vat_rate_percent == 19
    )
    vat_7_base_cents = sum(position.net_total_cents for position in vat_7_positions)
    vat_7_amount_cents = sum(position.vat_amount_cents for position in vat_7_positions)
    vat_19_base_cents = sum(position.net_total_cents for position in vat_19_positions)
    vat_19_amount_cents = sum(
        position.vat_amount_cents for position in vat_19_positions
    )
    gross_cents = sum(position.gross_total_cents for position in positions)

    if totals.net_cents != net_cents:
        raise ValueError("offer snapshot net total mismatch")
    if totals.vat_7_base_cents != vat_7_base_cents:
        raise ValueError("offer snapshot 7% VAT base mismatch")
    if totals.vat_7_amount_cents != vat_7_amount_cents:
        raise ValueError("offer snapshot 7% VAT amount mismatch")
    if totals.vat_19_base_cents != vat_19_base_cents:
        raise ValueError("offer snapshot 19% VAT base mismatch")
    if totals.vat_19_amount_cents != vat_19_amount_cents:
        raise ValueError("offer snapshot 19% VAT amount mismatch")
    if totals.gross_cents != gross_cents:
        raise ValueError("offer snapshot gross total mismatch")
    if (
        totals.gross_cents
        != totals.net_cents + totals.vat_7_amount_cents + totals.vat_19_amount_cents
    ):
        raise ValueError("offer snapshot gross arithmetic mismatch")


def _parse_position(
    payload: dict[str, object], *, label: str, v2: bool = False
) -> OfferSnapshotPosition:
    _reject_unknown_keys(payload, _POSITION_KEYS_V2 if v2 else _POSITION_KEYS, label)
    kind_value = _require_exact_str(payload.get("kind"), f"{label}.kind")
    if kind_value not in _POSITION_KINDS:
        raise ValueError("invalid position kind")
    kind = cast(SnapshotPositionKind, kind_value)
    quantity_mode_value = _require_exact_str(
        payload.get("quantity_mode"), f"{label}.quantity_mode"
    )
    if quantity_mode_value not in _QUANTITY_MODES:
        raise ValueError("invalid quantity_mode")
    quantity_mode = cast(SnapshotQuantityMode, quantity_mode_value)
    related_raw = payload.get("related_position_id")
    related_position_id: str | None
    if related_raw is None:
        related_position_id = None
    else:
        related_position_id = _require_uuid(related_raw, f"{label}.related_position_id")
    catalog_raw = payload.get("catalog_item_id")
    catalog_item_id: str | None
    allergens: tuple[str, ...] | None = None
    vegan: bool | None = None
    vegetarian: bool | None = None
    if v2 and kind == "catalog":
        if catalog_raw is None:
            raise ValueError("catalog position requires catalog_item_id")
        catalog_item_id = _require_catalog_item_id(
            catalog_raw, f"{label}.catalog_item_id"
        )
        allergens_raw = payload.get("allergens")
        if allergens_raw is None:
            raise ValueError("catalog position requires allergens")
        allergens = _parse_allergens(allergens_raw, f"{label}.allergens")
        vegan = _optional_bool(payload.get("vegan"), f"{label}.vegan")
        vegetarian = _optional_bool(payload.get("vegetarian"), f"{label}.vegetarian")
    else:
        if catalog_raw is None:
            catalog_item_id = None
        else:
            catalog_item_id = _optional_short_text(
                catalog_raw, f"{label}.catalog_item_id"
            )
        if v2:
            allergens_raw = payload.get("allergens")
            if allergens_raw is not None:
                allergens = _parse_allergens(allergens_raw, f"{label}.allergens")
            vegan = _optional_bool(payload.get("vegan"), f"{label}.vegan")
            vegetarian = _optional_bool(
                payload.get("vegetarian"), f"{label}.vegetarian"
            )
    return OfferSnapshotPosition(
        position_id=_require_uuid(payload.get("position_id"), f"{label}.position_id"),
        kind=kind,
        catalog_item_id=catalog_item_id,
        name=_require_short_text(payload.get("name"), f"{label}.name"),
        description=_optional_long_text(
            payload.get("description"), f"{label}.description"
        ),
        composition=_optional_long_text(
            payload.get("composition"), f"{label}.composition"
        ),
        quantity_mode=quantity_mode,
        quantity=_require_quantity(payload.get("quantity"), f"{label}.quantity"),
        unit_label=_require_short_text(
            payload.get("unit_label"), f"{label}.unit_label"
        ),
        unit_net_cents=_require_cents(
            payload.get("unit_net_cents"), f"{label}.unit_net_cents"
        ),
        net_total_cents=_require_cents(
            payload.get("net_total_cents"), f"{label}.net_total_cents"
        ),
        vat_rate_percent=_require_vat_rate(
            payload.get("vat_rate_percent"), f"{label}.vat_rate_percent"
        ),
        vat_amount_cents=_require_cents(
            payload.get("vat_amount_cents"), f"{label}.vat_amount_cents"
        ),
        gross_total_cents=_require_cents(
            payload.get("gross_total_cents"), f"{label}.gross_total_cents"
        ),
        notes=_optional_long_text(payload.get("notes"), f"{label}.notes"),
        related_position_id=related_position_id,
        allergens=allergens,
        vegan=vegan,
        vegetarian=vegetarian,
    )


def _parse_allergens(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return validate_allergen_codes([str(item) for item in value])


def _optional_bool(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value

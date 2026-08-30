"""Remote Core backend for the office panel (Proxmox pack, Phase 2).

The panel keeps its existing rendering code.  This adapter exposes the small
repository/service surface that rendering already consumes, while every write
is sent to the frozen Core Office API.  It never opens ``core.db``.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, NoReturn, cast
from urllib.parse import quote, urlencode, urlparse

from catering_system.domain.catalog import (
    CatalogDish,
    CatalogDishCreatePayload,
    PricingUnit,
    validate_allergen_codes,
    validate_pricing_unit,
)
from catering_system.domain.chat import (
    CHAT_REFERENCE_TYPE_SET,
    CHAT_THREAD_TYPE_SET,
)
from catering_system.domain.customer_document_eligibility import (
    DOCUMENT_BLOCKER_CODES,
    DocumentBlocker,
    DocumentBlockerCode,
)
from catering_system.domain.customer_document_preview import CustomerDocumentPreview
from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerAddress,
    CustomerDocumentCommercialReference,
    CustomerDocumentEvent,
    CustomerDocumentPosition,
    CustomerDocumentRecipient,
    CustomerDocumentWarning,
    DocumentType,
)
from catering_system.domain.inquiry import (
    PLANNING_MODE_SET,
    FulfillmentMode,
    Inquiry,
    InquiryOfficeNextAction,
    PlanningMode,
    set_inquiry_fulfillment_mode,
    validate_call_verification_status,
    validate_crm_stage,
    validate_customer_linkage,
    validate_fulfillment_mode,
    validate_planning_mode,
)
from catering_system.domain.inquiry_contact_completeness import (
    complete_inquiry_contact_information,
)
from catering_system.domain.inquiry_customer_snapshot import (
    DeliveryAddressMode,
    customer_address_to_mapping,
    customer_snapshot_from_mapping,
    customer_snapshot_to_mapping,
    set_inquiry_customer_addresses,
    snapshot_from_structured_contact,
)
from catering_system.domain.inquiry_offer_preparation import (
    InquiryOfferPreparationBlocker,
)
from catering_system.domain.manual_task import (
    ManualTask,
    validate_manual_task,
    validate_manual_task_priority,
    validate_manual_task_subject_type,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_confirmation_outbound import FakeOutboxMessage
from catering_system.domain.order_operational_context import (
    OrderVersionOperationalContextSnapshot,
)
from catering_system.domain.order_payment_reminder import (
    PAYMENT_METHODS,
    OrderPaymentReminder,
    PaymentMethod,
    PaymentReminderView,
    validate_payment_method,
)
from catering_system.domain.ready_to_send import ReadyToSendEvaluation
from catering_system.services.buffet_cards_service import BuffetCard, BuffetCardsView
from catering_system.services.inquiry_service import validate_inquiry_source
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentEligibility,
    OrderConfirmationDocumentSummary,
)
from catering_system.services.order_confirmation_outbound_service import (
    OutboundSendEligibility,
    OutboundSendSummary,
)
from catering_system.services.order_print_projection_service import (
    OrderPrintProjection,
    PrintChangeLine,
    PrintCommercialBlock,
    PrintCustomerBlock,
    PrintEventBlock,
    PrintFlagsBlock,
    PrintPositionLine,
)

_MAX_RESPONSE_BYTES = 512 * 1024
_READ_TIMEOUT_SECONDS = 3
_COMMAND_TIMEOUT_SECONDS = 5
_PAGE_SIZE = 100

_INQUIRY_SUMMARY_KEYS = frozenset(
    {
        "inquiry_id",
        "event_date",
        "created_at",
        "updated_at",
        "inquiry_source",
        "crm_stage",
        "time_window_text",
        "location_text",
        "guest_count_estimate",
        "planning_mode",
        "call_verification_required",
        "call_verification_status",
        "fulfillment_mode",
    }
)
_INQUIRY_LIST_KEYS = _INQUIRY_SUMMARY_KEYS | {
    "intake_subject",
    "linked_order_id",
    "orders_total_count",
}
# Optional typed list-row field (INQUIRY_CONTACT_COMPLETENESS_V1 §10) — the
# pre-completeness API contract has no snapshot on list rows.
_INQUIRY_LIST_OPTIONAL_KEYS = frozenset({"customer_snapshot"})
_INQUIRY_DETAIL_KEYS = _INQUIRY_LIST_KEYS | {
    "customer_linkage",
    "intake_message",
    "intake_summary",
    "intake_external_ref",
    "allows_conversion",
    "next_action",
    "orders",
    "orders_truncated",
    "offer_prefill",
}
_INQUIRY_DETAIL_OPTIONAL_KEYS = frozenset(
    {
        "offer",
        "customer_id",
        "customer_snapshot",
        # INQUIRY_CONTACT_COMPLETENESS_V1 §10 — typed optional read fields so
        # this client stays compatible with the pre-completeness API contract.
        "contact_completeness",
        "missing_contact_fields",
        "contact_completion_allowed",
        "offer_preparation_blockers",
    }
)
_CONTACT_COMPLETENESS_VALUES = frozenset(
    {"complete", "missing_email", "missing_phone", "missing_email_and_phone"}
)
_CONTACT_FIELD_VALUES = frozenset({"email", "phone"})
_INQUIRY_OFFER_PREPARATION_BLOCKERS = frozenset(
    {
        "inquiry_rejected",
        "inquiry_call_verification_unsatisfied",
        "inquiry_contact_missing_email",
        "inquiry_contact_missing_phone",
        "inquiry_contact_missing_email_and_phone",
        "active_order_exists",
        "offer_already_exists",
    }
)
_INQUIRY_OFFER_KEYS = frozenset({"offer_id", "offer_version_id", "commercial_state"})
_INQUIRY_OFFER_OPTIONAL_KEYS = frozenset({"accepted_variant_id", "acceptance_id"})
_INQUIRY_NEXT_ACTIONS = frozenset(
    {
        "verify",
        "prepare-offer",
        "prepare-next-version",
        "convert-accepted",
        "offer-pending",
    }
)
_OFFER_COMMERCIAL_STATES = frozenset(
    {
        "Prepared",
        "Sent",
        "Accepted",
        "Converted",
        "Rejected",
        "Withdrawn",
        "Superseded",
        "Expired",
    }
)
_ORDER_SUMMARY_KEYS = frozenset(
    {
        "order_id",
        "source_inquiry_id",
        "created_at",
        "updated_at",
        "candidate_order_version_id",
        "effective_order_version_id",
        "cancelled_at",
    }
)
_ORDER_LIST_KEYS = _ORDER_SUMMARY_KEYS | {
    "ready",
    "blocker_reason",
    "next_action",
    "operational_pause_active",
}
_ORDER_DETAIL_KEYS = _ORDER_SUMMARY_KEYS | {
    "ready_to_send",
    "version_change",
    "operational_pause",
    "payment_reminder",
    "confirmation_document",
    "versions",
    "versions_total_count",
    "versions_truncated",
}
_OPERATIONAL_PAUSE_INACTIVE_KEYS = frozenset({"active", "latest_pause_event_id"})
_OPERATIONAL_PAUSE_ACTIVE_KEYS = frozenset(
    {
        "active",
        "current_pause_event_id",
        "latest_pause_event_id",
        "reason_code",
        "note",
        "paused_at",
        "actor_reference",
    }
)
_ORDER_TOP_PAUSE_KEYS = frozenset(
    {"operational_pause_active", "operational_pause_reason_code"}
)
_VERSION_KEYS = frozenset(
    {
        "order_version_id",
        "order_id",
        "version_number",
        "created_at",
        "event_date",
        "time_window_text",
        "location_text",
        "guest_count_estimate",
        "planning_mode",
        "kitchen_print_confirmed_at",
        "parent_order_version_id",
        "created_by",
        "change_reason",
        "changed_fields",
        "superseded",
    }
)
_ERROR_CODES_BY_STATUS: dict[int, frozenset[str]] = {
    400: frozenset({"invalid_request"}),
    401: frozenset({"unauthorized"}),
    403: frozenset({"forbidden"}),
    404: frozenset({"not_found"}),
    405: frozenset({"method_not_allowed"}),
    409: frozenset(
        {
            "command_id_conflict",
            "stale_state",
            "already_converted",
            "external_ref_conflict",
            "conversion_already_exists",
            "sent_evidence_exists",
            "acceptance_already_exists",
            "rejection_evidence_exists",
            "withdrawal_evidence_exists",
            "order_already_paused",
            "order_not_paused",
            "already_exists",
        }
    ),
    413: frozenset({"body_too_large"}),
    415: frozenset({"unsupported_media_type"}),
    422: frozenset(
        {
            "active_order_crm_stage_conflict",
            "inquiry_rejected",
            "verification_gate_blocked",
            "order_cancelled",
            "kitchen_print_not_confirmed",
            "version_not_owned",
            "invalid_payment_reminder",
            "conversion_blocked",
            "accepted_offer_required",
            "offer_blocks_conversion",
            "sent_recording_blocked",
            "invalid_sent_evidence",
            "acceptance_blocked",
            "invalid_variant",
            "invalid_acceptance_evidence",
            "rejection_blocked",
            "withdrawal_blocked",
            "invalid_rejection_evidence",
            "invalid_withdrawal_evidence",
            "order_version_not_current_candidate",
            "operational_context_missing",
            "order_delete_confirmation_mismatch",
            "order_delete_name_unavailable",
            "validation_error",
            # Issue #39: the three document blockers. All are real Office API
            # business errors that were missing here, so the status whitelist
            # refused them and they surfaced as 502 invalid_response instead
            # of the 422 the operator needs to see.
            "offer_document_blocked",
            "confirmation_document_blocked",
            "order_not_ready_to_send",
            "invalid_chat_thread",
            "invalid_chat_message",
            "invalid_chat_mention",
            "invalid_chat_reference",
            "invalid_chat_reply",
        }
    ),
    500: frozenset({"internal"}),
    503: frozenset({"core_busy"}),
}

# Issue #39: the error contracts that may carry a `reasons` list, keyed by
# status. Deliberately narrower than _ERROR_CODES_BY_STATUS — `reasons` is
# not a general-purpose field, it is part of these three blocker contracts
# only. Every other status/code pair must still arrive as a bare
# {"error": ...} body, so an unexpected `reasons` anywhere else is a
# contract violation rather than something to tolerate.
#
# `confirmation_document_blocked` has both reasons-bearing and bare paths in
# the API, so it appears here *and* must keep working without `reasons`.
_ERROR_CODES_WITH_REASONS_BY_STATUS: dict[int, frozenset[str]] = {
    422: frozenset(
        {
            "offer_document_blocked",
            "confirmation_document_blocked",
            "order_not_ready_to_send",
        }
    ),
}


class RemoteCoreError(ValueError):
    """Stable remote failure; never contains response payload or bearer data."""

    def __init__(self, status: int, code: str, *, unavailable: bool = False) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.unavailable = unavailable


@dataclass(frozen=True)
class InquiryDetailMeta:
    orders_total_count: int
    orders_truncated: bool
    next_action: InquiryOfficeNextAction | None = None
    offer: dict[str, object] | None = None
    offer_preparation_blockers: tuple[InquiryOfferPreparationBlocker, ...] = ()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _bad_response() -> NoReturn:
    raise RemoteCoreError(502, "invalid_response", unavailable=True)


_CONTENT_DISPOSITION_FILENAME = re.compile(r'filename="([^"]+)"')


def _filename_from_content_disposition(value: str | None) -> str | None:
    if value is None:
        return None
    match = _CONTENT_DISPOSITION_FILENAME.search(value)
    return match.group(1) if match else None


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        _bad_response()
    return cast(dict[str, object], value)


def _optional_inquiry_next_action(value: object) -> InquiryOfficeNextAction | None:
    if value is None:
        return None
    action = _str(value)
    if action not in _INQUIRY_NEXT_ACTIONS:
        _bad_response()
    return cast(InquiryOfficeNextAction, action)


def _offer_preparation_blockers(
    value: object,
) -> tuple[InquiryOfferPreparationBlocker, ...]:
    reasons: list[InquiryOfferPreparationBlocker] = []
    for raw_reason in _list(value):
        if (
            not isinstance(raw_reason, str)
            or raw_reason not in _INQUIRY_OFFER_PREPARATION_BLOCKERS
            or raw_reason in reasons
        ):
            _bad_response()
        reasons.append(cast(InquiryOfferPreparationBlocker, raw_reason))
    return tuple(reasons)


def _inquiry_offer_projection(value: object) -> dict[str, object]:
    row = _dict(value)
    keys = set(row)
    allowed = _INQUIRY_OFFER_KEYS | _INQUIRY_OFFER_OPTIONAL_KEYS
    if not _INQUIRY_OFFER_KEYS <= keys <= allowed:
        _bad_response()
    _uuid4(row["offer_id"])
    _uuid4(row["offer_version_id"])
    state = _str(row["commercial_state"])
    if state not in _OFFER_COMMERCIAL_STATES:
        _bad_response()
    if "accepted_variant_id" in row:
        _uuid4(row["accepted_variant_id"])
    if "acceptance_id" in row:
        _uuid4(row["acceptance_id"])
    return row


def _exact(data: Mapping[str, object], keys: frozenset[str] | set[str]) -> None:
    if set(data) != set(keys):
        _bad_response()


def _error_body_code(parsed: Mapping[str, object], status: int) -> str:
    """Issue #39: read the error code out of an Office API error body.

    Most errors are a bare `{"error": "<code>"}`. Three 422 blocker
    contracts also attach a `reasons` list, and validating every body with
    an exact `{"error"}` key set rejected those valid responses, turning a
    real business error into 502 invalid_response.

    `reasons` is accepted only for the status/code pairs in
    _ERROR_CODES_WITH_REASONS_BY_STATUS — it is part of those contracts, not
    a field any error may carry. On any other pair its presence is a
    contract violation. When it is allowed it must still be a list of
    strings, so a malformed one fails closed rather than being carried
    along as trusted data. Unknown keys are refused as before.
    """
    keys = set(parsed)
    if not ({"error"} <= keys <= {"error", "reasons"}):
        _bad_response()
    code = _str(parsed["error"])
    if "reasons" in parsed:
        allowed = _ERROR_CODES_WITH_REASONS_BY_STATUS.get(status, frozenset())
        if code not in allowed:
            _bad_response()
        for reason in _list(parsed["reasons"]):
            _str(reason)
    return code


def _operational_pause(value: object) -> dict[str, object]:
    row = _dict(value)
    keys = set(row)
    if keys == _OPERATIONAL_PAUSE_INACTIVE_KEYS:
        if _bool(row["active"]):
            _bad_response()
        _optional_uuid4(row["latest_pause_event_id"])
        return row
    if keys != _OPERATIONAL_PAUSE_ACTIVE_KEYS:
        _bad_response()
    if not _bool(row["active"]):
        _bad_response()
    _uuid4(row["current_pause_event_id"])
    _uuid4(row["latest_pause_event_id"])
    _str(row["reason_code"])
    _optional_str(row["note"])
    _datetime(row["paused_at"])
    _str(row["actor_reference"])
    return row


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        _bad_response()
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        _bad_response()
    return value


def _uuid4(value: object) -> str:
    raw = _str(value)
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        _bad_response()
    if parsed.version != 4 or str(parsed) != raw:
        _bad_response()
    return raw


def _catalog_item_id(value: object) -> str:
    raw = _str(value)
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        _bad_response()
    if parsed.version not in {4, 5} or str(parsed) != raw:
        _bad_response()
    return raw


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _str(value)


def _optional_uuid4(value: object) -> str | None:
    if value is None:
        return None
    return _uuid4(value)


def _bool(value: object) -> bool:
    if not isinstance(value, bool):
        _bad_response()
    return value


def _int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _bad_response()
    return value


def _nonnegative_int(value: object) -> int:
    parsed = _int(value)
    if parsed < 0:
        _bad_response()
    return parsed


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int(value)


def _optional_pricing_unit(value: object) -> PricingUnit | None:
    """CATALOG_ADMIN_COMPLETION_V1A review fix: fail-closed against the
    closed pricing_unit set, not just a loose string type-check — NULL
    stays valid for legacy rows, but an unknown non-null value (a tampered
    or buggy Office API response) is rejected as an invalid contract."""
    if value is None:
        return None
    try:
        return validate_pricing_unit(_str(value))
    except ValueError:
        _bad_response()


def _catalog_dish_from_detail(detail: dict[str, object]) -> CatalogDish:
    """CATALOG_ADMIN_REMOTE_CLIENT_V1: builds and returns a real, fully
    domain-validated CatalogDish from an already-structurally-checked
    catalog_dish_detail() payload — construction itself is the strict
    response validation (UUID shape, non-negative price, known allergen
    codes, closed category/pricing_unit/vat_rate_percent sets, timezone-
    aware timestamps). Any mismatch — from either the Office API or a
    tampered response — surfaces as the same _bad_response() every other
    contract violation in this file does."""
    try:
        return CatalogDish(
            dish_id=_uuid4(detail["dish_id"]),
            name=_str(detail["name"]),
            description=_optional_str(detail.get("description")),
            composition=_optional_str(detail.get("composition")),
            notes=_optional_str(detail.get("notes")),
            current_unit_net_cents=_nonnegative_int(detail["current_unit_net_cents"]),
            allergens=validate_allergen_codes(
                [_str(code) for code in _list(detail["allergens"])]
            ),
            active=_bool(detail["active"]),
            created_at=_datetime(detail["created_at"]),
            updated_at=_datetime(detail["updated_at"]),
            category=_optional_str(detail.get("category")),
            pricing_unit=_optional_pricing_unit(detail.get("pricing_unit")),
            vat_rate_percent=_optional_int(detail.get("vat_rate_percent")),
        )
    except ValueError:
        _bad_response()


_CATALOG_PRICE_HISTORY_KEYS = frozenset(
    {
        "entry_id",
        "dish_id",
        "old_unit_net_cents",
        "new_unit_net_cents",
        "old_price_display",
        "new_price_display",
        "changed_at",
        "changed_by",
        "effective_from",
    }
)


def _catalog_price_history_entry(entry: dict[str, object], *, dish_id: str) -> None:
    """REMOTE_CATALOG_PRICE_HISTORY_CONTRACT_FIX_V1 (issue #37).

    The key set previously omitted `old_price_display`/`new_price_display`,
    which `views._price_history_shape` has always emitted, so `_exact()`
    rejected every dish that had ever had its price changed — a dish opened
    fine until the first price edit, then returned 502 invalid_response.

    The display strings are read, never recomputed: they are the Office
    API's rendering (`format_catalog_price_eur`), and re-deriving them here
    would put a second, silently diverging formatter in the client.

    `old_unit_net_cents` and `old_price_display` are both nullable and null
    *together* — the first entry of a dish that had no previous price. That
    pairing is an invariant of the producer, so a response where only one of
    the two is null is malformed and rejected rather than guessed at.
    """
    _exact(entry, _CATALOG_PRICE_HISTORY_KEYS)
    _uuid4(entry["entry_id"])
    if _uuid4(entry["dish_id"]) != dish_id:
        _bad_response()
    old_cents = _optional_int(entry["old_unit_net_cents"])
    _nonnegative_int(entry["new_unit_net_cents"])
    old_display = _optional_str(entry["old_price_display"])
    if (old_cents is None) != (old_display is None):
        _bad_response()
    _str(entry["new_price_display"])
    _datetime(entry["changed_at"])
    _str(entry["changed_by"])
    if entry["effective_from"] is not None:
        _date(entry["effective_from"])


def _guest_count(value: object) -> int | None:
    parsed = _optional_int(value)
    if parsed is not None and not 1 <= parsed <= 2000:
        _bad_response()
    return parsed


def _date(value: object) -> date:
    try:
        return date.fromisoformat(_str(value))
    except ValueError:
        _bad_response()


def _datetime(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(_str(value))
    except ValueError:
        _bad_response()
    if parsed.tzinfo is None:
        _bad_response()
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _datetime(value)


def _inquiry(
    data: Mapping[str, object], *, list_row: bool = False, detail: bool = False
) -> Inquiry:
    if detail:
        keys = set(data)
        allowed = _INQUIRY_DETAIL_KEYS | _INQUIRY_DETAIL_OPTIONAL_KEYS
        if not _INQUIRY_DETAIL_KEYS <= keys <= allowed:
            _bad_response()
    elif list_row:
        keys = set(data)
        allowed = _INQUIRY_LIST_KEYS | _INQUIRY_LIST_OPTIONAL_KEYS
        if not _INQUIRY_LIST_KEYS <= keys <= allowed:
            _bad_response()
    else:
        _exact(data, _INQUIRY_SUMMARY_KEYS)
    linkage_raw = data.get("customer_linkage", {})
    try:
        linkage = validate_customer_linkage(_dict(linkage_raw))
        source = validate_inquiry_source(_str(data["inquiry_source"]))
        crm_stage = validate_crm_stage(_str(data["crm_stage"]))
        planning_mode = validate_planning_mode(_str(data["planning_mode"]))
        verification = validate_call_verification_status(
            _str(data["call_verification_status"])
        )
        fulfillment_mode = validate_fulfillment_mode(_str(data["fulfillment_mode"]))
    except (KeyError, TypeError, ValueError):
        _bad_response()
    return Inquiry(
        inquiry_id=_uuid4(data.get("inquiry_id")),
        event_date=_date(data.get("event_date")),
        created_at=_datetime(data.get("created_at")),
        updated_at=_datetime(data.get("updated_at")),
        inquiry_source=source,
        crm_stage=crm_stage,
        customer_linkage=linkage,
        time_window_text=_str(data.get("time_window_text")),
        location_text=_str(data.get("location_text")),
        guest_count_estimate=_guest_count(data.get("guest_count_estimate")),
        planning_mode=planning_mode,
        call_verification_required=_bool(data.get("call_verification_required")),
        call_verification_status=verification,
        fulfillment_mode=fulfillment_mode,
        intake_subject=_optional_str(data.get("intake_subject")),
        intake_message=_optional_str(data.get("intake_message")),
        intake_summary=_optional_str(data.get("intake_summary")),
        intake_external_ref=_optional_str(data.get("intake_external_ref")),
        customer_id=_optional_str(data.get("customer_id")),
        customer_snapshot=customer_snapshot_from_mapping(
            _dict(data["customer_snapshot"])
            if isinstance(data.get("customer_snapshot"), dict)
            else None
        ),
    )


def _order(
    data: Mapping[str, object], *, list_row: bool = False, detail: bool = False
) -> Order:
    _exact(
        data,
        _ORDER_DETAIL_KEYS
        if detail
        else (_ORDER_LIST_KEYS if list_row else _ORDER_SUMMARY_KEYS),
    )
    return Order(
        order_id=_uuid4(data.get("order_id")),
        source_inquiry_id=_uuid4(data.get("source_inquiry_id")),
        created_at=_datetime(data.get("created_at")),
        updated_at=_datetime(data.get("updated_at")),
        candidate_order_version_id=_optional_uuid4(
            data.get("candidate_order_version_id")
        ),
        effective_order_version_id=_optional_uuid4(
            data.get("effective_order_version_id")
        ),
        cancelled_at=_optional_datetime(data.get("cancelled_at")),
    )


def _version(data: Mapping[str, object]) -> OrderVersion:
    _exact(data, _VERSION_KEYS)
    try:
        planning_mode = validate_planning_mode(_str(data["planning_mode"]))
    except (KeyError, ValueError):
        _bad_response()
    _bool(data.get("superseded"))
    return OrderVersion(
        order_version_id=_uuid4(data.get("order_version_id")),
        order_id=_uuid4(data.get("order_id")),
        version_number=_nonnegative_int(data.get("version_number")),
        created_at=_datetime(data.get("created_at")),
        event_date=_date(data.get("event_date")),
        time_window_text=_str(data.get("time_window_text")),
        location_text=_str(data.get("location_text")),
        guest_count_estimate=_guest_count(data.get("guest_count_estimate")),
        planning_mode=planning_mode,
        kitchen_print_confirmed_at=_optional_datetime(
            data.get("kitchen_print_confirmed_at")
        ),
        parent_order_version_id=_optional_uuid4(data.get("parent_order_version_id")),
        created_by=_optional_str(data.get("created_by")),
        change_reason=_optional_str(data.get("change_reason")),
        changed_fields=tuple(
            _str(value) for value in _list(data.get("changed_fields"))
        ),
    )


_PRINT_POSITION_KEYS = frozenset(
    {
        "position_id",
        "kind",
        "name",
        "description",
        "composition",
        "notes",
        "quantity_display",
        "unit_label",
    }
)
_PRINT_EVENT_KEYS = frozenset(
    {
        "order_id",
        "order_version_id",
        "version_number",
        "event_date",
        "time_window_text",
        "location_text",
        "guest_count_estimate",
        "planning_mode",
        "kitchen_print_confirmed_at",
        "order_cancelled_at",
        "is_candidate",
        "is_effective",
        "change_reason",
        "changed_fields",
        "change_lines",
    }
)
_PRINT_CHANGE_LINE_KEYS = frozenset({"label", "before", "after"})
_PRINT_COMMERCIAL_KEYS = frozenset(
    {
        "source",
        "offer_id",
        "offer_version_id",
        "accepted_variant_id",
        "variant_label",
        "payment_method",
        "gross_total_cents",
        "positions",
    }
)
_PRINT_CUSTOMER_KEYS = frozenset(
    {
        "company_name",
        "contact_name",
        "phone",
        "delivery_address_lines",
        "fulfillment_mode",
    }
)
_PRINT_FLAGS_KEYS = frozenset(
    {
        "intent",
        "is_preview",
        "is_final_allowed",
        "is_stale",
        "watermark",
    }
)
_PRINT_PROJECTION_KEYS = frozenset({"event", "commercial", "customer", "flags"})


def _print_position_line(data: Mapping[str, object]) -> PrintPositionLine:
    _exact(data, _PRINT_POSITION_KEYS)
    return PrintPositionLine(
        position_id=_uuid4(data["position_id"]),
        kind=_str(data["kind"]),
        name=_str(data["name"]),
        description=_optional_str(data.get("description")),
        composition=_optional_str(data.get("composition")),
        notes=_optional_str(data.get("notes")),
        quantity_display=_optional_str(data.get("quantity_display")),
        unit_label=_optional_str(data.get("unit_label")),
    )


def _print_change_line(data: Mapping[str, object]) -> PrintChangeLine:
    _exact(data, _PRINT_CHANGE_LINE_KEYS)
    return PrintChangeLine(
        label=_str(data["label"]),
        before=_str(data["before"]),
        after=_str(data["after"]),
    )


def _print_projection(data: Mapping[str, object]) -> OrderPrintProjection:
    _exact(data, _PRINT_PROJECTION_KEYS)
    event_data = _dict(data["event"])
    _exact(event_data, _PRINT_EVENT_KEYS)
    commercial_data = _dict(data["commercial"])
    _exact(commercial_data, _PRINT_COMMERCIAL_KEYS)
    customer_data = _dict(data["customer"])
    _exact(customer_data, _PRINT_CUSTOMER_KEYS)
    flags_data = _dict(data["flags"])
    _exact(flags_data, _PRINT_FLAGS_KEYS)
    source = _str(commercial_data["source"])
    if source not in {"offer_conversion", "none"}:
        _bad_response()
    intent = _str(flags_data["intent"])
    if intent not in {"preview", "change_preview", "final"}:
        _bad_response()
    watermark = flags_data.get("watermark")
    if watermark is not None and watermark not in {
        "ENTWURF",
        "VERALTET",
        "ÄNDERUNG – NOCH NICHT WIRKSAM",
    }:
        _bad_response()
    try:
        planning_mode = validate_planning_mode(_str(event_data["planning_mode"]))
        fulfillment_mode = validate_fulfillment_mode(
            _str(customer_data["fulfillment_mode"])
        )
    except ValueError:
        _bad_response()
    payment_method_raw = commercial_data.get("payment_method")
    try:
        payment_method = (
            None
            if payment_method_raw is None
            else validate_payment_method(_str(payment_method_raw))
        )
    except ValueError:
        _bad_response()
    return OrderPrintProjection(
        event=PrintEventBlock(
            order_id=_uuid4(event_data["order_id"]),
            order_version_id=_uuid4(event_data["order_version_id"]),
            version_number=_nonnegative_int(event_data["version_number"]),
            event_date=_date(event_data["event_date"]),
            time_window_text=_str(event_data["time_window_text"]),
            location_text=_str(event_data["location_text"]),
            guest_count_estimate=_guest_count(event_data.get("guest_count_estimate")),
            planning_mode=planning_mode,
            kitchen_print_confirmed_at=_optional_datetime(
                event_data.get("kitchen_print_confirmed_at")
            ),
            order_cancelled_at=_optional_datetime(event_data.get("order_cancelled_at")),
            is_candidate=_bool(event_data["is_candidate"]),
            is_effective=_bool(event_data["is_effective"]),
            change_reason=_optional_str(event_data.get("change_reason")),
            changed_fields=tuple(
                _str(value) for value in _list(event_data.get("changed_fields"))
            ),
            change_lines=tuple(
                _print_change_line(_dict(value))
                for value in _list(event_data["change_lines"])
            ),
        ),
        commercial=PrintCommercialBlock(
            source=source,  # type: ignore[arg-type]
            offer_id=_optional_uuid4(commercial_data.get("offer_id")),
            offer_version_id=_optional_uuid4(commercial_data.get("offer_version_id")),
            accepted_variant_id=_optional_uuid4(
                commercial_data.get("accepted_variant_id")
            ),
            variant_label=_optional_str(commercial_data.get("variant_label")),
            payment_method=payment_method,
            gross_total_cents=_optional_int(commercial_data.get("gross_total_cents")),
            positions=tuple(
                _print_position_line(_dict(item))
                for item in _list(commercial_data["positions"])
            ),
        ),
        customer=PrintCustomerBlock(
            company_name=_optional_str(customer_data.get("company_name")),
            contact_name=_optional_str(customer_data.get("contact_name")),
            phone=_optional_str(customer_data.get("phone")),
            delivery_address_lines=tuple(
                _str(line) for line in _list(customer_data["delivery_address_lines"])
            ),
            fulfillment_mode=fulfillment_mode,
        ),
        flags=PrintFlagsBlock(
            intent=intent,  # type: ignore[arg-type]
            is_preview=_bool(flags_data["is_preview"]),
            is_final_allowed=_bool(flags_data["is_final_allowed"]),
            is_stale=_bool(flags_data["is_stale"]),
            watermark=watermark,  # type: ignore[arg-type]
        ),
    )


_BUFFET_CARD_KEYS = frozenset(
    {
        "position_id",
        "name",
        "description",
        "composition",
        "notes",
    }
)
_BUFFET_CARDS_DATA_KEYS = frozenset(
    {
        "projection",
        "cards",
        "effective_version_number",
    }
)


def _buffet_card(data: Mapping[str, object]) -> BuffetCard:
    _exact(data, _BUFFET_CARD_KEYS)
    return BuffetCard(
        position_id=_uuid4(data["position_id"]),
        name=_str(data["name"]),
        description=_optional_str(data.get("description")),
        composition=_optional_str(data.get("composition")),
        notes=_optional_str(data.get("notes")),
    )


def _buffet_cards_view(data: Mapping[str, object]) -> BuffetCardsView:
    _exact(data, _BUFFET_CARDS_DATA_KEYS)
    effective = data.get("effective_version_number")
    if effective is not None and not isinstance(effective, int):
        _bad_response()
    return BuffetCardsView(
        projection=_print_projection(_dict(data["projection"])),
        cards=tuple(_buffet_card(_dict(item)) for item in _list(data["cards"])),
        effective_version_number=effective,
    )


def _next_action(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    action = _dict(value)
    _exact(action, {"action", "order_version_id"})
    name = _str(action["action"])
    if name not in {"print-confirm", "effective"}:
        _bad_response()
    return {"action": name, "order_version_id": _uuid4(action["order_version_id"])}


def _ready_evaluation(value: object, order_id: str) -> ReadyToSendEvaluation:
    evaluation = _dict(value)
    _exact(evaluation, {"ready", "reasons"})
    return ReadyToSendEvaluation(
        order_id=order_id,
        ready=_bool(evaluation["ready"]),
        reasons=tuple(_str(reason) for reason in _list(evaluation["reasons"])),
    )


_PAYMENT_REMINDER_KEYS = frozenset(
    {
        "order_id",
        "payment_method",
        "payment_method_label",
        "invoice_created",
        "invoice_number",
        "sent_on",
        "due_on",
        "paid_on",
        "cash_received",
        "quittung_printed",
        "invoice_state_label",
        "payment_state_label",
        "next_step",
        "next_step_due_on",
        "invoice_created_at",
        "invoice_created_by",
        "invoice_sent_recorded_at",
        "invoice_sent_recorded_by",
        "payment_reminder_sent_at",
        "payment_reminder_sent_by",
        "mahnung_sent_at",
        "mahnung_sent_by",
        "quittung_printed_at",
        "quittung_printed_by",
        "paid_recorded_at",
        "paid_recorded_by",
        "updated_at",
    }
)


def _payment_reminder(value: object, order_id: str) -> PaymentReminderView:
    data = _dict(value)
    _exact(data, _PAYMENT_REMINDER_KEYS)
    if _uuid4(data["order_id"]) != order_id:
        _bad_response()
    method_raw = data["payment_method"]
    try:
        method = (
            None if method_raw is None else validate_payment_method(_str(method_raw))
        )
    except ValueError:
        _bad_response()
    return PaymentReminderView(
        order_id=order_id,
        payment_method=method,
        payment_method_label=_str(data["payment_method_label"]),
        invoice_created=_bool(data["invoice_created"]),
        invoice_number=_optional_str(data["invoice_number"]),
        sent_on=None if data["sent_on"] is None else _date(data["sent_on"]),
        due_on=None if data["due_on"] is None else _date(data["due_on"]),
        paid_on=None if data["paid_on"] is None else _date(data["paid_on"]),
        cash_received=_bool(data["cash_received"]),
        quittung_printed=_bool(data["quittung_printed"]),
        invoice_state_label=_optional_str(data["invoice_state_label"]),
        payment_state_label=_str(data["payment_state_label"]),
        next_step=_optional_str(data["next_step"]),
        updated_at=(
            None if data["updated_at"] is None else _datetime(data["updated_at"])
        ),
        next_step_due_on=(
            None
            if data["next_step_due_on"] is None
            else _date(data["next_step_due_on"])
        ),
        invoice_created_at=_optional_datetime(data["invoice_created_at"]),
        invoice_created_by=_optional_str(data["invoice_created_by"]),
        invoice_sent_recorded_at=_optional_datetime(
            data["invoice_sent_recorded_at"]
        ),
        invoice_sent_recorded_by=_optional_str(data["invoice_sent_recorded_by"]),
        payment_reminder_sent_at=_optional_datetime(
            data["payment_reminder_sent_at"]
        ),
        payment_reminder_sent_by=_optional_str(data["payment_reminder_sent_by"]),
        mahnung_sent_at=_optional_datetime(data["mahnung_sent_at"]),
        mahnung_sent_by=_optional_str(data["mahnung_sent_by"]),
        quittung_printed_at=_optional_datetime(data["quittung_printed_at"]),
        quittung_printed_by=_optional_str(data["quittung_printed_by"]),
        paid_recorded_at=_optional_datetime(data["paid_recorded_at"]),
        paid_recorded_by=_optional_str(data["paid_recorded_by"]),
    )


def _manual_task(value: object) -> ManualTask:
    data = _dict(value)
    _exact(
        data,
        {
            "task_id",
            "title",
            "description",
            "due_at",
            "status",
            "created_at",
            "completed_at",
            "created_by_employee_id",
            "assigned_to_employee_id",
            "subject_type",
            "subject_id",
            "priority",
        },
    )
    try:
        task = validate_manual_task(
            ManualTask(
                task_id=_uuid4(data["task_id"]),
                title=_str(data["title"]),
                description=_str(data["description"]),
                due_at=_optional_datetime(data["due_at"]),
                created_at=_datetime(data["created_at"]),
                completed_at=_optional_datetime(data["completed_at"]),
                created_by_employee_id=_uuid4(data["created_by_employee_id"]),
                assigned_to_employee_id=_optional_uuid4(
                    data["assigned_to_employee_id"]
                ),
                subject_type=validate_manual_task_subject_type(
                    _str(data["subject_type"])
                ),
                subject_id=_optional_uuid4(data["subject_id"]),
                priority=validate_manual_task_priority(_str(data["priority"])),
            )
        )
    except (TypeError, ValueError):
        _bad_response()
    if _str(data["status"]) != task.status:
        _bad_response()
    return task


_CHAT_THREAD_KEYS = frozenset(
    {"thread_id", "thread_type", "title", "created_by_employee_id", "created_at"}
)
_CHAT_THREAD_WITH_PARTICIPANTS_KEYS = _CHAT_THREAD_KEYS | {"participants"}
_CHAT_PARTICIPANT_KEYS = frozenset(
    {
        "thread_id",
        "employee_id",
        "display_name",
        "joined_at",
        "last_read_message_id",
    }
)
_CHAT_MESSAGE_PREVIEW_KEYS = frozenset(
    {"message_id", "author_employee_id", "body", "created_at"}
)
_CHAT_REFERENCE_KEYS = frozenset({"reference_type", "reference_id"})
_CHAT_MENTION_KEYS = frozenset({"employee_id", "display_name"})
_CHAT_MESSAGE_KEYS = frozenset(
    {
        "message_id",
        "thread_id",
        "author_employee_id",
        "author_display_name",
        "body",
        "reply_to_message_id",
        "created_at",
        "mentions",
        "references",
    }
)
_CHAT_SUMMARY_KEYS = frozenset(
    {
        "thread",
        "participants",
        "latest_message_preview",
        "unread_count",
        "last_activity_at",
    }
)
_CHAT_DETAIL_KEYS = frozenset(
    {"thread", "participants", "current_participant", "messages"}
)
_CHAT_ENTITY_RESULT_KEYS = frozenset(
    {"reference_type", "reference_id", "primary_label", "secondary_label", "meta"}
)
_CHAT_EMPLOYEE_KEYS = frozenset({"employee_id", "display_name"})


def _chat_reference_type(value: object) -> str:
    raw = _str(value)
    if raw not in CHAT_REFERENCE_TYPE_SET:
        _bad_response()
    return raw


def _chat_thread(data: Mapping[str, object], *, participants: bool = False) -> None:
    _exact(
        data,
        _CHAT_THREAD_WITH_PARTICIPANTS_KEYS if participants else _CHAT_THREAD_KEYS,
    )
    if _str(data["thread_type"]) not in CHAT_THREAD_TYPE_SET:
        _bad_response()
    _uuid4(data["thread_id"])
    _optional_str(data["title"])
    _uuid4(data["created_by_employee_id"])
    _datetime(data["created_at"])
    if participants:
        for raw_participant in _list(data["participants"]):
            _chat_participant(_dict(raw_participant))


def _chat_participant(data: Mapping[str, object]) -> None:
    _exact(data, _CHAT_PARTICIPANT_KEYS)
    _uuid4(data["thread_id"])
    _uuid4(data["employee_id"])
    _str(data["display_name"])
    _datetime(data["joined_at"])
    _optional_uuid4(data["last_read_message_id"])


def _chat_message_preview(value: object) -> None:
    if value is None:
        return
    data = _dict(value)
    _exact(data, _CHAT_MESSAGE_PREVIEW_KEYS)
    _uuid4(data["message_id"])
    _uuid4(data["author_employee_id"])
    _str(data["body"])
    _datetime(data["created_at"])


def _chat_message(value: object) -> None:
    data = _dict(value)
    _exact(data, _CHAT_MESSAGE_KEYS)
    _uuid4(data["message_id"])
    _uuid4(data["thread_id"])
    _uuid4(data["author_employee_id"])
    _str(data["author_display_name"])
    _str(data["body"])
    _optional_uuid4(data["reply_to_message_id"])
    _datetime(data["created_at"])
    for raw_mention in _list(data["mentions"]):
        mention = _dict(raw_mention)
        _exact(mention, _CHAT_MENTION_KEYS)
        _uuid4(mention["employee_id"])
        _str(mention["display_name"])
    for raw_reference in _list(data["references"]):
        reference = _dict(raw_reference)
        _exact(reference, _CHAT_REFERENCE_KEYS)
        _chat_reference_type(reference["reference_type"])
        _uuid4(reference["reference_id"])


def _chat_summary(value: object) -> dict[str, object]:
    data = _dict(value)
    _exact(data, _CHAT_SUMMARY_KEYS)
    _chat_thread(_dict(data["thread"]))
    for raw_participant in _list(data["participants"]):
        _chat_participant(_dict(raw_participant))
    _chat_message_preview(data["latest_message_preview"])
    _nonnegative_int(data["unread_count"])
    _datetime(data["last_activity_at"])
    return data


def _chat_detail(value: object) -> dict[str, object]:
    data = _dict(value)
    _exact(data, _CHAT_DETAIL_KEYS)
    _chat_thread(_dict(data["thread"]))
    for raw_participant in _list(data["participants"]):
        _chat_participant(_dict(raw_participant))
    _chat_participant(_dict(data["current_participant"]))
    for raw_message in _list(data["messages"]):
        _chat_message(raw_message)
    return data


def _chat_entity_result(value: object) -> dict[str, object]:
    data = _dict(value)
    _exact(data, _CHAT_ENTITY_RESULT_KEYS)
    _chat_reference_type(data["reference_type"])
    _uuid4(data["reference_id"])
    _str(data["primary_label"])
    _str(data["secondary_label"])
    _dict(data["meta"])
    return data


def _chat_employee(value: object) -> dict[str, object]:
    data = _dict(value)
    _exact(data, _CHAT_EMPLOYEE_KEYS)
    _uuid4(data["employee_id"])
    _str(data["display_name"])
    return data


def _validate_offer_prefill(value: object) -> None:
    payload = _dict(value)
    _exact(payload, {"schema_version", "source", "inquiry_id", "transfer"})
    if _str(payload["schema_version"]) != "core_inquiry_offer_prefill_v1":
        _bad_response()
    if _str(payload["source"]) != "silberloeffel-core":
        _bad_response()
    _uuid4(payload["inquiry_id"])
    transfer = _dict(payload["transfer"])
    transfer_keys = set(transfer)
    required_transfer_keys = {"planning", "orderContextPrefill"}
    allowed_transfer_keys = required_transfer_keys | {"fulfillmentPrefill"}
    if not required_transfer_keys <= transfer_keys <= allowed_transfer_keys:
        _bad_response()
    planning = _dict(transfer["planning"])
    _exact(
        planning,
        {
            "persons",
            "budget",
            "budgetEnabled",
            "desiredModules",
            "dietaryRequirements",
            "eventType",
            "serviceStyle",
        },
    )
    _guest_count(planning["persons"])
    if planning["budget"] is not None:
        _bad_response()
    _bool(planning["budgetEnabled"])
    if _list(planning["desiredModules"]):
        _bad_response()
    for key in ("dietaryRequirements", "eventType", "serviceStyle"):
        _str(planning[key])
    context = _dict(transfer["orderContextPrefill"])
    _exact(
        context,
        {
            "companyName",
            "contactPerson",
            "email",
            "phone",
            "eventDate",
            "eventTime",
            "location",
            "billingAddress",
            "remarks",
        },
    )
    for item in context.values():
        _str(item)
    _date(context["eventDate"])

    if "fulfillmentPrefill" in transfer:
        fulfillment = _dict(transfer["fulfillmentPrefill"])
        _exact(
            fulfillment,
            {
                "fulfillmentMode",
                "deliveryAddressMode",
                "invoiceAddress",
                "deliveryAddress",
            },
        )
        validate_fulfillment_mode(_str(fulfillment["fulfillmentMode"]))
        if _str(fulfillment["deliveryAddressMode"]) not in {
            "UNKNOWN",
            "SAME_AS_INVOICE",
            "SEPARATE",
        }:
            _bad_response()
        for address_key in ("invoiceAddress", "deliveryAddress"):
            address = _dict(fulfillment[address_key])
            _exact(address, {"street", "postalCode", "city", "country"})
            for item in address.values():
                _str(item)


class RemoteCoreClient:
    """Strict bearer client plus read facades used by ``OfficePanel``."""

    is_remote = True

    def __init__(self, base_url: str, token: str) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CORE_OFFICE_API_URL must be an absolute HTTP(S) URL")
        if not token:
            raise ValueError("CORE_OFFICE_API_TOKEN is required in remote mode")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._command_id = ""
        self._form: dict[str, str] = {}
        self._order_details: dict[str, dict[str, object]] = {}
        self._inquiry_detail_meta: dict[str, InquiryDetailMeta] = {}
        self._order_version_meta: dict[str, tuple[int, bool]] = {}
        self._known_order_ids: list[str] = []
        self._evaluations: dict[str, ReadyToSendEvaluation] = {}
        self._confirmation_eligibility: dict[
            str, OrderConfirmationDocumentEligibility
        ] = {}
        self.inquiry_service = _RemoteInquiryService(self)
        self.order_service = _RemoteOrderService(self)
        self.payment_reminder_service = _RemotePaymentReminderService(self)
        self.confirmation_document_service = _RemoteConfirmationDocumentService(self)
        self.confirmation_outbound_service = _RemoteConfirmationOutboundService(self)
        self.catalog_dish_write_service = _RemoteCatalogDishWriteService(self)
        self.core = _RemoteOperationalCoreService(self)

    def begin_request(self, form: Mapping[str, str] | None = None) -> None:
        self._order_details.clear()
        self._inquiry_detail_meta.clear()
        self._order_version_meta.clear()
        self._known_order_ids = []
        self._evaluations.clear()
        self._confirmation_eligibility.clear()
        self._form = dict(form or {})
        self._command_id = self._form.get("_command_id", "")

    def new_page_command_id(self) -> str:
        return str(uuid.uuid4())

    def _id(self) -> str:
        return self._command_id or str(uuid.uuid4())

    def form_value(self, key: str) -> str | None:
        return self._form.get(key)

    def _url(self, path: str, query: Mapping[str, object] | None = None) -> str:
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urlencode(query)
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        body: Mapping[str, object] | None = None,
        expected: set[int],
        employee_session_token: str | None = None,
    ) -> dict[str, object]:
        data = None
        headers = {"Authorization": f"Bearer {self._token}"}
        if employee_session_token is not None:
            headers["X-Employee-Session"] = employee_session_token
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._url(path, query), data=data, headers=headers, method=method
        )
        timeout = _READ_TIMEOUT_SECONDS if method == "GET" else _COMMAND_TIMEOUT_SECONDS
        try:
            response = self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise RemoteCoreError(
                    502, "redirect_refused", unavailable=True
                ) from exc
            raw = exc.read(_MAX_RESPONSE_BYTES + 1)
            if (
                exc.headers.get_content_type() != "application/json"
                or len(raw) > _MAX_RESPONSE_BYTES
            ):
                _bad_response()
            try:
                parsed = _dict(json.loads(raw.decode("utf-8")))
                code = _error_body_code(parsed, exc.code)
            except (UnicodeDecodeError, json.JSONDecodeError, RemoteCoreError) as error:
                raise RemoteCoreError(
                    502, "invalid_response", unavailable=True
                ) from error
            if code not in _ERROR_CODES_BY_STATUS.get(exc.code, frozenset()):
                _bad_response()
            raise RemoteCoreError(exc.code, code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RemoteCoreError(503, "unreachable", unavailable=True) from exc
        with response:
            if response.status not in expected:
                raise RemoteCoreError(
                    response.status, "unexpected_status", unavailable=True
                )
            if response.headers.get_content_type() != "application/json":
                _bad_response()
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            _bad_response()
        try:
            return _dict(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _bad_response()

    def get(
        self,
        path: str,
        query: Mapping[str, object] | None = None,
        *,
        employee_session_token: str | None = None,
    ) -> dict[str, object]:
        return self._request(
            "GET",
            path,
            query=query,
            expected={200},
            employee_session_token=employee_session_token,
        )

    def get_text(self, path: str, query: Mapping[str, object] | None = None) -> str:
        url = self._url(path, query)
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        try:
            response = self._opener.open(request, timeout=_READ_TIMEOUT_SECONDS)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RemoteCoreError(503, "unreachable", unavailable=True) from exc
        with response:
            if response.status != 200:
                raise RemoteCoreError(
                    response.status, "unexpected_status", unavailable=True
                )
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            _bad_response()
        return raw.decode("utf-8")

    def get_bytes(
        self, path: str, query: Mapping[str, object] | None = None
    ) -> tuple[bytes, str | None]:
        """Raw binary GET (offer-document PDF download). The token is
        attached here, server-side, and never reaches the browser. Unlike
        get_text, HTTPError is handled explicitly so the real status code
        (404/422/...) survives as a RemoteCoreError.status, not collapsed
        into a generic 503 — callers need that to map errors correctly."""
        request = urllib.request.Request(
            self._url(path, query),
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        try:
            response = self._opener.open(request, timeout=_READ_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise RemoteCoreError(
                    502, "redirect_refused", unavailable=True
                ) from exc
            raw = exc.read(_MAX_RESPONSE_BYTES + 1)
            code = "unexpected_status"
            if (
                exc.headers.get_content_type() == "application/json"
                and len(raw) <= _MAX_RESPONSE_BYTES
            ):
                try:
                    parsed = _dict(json.loads(raw.decode("utf-8")))
                    code = _error_body_code(parsed, exc.code)
                except (UnicodeDecodeError, json.JSONDecodeError, RemoteCoreError):
                    # get_bytes keeps its existing fallback: the real HTTP
                    # status survives, the code degrades to unexpected_status.
                    pass
            raise RemoteCoreError(exc.code, code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RemoteCoreError(503, "unreachable", unavailable=True) from exc
        with response:
            if response.status != 200:
                raise RemoteCoreError(
                    response.status, "unexpected_status", unavailable=True
                )
            if response.headers.get_content_type() != "application/pdf":
                _bad_response()
            disposition = response.headers.get("Content-Disposition")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            _bad_response()
        return raw, _filename_from_content_disposition(disposition)

    def command(
        self,
        path: str,
        args: Mapping[str, object],
        expect: Mapping[str, object],
        expected: set[int],
        result_keys: set[str],
        *,
        command_id: str | None = None,
        optional_result_keys: frozenset[str] | set[str] = frozenset(),
        employee_session_token: str | None = None,
    ) -> dict[str, object]:
        """`result_keys` must all be present. `optional_result_keys` may be
        present — for commands whose response carries a field only in some
        outcomes (REMOTE_CATALOG_PRICE_HISTORY_CONTRACT_FIX_V1: the catalog
        update returns `price_history_entry_id` only when the price actually
        changed). Anything outside both sets is still rejected, so this
        widens the contract by exactly the declared keys and no more."""
        command_id = command_id or self._id()
        result = self._request(
            "POST",
            path,
            body={
                "command_id": command_id,
                "expect": dict(expect),
                "args": dict(args),
            },
            expected=expected,
            employee_session_token=employee_session_token,
        )
        required = result_keys | {"command_id"}
        if not required <= set(result) <= required | set(optional_result_keys):
            _bad_response()
        if _str(result["command_id"]) != command_id:
            _bad_response()
        self._order_details.clear()
        self._inquiry_detail_meta.clear()
        self._order_version_meta.clear()
        self._known_order_ids = []
        self._evaluations.clear()
        self._confirmation_eligibility.clear()
        return result

    def convert_accepted_offer(
        self,
        offer_id: str,
        offer_version_id: str,
        *,
        accepted_variant_id: str,
        acceptance_id: str,
        payment_method: str,
    ) -> tuple[str, str]:
        result = self.command(
            f"/office/v1/offers/{quote(offer_id, safe='')}/versions/"
            f"{quote(offer_version_id, safe='')}/convert-accepted",
            {
                "accepted_variant_id": accepted_variant_id,
                "acceptance_id": acceptance_id,
                "payment_method": payment_method,
            },
            {},
            expected={201, 200},
            result_keys={
                "offer_id",
                "offer_version_id",
                "accepted_variant_id",
                "acceptance_id",
                "order_id",
                "order_version_id",
            },
        )
        if _uuid4(result["offer_id"]) != offer_id:
            _bad_response()
        if _uuid4(result["offer_version_id"]) != offer_version_id:
            _bad_response()
        return _uuid4(result["order_id"]), _uuid4(result["order_version_id"])

    def prepare_next_offer_version(
        self,
        offer_id: str,
        snapshot: Mapping[str, object],
        *,
        latest_version_number: int,
        command_id: str | None = None,
    ) -> dict[str, object]:
        """Append OfferVersion N+1; configurator/clients choose this when Offer exists."""
        result = self.command(
            f"/office/v1/offers/{quote(offer_id, safe='')}/prepare-next-version",
            {"snapshot": dict(snapshot)},
            {"latest_version_number": latest_version_number},
            expected={201},
            result_keys={
                "offer_id",
                "offer_version_id",
                "version_number",
                "snapshot_id",
            },
            command_id=command_id,
        )
        if _uuid4(result["offer_id"]) != offer_id:
            _bad_response()
        _uuid4(result["offer_version_id"])
        if _int(result["version_number"]) != latest_version_number + 1:
            _bad_response()
        _str(result["snapshot_id"])
        return result

    def mark_offer_sent(
        self,
        offer_id: str,
        offer_version_id: str,
        *,
        sent_at: str,
        channel: str,
        recipient_reference: str,
        evidence_reference: str,
    ) -> None:
        self.command(
            f"/office/v1/offers/{quote(offer_id, safe='')}/versions/"
            f"{quote(offer_version_id, safe='')}/mark-sent",
            {
                "sent_at": sent_at,
                "channel": channel,
                "recipient_reference": recipient_reference,
                "evidence_reference": evidence_reference,
            },
            {},
            expected={200},
            result_keys={"offer_id", "offer_version_id", "sent_at"},
        )

    def record_offer_acceptance(
        self,
        offer_id: str,
        offer_version_id: str,
        *,
        accepted_variant_id: str,
        accepted_at: str,
        channel: str,
        evidence_reference: str,
        note: str | None = None,
    ) -> None:
        args: dict[str, object] = {
            "accepted_variant_id": accepted_variant_id,
            "accepted_at": accepted_at,
            "channel": channel,
            "evidence_reference": evidence_reference,
        }
        if note is not None:
            args["note"] = note
        self.command(
            f"/office/v1/offers/{quote(offer_id, safe='')}/versions/"
            f"{quote(offer_version_id, safe='')}/record-acceptance",
            args,
            {},
            expected={200},
            result_keys={
                "offer_id",
                "offer_version_id",
                "accepted_variant_id",
                "acceptance_id",
            },
        )

    def record_offer_rejection(
        self,
        offer_id: str,
        offer_version_id: str,
        *,
        rejected_at: str,
        evidence_reference: str | None = None,
    ) -> None:
        args: dict[str, object] = {"rejected_at": rejected_at}
        if evidence_reference is not None:
            args["evidence_reference"] = evidence_reference
        self.command(
            f"/office/v1/offers/{quote(offer_id, safe='')}/versions/"
            f"{quote(offer_version_id, safe='')}/record-rejection",
            args,
            {},
            expected={200},
            result_keys={"offer_id", "offer_version_id", "rejected_at"},
        )

    def record_offer_withdrawal(
        self,
        offer_id: str,
        offer_version_id: str,
        *,
        reason: str | None = None,
    ) -> None:
        args: dict[str, object] = {}
        if reason is not None:
            args["reason"] = reason
        self.command(
            f"/office/v1/offers/{quote(offer_id, safe='')}/versions/"
            f"{quote(offer_version_id, safe='')}/record-withdrawal",
            args,
            {},
            expected={200},
            result_keys={"offer_id", "offer_version_id", "withdrawn_at"},
        )

    def delete_order(
        self,
        order_id: str,
        *,
        confirmation_name: str,
        employee_session_token: str,
    ) -> None:
        result = self.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/delete",
            {"confirmation_name": confirmation_name},
            {},
            expected={200},
            result_keys={"order_id"},
            employee_session_token=employee_session_token,
        )
        if _uuid4(result["order_id"]) != order_id:
            _bad_response()

    # -- reads / repository-shaped facade ---------------------------------

    def queue_view(self) -> dict[str, object]:
        body = self.get("/office/v1/queue")
        _exact(
            body,
            {
                "attention",
                "week",
                "neue_anfragen_top",
                "auftraege_top",
                "pausiert_top",
            },
        )
        attention = _dict(body["attention"])
        _exact(
            attention,
            {
                "neue_anfragen",
                "druck_fehlt",
                "nicht_wirksam",
                "versand_blockiert",
                "aenderungen_warten_auf_kuechendruck",
                "pausiert",
                "storniert",
            },
        )
        for value in attention.values():
            _nonnegative_int(value)

        week = _dict(body["week"])
        _exact(week, {"iso_year", "iso_week", "entries", "total_count", "truncated"})
        iso_year, iso_week = _int(week["iso_year"]), _int(week["iso_week"])
        try:
            date.fromisocalendar(iso_year, iso_week, 1)
        except ValueError:
            _bad_response()
        entries = _list(week["entries"])
        for raw in entries:
            entry = _dict(raw)
            _exact(
                entry,
                {
                    "order_id",
                    "event_date",
                    "time_window_text",
                    "location_text",
                    "guest_count_estimate",
                },
            )
            _uuid4(entry["order_id"])
            _date(entry["event_date"])
            _str(entry["time_window_text"])
            _str(entry["location_text"])
            _guest_count(entry["guest_count_estimate"])
        total = _nonnegative_int(week["total_count"])
        truncated = _bool(week["truncated"])
        if total < len(entries) or truncated != (total > len(entries)):
            _bad_response()

        inquiry_rows = _list(body["neue_anfragen_top"])
        if len(inquiry_rows) > 5:
            _bad_response()
        for raw in inquiry_rows:
            row = _dict(raw)
            row_keys = set(row)
            allowed = _INQUIRY_SUMMARY_KEYS | {"next_action", "offer"}
            if not (_INQUIRY_SUMMARY_KEYS | {"next_action"}) <= row_keys <= allowed:
                _bad_response()
            _inquiry({key: row[key] for key in _INQUIRY_SUMMARY_KEYS})
            if _str(row["next_action"]) not in _INQUIRY_NEXT_ACTIONS:
                _bad_response()
            if "offer" in row:
                _inquiry_offer_projection(row["offer"])

        order_rows = _list(body["auftraege_top"])
        if len(order_rows) > 5:
            _bad_response()
        for raw in order_rows:
            row = _dict(raw)
            _exact(
                row,
                _ORDER_SUMMARY_KEYS
                | {"blocker_reason", "next_action", "operational_pause_active"},
            )
            _order({key: row[key] for key in _ORDER_SUMMARY_KEYS})
            _optional_str(row["blocker_reason"])
            _next_action(row["next_action"])
            _bool(row["operational_pause_active"])
        paused_rows = _list(body["pausiert_top"])
        if len(paused_rows) > 5:
            _bad_response()
        for raw in paused_rows:
            row = _dict(raw)
            _exact(
                row,
                _ORDER_SUMMARY_KEYS
                | {"blocker_reason", "next_action"}
                | _ORDER_TOP_PAUSE_KEYS,
            )
            _order({key: row[key] for key in _ORDER_SUMMARY_KEYS})
            _optional_str(row["blocker_reason"])
            _next_action(row["next_action"])
            if not _bool(row["operational_pause_active"]):
                _bad_response()
            _str(row["operational_pause_reason_code"])
        return body

    def work_center(self) -> dict[str, object]:
        body = self.get("/office/v1/work-center")
        _exact(
            body,
            {
                "rueckrufe_open",
                "missed_calls_open",
                "offers_waiting",
                "offers_accepted",
                "upcoming_orders",
                "open_tasks",
                "today_calendar_entries",
                "pending_order_changes",
            },
        )
        for value in body.values():
            _nonnegative_int(value)
        return body

    def list_offers(self) -> dict[str, object]:
        body = self.get("/office/v1/offers")
        _exact(body, {"offers"})
        rows = _list(body["offers"])
        allowed_states = {
            "Prepared",
            "Sent",
            "Accepted",
            "Converted",
            "Expired",
            "Withdrawn",
            "Rejected",
            "Superseded",
        }
        for raw in rows:
            row = _dict(raw)
            _exact(
                row, {"offer_id", "inquiry_id", "state", "event_date", "valid_until"}
            )
            _uuid4(row["offer_id"])
            _uuid4(row["inquiry_id"])
            state = _str(row["state"])
            if state not in allowed_states:
                _bad_response()
            _date(row["event_date"])
            _date(row["valid_until"])
        return body

    def offer_queue(
        self,
        *,
        group: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        params: list[str] = []
        if group is not None:
            params.append(f"group={quote(group, safe='')}")
        if limit != 100:
            params.append(f"limit={limit}")
        if offset != 0:
            params.append(f"offset={offset}")
        path = "/office/v1/offer-queue"
        if params:
            path = f"{path}?{'&'.join(params)}"
        body = self.get(path)
        _exact(body, {"today", "sections", "total_count", "limit", "offset"})
        _date(body["today"])
        _nonnegative_int(body["total_count"])
        limit_value = _nonnegative_int(body["limit"])
        offset_value = _nonnegative_int(body["offset"])
        if limit_value < 1 or offset_value < 0:
            _bad_response()
        allowed_groups = {"action_required", "overdue", "history"}
        allowed_subkinds = {
            "prepared",
            "sent",
            "accepted",
            "accepted_contact_blocked",
            "expired",
            "converted",
            "rejected",
            "withdrawn",
            "superseded",
            "inquiry_closed",
        }
        allowed_next_actions = {
            "mark_sent",
            "await_customer",
            "convert_accepted",
            "complete_contact",
            "prepare_next_version",
            "none",
        }
        allowed_states = {
            "Prepared",
            "Sent",
            "Accepted",
            "Converted",
            "Expired",
            "Withdrawn",
            "Rejected",
            "Superseded",
        }
        for raw_section in _list(body["sections"]):
            section = _dict(raw_section)
            _exact(section, {"group", "label", "count", "items"})
            group_value = _str(section["group"])
            if group_value not in allowed_groups:
                _bad_response()
            _str(section["label"])
            _nonnegative_int(section["count"])
            for raw_item in _list(section["items"]):
                item = _dict(raw_item)
                keys = {
                    "offer_id",
                    "inquiry_id",
                    "offer_version_id",
                    "version_number",
                    "state",
                    "state_label",
                    "queue_group",
                    "queue_subkind",
                    "next_action",
                    "next_action_label",
                    "customer_display",
                    "intake_subject",
                    "event_date",
                    "guest_count",
                    "valid_until",
                    "days_until_valid_until",
                    "days_overdue",
                    "prepared_at",
                    "sent_at",
                }
                if not keys <= set(item):
                    _bad_response()
                if (
                    item.get("validity_hint") is not None
                    and _str(item["validity_hint"]) != "expires_today"
                ):
                    _bad_response()
                _uuid4(item["offer_id"])
                _uuid4(item["inquiry_id"])
                _uuid4(item["offer_version_id"])
                _int(item["version_number"])
                if _str(item["state"]) not in allowed_states:
                    _bad_response()
                _str(item["state_label"])
                if _str(item["queue_group"]) not in allowed_groups:
                    _bad_response()
                if _str(item["queue_subkind"]) not in allowed_subkinds:
                    _bad_response()
                if _str(item["next_action"]) not in allowed_next_actions:
                    _bad_response()
                _str(item["next_action_label"])
                _str(item["customer_display"])
                if item["intake_subject"] is not None:
                    _str(item["intake_subject"])
                _date(item["event_date"])
                if item["guest_count"] is not None:
                    _guest_count(item["guest_count"])
                _date(item["valid_until"])
                _int(item["days_until_valid_until"])
                if item["days_overdue"] is not None:
                    _int(item["days_overdue"])
                _datetime(item["prepared_at"])
                if item["sent_at"] is not None:
                    _datetime(item["sent_at"])
        return body

    def offer_detail(self, offer_id: str) -> dict[str, object] | None:
        try:
            body = self.get(f"/office/v1/offers/{quote(offer_id, safe='')}")
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        allowed_states = {
            "Prepared",
            "Sent",
            "Accepted",
            "Converted",
            "Expired",
            "Withdrawn",
            "Rejected",
            "Superseded",
        }
        required = {
            "offer_id",
            "inquiry_id",
            "offer_version_id",
            "commercial_state",
            "acceptance_id",
            "versions",
            "sent_evidence",
            "acceptance",
            "history",
        }
        keys = set(body)
        if not required <= keys or keys - required - {"order_id"}:
            _bad_response()
        _uuid4(body["offer_id"])
        _uuid4(body["inquiry_id"])
        _uuid4(body["offer_version_id"])
        if body["acceptance_id"] is not None:
            _uuid4(body["acceptance_id"])
        state = _str(body["commercial_state"])
        if state not in allowed_states:
            _bad_response()
        if "order_id" in body:
            _uuid4(body["order_id"])
        sent = body["sent_evidence"]
        if sent is not None:
            sent_row = _dict(sent)
            _exact(sent_row, {"sent_at", "channel"})
            _datetime(sent_row["sent_at"])
            _str(sent_row["channel"])
        acceptance = body["acceptance"]
        if acceptance is not None:
            acc_row = _dict(acceptance)
            _exact(acc_row, {"accepted_at", "channel", "accepted_variant_id"})
            _datetime(acc_row["accepted_at"])
            _str(acc_row["channel"])
            _uuid4(acc_row["accepted_variant_id"])
        for raw in _list(body["versions"]):
            version = _dict(raw)
            _exact(
                version,
                {
                    "offer_version_id",
                    "version",
                    "state",
                    "created_at",
                    "sent_at",
                    "event_date",
                    "valid_until",
                    "time_window_text",
                    "location_text",
                    "guest_count",
                    "planning_mode",
                    "variants",
                },
            )
            version_state = _str(version["state"])
            if version_state not in allowed_states:
                _bad_response()
            _uuid4(version["offer_version_id"])
            _int(version["version"])
            _datetime(version["created_at"])
            if version["sent_at"] is not None:
                _datetime(version["sent_at"])
            _date(version["event_date"])
            _date(version["valid_until"])
            _str(version["time_window_text"])
            _str(version["location_text"])
            if version["guest_count"] is not None:
                _nonnegative_int(version["guest_count"])
            _str(version["planning_mode"])
            for variant_raw in _list(version["variants"]):
                variant = _dict(variant_raw)
                _exact(variant, {"variant_id", "name", "positions"})
                _uuid4(variant["variant_id"])
                _str(variant["name"])
                for position_raw in _list(variant["positions"]):
                    position = _dict(position_raw)
                    _exact(
                        position,
                        {
                            "position_id",
                            "kind",
                            "name",
                            "unit_net_cents",
                            "net_total_cents",
                            "catalog_item_id",
                            "description",
                            "composition",
                            "allergens",
                            "allergen_labels",
                            "allergens_unknown",
                        },
                    )
                    _uuid4(position["position_id"])
                    _str(position["kind"])
                    _str(position["name"])
                    _nonnegative_int(position["unit_net_cents"])
                    _nonnegative_int(position["net_total_cents"])
                    if position["catalog_item_id"] is not None:
                        _str(position["catalog_item_id"])
                    if position["description"] is not None:
                        _str(position["description"])
                    if position["composition"] is not None:
                        _str(position["composition"])
                    allergens = position["allergens"]
                    if allergens is not None:
                        for code in _list(allergens):
                            _str(code)
                        for label in _list(position["allergen_labels"]):
                            _str(label)
                    _bool(position["allergens_unknown"])
        for raw in _list(body["history"]):
            entry = _dict(raw)
            _exact(entry, {"at", "label"})
            _datetime(entry["at"])
            _str(entry["label"])
        return body

    def offer_document_exists(self, offer_id: str, offer_version_id: str) -> bool:
        """Read-only existence check for the frozen OfferDocumentSnapshot —
        used only to decide whether the panel shows the download button."""
        try:
            self.get(
                f"/office/v1/offers/{quote(offer_id, safe='')}/offer-document",
                {"offer_version_id": offer_version_id},
            )
        except RemoteCoreError as exc:
            if exc.status == 404:
                return False
            raise
        return True

    def offer_document_pdf(
        self, offer_id: str, offer_version_id: str
    ) -> tuple[bytes, str | None]:
        """Download the already-persisted immutable snapshot as PDF.
        Never creates a snapshot; the Bearer token stays server-side."""
        return self.get_bytes(
            f"/office/v1/offers/{quote(offer_id, safe='')}/offer-document/pdf",
            {"offer_version_id": offer_version_id},
        )

    def list_contacts(self) -> dict[str, object]:
        body = self.get("/office/v1/contacts")
        _exact(body, {"contacts"})
        allowed_sources = {
            "linkage_contact",
            "linkage_customer",
            "intake_email",
            "intake_phone",
            "inquiry",
        }
        for raw in _list(body["contacts"]):
            row = _dict(raw)
            _exact(
                row,
                {
                    "contact_key",
                    "identity_source",
                    "display_name",
                    "email",
                    "phone",
                    "inquiry_count",
                    "open_inquiries",
                    "active_orders",
                    "linked_order_count",
                    "contact_status",
                    "last_activity",
                },
            )
            _str(row["contact_key"])
            source = _str(row["identity_source"])
            if source not in allowed_sources:
                _bad_response()
            _str(row["display_name"])
            _optional_str(row["email"])
            _optional_str(row["phone"])
            _nonnegative_int(row["inquiry_count"])
            _nonnegative_int(row["open_inquiries"])
            _nonnegative_int(row["active_orders"])
            _nonnegative_int(row["linked_order_count"])
            status = _str(row["contact_status"])
            if status not in {"interessent", "kunde"}:
                _bad_response()
            _datetime(row["last_activity"])
        return body

    def list_catalog_dishes(
        self,
        *,
        active: bool | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        """CATALOG_ADMIN_PANEL_V1: sends the status filter as `active`
        (true/false/omitted) so Core applies it in SQL before LIMIT. Never
        sends the legacy `active_only` — that alias exists on the API only
        for callers older than this change."""
        params: dict[str, str] = {}
        if active is not None:
            params["active"] = "true" if active else "false"
        if q:
            params["q"] = q
        if limit != 100:
            params["limit"] = str(limit)
        if offset:
            params["offset"] = str(offset)
        body = self.get("/office/v1/catalog/dishes", params or None)
        _exact(body, {"dishes", "total_count", "truncated"})
        for raw in _list(body["dishes"]):
            row = _dict(raw)
            _exact(
                row,
                {
                    "dish_id",
                    "name",
                    "current_unit_net_cents",
                    "price_display",
                    "allergens",
                    "allergen_labels",
                    "active",
                    "category",
                    "pricing_unit",
                    "vat_rate_percent",
                },
            )
            _uuid4(row["dish_id"])
            _str(row["name"])
            _nonnegative_int(row["current_unit_net_cents"])
            _str(row["price_display"])
            for code in _list(row["allergens"]):
                _str(code)
            for label in _list(row["allergen_labels"]):
                _str(label)
            _bool(row["active"])
            _optional_str(row["category"])
            _optional_pricing_unit(row["pricing_unit"])
            _optional_int(row["vat_rate_percent"])
        _nonnegative_int(body["total_count"])
        _bool(body["truncated"])
        return body

    def catalog_dish_detail(self, dish_id: str) -> dict[str, object] | None:
        try:
            body = self.get(f"/office/v1/catalog/dishes/{quote(dish_id, safe='')}")
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        _exact(
            body,
            {
                "dish_id",
                "name",
                "current_unit_net_cents",
                "price_display",
                "allergens",
                "allergen_labels",
                "active",
                "category",
                "pricing_unit",
                "vat_rate_percent",
                "description",
                "composition",
                "notes",
                "created_at",
                "updated_at",
                "price_history",
            },
        )
        if _uuid4(body["dish_id"]) != dish_id:
            _bad_response()
        _optional_str(body["category"])
        _optional_pricing_unit(body["pricing_unit"])
        _optional_int(body["vat_rate_percent"])
        for raw in _list(body["price_history"]):
            _catalog_price_history_entry(_dict(raw), dish_id=dish_id)
        return body

    def list_allergen_codes(self) -> dict[str, object]:
        body = self.get("/office/v1/catalog/allergen-codes")
        _exact(body, {"allergen_codes"})
        for raw in _list(body["allergen_codes"]):
            row = _dict(raw)
            _exact(row, {"code", "label"})
            _str(row["code"])
            _str(row["label"])
        return body

    def update_catalog_dish(
        self,
        dish_id: str,
        *,
        args: dict[str, object],
        expected_updated_at: str,
        command_id: str | None = None,
    ) -> dict[str, object]:
        # REMOTE_CATALOG_PRICE_HISTORY_CONTRACT_FIX_V1 (issue #37, second
        # mismatch): the API appends `price_history_entry_id` only when the
        # price actually changed. Declaring it optional is what makes the
        # `in result` check below reachable at all — before this, `_exact`
        # rejected the very responses that carried it, so every remote price
        # edit failed with 502 even though Core had already committed it.
        result = self.command(
            f"/office/v1/catalog/dishes/{quote(dish_id, safe='')}/update",
            args,
            {"updated_at": expected_updated_at},
            command_id=command_id,
            expected={200},
            result_keys={"dish_id", "updated_at", "price_changed"},
            optional_result_keys={"price_history_entry_id"},
        )
        if _uuid4(result["dish_id"]) != dish_id:
            _bad_response()
        _datetime(result["updated_at"])
        price_changed = _bool(result["price_changed"])
        # The id and the flag travel together: a price change records an
        # entry, an unchanged price records none.
        if price_changed != ("price_history_entry_id" in result):
            _bad_response()
        if "price_history_entry_id" in result:
            _uuid4(result["price_history_entry_id"])
        return result

    def create_catalog_dish(
        self,
        *,
        name: str,
        category: str,
        pricing_unit: str,
        current_unit_net_cents: int,
        vat_rate_percent: int,
        description: str | None = None,
        composition: str | None = None,
        notes: str | None = None,
        allergens: Sequence[str] = (),
        command_id: str | None = None,
    ) -> CatalogDish:
        """CATALOG_ADMIN_REMOTE_CLIENT_V1: mirrors the Office API's
        POST /office/v1/catalog/dishes contract exactly — dish_id and active
        are never accepted here (the server always mints dish_id and always
        starts a new dish inactive), so there is no parameter for either.
        No `expect` — a create has no prior state to stake a precondition
        on. The command response is minimal (dish_id/active/updated_at);
        the full CatalogDish is built from a follow-up catalog_dish_detail()
        read, matching the read endpoint's own strict validation."""
        args: dict[str, object] = {
            "name": name,
            "category": category,
            "pricing_unit": pricing_unit,
            "current_unit_net_cents": current_unit_net_cents,
            "vat_rate_percent": vat_rate_percent,
            "description": description,
            "composition": composition,
            "notes": notes,
            "allergens": list(allergens),
        }
        result = self.command(
            "/office/v1/catalog/dishes",
            args,
            {},
            command_id=command_id,
            expected={201},
            result_keys={"dish_id", "active", "updated_at"},
        )
        dish_id = _uuid4(result["dish_id"])
        if _bool(result["active"]) is not False:
            _bad_response()
        _datetime(result["updated_at"])
        detail = self.catalog_dish_detail(dish_id)
        if detail is None:
            _bad_response()
        return _catalog_dish_from_detail(detail)

    def _set_catalog_dish_active(
        self,
        dish_id: str,
        *,
        active: bool,
        expected_updated_at: str,
        command_id: str | None = None,
    ) -> CatalogDish:
        path = (
            f"/office/v1/catalog/dishes/{quote(dish_id, safe='')}"
            f"/{'activate' if active else 'deactivate'}"
        )
        result = self.command(
            path,
            {},
            {"updated_at": expected_updated_at},
            command_id=command_id,
            expected={200},
            result_keys={"dish_id", "active", "updated_at"},
        )
        if _uuid4(result["dish_id"]) != dish_id:
            _bad_response()
        if _bool(result["active"]) != active:
            _bad_response()
        _datetime(result["updated_at"])
        detail = self.catalog_dish_detail(dish_id)
        if detail is None:
            _bad_response()
        return _catalog_dish_from_detail(detail)

    def activate_catalog_dish(
        self,
        dish_id: str,
        *,
        expected_updated_at: str,
        command_id: str | None = None,
    ) -> CatalogDish:
        return self._set_catalog_dish_active(
            dish_id,
            active=True,
            expected_updated_at=expected_updated_at,
            command_id=command_id,
        )

    def deactivate_catalog_dish(
        self,
        dish_id: str,
        *,
        expected_updated_at: str,
        command_id: str | None = None,
    ) -> CatalogDish:
        return self._set_catalog_dish_active(
            dish_id,
            active=False,
            expected_updated_at=expected_updated_at,
            command_id=command_id,
        )

    def contact_detail(self, contact_key: str) -> dict[str, object] | None:
        try:
            body = self.get(f"/office/v1/contacts/{quote(contact_key, safe='')}")
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        allowed_sources = {
            "linkage_contact",
            "linkage_customer",
            "intake_email",
            "intake_phone",
            "inquiry",
        }
        allowed_offer_states = {
            "Prepared",
            "Sent",
            "Accepted",
            "Converted",
            "Expired",
            "Withdrawn",
            "Rejected",
            "Superseded",
        }
        _exact(
            body,
            {
                "contact_key",
                "identity_source",
                "display_name",
                "email",
                "phone",
                "inquiry_count",
                "open_inquiries",
                "active_orders",
                "linked_order_count",
                "contact_status",
                "last_activity",
                "inquiry_ids",
                "inquiries",
                "offers",
                "orders",
            },
        )
        if _str(body["contact_key"]) != contact_key:
            _bad_response()
        if _str(body["identity_source"]) not in allowed_sources:
            _bad_response()
        _nonnegative_int(body["linked_order_count"])
        if _str(body["contact_status"]) not in {"interessent", "kunde"}:
            _bad_response()
        _datetime(body["last_activity"])
        for raw in _list(body["inquiry_ids"]):
            _uuid4(raw)
        for raw in _list(body["inquiries"]):
            row = _dict(raw)
            _exact(
                row,
                {
                    "inquiry_id",
                    "intake_subject",
                    "event_date",
                    "crm_stage",
                    "is_open",
                },
            )
            _uuid4(row["inquiry_id"])
            _optional_str(row["intake_subject"])
            _date(row["event_date"])
            _str(row["crm_stage"])
            _bool(row["is_open"])
        for raw in _list(body["offers"]):
            row = _dict(raw)
            _exact(row, {"offer_id", "inquiry_id", "state"})
            _uuid4(row["offer_id"])
            _uuid4(row["inquiry_id"])
            if _str(row["state"]) not in allowed_offer_states:
                _bad_response()
        for raw in _list(body["orders"]):
            row = _dict(raw)
            _exact(row, {"order_id", "inquiry_id", "cancelled_at"})
            _uuid4(row["order_id"])
            _uuid4(row["inquiry_id"])
            _optional_datetime(row["cancelled_at"])
        return body

    def list_emails(self) -> dict[str, object]:
        body = self.get("/office/v1/emails")
        _exact(body, {"emails"})
        for raw in _list(body["emails"]):
            row = _dict(raw)
            _exact(
                row,
                {
                    "email_id",
                    "inquiry_id",
                    "contact_key",
                    "sender_name",
                    "sender_email",
                    "subject",
                    "preview",
                    "crm_stage",
                    "received_at",
                    "external_ref",
                    "linked_offer_id",
                    "linked_order_ids",
                },
            )
            inquiry_id = _uuid4(row["inquiry_id"])
            if _uuid4(row["email_id"]) != inquiry_id:
                _bad_response()
            _str(row["contact_key"])
            _optional_str(row["sender_name"])
            _optional_str(row["sender_email"])
            _optional_str(row["subject"])
            _optional_str(row["preview"])
            _str(row["crm_stage"])
            _datetime(row["received_at"])
            _optional_str(row["external_ref"])
            _optional_uuid4(row["linked_offer_id"])
            for order_id in _list(row["linked_order_ids"]):
                _uuid4(order_id)
        return body

    def email_detail(self, inquiry_id: str) -> dict[str, object] | None:
        try:
            body = self.get(f"/office/v1/emails/{quote(inquiry_id, safe='')}")
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        _exact(
            body,
            {
                "email_id",
                "inquiry_id",
                "contact_key",
                "sender_name",
                "sender_email",
                "subject",
                "preview",
                "crm_stage",
                "received_at",
                "external_ref",
                "linked_offer_id",
                "linked_order_ids",
            },
        )
        if _uuid4(body["inquiry_id"]) != inquiry_id:
            _bad_response()
        if _uuid4(body["email_id"]) != inquiry_id:
            _bad_response()
        _str(body["contact_key"])
        _optional_str(body["sender_name"])
        _optional_str(body["sender_email"])
        _optional_str(body["subject"])
        _optional_str(body["preview"])
        _str(body["crm_stage"])
        _datetime(body["received_at"])
        _optional_str(body["external_ref"])
        _optional_uuid4(body["linked_offer_id"])
        for order_id in _list(body["linked_order_ids"]):
            _uuid4(order_id)
        return body

    def list_tasks(self) -> dict[str, object]:
        body = self.get("/office/v1/tasks")
        _exact(body, {"tasks"})
        allowed_categories = {
            "verify",
            "prepare_offer",
            "prepare_next_version",
            "convert_accepted",
            "order_print",
            "order_effective",
            "payment",
        }
        allowed_entities = {"inquiry", "offer", "order"}
        allowed_urgency = {"overdue", "normal"}
        for raw in _list(body["tasks"]):
            row = _dict(raw)
            _exact(
                row,
                {
                    "task_id",
                    "category",
                    "title",
                    "subtitle",
                    "entity_type",
                    "entity_id",
                    "action_label",
                    "action_href",
                    "due_at",
                    "urgency",
                    "opened_at",
                },
            )
            _str(row["task_id"])
            if _str(row["category"]) not in allowed_categories:
                _bad_response()
            _str(row["title"])
            _str(row["subtitle"])
            if _str(row["entity_type"]) not in allowed_entities:
                _bad_response()
            _str(row["entity_id"])
            _str(row["action_label"])
            _str(row["action_href"])
            if row["due_at"] is not None:
                _date(row["due_at"])
            if _str(row["urgency"]) not in allowed_urgency:
                _bad_response()
            _datetime(row["opened_at"])
        return body

    def list_manual_tasks(
        self,
        *,
        employee_session_token: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> list[ManualTask]:
        query: dict[str, object] | None = None
        if subject_type is not None or subject_id is not None:
            if subject_type is None or subject_id is None:
                raise ValueError("subject_type and subject_id must be paired")
            query = {"subject_type": subject_type, "subject_id": subject_id}
        body = self.get(
            "/office/v1/manual-tasks",
            query=query,
            employee_session_token=employee_session_token,
        )
        _exact(body, {"manual_tasks"})
        return [_manual_task(raw) for raw in _list(body["manual_tasks"])]

    def list_manual_task_subjects(
        self, *, employee_session_token: str
    ) -> list[dict[str, object]]:
        body = self.get(
            "/office/v1/manual-task-subjects",
            employee_session_token=employee_session_token,
        )
        _exact(body, {"subjects"})
        results: list[dict[str, object]] = []
        for raw in _list(body["subjects"]):
            row = _dict(raw)
            _exact(
                row,
                {"subject_type", "subject_id", "contact_key", "label", "href"},
            )
            subject_type = _str(row["subject_type"])
            if subject_type not in {"CONTACT", "INQUIRY", "OFFER", "ORDER"}:
                _bad_response()
            subject_id = _optional_uuid4(row["subject_id"])
            contact_key = _optional_str(row["contact_key"])
            label = _str(row["label"])
            href = _str(row["href"])
            if subject_type == "CONTACT":
                if contact_key is None:
                    _bad_response()
            elif subject_id is None or contact_key is not None:
                _bad_response()
            results.append(
                {
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "contact_key": contact_key,
                    "label": label,
                    "href": href,
                }
            )
        return results

    def create_manual_task(
        self,
        *,
        employee_session_token: str,
        title: str,
        description: str | None = None,
        due_at: datetime | None = None,
        assigned_to_employee_id: str | None = None,
        subject_type: str = "NONE",
        subject_id: str | None = None,
        subject_contact_key: str | None = None,
        priority: str = "NORMAL",
        command_id: str | None = None,
    ) -> ManualTask:
        result = self.command(
            "/office/v1/manual-tasks",
            args={
                "title": title,
                "description": description,
                "due_at": due_at.isoformat() if due_at is not None else None,
                "assigned_to_employee_id": assigned_to_employee_id,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "subject_contact_key": subject_contact_key,
                "priority": priority,
            },
            expect={},
            expected={201},
            result_keys={"manual_task"},
            command_id=command_id,
            employee_session_token=employee_session_token,
        )
        return _manual_task(result["manual_task"])

    def complete_manual_task(
        self,
        task_id: str,
        *,
        employee_session_token: str,
        command_id: str | None = None,
    ) -> ManualTask:
        result = self.command(
            f"/office/v1/manual-tasks/{quote(task_id, safe='')}/complete",
            args={},
            expect={},
            expected={200},
            result_keys={"manual_task"},
            command_id=command_id,
            employee_session_token=employee_session_token,
        )
        return _manual_task(result["manual_task"])

    def create_chat_thread(
        self,
        *,
        employee_session_token: str,
        thread_type: str,
        participant_employee_ids: Sequence[str],
        title: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, object]:
        args: dict[str, object] = {
            "thread_type": thread_type,
            "participant_employee_ids": list(participant_employee_ids),
        }
        if title is not None:
            args["title"] = title
        result = self.command(
            "/office/v1/chat/threads",
            args=args,
            expect={},
            expected={200, 201},
            result_keys={"thread"},
            command_id=command_id,
            employee_session_token=employee_session_token,
        )
        thread = _dict(result["thread"])
        _chat_thread(thread, participants=True)
        return thread

    def list_chat_threads(
        self, *, employee_session_token: str
    ) -> list[dict[str, object]]:
        body = self.get(
            "/office/v1/chat/threads",
            employee_session_token=employee_session_token,
        )
        _exact(body, {"threads"})
        return [_chat_summary(raw) for raw in _list(body["threads"])]

    def get_chat_thread(
        self, thread_id: str, *, employee_session_token: str
    ) -> dict[str, object]:
        body = self.get(
            f"/office/v1/chat/threads/{quote(thread_id, safe='')}",
            employee_session_token=employee_session_token,
        )
        return _chat_detail(body)

    def send_chat_message(
        self,
        thread_id: str,
        *,
        employee_session_token: str,
        body: str,
        reply_to_message_id: str | None = None,
        mention_employee_ids: Sequence[str] = (),
        references: Sequence[Mapping[str, object]] = (),
        command_id: str | None = None,
    ) -> dict[str, object]:
        result = self.command(
            f"/office/v1/chat/threads/{quote(thread_id, safe='')}/messages",
            args={
                "body": body,
                "reply_to_message_id": reply_to_message_id,
                "mention_employee_ids": list(mention_employee_ids),
                "references": [dict(reference) for reference in references],
            },
            expect={},
            expected={201},
            result_keys={"message"},
            command_id=command_id,
            employee_session_token=employee_session_token,
        )
        _chat_message(result["message"])
        return _dict(result["message"])

    def mark_chat_thread_read(
        self,
        thread_id: str,
        *,
        employee_session_token: str,
        last_read_message_id: str | None,
        command_id: str | None = None,
    ) -> dict[str, object]:
        result = self.command(
            f"/office/v1/chat/threads/{quote(thread_id, safe='')}/read",
            args={"last_read_message_id": last_read_message_id},
            expect={},
            expected={200},
            result_keys={"thread_id", "employee_id", "last_read_message_id"},
            command_id=command_id,
            employee_session_token=employee_session_token,
        )
        _uuid4(result["thread_id"])
        _uuid4(result["employee_id"])
        _optional_uuid4(result["last_read_message_id"])
        return result

    def autocomplete_chat_participants(
        self,
        thread_id: str,
        *,
        employee_session_token: str,
        q: str = "",
    ) -> list[dict[str, object]]:
        body = self.get(
            f"/office/v1/chat/threads/{quote(thread_id, safe='')}/participants",
            query={"q": q} if q else None,
            employee_session_token=employee_session_token,
        )
        _exact(body, {"participants"})
        participants = []
        for raw_participant in _list(body["participants"]):
            participant = _dict(raw_participant)
            _chat_participant(participant)
            participants.append(participant)
        return participants

    def search_chat_entities(
        self,
        *,
        employee_session_token: str,
        q: str,
        reference_type: str,
    ) -> list[dict[str, object]]:
        body = self.get(
            "/office/v1/chat/entity-search",
            query={"q": q, "type": reference_type},
            employee_session_token=employee_session_token,
        )
        _exact(body, {"results"})
        return [_chat_entity_result(raw) for raw in _list(body["results"])]

    def search_chat_employees(
        self, *, employee_session_token: str, q: str = ""
    ) -> list[dict[str, object]]:
        body = self.get(
            "/office/v1/chat/employees",
            query={"q": q} if q else None,
            employee_session_token=employee_session_token,
        )
        _exact(body, {"employees"})
        return [_chat_employee(raw) for raw in _list(body["employees"])]

    def search_chat(
        self, *, employee_session_token: str, q: str
    ) -> list[dict[str, object]]:
        body = self.get(
            "/office/v1/chat/search",
            query={"q": q},
            employee_session_token=employee_session_token,
        )
        _exact(body, {"results"})
        return [_chat_summary(raw) for raw in _list(body["results"])]

    def list_calendar(self, from_date: date, to_date: date) -> dict[str, object]:
        params = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        }
        body = self.get("/office/v1/calendar", query=params)
        _exact(body, {"entries"})
        allowed_kinds = {"event_confirmed", "event_planned", "event_tentative"}
        allowed_entities = {"inquiry", "offer", "order"}
        for raw in _list(body["entries"]):
            row = _dict(raw)
            _exact(
                row,
                {
                    "entry_id",
                    "entry_kind",
                    "status_label",
                    "title",
                    "event_date",
                    "time_window_text",
                    "location_text",
                    "guest_count_estimate",
                    "entity_type",
                    "entity_id",
                    "action_label",
                    "action_href",
                    "source_inquiry_id",
                },
            )
            _str(row["entry_id"])
            if _str(row["entry_kind"]) not in allowed_kinds:
                _bad_response()
            _str(row["status_label"])
            _str(row["title"])
            _date(row["event_date"])
            _str(row["time_window_text"])
            _str(row["location_text"])
            if row["guest_count_estimate"] is not None:
                _nonnegative_int(row["guest_count_estimate"])
            if _str(row["entity_type"]) not in allowed_entities:
                _bad_response()
            _str(row["entity_id"])
            _str(row["action_label"])
            _str(row["action_href"])
            _uuid4(row["source_inquiry_id"])
        return body

    def _validate_page(
        self,
        page: dict[str, object],
        item_key: str,
        offset: int,
    ) -> list[object]:
        _exact(page, {item_key, "total_count", "limit", "offset"})
        if _int(page["limit"]) != _PAGE_SIZE or _int(page["offset"]) != offset:
            _bad_response()
        items = _list(page[item_key])
        total = _nonnegative_int(page["total_count"])
        if len(items) > _PAGE_SIZE or total < offset + len(items):
            _bad_response()
        return items

    def list_all(self) -> list[Inquiry]:
        rows: list[Inquiry] = []
        offset = 0
        while True:
            page = self.get(
                "/office/v1/inquiries", {"limit": _PAGE_SIZE, "offset": offset}
            )
            items = self._validate_page(page, "inquiries", offset)
            for item in items:
                data = _dict(item)
                rows.append(_inquiry(data, list_row=True))
                _optional_uuid4(data["linked_order_id"])
                _nonnegative_int(data["orders_total_count"])
            total = _int(page["total_count"])
            offset += len(items)
            if offset >= total or not items:
                if rows != sorted(
                    rows, key=lambda inquiry: (inquiry.event_date, inquiry.inquiry_id)
                ):
                    _bad_response()
                return rows

    def get_by_id(self, inquiry_id: str) -> Inquiry | None:
        try:
            detail = self.get(f"/office/v1/inquiries/{quote(inquiry_id, safe='')}")
            inquiry = _inquiry(detail, detail=True)
            detail_keys = set(detail)
            allowed = _INQUIRY_DETAIL_KEYS | _INQUIRY_DETAIL_OPTIONAL_KEYS
            if not _INQUIRY_DETAIL_KEYS <= detail_keys <= allowed:
                _bad_response()
            _optional_uuid4(detail["linked_order_id"])
            total = _nonnegative_int(detail["orders_total_count"])
            truncated = _bool(detail["orders_truncated"])
            orders = _list(detail["orders"])
            if total < len(orders) or truncated != (total > len(orders)):
                _bad_response()
            for raw in orders:
                row = _dict(raw)
                _exact(row, {"order_id", "cancelled_at"})
                _uuid4(row["order_id"])
                _optional_datetime(row["cancelled_at"])
            _bool(detail["allows_conversion"])
            if "contact_completeness" in detail:
                completeness = _str(detail["contact_completeness"])
                if completeness not in _CONTACT_COMPLETENESS_VALUES:
                    _bad_response()
            if "missing_contact_fields" in detail:
                for raw_field in _list(detail["missing_contact_fields"]):
                    if (
                        not isinstance(raw_field, str)
                        or raw_field not in _CONTACT_FIELD_VALUES
                    ):
                        _bad_response()
            if "contact_completion_allowed" in detail:
                _bool(detail["contact_completion_allowed"])
            next_action = _optional_inquiry_next_action(detail.get("next_action"))
            offer_preparation_blockers = (
                _offer_preparation_blockers(detail["offer_preparation_blockers"])
                if "offer_preparation_blockers" in detail
                else ()
            )
            offer = (
                _inquiry_offer_projection(detail["offer"])
                if "offer" in detail
                else None
            )
            _validate_offer_prefill(detail["offer_prefill"])
            if _uuid4(_dict(detail["offer_prefill"])["inquiry_id"]) != inquiry_id:
                _bad_response()
            self._inquiry_detail_meta[inquiry_id] = InquiryDetailMeta(
                orders_total_count=total,
                orders_truncated=truncated,
                next_action=next_action,
                offer=offer,
                offer_preparation_blockers=offer_preparation_blockers,
            )
            return inquiry
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise

    def find_by_source_and_external_ref(
        self, inquiry_source: str, intake_external_ref: str
    ) -> Inquiry | None:
        return next(
            (
                inquiry
                for inquiry in self.list_all()
                if inquiry.inquiry_source == inquiry_source
                and inquiry.intake_external_ref == intake_external_ref
            ),
            None,
        )

    def list_orders(self) -> list[Order]:
        rows: list[Order] = []
        offset = 0
        while True:
            page = self.get(
                "/office/v1/orders", {"limit": _PAGE_SIZE, "offset": offset}
            )
            items = self._validate_page(page, "orders", offset)
            for item in items:
                data = _dict(item)
                order = _order(data, list_row=True)
                rows.append(order)
                self._known_order_ids.append(order.order_id)
                reason = data["blocker_reason"]
                _next_action(data["next_action"])
                _bool(data["operational_pause_active"])
                self._evaluations[order.order_id] = ReadyToSendEvaluation(
                    order_id=order.order_id,
                    ready=_bool(data["ready"]),
                    reasons=() if reason is None else (_str(reason),),
                )
            total = _int(page["total_count"])
            offset += len(items)
            if offset >= total or not items:
                if rows != sorted(rows, key=lambda order: order.order_id):
                    _bad_response()
                return rows

    def _order_detail(self, order_id: str) -> dict[str, object] | None:
        if order_id in self._order_details:
            return self._order_details[order_id]
        try:
            detail = self.get(f"/office/v1/orders/{quote(order_id, safe='')}")
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        self._order_details[order_id] = detail
        _order(detail, detail=True)
        self._evaluations[order_id] = _ready_evaluation(
            detail["ready_to_send"], order_id
        )
        _operational_pause(detail["operational_pause"])
        _payment_reminder(detail["payment_reminder"], order_id)
        if "confirmation_document" in detail:
            self._confirmation_eligibility[order_id] = (
                _confirmation_document_eligibility(detail["confirmation_document"])
            )
        versions = _list(detail["versions"])
        total = _nonnegative_int(detail["versions_total_count"])
        truncated = _bool(detail["versions_truncated"])
        if total < len(versions) or truncated != (total > len(versions)):
            _bad_response()
        parsed_versions = [_version(_dict(raw)) for raw in versions]
        for version in parsed_versions:
            if version.order_id != order_id:
                _bad_response()
        numbers = [version.version_number for version in parsed_versions]
        if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
            _bad_response()
        self._order_version_meta[order_id] = (total, truncated)
        return detail

    def get_order(self, order_id: str) -> Order | None:
        detail = self._order_detail(order_id)
        return None if detail is None else _order(detail, detail=True)

    def list_order_versions(self, order_id: str) -> list[OrderVersion]:
        detail = self._order_detail(order_id)
        if detail is None:
            return []
        return [_version(_dict(row)) for row in _list(detail.get("versions"))]

    def inquiry_detail_meta(self, inquiry_id: str) -> InquiryDetailMeta:
        return self._inquiry_detail_meta.get(
            inquiry_id,
            InquiryDetailMeta(orders_total_count=0, orders_truncated=False),
        )

    def inquiry_orders_meta(self, inquiry_id: str) -> tuple[int, bool]:
        meta = self.inquiry_detail_meta(inquiry_id)
        return meta.orders_total_count, meta.orders_truncated

    def order_versions_meta(self, order_id: str) -> tuple[int, bool]:
        return self._order_version_meta.get(order_id, (0, False))

    def get_order_version(self, order_version_id: str) -> OrderVersion | None:
        """Global version lookup, matching the repo Protocol signature (no
        owning order_id parameter). The frozen contract has no by-version-id
        route — only ``GET /orders/{id}`` (embeds all versions) or
        ``print-data?version=`` (needs the order_id too) — so this first
        checks already-fetched order details, then falls back to fetching
        the remaining known orders (from the last ``list_orders()`` call)
        one at a time until the version turns up. Each order's detail is
        fetched at most once per request (cached in ``_order_details``), so
        repeated calls (e.g. WochenuebersichtService looping every order)
        cost at most one GET per order, not one per call."""
        for detail in self._order_details.values():
            for row in _list(detail.get("versions")):
                version = _version(_dict(row))
                if version.order_version_id == order_version_id:
                    return version
        for order_id in self._known_order_ids:
            if order_id in self._order_details:
                continue
            fetched = self._order_detail(order_id)
            if fetched is None:
                continue
            for row in _list(fetched.get("versions")):
                version = _version(_dict(row))
                if version.order_version_id == order_version_id:
                    return version
        return None

    def evaluation(self, order_id: str) -> ReadyToSendEvaluation:
        if order_id not in self._evaluations:
            self._order_detail(order_id)
        return self._evaluations.get(
            order_id,
            ReadyToSendEvaluation(
                order_id=order_id,
                ready=False,
                reasons=("ready_to_send_order_not_found",),
            ),
        )

    def payment_reminder_view(self, order_id: str) -> PaymentReminderView:
        detail = self._order_detail(order_id)
        if detail is None:
            raise RemoteCoreError(404, "not_found")
        return _payment_reminder(detail["payment_reminder"], order_id)

    def print_data(self, order_id: str, version_id: str) -> OrderPrintProjection | None:
        try:
            body = self.get(
                f"/office/v1/orders/{quote(order_id, safe='')}/print-data",
                {"version": version_id},
            )
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        _exact(body, {"order", "version", "projection"})
        projection = _print_projection(_dict(body["projection"]))
        if projection.event.order_id != order_id:
            _bad_response()
        if projection.event.order_version_id != version_id:
            _bad_response()
        return projection

    def buffet_cards_data(
        self, order_id: str, version_id: str
    ) -> BuffetCardsView | None:
        try:
            body = self.get(
                f"/office/v1/orders/{quote(order_id, safe='')}/buffet-cards-data",
                {"version": version_id},
            )
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        view = _buffet_cards_view(body)
        if view.projection.event.order_id != order_id:
            _bad_response()
        if view.projection.event.order_version_id != version_id:
            _bad_response()
        return view

    # Writes must never fall through repository semantics in remote mode: the
    # panel is wired to use the _Remote*Service facades below for every
    # mutation (named Core Office API commands only), never these repo-shaped
    # methods. Each stub matches its Protocol signature exactly — both so the
    # tripwire actually raises this message (a mismatched arity would raise a
    # plain TypeError instead) and so RemoteCoreClient stays structurally
    # assignable to InquiryRepository/OrderRepository for the read methods.
    def save(self, inquiry: Inquiry) -> None:
        self._write_forbidden()

    def update(self, inquiry: Inquiry) -> None:
        self._write_forbidden()

    def save_order_with_initial_version(
        self,
        order: Order,
        version: OrderVersion,
        operational_context: OrderVersionOperationalContextSnapshot | None = None,
    ) -> None:
        self._write_forbidden()

    def update_order(self, order: Order) -> None:
        self._write_forbidden()

    def append_order_version(
        self,
        order: Order,
        version: OrderVersion,
        operational_context: OrderVersionOperationalContextSnapshot | None = None,
    ) -> None:
        self._write_forbidden()

    def update_order_version(self, version: OrderVersion) -> None:
        self._write_forbidden()

    def get_operational_context(
        self, order_version_id: str
    ) -> OrderVersionOperationalContextSnapshot | None:
        raise RuntimeError(
            "remote panel reads operational context through print-data projections"
        )

    def _write_forbidden(self) -> NoReturn:
        raise RuntimeError("remote panel writes only through Core Office API commands")


class _RemoteInquiryService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def create_inquiry(self, **values: Any) -> Inquiry:
        args = {
            "event_date": values["event_date"].isoformat(),
            "inquiry_source": values["inquiry_source"],
            "time_window_text": values["time_window_text"],
            "location_text": values["location_text"],
            "guest_count_estimate": values["guest_count_estimate"],
            "planning_mode": values["planning_mode"],
            "call_verification_required": values["call_verification_required"],
        }
        for key in (
            "intake_subject",
            "intake_message",
            "intake_summary",
            "intake_external_ref",
            # Structured contact contract (INQUIRY_CONTACT_COMPLETENESS_V1
            # §6): the snapshot is built Core-side from these args.
            "contact_email",
            "contact_phone",
            "contact_name",
            "company_name",
        ):
            value = values.get(key)
            if value is not None:
                args[key] = value
        result = self._client.command(
            "/office/v1/inquiries",
            args,
            {},
            expected={201},
            result_keys={"inquiry_id", "updated_at"},
        )
        timestamp = _datetime(result["updated_at"])
        # Only the id is consumed before the redirect.  Returning the
        # submitted snapshot avoids a post-commit GET which could fail after
        # the write and produce the false message "nothing was saved".
        return Inquiry(
            inquiry_id=_uuid4(result["inquiry_id"]),
            event_date=values["event_date"],
            created_at=timestamp,
            updated_at=timestamp,
            inquiry_source=validate_inquiry_source(values["inquiry_source"]),
            crm_stage=validate_crm_stage(values["crm_stage"]),
            customer_linkage=validate_customer_linkage(values["customer_linkage"]),
            time_window_text=values["time_window_text"],
            location_text=values["location_text"],
            guest_count_estimate=values["guest_count_estimate"],
            planning_mode=validate_planning_mode(values["planning_mode"]),
            call_verification_required=values["call_verification_required"],
            call_verification_status=validate_call_verification_status(
                values["call_verification_status"]
            ),
            intake_subject=values.get("intake_subject"),
            intake_message=values.get("intake_message"),
            intake_summary=values.get("intake_summary"),
            intake_external_ref=values.get("intake_external_ref"),
            customer_id=None,
            # Rebuild the snapshot with the same domain rule Core applied so
            # the redirect target renders truthfully without a post-commit GET.
            customer_snapshot=snapshot_from_structured_contact(
                contact_email=values.get("contact_email"),
                contact_phone=values.get("contact_phone"),
                contact_name=values.get("contact_name"),
                company_name=values.get("company_name"),
                intake_message=values.get("intake_message"),
                intake_subject=values.get("intake_subject"),
            ),
        )

    def update_inquiry(self, inquiry_id: str, **values: Any) -> Inquiry:
        current = self._client.get_by_id(inquiry_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        args: dict[str, object] = {
            "event_date": values["event_date"].isoformat(),
            "crm_stage": values["crm_stage"],
            "time_window_text": values["time_window_text"],
            "location_text": values["location_text"],
            "guest_count_estimate": values["guest_count_estimate"],
            "planning_mode": values["planning_mode"],
        }
        for key in (
            "intake_subject",
            "intake_message",
            "intake_summary",
            "intake_external_ref",
        ):
            if key in values:
                args[key] = values[key]
        expected_at = self._client.form_value("_expect_updated_at")
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry_id, safe='')}/update",
            args,
            {"updated_at": expected_at or current.updated_at.isoformat()},
            expected={200},
            result_keys={"inquiry_id", "updated_at"},
        )
        if _uuid4(result["inquiry_id"]) != inquiry_id:
            _bad_response()
        return replace(
            current,
            event_date=values["event_date"],
            crm_stage=validate_crm_stage(values["crm_stage"]),
            time_window_text=values["time_window_text"],
            location_text=values["location_text"],
            guest_count_estimate=values["guest_count_estimate"],
            planning_mode=validate_planning_mode(values["planning_mode"]),
            updated_at=_datetime(result["updated_at"]),
            intake_subject=values.get("intake_subject", current.intake_subject),
            intake_message=values.get("intake_message", current.intake_message),
            intake_summary=values.get("intake_summary", current.intake_summary),
            intake_external_ref=values.get(
                "intake_external_ref", current.intake_external_ref
            ),
            customer_id=current.customer_id,
            customer_snapshot=current.customer_snapshot,
        )

    def complete_inquiry_contact_information(
        self,
        inquiry_id: str,
        *,
        email: str | None = None,
        phone: str | None = None,
    ) -> Inquiry:
        current = self._client.get_by_id(inquiry_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        args: dict[str, object] = {}
        if email is not None:
            args["email"] = email
        if phone is not None:
            args["phone"] = phone
        expected_at = self._client.form_value("_expect_updated_at")
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry_id, safe='')}/contact-completion",
            args,
            {"updated_at": expected_at or current.updated_at.isoformat()},
            expected={200},
            result_keys={
                "inquiry_id",
                "updated_at",
                "contact_completeness",
                "missing_contact_fields",
            },
        )
        if _uuid4(result["inquiry_id"]) != inquiry_id:
            _bad_response()
        # Reapply the same append-only domain operation locally so the
        # redirect target renders the completed snapshot without a
        # post-commit GET (same convention as update_inquiry above).
        updated = complete_inquiry_contact_information(
            current, email=email, phone=phone
        )
        return replace(updated, updated_at=_datetime(result["updated_at"]))

    def set_inquiry_customer_addresses(
        self,
        inquiry_id: str,
        *,
        invoice_address: CustomerAddress | None,
        delivery_address: CustomerAddress | None,
        delivery_address_mode: DeliveryAddressMode | str,
    ) -> Inquiry:
        current = self._client.get_by_id(inquiry_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        args: dict[str, object] = {
            "invoice_address": customer_address_to_mapping(invoice_address),
            "delivery_address": customer_address_to_mapping(delivery_address),
            "delivery_address_mode": delivery_address_mode,
        }
        expected_at = self._client.form_value("_expect_updated_at")
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry_id, safe='')}/customer-addresses",
            args,
            {"updated_at": expected_at or current.updated_at.isoformat()},
            expected={200},
            result_keys={
                "inquiry_id",
                "updated_at",
                "customer_snapshot",
            },
        )
        if _uuid4(result["inquiry_id"]) != inquiry_id:
            _bad_response()
        mapped = result["customer_snapshot"]
        if not isinstance(mapped, dict):
            _bad_response()
        # Reapply domain locally for redirect render parity (no silent defaults).
        updated = set_inquiry_customer_addresses(
            current,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
            delivery_address_mode=delivery_address_mode,
        )
        if customer_snapshot_to_mapping(updated.customer_snapshot) != mapped:
            _bad_response()
        return replace(updated, updated_at=_datetime(result["updated_at"]))

    def set_inquiry_fulfillment_mode(
        self,
        inquiry_id: str,
        *,
        fulfillment_mode: FulfillmentMode | str,
    ) -> Inquiry:
        current = self._client.get_by_id(inquiry_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        args: dict[str, object] = {"fulfillment_mode": fulfillment_mode}
        expected_at = self._client.form_value("_expect_updated_at")
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry_id, safe='')}/fulfillment-mode",
            args,
            {"updated_at": expected_at or current.updated_at.isoformat()},
            expected={200},
            result_keys={
                "inquiry_id",
                "updated_at",
                "fulfillment_mode",
            },
        )
        if _uuid4(result["inquiry_id"]) != inquiry_id:
            _bad_response()
        # Reapply domain locally for redirect render parity (no silent defaults).
        updated = set_inquiry_fulfillment_mode(current, fulfillment_mode)
        if updated.fulfillment_mode != result["fulfillment_mode"]:
            _bad_response()
        return replace(updated, updated_at=_datetime(result["updated_at"]))

    def verify_customer_by_call(self, inquiry_id: str) -> Inquiry:
        current = self._client.get_by_id(inquiry_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry_id, safe='')}/verify",
            {},
            {},
            expected={200},
            result_keys={"inquiry_id", "updated_at"},
        )
        if _uuid4(result["inquiry_id"]) != inquiry_id:
            _bad_response()
        return replace(
            current,
            call_verification_status="verified",
            updated_at=_datetime(result["updated_at"]),
        )


class _RemoteOrderService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def convert_inquiry_to_order(self, inquiry: Inquiry) -> tuple[Order, OrderVersion]:
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry.inquiry_id, safe='')}/convert",
            {},
            {},
            expected={200, 201},
            result_keys={"order_id", "order_version_id"},
        )
        order_id = _uuid4(result["order_id"])
        version_id = _uuid4(result["order_version_id"])
        # These snapshots are redirect-only return values; Core remains the
        # authority and the following GET request renders the persisted data.
        order = Order(
            order_id=order_id,
            source_inquiry_id=inquiry.inquiry_id,
            created_at=inquiry.updated_at,
            updated_at=inquiry.updated_at,
        )
        version = OrderVersion(
            order_version_id=version_id,
            order_id=order_id,
            version_number=1,
            created_at=inquiry.updated_at,
            event_date=inquiry.event_date,
            time_window_text=inquiry.time_window_text,
            location_text=inquiry.location_text,
            guest_count_estimate=inquiry.guest_count_estimate,
            planning_mode=inquiry.planning_mode,
        )
        return order, version

    def create_relevant_order_change_version(
        self, order: Order, **values: Any
    ) -> OrderVersion:
        versions = self._client.list_order_versions(order.order_id)
        total_count, _truncated = self._client.order_versions_meta(order.order_id)
        latest = total_count or max(
            (version.version_number for version in versions), default=0
        )
        expected_latest = self._client.form_value("_expect_latest_version_number")
        expected_effective = self._client.form_value(
            "_expect_current_effective_order_version_id"
        )
        expected_candidate = self._client.form_value(
            "_expect_current_candidate_order_version_id"
        )
        result = self._client.command(
            f"/office/v1/orders/{quote(order.order_id, safe='')}/versions",
            {
                "event_date": values["event_date"].isoformat(),
                "time_window_text": values["time_window_text"],
                "location_text": values["location_text"],
                "guest_count_estimate": values["guest_count_estimate"],
                "planning_mode": values["planning_mode"],
                "actor_reference": "office-panel",
                "change_reason": values.get("change_reason")
                or "Operational order change",
            },
            {
                "latest_version_number": (
                    int(expected_latest) if expected_latest is not None else latest
                ),
                "current_effective_order_version_id": (
                    order.effective_order_version_id
                    if expected_effective is None
                    else (expected_effective or None)
                ),
                "current_candidate_order_version_id": (
                    order.candidate_order_version_id
                    if expected_candidate is None
                    else (expected_candidate or None)
                ),
            },
            expected={201},
            result_keys={
                "order_version_id",
                "version_number",
                "candidate_order_version_id",
                "parent_order_version_id",
                "changed_fields",
            },
        )
        return OrderVersion(
            order_version_id=_uuid4(result["order_version_id"]),
            order_id=order.order_id,
            version_number=_int(result["version_number"]),
            created_at=order.updated_at,
            event_date=values["event_date"],
            time_window_text=values["time_window_text"],
            location_text=values["location_text"],
            guest_count_estimate=values["guest_count_estimate"],
            planning_mode=validate_planning_mode(values["planning_mode"]),
            parent_order_version_id=_optional_uuid4(result["parent_order_version_id"]),
            created_by="office-panel",
            change_reason=str(
                values.get("change_reason") or "Operational order change"
            ),
            changed_fields=tuple(
                _str(value) for value in _list(result["changed_fields"])
            ),
        )

    def propose_order_version_change(
        self, order_id: str, **values: Any
    ) -> OrderVersion:
        order = self._client.get_order(order_id)
        if order is None:
            raise RemoteCoreError(404, "not_found")
        return self.create_relevant_order_change_version(order, **values)

    def propose_delivery_address_change(
        self,
        order_id: str,
        *,
        parent_order_version_id: str,
        delivery_address: CustomerAddress | None,
        actor_reference: str,
        change_reason: str,
    ) -> OrderVersion:
        order = self._client.get_order(order_id)
        if order is None:
            raise RemoteCoreError(404, "not_found")
        versions = self._client.list_order_versions(order.order_id)
        parent = next(
            (
                version
                for version in versions
                if version.order_version_id == parent_order_version_id
            ),
            None,
        )
        if parent is None:
            raise RemoteCoreError(422, "version_not_owned")
        total_count, _truncated = self._client.order_versions_meta(order.order_id)
        latest = total_count or max(
            (version.version_number for version in versions), default=0
        )
        expected_latest = self._client.form_value("_expect_latest_version_number")
        expected_effective = self._client.form_value(
            "_expect_current_effective_order_version_id"
        )
        expected_candidate = self._client.form_value(
            "_expect_current_candidate_order_version_id"
        )
        result = self._client.command(
            f"/office/v1/orders/{quote(order.order_id, safe='')}/versions",
            {
                "parent_order_version_id": parent_order_version_id,
                "delivery_address": customer_address_to_mapping(delivery_address),
                "actor_reference": actor_reference,
                "change_reason": change_reason,
            },
            {
                "latest_version_number": (
                    int(expected_latest) if expected_latest is not None else latest
                ),
                "current_effective_order_version_id": (
                    order.effective_order_version_id
                    if expected_effective is None
                    else (expected_effective or None)
                ),
                "current_candidate_order_version_id": (
                    order.candidate_order_version_id
                    if expected_candidate is None
                    else (expected_candidate or None)
                ),
            },
            expected={201},
            result_keys={
                "order_version_id",
                "version_number",
                "candidate_order_version_id",
                "parent_order_version_id",
                "changed_fields",
            },
        )
        return OrderVersion(
            order_version_id=_uuid4(result["order_version_id"]),
            order_id=order.order_id,
            version_number=_int(result["version_number"]),
            created_at=order.updated_at,
            event_date=parent.event_date,
            time_window_text=parent.time_window_text,
            location_text=parent.location_text,
            guest_count_estimate=parent.guest_count_estimate,
            planning_mode=parent.planning_mode,
            parent_order_version_id=_optional_uuid4(result["parent_order_version_id"]),
            created_by=actor_reference,
            change_reason=change_reason,
            changed_fields=tuple(
                _str(value) for value in _list(result["changed_fields"])
            ),
        )


class _RemoteCatalogDishWriteService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def update(
        self,
        dish_id: str,
        *,
        args: dict[str, object],
        expected_updated_at: str,
    ) -> None:
        self._client.update_catalog_dish(
            dish_id,
            args=args,
            expected_updated_at=expected_updated_at,
            command_id=self._client._id(),
        )

    def create_dish(self, create: CatalogDishCreatePayload) -> CatalogDish:
        """CATALOG_ADMIN_REMOTE_CLIENT_V1: mirrors direct-mode
        CatalogDishWriteService.create_dish's name and payload type; dish_id
        and active are never accepted, matching the Office API contract."""
        return self._client.create_catalog_dish(
            name=create.name,
            category=create.category,
            pricing_unit=create.pricing_unit,
            current_unit_net_cents=create.current_unit_net_cents,
            vat_rate_percent=create.vat_rate_percent,
            description=create.description,
            composition=create.composition,
            notes=create.notes,
            allergens=create.allergens,
            command_id=self._client._id(),
        )

    def activate_dish(self, dish_id: str, *, expected_updated_at: str) -> CatalogDish:
        return self._client.activate_catalog_dish(
            dish_id,
            expected_updated_at=expected_updated_at,
            command_id=self._client._id(),
        )

    def deactivate_dish(self, dish_id: str, *, expected_updated_at: str) -> CatalogDish:
        return self._client.deactivate_catalog_dish(
            dish_id,
            expected_updated_at=expected_updated_at,
            command_id=self._client._id(),
        )


class _RemotePaymentReminderService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def view(self, order_id: str) -> PaymentReminderView:
        return self._client.payment_reminder_view(order_id)

    def save(
        self,
        reminder: OrderPaymentReminder,
        *,
        actor_reference: str = "office-panel",
        mark_payment_reminder_sent: bool = False,
        mark_mahnung_sent: bool = False,
    ) -> PaymentReminderView:
        expected_at = self._client.form_value("_expect_payment_reminder_updated_at")
        current = self.view(reminder.order_id)
        result = self._client.command(
            f"/office/v1/orders/{quote(reminder.order_id, safe='')}/payment-reminder",
            {
                "payment_method": reminder.payment_method,
                "invoice_created": reminder.invoice_created,
                "invoice_number": reminder.invoice_number,
                "sent_on": reminder.sent_on.isoformat() if reminder.sent_on else None,
                "due_on": None,
                "paid_on": reminder.paid_on.isoformat() if reminder.paid_on else None,
                "cash_received": reminder.cash_received,
                "quittung_printed": reminder.quittung_printed,
                "payment_reminder_sent": mark_payment_reminder_sent,
                "mahnung_sent": mark_mahnung_sent,
                "actor_reference": actor_reference,
            },
            {
                "updated_at": (
                    expected_at
                    if expected_at
                    else (
                        current.updated_at.isoformat() if current.updated_at else None
                    )
                )
            },
            expected={200},
            result_keys={"order_id", "updated_at"},
        )
        if _uuid4(result["order_id"]) != reminder.order_id:
            _bad_response()
        return replace(current, updated_at=_datetime(result["updated_at"]))


class _RemoteOperationalCoreService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def evaluate_ready_to_send(self, order_id: str) -> ReadyToSendEvaluation:
        return self._client.evaluation(order_id)

    def request_ready_to_send(self, order_id: str) -> ReadyToSendEvaluation:
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/ready",
            {},
            {},
            expected={200},
            result_keys={"evaluation"},
        )
        return _ready_evaluation(result["evaluation"], order_id)

    def confirm_kitchen_print(
        self, order_id: str, order_version_id: str
    ) -> OrderVersion:
        versions = self._client.list_order_versions(order_id)
        current = next(
            (
                version
                for version in versions
                if version.order_version_id == order_version_id
            ),
            None,
        )
        if current is None:
            raise RemoteCoreError(422, "version_not_owned")
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/print-confirm",
            {"order_version_id": order_version_id},
            {},
            expected={200},
            result_keys={
                "order_id",
                "order_version_id",
                "print_job_id",
                "kitchen_print_confirmed_at",
            },
        )
        if (
            _uuid4(result["order_id"]) != order_id
            or _uuid4(result["order_version_id"]) != order_version_id
        ):
            _bad_response()
        return replace(
            current,
            kitchen_print_confirmed_at=_optional_datetime(
                result["kitchen_print_confirmed_at"]
            ),
        )

    def make_order_version_effective(
        self, order_id: str, order_version_id: str
    ) -> Order:
        current = self._client.get_order(order_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        expected_effective = self._client.form_value("_expect_effective_version_id")
        expected_candidate = self._client.form_value("_expect_candidate_version_id")
        expect_value = (
            current.effective_order_version_id
            if expected_effective is None
            else (expected_effective or None)
        )
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/effective",
            {"order_version_id": order_version_id},
            {
                "current_effective_order_version_id": expect_value,
                "current_candidate_order_version_id": (
                    current.candidate_order_version_id
                    if expected_candidate is None
                    else (expected_candidate or None)
                ),
            },
            expected={200},
            result_keys={
                "order_id",
                "effective_order_version_id",
                "candidate_order_version_id",
                "updated_at",
            },
        )
        if (
            _uuid4(result["order_id"]) != order_id
            or _uuid4(result["effective_order_version_id"]) != order_version_id
        ):
            _bad_response()
        return replace(
            current,
            effective_order_version_id=order_version_id,
            candidate_order_version_id=None,
            updated_at=_datetime(result["updated_at"]),
        )

    def cancel_order(self, order_id: str) -> Order:
        current = self._client.get_order(order_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        expected_at = self._client.form_value("_expect_updated_at")
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/cancel",
            {},
            {"updated_at": expected_at or current.updated_at.isoformat()},
            expected={200},
            result_keys={"order_id", "cancelled_at", "updated_at"},
        )
        if _uuid4(result["order_id"]) != order_id:
            _bad_response()
        self._client._order_details.pop(order_id, None)
        return replace(
            current,
            cancelled_at=_datetime(result["cancelled_at"]),
            updated_at=_datetime(result["updated_at"]),
        )

    def get_operational_pause_projection(self, order_id: str) -> dict[str, object]:
        detail = self._client._order_detail(order_id)
        if detail is None:
            raise RemoteCoreError(404, "not_found")
        return _operational_pause(detail["operational_pause"])

    def get_active_operational_pause(self, order_id: str) -> dict[str, object] | None:
        detail = self._client._order_detail(order_id)
        if detail is None:
            return None
        pause = _operational_pause(detail["operational_pause"])
        if not _bool(pause["active"]):
            return None
        return pause

    def pause_order(
        self,
        order_id: str,
        *,
        reason_code: str,
        note: str | None,
        actor_reference: str,
        command_id: str,
        expected_latest_pause_event_id: str | None,
    ) -> dict[str, object]:
        detail = self._client._order_detail(order_id)
        if detail is None:
            raise RemoteCoreError(404, "not_found")
        _operational_pause(detail["operational_pause"])
        args: dict[str, object] = {"reason_code": reason_code}
        if note is not None:
            args["note"] = note
        if actor_reference:
            args["actor_reference"] = actor_reference
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/pause",
            args,
            {
                "operational_pause_active": False,
                "latest_pause_event_id": expected_latest_pause_event_id,
            },
            expected={200},
            result_keys={"order_id", "pause_event_id", "operational_pause"},
            command_id=command_id,
        )
        if _uuid4(result["order_id"]) != order_id:
            _bad_response()
        self._client._order_details.pop(order_id, None)
        return _operational_pause(result["operational_pause"])

    def resume_order(
        self,
        order_id: str,
        *,
        reason_code: str,
        note: str | None,
        actor_reference: str,
        command_id: str,
        expected_current_pause_event_id: str,
        expected_latest_pause_event_id: str,
    ) -> dict[str, object]:
        detail = self._client._order_detail(order_id)
        if detail is None:
            raise RemoteCoreError(404, "not_found")
        pause = _operational_pause(detail["operational_pause"])
        if not _bool(pause["active"]):
            raise RemoteCoreError(409, "order_not_paused")
        args: dict[str, object] = {"reason_code": reason_code}
        if note is not None:
            args["note"] = note
        if actor_reference:
            args["actor_reference"] = actor_reference
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/resume",
            args,
            {
                "operational_pause_active": True,
                "current_pause_event_id": expected_current_pause_event_id,
                "latest_pause_event_id": expected_latest_pause_event_id,
            },
            expected={200},
            result_keys={"order_id", "pause_event_id", "operational_pause"},
            command_id=command_id,
        )
        if _uuid4(result["order_id"]) != order_id:
            _bad_response()
        self._client._order_details.pop(order_id, None)
        return _operational_pause(result["operational_pause"])


_CONFIRMATION_DOCUMENT_KEYS = frozenset(
    {
        "state",
        "available",
        "can_prepare",
        "blocker_code",
        "snapshot",
    }
)
_CONFIRMATION_SUMMARY_KEYS = frozenset(
    {
        "document_snapshot_id",
        "order_id",
        "order_version_id",
        "document_reference",
        "created_at",
        "created_by",
        "recipient_status",
        "recipient_email_masked",
        "document_hash_short",
        "net_total_cents",
        "vat_total_cents",
        "gross_total_cents",
        "effective_version_number",
    }
)
_CUSTOMER_DOCUMENT_PREVIEW_KEYS = frozenset(
    {
        "document_type",
        "eligible",
        "fulfillment_mode",
        "blockers",
        "warnings",
        "recipient",
        "event",
        "commercial",
        "positions",
        "payment_method",
        "payment_customer_visible_text",
        "net_total_cents",
        "vat_total_cents",
        "gross_total_cents",
    }
)
_PREVIEW_RECIPIENT_KEYS = frozenset(
    {
        "name",
        "email",
        "company_name",
        "phone",
        "invoice_address",
        "delivery_address",
        "delivery_address_differs",
    }
)
_PREVIEW_ADDRESS_KEYS = frozenset({"street", "postal_code", "city", "country"})
_PREVIEW_BLOCKER_KEYS = frozenset({"code", "detail"})
_PREVIEW_COMMERCIAL_KEYS = frozenset(
    {
        "snapshot_id",
        "source_offer_id",
        "source_offer_version_id",
        "variant_label",
    }
)
_PREVIEW_EVENT_KEYS = frozenset(
    {
        "order_id",
        "order_version_id",
        "version_number",
        "event_date",
        "time_window_text",
        "location_text",
        "guest_count_estimate",
        "planning_mode",
    }
)
_PREVIEW_POSITION_KEYS = frozenset(
    {
        "position_id",
        "kind",
        "name",
        "description",
        "composition",
        "quantity",
        "unit_label",
        "unit_net_cents",
        "net_total_cents",
        "vat_rate_percent",
        "vat_amount_cents",
        "gross_total_cents",
        "related_position_id",
    }
)
_DOCUMENT_BLOCKER_CODE_SET: frozenset[str] = frozenset(DOCUMENT_BLOCKER_CODES)
_DOCUMENT_WARNING_SET: frozenset[str] = frozenset({WARNING_DELIVERY_ADDRESS_DIFFERS})
_PAYMENT_METHOD_SET: frozenset[str] = frozenset(PAYMENT_METHODS)


def _confirmation_document_summary(raw: object) -> OrderConfirmationDocumentSummary:
    data = _dict(raw)
    _exact(data, _CONFIRMATION_SUMMARY_KEYS)
    return OrderConfirmationDocumentSummary(
        document_snapshot_id=_uuid4(data["document_snapshot_id"]),
        order_id=_uuid4(data["order_id"]),
        order_version_id=_uuid4(data["order_version_id"]),
        document_reference=_str(data["document_reference"]),
        created_at=_datetime(data["created_at"]),
        created_by=_str(data["created_by"]),
        recipient_status=(
            "ready" if _str(data["recipient_status"]) == "ready" else "missing"
        ),
        recipient_email_masked=_optional_str(data["recipient_email_masked"]),
        document_hash_short=_str(data["document_hash_short"]),
        net_total_cents=_int(data["net_total_cents"]),
        vat_total_cents=_int(data["vat_total_cents"]),
        gross_total_cents=_int(data["gross_total_cents"]),
        effective_version_number=_int(data["effective_version_number"]),
    )


def _confirmation_document_eligibility(
    raw: object,
) -> OrderConfirmationDocumentEligibility:
    data = _dict(raw)
    _exact(data, _CONFIRMATION_DOCUMENT_KEYS)
    snapshot_raw = data.get("snapshot")
    snapshot = (
        _confirmation_document_summary(snapshot_raw)
        if snapshot_raw is not None
        else None
    )
    blocker = data.get("blocker_code")
    return OrderConfirmationDocumentEligibility(
        available=_bool(data["available"]),
        state=_str(data["state"]),
        blocker_code=_optional_str(blocker),
        can_prepare=_bool(data["can_prepare"]),
        snapshot=snapshot,
    )


def _preview_address(raw: object) -> CustomerAddress | None:
    if raw is None:
        return None
    data = _dict(raw)
    _exact(data, _PREVIEW_ADDRESS_KEYS)
    try:
        return CustomerAddress(
            street=_optional_str(data["street"]),
            postal_code=_optional_str(data["postal_code"]),
            city=_optional_str(data["city"]),
            country=_optional_str(data["country"]),
        )
    except ValueError:
        _bad_response()


def _preview_blocker(raw: object) -> DocumentBlocker:
    data = _dict(raw)
    _exact(data, _PREVIEW_BLOCKER_KEYS)
    code = _str(data["code"])
    if code not in _DOCUMENT_BLOCKER_CODE_SET:
        _bad_response()
    try:
        return DocumentBlocker(
            code=cast(DocumentBlockerCode, code),
            detail=_optional_str(data["detail"]),
        )
    except ValueError:
        _bad_response()


def _preview_warnings(raw: object) -> tuple[CustomerDocumentWarning, ...]:
    items = _list(raw)
    warnings: list[CustomerDocumentWarning] = []
    for item in items:
        code = _str(item)
        if code not in _DOCUMENT_WARNING_SET:
            _bad_response()
        warnings.append(cast(CustomerDocumentWarning, code))
    return tuple(warnings)


def _preview_recipient(raw: object) -> CustomerDocumentRecipient:
    data = _dict(raw)
    _exact(data, _PREVIEW_RECIPIENT_KEYS)
    differs = _bool(data["delivery_address_differs"])
    invoice = _preview_address(data["invoice_address"])
    delivery = _preview_address(data["delivery_address"])
    recipient_warnings: tuple[CustomerDocumentWarning, ...] = (
        (WARNING_DELIVERY_ADDRESS_DIFFERS,) if differs else ()
    )
    try:
        return CustomerDocumentRecipient(
            name=_str(data["name"]),
            email=_optional_str(data["email"]),
            company_name=_optional_str(data["company_name"]),
            phone=_optional_str(data["phone"]),
            invoice_address=invoice,
            delivery_address=delivery,
            delivery_address_differs=differs,
            warnings=recipient_warnings,
        )
    except ValueError:
        _bad_response()


def _preview_commercial(
    raw: object,
) -> CustomerDocumentCommercialReference | None:
    if raw is None:
        return None
    data = _dict(raw)
    _exact(data, _PREVIEW_COMMERCIAL_KEYS)
    try:
        return CustomerDocumentCommercialReference(
            snapshot_id=_str(data["snapshot_id"]),
            source_offer_id=_str(data["source_offer_id"]),
            source_offer_version_id=_str(data["source_offer_version_id"]),
            variant_label=_str(data["variant_label"]),
        )
    except ValueError:
        _bad_response()


def _preview_event(raw: object) -> CustomerDocumentEvent | None:
    if raw is None:
        return None
    data = _dict(raw)
    _exact(data, _PREVIEW_EVENT_KEYS)
    planning = _str(data["planning_mode"])
    if planning not in PLANNING_MODE_SET:
        _bad_response()
    try:
        return CustomerDocumentEvent(
            order_id=_str(data["order_id"]),
            order_version_id=_str(data["order_version_id"]),
            version_number=_nonnegative_int(data["version_number"]),
            event_date=_date(data["event_date"]),
            time_window_text=_str(data["time_window_text"]),
            location_text=_str(data["location_text"]),
            guest_count_estimate=_optional_int(data["guest_count_estimate"]),
            planning_mode=cast(PlanningMode, planning),
        )
    except ValueError:
        _bad_response()


def _preview_position(raw: object) -> CustomerDocumentPosition:
    data = _dict(raw)
    _exact(data, _PREVIEW_POSITION_KEYS)
    try:
        return CustomerDocumentPosition(
            position_id=_str(data["position_id"]),
            kind=_str(data["kind"]),
            name=_str(data["name"]),
            description=_optional_str(data["description"]),
            composition=_optional_str(data["composition"]),
            quantity=_optional_str(data["quantity"]),
            unit_label=_optional_str(data["unit_label"]),
            unit_net_cents=_nonnegative_int(data["unit_net_cents"]),
            net_total_cents=_nonnegative_int(data["net_total_cents"]),
            vat_rate_percent=_int(data["vat_rate_percent"]),
            vat_amount_cents=_nonnegative_int(data["vat_amount_cents"]),
            gross_total_cents=_nonnegative_int(data["gross_total_cents"]),
            related_position_id=_optional_str(data["related_position_id"]),
        )
    except ValueError:
        _bad_response()


def _customer_document_preview(raw: object) -> CustomerDocumentPreview:
    data = _dict(raw)
    _exact(data, _CUSTOMER_DOCUMENT_PREVIEW_KEYS)
    document_type_raw = _str(data["document_type"])
    if document_type_raw != "ORDER_CONFIRMATION":
        _bad_response()
    document_type: DocumentType = "ORDER_CONFIRMATION"
    eligible = _bool(data["eligible"])
    fulfillment_mode = validate_fulfillment_mode(_str(data["fulfillment_mode"]))
    blockers = tuple(_preview_blocker(item) for item in _list(data["blockers"]))
    warnings = _preview_warnings(data["warnings"])
    recipient = _preview_recipient(data["recipient"])
    if (WARNING_DELIVERY_ADDRESS_DIFFERS in warnings) != (
        recipient.delivery_address_differs
    ):
        _bad_response()
    payment_raw = data["payment_method"]
    payment: PaymentMethod | None
    if payment_raw is None:
        payment = None
    else:
        method = _str(payment_raw)
        if method not in _PAYMENT_METHOD_SET:
            _bad_response()
        payment = cast(PaymentMethod, method)
    try:
        return CustomerDocumentPreview(
            document_type=document_type,
            eligible=eligible,
            warnings=warnings,
            blockers=blockers,
            recipient=recipient,
            event=_preview_event(data["event"]),
            commercial_reference=_preview_commercial(data["commercial"]),
            positions=tuple(
                _preview_position(item) for item in _list(data["positions"])
            ),
            payment_method=payment,
            payment_customer_visible_text=_optional_str(
                data["payment_customer_visible_text"]
            ),
            net_total_cents=_optional_int(data["net_total_cents"]),
            vat_total_cents=_optional_int(data["vat_total_cents"]),
            gross_total_cents=_optional_int(data["gross_total_cents"]),
            fulfillment_mode=fulfillment_mode,
        )
    except ValueError:
        _bad_response()


class _RemoteConfirmationDocumentService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def eligibility(self, order_id: str) -> OrderConfirmationDocumentEligibility:
        if order_id in self._client._confirmation_eligibility:
            return self._client._confirmation_eligibility[order_id]
        detail = self._client._order_detail(order_id)
        if detail is None:
            raise ValueError(f"no order with id {order_id!r}")
        return self._client._confirmation_eligibility.get(
            order_id,
            OrderConfirmationDocumentEligibility(
                available=False,
                state="nicht_verfuegbar",
                blocker_code="nicht_verfuegbar",
                can_prepare=False,
            ),
        )

    def prepare_snapshot(
        self,
        order_id: str,
        expected_effective_order_version_id: str,
        created_by: str,
    ) -> OrderConfirmationDocumentSummary:
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/confirmation-document",
            {"created_by": created_by},
            {"current_effective_order_version_id": expected_effective_order_version_id},
            expected={201, 200},
            result_keys={"order_id", "document_snapshot_id", "snapshot"},
        )
        if _uuid4(result["order_id"]) != order_id:
            _bad_response()
        summary = _confirmation_document_summary(result["snapshot"])
        return summary

    def preview_html(self, order_id: str) -> str:
        return self._client.get_text(
            f"/office/v1/orders/{quote(order_id, safe='')}/confirmation-document/preview",
            {"format": "html"},
        )

    def preview_order_confirmation(self, order_id: str) -> CustomerDocumentPreview:
        """Live CDP preview before create — V1-E (exact-key, fail-closed)."""
        payload = self._client.get(
            f"/office/v1/orders/{quote(order_id, safe='')}/confirmation-preview"
        )
        return _customer_document_preview(payload)


class _RemoteConfirmationOutboundService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def send_eligibility(
        self,
        order_id: str,
        *,
        document_snapshot_id: str | None = None,
    ) -> OutboundSendEligibility:
        confirmation = self._client.confirmation_document_service.eligibility(order_id)
        snapshot = confirmation.snapshot
        if (
            document_snapshot_id is not None
            and snapshot is not None
            and snapshot.document_snapshot_id != document_snapshot_id
        ):
            snapshot = None
        if snapshot is None:
            return OutboundSendEligibility(
                state="dokument_fehlt",
                can_send=False,
                blocker_code="dokument_fehlt",
            )
        status = self._client.get(
            f"/office/v1/orders/{quote(order_id, safe='')}/confirmation-document/send-status"
        )
        if status.get("state") == "sent":
            summary = OutboundSendSummary(
                send_attempt_id=_str(status["send_attempt_id"]),
                send_evidence_id=_str(status["send_evidence_id"]),
                fake_outbox_message_id=_str(status["fake_outbox_message_id"]),
                document_snapshot_id=_str(status["document_snapshot_id"]),
                document_hash=_str(status["document_hash"]),
                document_hash_short=_str(status["document_hash_short"]),
                payload_hash=_str(status["payload_hash"]),
                payload_hash_short=_str(status["payload_hash_short"]),
                recipient_email_masked=_str(status["recipient_email_masked"]),
                transport_kind=_str(status["transport_kind"]),
                outcome=_str(status["outcome"]),
                accepted_at=_str(status["accepted_at"]),
                real_delivery=False,
            )
            return OutboundSendEligibility(
                state="testversand_protokolliert",
                can_send=False,
                send_summary=summary,
            )
        blocker_map = {
            "empfaenger_fehlt": "empfaenger_fehlt",
            "aenderung_wartet": "pending_order_version_change",
        }
        if confirmation.blocker_code in blocker_map:
            state = blocker_map[confirmation.blocker_code]
            return OutboundSendEligibility(
                state=state,
                can_send=False,
                blocker_code=state,
            )
        if confirmation.state != "dokument_erstellt":
            return OutboundSendEligibility(
                state="dokument_fehlt",
                can_send=False,
                blocker_code="dokument_fehlt",
            )
        return OutboundSendEligibility(
            state="testversand_bereit",
            can_send=True,
        )

    def send_to_fake_outbox(
        self,
        order_id: str,
        document_snapshot_id: str,
        expected_effective_order_version_id: str,
        requested_by: str,
    ) -> None:
        self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/confirmation-document/send",
            {
                "document_snapshot_id": document_snapshot_id,
                "requested_by": requested_by,
            },
            {"current_effective_order_version_id": expected_effective_order_version_id},
            expected={201, 200, 409},
            result_keys={
                "order_id",
                "send_attempt_id",
                "send_evidence_id",
                "fake_outbox_message_id",
                "document_snapshot_id",
                "document_hash",
                "payload_hash",
                "recipient_email_masked",
                "transport_kind",
                "outcome",
                "accepted_at",
                "real_delivery",
            },
        )

    def fake_outbox_message(
        self, order_id: str, *, document_snapshot_id: str | None = None
    ) -> FakeOutboxMessage:
        query: dict[str, object] = {}
        if document_snapshot_id is not None:
            query["document_snapshot_id"] = document_snapshot_id
        raw = self._client.get(
            f"/office/v1/orders/{quote(order_id, safe='')}/confirmation-document/fake-outbox",
            query or None,
        )
        from datetime import UTC, datetime

        return FakeOutboxMessage(
            fake_outbox_message_id=_str(raw["fake_outbox_message_id"]),
            send_attempt_id=_str(raw["send_attempt_id"]),
            order_id=order_id,
            document_snapshot_id=_str(raw["document_snapshot_id"]),
            recipient_email=_str(raw["recipient_email"]),
            subject=_str(raw["subject"]),
            text_body=_str(raw["text_body"]),
            html_body=_str(raw["html_body"]),
            payload_hash=_str(raw["payload_hash"]),
            created_at=datetime.now(UTC),
        )

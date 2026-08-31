"""Core Office API — the office panel's only path to core.db
(PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1, frozen 38930bf).

stdlib-only, single-threaded (sqlite3 thread affinity, WORKLOG Entry 048),
no outbound HTTP. Every route is a named business read or command mapping
onto the existing services and their gates — no generic CRUD. Bearer is
checked before anything else on every method; commands are atomic with
their idempotency-ledger record; domain events flush only post-commit.

Logs carry route, status, command_id and opaque Core IDs only — never
contacts, addresses, payloads, or tokens (pack §5).
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import re
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TypeVar
from urllib.parse import parse_qsl, quote, unquote, urlparse

from catering_system.domain.catalog import (
    AllergenCode,
    CatalogDishAlreadyExistsError,
    CatalogDishCreatePayload,
    CatalogDishNotFoundError,
    CatalogDishStaleError,
    CatalogDishUpdatePayload,
    validate_allergen_codes,
    validate_pricing_unit,
)
from catering_system.domain.chat import (
    ChatMessage,
    ChatMessageBundle,
    ChatParticipant,
    ChatReferenceType,
    ChatThread,
    ChatThreadSummary,
    validate_chat_reference_type,
    validate_chat_thread_type,
)
from catering_system.domain.customer_gastronomic_preference import (
    CustomerGastronomicPreference,
    validate_preference_kind,
    validate_preference_source,
)
from catering_system.domain.customer_order_history import CustomerOrderHistoryEntry
from catering_system.domain.courier_cash_handoff import (
    CourierCashCommand,
    UnsupportedCourierCashContractVersion,
)
from catering_system.domain.customer_document_eligibility import (
    CustomerDocumentCreationBlocked,
)
from catering_system.domain.employee_auth import AuthenticatedEmployee
from catering_system.domain.inquiry import (
    ACTIVE_ORDER_CRM_STAGE,
    CRM_PIPELINE,
    inquiry_crm_stage_is_compatible_with_active_order,
    validate_crm_stage,
    validate_fulfillment_mode,
    validate_planning_mode,
)
from catering_system.domain.inquiry_contact_completeness import (
    derive_inquiry_contact_completeness,
    missing_contact_fields,
)
from catering_system.domain.inquiry_customer_snapshot import (
    customer_address_from_mapping,
    customer_snapshot_to_mapping,
    validate_delivery_address_mode,
)
from catering_system.domain.manual_task import (
    ManualTask,
    ManualTaskSubjectType,
    validate_manual_task_priority,
    validate_manual_task_subject_type,
)
from catering_system.domain.offer import (
    ACCEPTANCE_CHANNELS,
    SENT_CHANNELS,
    AcceptanceChannel,
    SentChannel,
)
from catering_system.domain.offer_document_snapshot import (
    OfferDocumentCreationBlocked,
    OfferDocumentVariantConflictError,
)
from catering_system.domain.offer_pdf import (
    OfferPdfRenderError,
    OfferPdfStaticContent,
    OfferPdfUnsupportedCharacterError,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import (
    MissingCommercialSnapshotError,
)
from catering_system.domain.order_payment_reminder import (
    OrderPaymentReminder,
    validate_payment_method,
)
from catering_system.repositories.bootstrap_customer_identity_schema import (
    bootstrap_customer_identity_schema,
)
from catering_system.repositories.bootstrap_employee_auth_schema import (
    bootstrap_employee_auth_schema,
)
from catering_system.repositories.core_transaction import (
    CoreBusyError,
    CoreCommandExecutor,
    DeferredEventSink,
    open_core_connection,
)
from catering_system.repositories.inquiry_repository import (
    DuplicateExternalReferenceError,
)
from catering_system.repositories.office_api_ledger import (
    OfficeCommandLedger,
    command_fingerprint,
)
from catering_system.repositories.sqlite_catalog_repository import (
    SQLiteCatalogRepository,
)
from catering_system.repositories.sqlite_chat_repository import SQLiteChatRepository
from catering_system.repositories.sqlite_courier_cash_repository import (
    SQLiteCourierCashRepository,
)
from catering_system.repositories.sqlite_configurator_handoff_repository import (
    SQLiteConfiguratorHandoffRepository,
)
from catering_system.repositories.sqlite_contact_profile_repository import (
    SQLiteContactProfileRepository,
)
from catering_system.repositories.sqlite_customer_gastronomic_preference_repository import (
    SQLiteCustomerGastronomicPreferenceRepository,
)
from catering_system.repositories.sqlite_customer_identity_repository import (
    SQLiteCustomerIdentityRepository,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_kitchen_print_job_repository import (
    SQLiteKitchenPrintJobRepository,
)
from catering_system.repositories.sqlite_manual_task_repository import (
    SQLiteManualTaskRepository,
)
from catering_system.repositories.sqlite_offer_document_snapshot_repository import (
    SQLiteOfferDocumentSnapshotRepository,
)
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
)
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_confirmation_document_repository import (
    SQLiteOrderConfirmationDocumentRepository,
)
from catering_system.repositories.sqlite_order_confirmation_outbound_repository import (
    SQLiteOrderConfirmationOutboundRepository,
)
from catering_system.repositories.sqlite_order_operational_pause_repository import (
    SQLiteOrderOperationalPauseRepository,
)
from catering_system.repositories.sqlite_production_capacity_repository import (
    SQLiteProductionCapacityRepository,
)
from catering_system.repositories.order_purge import purge_order_with_dependencies
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.repositories.sqlite_payment_reminder_repository import (
    SQLitePaymentReminderRepository,
)
from catering_system.services.buffet_cards_service import BuffetCardsService
from catering_system.services.calendar_projection_service import (
    CalendarProjectionService,
)
from catering_system.services.catalog_dish_service import CatalogDishService
from catering_system.services.catalog_dish_write_service import CatalogDishWriteService
from catering_system.services.chat_service import (
    ChatAccessDenied,
    ChatNotFoundError,
    ChatReferenceNotFoundError,
    ChatService,
)
from catering_system.services.courier_cash_context_service import (
    CourierCashContextService,
)
from catering_system.services.courier_cash_service import (
    CourierCashCommandError,
    CourierCashService,
)
from catering_system.services.customer_order_history_service import (
    CustomerOrderHistoryCustomerNotFoundError,
    CustomerOrderHistoryService,
)
from catering_system.services.customer_gastronomic_preference_service import (
    CustomerGastronomicPreferenceNotFoundError,
    CustomerGastronomicPreferenceService,
    CustomerNotFoundError,
)
from catering_system.services.configurator_handoff_service import (
    HANDOFF_OPERATION_PREPARE_FIRST_OFFER,
    ConfiguratorHandoffService,
)
from catering_system.services.contact_profile_service import ContactProfileService
from catering_system.services.contact_projection_service import ContactProjectionService
from catering_system.services.customer_document_preview import (
    CustomerDocumentPreviewNotFoundError,
    CustomerDocumentPreviewService,
)
from catering_system.services.email_intake_projection_service import (
    EmailIntakeProjectionService,
)
from catering_system.services.employee_auth_service import (
    AuthenticationError,
    EmployeeAuthService,
)
from catering_system.services.inquiry_service import (
    InquiryService,
    validate_inquiry_source,
)
from catering_system.services.kitchen_print_service import KitchenPrintService
from catering_system.services.manual_task_service import ManualTaskService
from catering_system.services.offer_document_snapshot_service import (
    OfferDocumentNotFoundError,
    OfferDocumentSnapshotService,
)
from catering_system.services.offer_pdf_renderer import (
    offer_document_pdf_filename,
    render_offer_document_pdf,
)
from catering_system.services.offer_queue_projection_service import (
    OfferQueueProjectionService,
)
from catering_system.services.offer_service import (
    OfferPreparationBlockedError,
    OfferService,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.recommendation_capacity_service import (
    RecommendationCapacityService,
)
from catering_system.services.recommendation_demand_service import (
    RecommendationDemandService,
)
from catering_system.services.order_confirmation_document_preview import (
    build_preview,
    render_preview_html,
)
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentBlockedError,
    OrderConfirmationDocumentNotFoundError,
    OrderConfirmationDocumentService,
    OrderConfirmationDocumentStaleVersionError,
)
from catering_system.services.order_confirmation_outbound_service import (
    OrderConfirmationOutboundAlreadySentError,
    OrderConfirmationOutboundBlockedError,
    OrderConfirmationOutboundNotFoundError,
    OrderConfirmationOutboundPayloadInvalidError,
    OrderConfirmationOutboundRecipientMissingError,
    OrderConfirmationOutboundService,
    OrderConfirmationOutboundStaleVersionError,
)
from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
    PrintFinalRequiresEffectiveError,
    PrintProjectionNotFoundError,
)
from catering_system.services.order_service import (
    OperationalContextMissingError,
    OrderService,
)
from catering_system.services.payment_reminder_service import PaymentReminderService
from catering_system.services.task_projection_service import TaskProjectionService
from catering_system.services.wochenuebersicht_service import WochenuebersichtService
from catering_system.services.work_center_service import WorkCenterService
from catering_system.ui import office_api_views as views
from catering_system.ui.office_api_employee_introspect import (
    EMPLOYEE_INTROSPECT_PATH,
    parse_employee_session_header_values,
    perform_employee_introspection,
)
from catering_system.ui.office_api_service_auth import (
    OfficeApiServiceAuth,
    read_introspection_service_tokens_from_env,
)
from catering_system.ui.office_panel_offer_prefill import offer_prefill_payload

_log = logging.getLogger(__name__)

CLIENT_ID = "office-panel"  # per-client token identity (pack §6.1)
CONFIGURATOR_HANDOFF_SERVICE_ID = "configurator-handoff"
_MAX_BODY_BYTES = 64 * 1024
_MAX_COURIER_CASH_BODY_BYTES = 16 * 1024
_COURIER_CASH_PATH = "/machine/v1/courier/cash-events"
_MAX_PREPARE_OFFER_BODY_BYTES = 256 * 1024
_MAX_RESPONSE_BYTES = 512 * 1024  # pack §4.0 hard response cap
_MAX_Q_CHARS = 200
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_EnumValue = TypeVar("_EnumValue", bound=str)


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        retry_after: bool = False,
        *,
        reasons: tuple[str, ...] | None = None,
        offer_id: str | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.retry_after = retry_after
        self.reasons = reasons
        self.offer_id = offer_id


def _invalid() -> ApiError:
    return ApiError(400, "invalid_request")


# --- strict JSON / value validation ------------------------------------------


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def strict_json_loads(raw: bytes) -> dict[str, object]:
    try:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise _invalid() from exc
    if not isinstance(document, dict):
        raise _invalid()
    return document


def _v_str(value: object, max_len: int) -> str:
    if not isinstance(value, str) or len(value) > max_len:
        raise _invalid()
    return value


def _v_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise _invalid()
    return value


def _v_query_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise _invalid()


def _catalog_active_filter(params: dict[str, str]) -> bool | None:
    """CATALOG_ADMIN_PANEL_V1: resolves the catalog list's status filter.

    `active` is the current contract — true/false select one status, omitted
    means no filter. `active_only` is kept as a legacy alias because it is a
    published query parameter: `active_only=true` still means "active only",
    and `active_only=false` keeps its original meaning of *no* filter (it
    never selected inactive dishes).

    Sending both is rejected with 400 rather than resolved by precedence:
    `active=false&active_only=true` has no honest answer, and silently
    picking one would hide a caller's bug behind a wrong dish list.
    """
    if "active" in params and "active_only" in params:
        raise _invalid()
    if "active" in params:
        return _v_query_bool(params["active"])
    if "active_only" in params:
        return True if _v_query_bool(params["active_only"]) else None
    return None


def _v_date(value: object) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise _invalid()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid() from exc


def _v_optional_date(value: object) -> date | None:
    return None if value is None else _v_date(value)


def _v_optional_local_time(value: object) -> time | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise _invalid()
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise _invalid() from exc
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise _invalid()
    return parsed


def _v_optional_str(value: object, max_len: int) -> str | None:
    if value is None:
        return None
    result = _v_str(value, max_len).strip()
    return result or None


def _v_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _invalid() from exc
    # pack §4.1: timestamps are ISO-8601 UTC with offset — a naive value or a
    # non-UTC offset is a type violation, not silently accepted (utcoffset() is
    # None for naive datetimes, so this rejects both).
    if parsed.utcoffset() != timedelta(0):
        raise _invalid()
    return parsed


def _v_optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _v_datetime(value)


def _v_guest_count(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid()
    if not 1 <= value <= 2000:
        raise _invalid()
    return value


def _v_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid()
    return value


def _v_enum(  # noqa: UP047
    value: object, validator: Callable[[str], _EnumValue]
) -> _EnumValue:
    if not isinstance(value, str):
        raise _invalid()
    try:
        return validator(value)
    except (ValueError, TypeError) as exc:
        raise _invalid() from exc


def _v_sent_channel(value: object) -> SentChannel:
    if not isinstance(value, str) or value not in SENT_CHANNELS:
        raise _invalid()
    channel: SentChannel = value
    return channel


def _v_acceptance_channel(value: object) -> AcceptanceChannel:
    if not isinstance(value, str) or value not in ACCEPTANCE_CHANNELS:
        raise _invalid()
    channel: AcceptanceChannel = value
    return channel


def _v_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid()
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise _invalid() from exc
    # pack §4.3: command_id is a uuid4; every Core-minted id is uuid4 too, so
    # requiring version 4 tightens the contract without rejecting any real id.
    if parsed.version != 4:
        raise _invalid()
    return value


def _v_optional_uuid4(value: object) -> str | None:
    if value is None:
        return None
    return _v_uuid(value)


def _v_catalog_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid()
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise _invalid() from exc
    if parsed.version not in {4, 5}:
        raise _invalid()
    return str(parsed)


def _exact_keys(mapping: dict[str, object], keys: set[str]) -> None:
    if set(mapping) != keys:
        raise _invalid()


_ABSENT = object()


def _v_allergen_codes(value: object) -> tuple[AllergenCode, ...]:
    if not isinstance(value, list):
        raise _invalid()
    try:
        return validate_allergen_codes([str(item) for item in value])
    except ValueError as exc:
        raise _invalid() from exc


def _v_catalog_text(value: object, max_len: int) -> str | None:
    if value is None:
        return None
    text = _v_str(value, max_len).strip()
    return text or None


def _chat_thread_shape(thread: ChatThread) -> dict[str, object]:
    return {
        "thread_id": thread.thread_id,
        "thread_type": thread.thread_type,
        "title": thread.title,
        "created_by_employee_id": thread.created_by_employee_id,
        "created_at": thread.created_at.isoformat(),
    }


def _chat_participant_shape(
    participant: ChatParticipant, display_name: str
) -> dict[str, object]:
    return {
        "thread_id": participant.thread_id,
        "employee_id": participant.employee_id,
        "display_name": display_name,
        "joined_at": participant.joined_at.isoformat(),
        "last_read_message_id": participant.last_read_message_id,
    }


def _chat_employee_shape(employee_id: str, display_name: str) -> dict[str, object]:
    return {"employee_id": employee_id, "display_name": display_name}


def _chat_message_preview_shape(
    message: ChatMessage | None,
) -> dict[str, object] | None:
    if message is None:
        return None
    return {
        "message_id": message.message_id,
        "author_employee_id": message.author_employee_id,
        "body": message.body,
        "created_at": message.created_at.isoformat(),
    }


def _chat_message_shape(
    bundle: ChatMessageBundle,
    *,
    author_display_name: str,
    mention_display_names: dict[str, str],
) -> dict[str, object]:
    message = bundle.message
    return {
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "author_employee_id": message.author_employee_id,
        "author_display_name": author_display_name,
        "body": message.body,
        "reply_to_message_id": message.reply_to_message_id,
        "created_at": message.created_at.isoformat(),
        "mentions": [
            {
                "employee_id": mention.employee_id,
                "display_name": mention_display_names[mention.employee_id],
            }
            for mention in bundle.mentions
        ],
        "references": [
            {
                "reference_type": reference.reference_type,
                "reference_id": reference.reference_id,
            }
            for reference in bundle.references
        ],
    }


def _chat_reference_args(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise _invalid()
    references: list[tuple[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise _invalid()
        _exact_keys(raw, {"reference_type", "reference_id"})
        reference_type = _v_enum(raw["reference_type"], validate_chat_reference_type)
        references.append((reference_type, _v_uuid(raw["reference_id"])))
    return tuple(references)


def _chat_employee_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _invalid()
    return tuple(_v_uuid(employee_id) for employee_id in value)


def _chat_error(exc: Exception) -> ApiError:
    message = str(exc)
    if isinstance(exc, ChatNotFoundError):
        return ApiError(404, "not_found")
    if isinstance(exc, ChatAccessDenied):
        if "missing permission" in message or "application access" in message:
            return ApiError(403, "forbidden")
        return ApiError(404, "not_found")
    if isinstance(exc, ChatReferenceNotFoundError):
        return ApiError(422, "invalid_chat_reference")
    if "reply target" in message:
        return ApiError(422, "invalid_chat_reply")
    if "mentioned employee" in message:
        return ApiError(422, "invalid_chat_mention")
    if "message requires" in message or "body" in message:
        return ApiError(422, "invalid_chat_message")
    if "reference" in message:
        return ApiError(422, "invalid_chat_reference")
    if "message" in message:
        return ApiError(422, "invalid_chat_message")
    return ApiError(422, "invalid_chat_thread")


def _v_intake(
    args: dict[str, object], key: str, cap: int, keep: str | None
) -> str | None:
    """Optional intake string arg (pack §4.4). An omitted key returns `keep`
    — "" on create (the pack default), the current stored value on update so
    an unsent field is preserved, never wiped. An explicit JSON `null` or any
    non-string is a type violation → 400 (exact types, no coercion); an empty
    string is a deliberate clear."""
    value = args.get(key, _ABSENT)
    if value is _ABSENT:
        return keep
    return _v_str(value, cap)


def _manual_task_shape(task: ManualTask) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "description": task.description,
        "due_at": task.due_at.isoformat() if task.due_at is not None else None,
        "status": task.status,
        "created_at": task.created_at.isoformat(),
        "completed_at": (
            task.completed_at.isoformat() if task.completed_at is not None else None
        ),
        "created_by_employee_id": task.created_by_employee_id,
        "assigned_to_employee_id": task.assigned_to_employee_id,
        "subject_type": task.subject_type,
        "subject_id": task.subject_id,
        "priority": task.priority,
    }


def _customer_order_history_shape(
    entry: CustomerOrderHistoryEntry,
) -> dict[str, object]:
    return {
        "order_id": entry.order_id,
        "source_inquiry_id": entry.source_inquiry_id,
        "order_version_id": entry.order_version_id,
        "event_date": entry.event_date.isoformat(),
        "guest_count": entry.guest_count,
        "fulfillment_mode": entry.fulfillment_mode,
        "accepted_offer_id": entry.accepted_offer_id,
        "accepted_offer_version_id": entry.accepted_offer_version_id,
        "accepted_variant_id": entry.accepted_variant_id,
        "accepted_variant_label": entry.accepted_variant_label,
        "dishes": [
            {
                "position_id": dish.position_id,
                "name": dish.name,
                "kind": dish.kind,
                "catalog_item_id": dish.catalog_item_id,
                "gross_total_cents": dish.gross_total_cents,
            }
            for dish in entry.dishes
        ],
        "gross_total_cents": entry.gross_total_cents,
        "order_created_at": entry.order_created_at.isoformat(),
        "cancelled_at": (
            entry.cancelled_at.isoformat() if entry.cancelled_at is not None else None
        ),
    }


def _gastronomic_preference_shape(
    preference: CustomerGastronomicPreference,
) -> dict[str, object]:
    return {
        "preference_id": preference.preference_id,
        "customer_id": preference.customer_id,
        "kind": preference.kind,
        "value": preference.value,
        "source": preference.source,
        "created_at": preference.created_at.isoformat(),
        "updated_at": preference.updated_at.isoformat(),
    }


# --- API core ----------------------------------------------------------------


class OfficeApi:
    """All routes against one shared connection; commands run inside the
    CoreCommandExecutor so precondition + write + ledger are atomic."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        offer_pdf_static_content: OfferPdfStaticContent,
        employee_auth_now: Callable[[], datetime] | None = None,
    ) -> None:
        self._conn = connection
        self.offer_pdf_static_content = offer_pdf_static_content
        self.inquiries = SQLiteInquiryRepository.from_connection(connection)
        bootstrap_customer_identity_schema(connection)
        self.customer_identities = SQLiteCustomerIdentityRepository.from_connection(
            connection
        )
        self.customer_gastronomic_preferences = (
            SQLiteCustomerGastronomicPreferenceRepository.from_connection(connection)
        )
        bootstrap_employee_auth_schema(connection)
        self.orders = SQLiteOrderRepository.from_connection(connection)
        self.kitchen_print_jobs = SQLiteKitchenPrintJobRepository.from_connection(
            connection
        )
        self.offers = SQLiteOfferRepository.from_connection(connection)
        self.catalog = SQLiteCatalogRepository.from_connection(connection)
        self.contact_profiles = SQLiteContactProfileRepository.from_connection(
            connection
        )
        self.employee_auth_repository = SQLiteEmployeeAuthRepository.from_connection(
            connection
        )
        if employee_auth_now is not None:
            self.employee_auth_service = EmployeeAuthService(
                self.employee_auth_repository,
                now=employee_auth_now,
            )
        else:
            self.employee_auth_service = EmployeeAuthService(
                self.employee_auth_repository
            )
        self.configurator_handoffs = (
            SQLiteConfiguratorHandoffRepository.from_connection(connection)
        )
        self.configurator_handoff_service = ConfiguratorHandoffService(
            self.configurator_handoffs
        )
        self.payment_reminders = SQLitePaymentReminderRepository.from_connection(
            connection
        )
        self.courier_cash = SQLiteCourierCashRepository.from_connection(connection)
        self.chat = SQLiteChatRepository.from_connection(connection)
        self.manual_tasks = SQLiteManualTaskRepository.from_connection(connection)
        self.confirmation_documents = (
            SQLiteOrderConfirmationDocumentRepository.from_connection(connection)
        )
        self.commercial_snapshots = (
            SQLiteOrderCommercialSnapshotRepository.from_connection(connection)
        )
        self.production_capacity = SQLiteProductionCapacityRepository.from_connection(
            connection
        )
        self.confirmation_outbound = (
            SQLiteOrderConfirmationOutboundRepository.from_connection(connection)
        )
        self.operational_pauses = SQLiteOrderOperationalPauseRepository.from_connection(
            connection
        )
        self.offer_documents = SQLiteOfferDocumentSnapshotRepository.from_connection(
            connection
        )
        self.ledger = OfficeCommandLedger(connection)
        self.events = DeferredEventSink()
        self.executor = CoreCommandExecutor(connection, self.events)
        self._active_command_id: str | None = None
        self._active_employee: AuthenticatedEmployee | None = None
        self.inquiry_service = InquiryService(self.inquiries, event_sink=self.events)
        self.customer_gastronomic_preference_service = (
            CustomerGastronomicPreferenceService(
                self.customer_identities, self.customer_gastronomic_preferences
            )
        )
        self.customer_order_history_service = CustomerOrderHistoryService(
            self.customer_identities, self.inquiries, self.orders, self.offers
        )
        self.order_service = OrderService(self.orders, event_sink=self.events)
        self.offer_service = OfferService(
            self.offers,
            self.inquiries,
            self.orders,
            self.commercial_snapshots,
            today=views.berlin_today,
        )
        self.offer_document_service = OfferDocumentSnapshotService(
            self.offers,
            self.inquiries,
            self.offer_documents,
            today=views.berlin_today,
        )
        self.payment_reminder_service = PaymentReminderService(
            self.payment_reminders,
            self.orders,
            today=views.berlin_today,
        )
        self.courier_cash_context_service = CourierCashContextService(
            self.orders,
            self.payment_reminders,
            self.courier_cash,
        )
        self.courier_cash_service = CourierCashService(
            self.orders,
            self.inquiries,
            self.payment_reminders,
            self.courier_cash,
            self.payment_reminder_service,
            self.courier_cash_context_service,
        )
        self.chat_service = ChatService(
            self.chat,
            self.employee_auth_repository,
            orders=self.orders,
            inquiries=self.inquiries,
            contacts=self.contact_profiles,
        )
        self.contact_profile_service = ContactProfileService(self.contact_profiles)
        self.manual_task_service = ManualTaskService(
            self.manual_tasks,
            employee_exists=self._employee_account_exists,
            subject_exists=self._manual_task_subject_exists,
        )
        self.confirmation_document_service = OrderConfirmationDocumentService(
            self.orders,
            self.inquiries,
            self.confirmation_documents,
            self.commercial_snapshots,
            payment_reminder_repository=self.payment_reminders,
        )
        self.customer_document_preview_service = CustomerDocumentPreviewService(
            self.orders,
            self.inquiries,
            self.commercial_snapshots,
            payment_reminder_repository=self.payment_reminders,
        )
        self.core = OperationalCoreService(
            self.orders,
            pause_repository=self.operational_pauses,
            event_sink=self.events,
        )
        self.kitchen_print_service = KitchenPrintService(
            self.orders,
            self.kitchen_print_jobs,
            event_sink=self.events,
        )
        self.confirmation_outbound_service = OrderConfirmationOutboundService(
            self.orders,
            self.confirmation_documents,
            self.confirmation_outbound,
            self.core,
        )
        self.week_service = WochenuebersichtService(self.orders)
        self.contact_projection_service = ContactProjectionService(
            self.inquiries,
            self.offers,
            self.orders,
            today=views.berlin_today,
        )
        self.email_intake_projection_service = EmailIntakeProjectionService(
            self.inquiries,
            self.offers,
            self.orders,
        )
        self.task_projection_service = TaskProjectionService(
            self.inquiries,
            self.offers,
            self.orders,
            self.payment_reminder_service,
            today=views.berlin_today,
            courier_cash_repository=self.courier_cash,
        )
        self.calendar_projection_service = CalendarProjectionService(
            self.inquiries,
            self.offers,
            self.orders,
            today=views.berlin_today,
        )
        self.work_center_service = WorkCenterService(
            self.inquiries,
            self.offers,
            self.orders,
            today=views.berlin_today,
            task_projection_service=self.task_projection_service,
            calendar_projection_service=self.calendar_projection_service,
        )
        self.offer_queue_projection_service = OfferQueueProjectionService(
            self.offers,
            self.inquiries,
            today=views.berlin_today,
        )
        self.print_projection_service = OrderPrintProjectionService(
            self.orders,
            self.commercial_snapshots,
            self.confirmation_documents,
        )
        self.buffet_cards_service = BuffetCardsService(
            self.orders,
            self.print_projection_service,
        )
        self.catalog_dish_service = CatalogDishService(self.catalog)
        self.catalog_dish_write_service = CatalogDishWriteService(self.catalog)
        self.recommendation_demand_service = RecommendationDemandService(
            self.orders,
            self.offers,
            self.commercial_snapshots,
            today=views.berlin_today,
        )
        self.recommendation_capacity_service = RecommendationCapacityService(
            self.catalog,
            self.production_capacity,
            self.orders,
            self.commercial_snapshots,
        )

    def _employee_account_exists(self, employee_id: str) -> bool:
        account = self.employee_auth_repository.get_account_by_id(employee_id)
        return account is not None and account.is_active

    def _manual_task_subject_exists(
        self, subject_type: ManualTaskSubjectType, subject_id: str
    ) -> bool:
        if subject_type == "ORDER":
            return self.orders.get_order(subject_id) is not None
        if subject_type == "INQUIRY":
            return self.inquiries.get_by_id(subject_id) is not None
        if subject_type == "OFFER":
            return self.offers.get(subject_id) is not None
        if subject_type == "CONTACT":
            return self.contact_profiles.get_profile(subject_id) is not None
        return False

    def exchange_configurator_handoff(
        self,
        *,
        code: str,
        employee_session_token: str,
    ) -> dict[str, object]:
        try:
            employee = self.employee_auth_service.authenticate_session(
                employee_session_token
            )
        except AuthenticationError as exc:
            raise ApiError(401, "unauthorized") from exc
        if not employee.application_access_allowed:
            raise ApiError(403, "forbidden")
        record = self.configurator_handoff_service.lookup(code)
        if record is None or record.operation != HANDOFF_OPERATION_PREPARE_FIRST_OFFER:
            raise ApiError(404, "not_found")
        if not hmac.compare_digest(record.issued_for_account_id, employee.account.id):
            raise ApiError(403, "forbidden")
        if "offers.prepare" not in employee.effective_permissions:
            raise ApiError(403, "forbidden")
        inquiry = self.inquiries.get_by_id(record.inquiry_id)
        if inquiry is None:
            raise ApiError(404, "not_found")
        now = datetime.now(UTC)
        if record.expires_at <= now:
            raise ApiError(404, "not_found")
        if record.consumed_at is not None:
            raise ApiError(410, "gone")

        def work() -> dict[str, object]:
            current = self.configurator_handoffs.get_by_token_hash(record.token_hash)
            if (
                current is None
                or current.operation != HANDOFF_OPERATION_PREPARE_FIRST_OFFER
            ):
                raise ApiError(404, "not_found")
            if current.expires_at <= now:
                raise ApiError(404, "not_found")
            if current.consumed_at is not None:
                raise ApiError(410, "gone")
            if not self.configurator_handoffs.consume(
                handoff_id=current.id,
                consumed_at=now,
                consumed_by_account_id=employee.account.id,
            ):
                raise ApiError(410, "gone")
            return {
                "handoff_id": current.id,
                "operation": current.operation,
                "inquiry": {
                    "inquiry_id": inquiry.inquiry_id,
                    "transfer": offer_prefill_payload(inquiry)["transfer"],
                },
                "expires_at": current.expires_at.isoformat(),
            }

        return self.executor.run(work)

    def customer_order_history(self, customer_id: str) -> dict[str, object]:
        try:
            entries = self.customer_order_history_service.list_for_customer(customer_id)
        except CustomerOrderHistoryCustomerNotFoundError as exc:
            raise ApiError(404, "customer_not_found") from exc
        return {
            "customer_id": customer_id,
            "orders": [_customer_order_history_shape(entry) for entry in entries],
        }

    def list_customer_gastronomic_preferences(
        self, customer_id: str
    ) -> dict[str, object]:
        try:
            preferences = (
                self.customer_gastronomic_preference_service.list_for_customer(
                    customer_id
                )
            )
        except CustomerNotFoundError as exc:
            raise ApiError(404, "customer_not_found") from exc
        return {
            "customer_id": customer_id,
            "preferences": [
                _gastronomic_preference_shape(preference) for preference in preferences
            ],
        }

    # -- reads -----------------------------------------------------------

    def work_center(self) -> dict[str, object]:
        return views.work_center_snapshot(self.work_center_service.snapshot())

    def queue_view(self) -> dict[str, object]:
        orders = self.orders.list_orders()
        inquiries = self.inquiries.list_all()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for order in orders:
            orders_by_inquiry.setdefault(order.source_inquiry_id, []).append(order)
        open_inquiries = []
        operating_today = views.berlin_today()
        for inquiry in inquiries:
            linked = orders_by_inquiry.get(inquiry.inquiry_id, [])
            offer = self.offers.get_by_source_inquiry_id(inquiry.inquiry_id)
            state = views.inquiry_office_state(
                inquiry,
                linked,
                offer=offer,
                today=operating_today,
            )
            if state.is_open:
                open_inquiries.append((inquiry, state))
        active = [o for o in orders if o.cancelled_at is None]
        without_print = [
            o
            for o in active
            if not any(
                v.kitchen_print_confirmed_at is not None
                for v in self.orders.list_order_versions(o.order_id)
            )
        ]
        not_effective = [o for o in active if o.effective_order_version_id is None]
        blocked = [
            o for o in active if not self.core.evaluate_ready_to_send(o.order_id).ready
        ]
        paused = [
            o
            for o in active
            if self.core.get_active_operational_pause(o.order_id) is not None
        ]
        pending_changes = [
            o
            for o in active
            if o.candidate_order_version_id is not None
            and o.candidate_order_version_id != o.effective_order_version_id
            and (
                candidate := self.orders.get_order_version(o.candidate_order_version_id)
            )
            is not None
            and candidate.kitchen_print_confirmed_at is None
        ]
        cancelled = [o for o in orders if o.cancelled_at is not None]

        iso = views.berlin_today().isocalendar()
        week = self.week_service.get_week_overview(iso.year, iso.week)
        return {
            "attention": {
                # Compatibility key for the local, not-yet-deployed Phase 2
                # transport. Its value now means truthful open inquiries.
                "neue_anfragen": len(open_inquiries),
                "druck_fehlt": len(without_print),
                "nicht_wirksam": len(not_effective),
                "versand_blockiert": len(blocked),
                "aenderungen_warten_auf_kuechendruck": len(pending_changes),
                "pausiert": len(paused),
                "storniert": len(cancelled),
            },
            "week": views.week_view(week),
            "neue_anfragen_top": [
                views.inquiry_top_row(inquiry, state)
                for inquiry, state in open_inquiries[: views.TOP_ROWS_CAP]
            ],
            "auftraege_top": [
                views.order_top_row(
                    o,
                    self.orders.list_order_versions(o.order_id),
                    self.core.evaluate_ready_to_send(o.order_id),
                )
                for o in blocked[: views.TOP_ROWS_CAP]
            ],
            "pausiert_top": [
                views.order_top_row(
                    o,
                    self.orders.list_order_versions(o.order_id),
                    self.core.evaluate_ready_to_send(o.order_id),
                    active_pause=self.core.get_active_operational_pause(o.order_id),
                )
                for o in paused[: views.TOP_ROWS_CAP]
            ],
        }

    def list_offers(self) -> dict[str, object]:
        inquiries_by_id = {
            inquiry.inquiry_id: inquiry for inquiry in self.inquiries.list_all()
        }
        return {
            "offers": views.offer_list_view(
                self.offers.list_all(),
                inquiries_by_id,
                today=views.berlin_today(),
            )
        }

    def offer_queue(
        self,
        *,
        group: str | None = None,
        limit: int = views.LIST_LIMIT_DEFAULT,
        offset: int = 0,
    ) -> dict[str, object]:
        snapshot = self.offer_queue_projection_service.snapshot(
            group=group,  # type: ignore[arg-type]
            limit=limit,
            offset=offset,
        )
        return views.offer_queue_view(snapshot)

    def offer_detail(self, offer_id: str) -> dict[str, object]:
        offer = self.offers.get(offer_id)
        if offer is None:
            raise ApiError(404, "not_found")
        return views.offer_detail(offer, today=views.berlin_today())

    def list_contacts(self) -> dict[str, object]:
        return {
            "contacts": views.contact_list_view(
                self.contact_projection_service.list_contacts()
            )
        }

    def contact_detail(self, contact_key: str) -> dict[str, object]:
        detail = self.contact_projection_service.contact_detail(unquote(contact_key))
        if detail is None:
            raise ApiError(404, "not_found")
        return views.contact_detail_view(
            detail.contact,
            list(detail.inquiries),
            list(detail.offers),
            list(detail.orders),
            today=views.berlin_today(),
        )

    def list_catalog_dishes(
        self,
        *,
        active: bool | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        if q is not None and len(q) > _MAX_Q_CHARS:
            raise _invalid()
        return views.catalog_dish_list_view(
            self.catalog_dish_service.list_dishes(
                active=active,
                q=q,
                limit=limit,
                offset=offset,
            )
        )

    def catalog_dish_detail(self, dish_id: str) -> dict[str, object]:
        dish = self.catalog_dish_service.get_dish(dish_id)
        if dish is None:
            raise ApiError(404, "not_found")
        history = self.catalog_dish_service.list_price_history(dish_id)
        return views.catalog_dish_detail_view(dish, history)

    def list_allergen_codes(self) -> dict[str, object]:
        return views.allergen_codes_view(
            self.catalog_dish_service.list_allergen_codes()
        )

    def cmd_update_catalog_dish(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        dish_id = _v_catalog_uuid(path_ids["id"])
        current = self.catalog_dish_service.get_dish(dish_id)
        if current is None:
            raise ApiError(404, "not_found")
        if _v_datetime(expect["updated_at"]) != current.updated_at:
            raise ApiError(409, "stale_state")
        new_cents = _v_int(args["current_unit_net_cents"])
        if new_cents < 0:
            raise _invalid()
        price_will_change = new_cents != current.current_unit_net_cents
        effective_from: date | None
        if price_will_change:
            effective_from = (
                _v_optional_date(args["effective_from"])
                if "effective_from" in args
                else views.berlin_today()
            )
        else:
            effective_from = None
        try:
            result = self.catalog_dish_write_service.update_dish(
                dish_id,
                update=CatalogDishUpdatePayload(
                    name=_v_str(args["name"], 500),
                    description=_v_catalog_text(args.get("description"), 20_000),
                    composition=_v_catalog_text(args.get("composition"), 20_000),
                    notes=_v_catalog_text(args.get("notes"), 20_000),
                    current_unit_net_cents=new_cents,
                    allergens=_v_allergen_codes(args["allergens"]),
                    active=_v_bool(args["active"]),
                    effective_from=effective_from,
                ),
                expected_updated_at=current.updated_at,
            )
        except CatalogDishNotFoundError as exc:
            raise ApiError(404, "not_found") from exc
        except CatalogDishStaleError as exc:
            raise ApiError(409, "stale_state") from exc
        except ValueError as exc:
            raise ApiError(422, "validation_error") from exc
        body: dict[str, object] = {
            "dish_id": result.dish.dish_id,
            "updated_at": result.dish.updated_at.isoformat(),
            "price_changed": result.price_changed,
        }
        if result.price_history_entry_id is not None:
            body["price_history_entry_id"] = result.price_history_entry_id
        return 200, body

    def cmd_create_catalog_dish(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        """CATALOG_ADMIN_COMPLETION_V1A: dish_id is minted server-side, never
        client-supplied — no expect/staleness check applies (a create has no
        prior state). New dishes are always active=false (decision #8)."""
        try:
            dish = self.catalog_dish_write_service.create_dish(
                CatalogDishCreatePayload(
                    name=_v_str(args["name"], 500),
                    category=_v_str(args["category"], 200),
                    pricing_unit=_v_enum(args["pricing_unit"], validate_pricing_unit),
                    current_unit_net_cents=_v_int(args["current_unit_net_cents"]),
                    vat_rate_percent=_v_int(args["vat_rate_percent"]),
                    description=_v_catalog_text(args.get("description"), 20_000),
                    composition=_v_catalog_text(args.get("composition"), 20_000),
                    notes=_v_catalog_text(args.get("notes"), 20_000),
                    allergens=(
                        _v_allergen_codes(args["allergens"])
                        if "allergens" in args
                        else ()
                    ),
                )
            )
        except CatalogDishAlreadyExistsError as exc:
            raise ApiError(409, "already_exists") from exc
        except ValueError as exc:
            raise ApiError(422, "validation_error") from exc
        return 201, {
            "dish_id": dish.dish_id,
            "active": dish.active,
            "updated_at": dish.updated_at.isoformat(),
        }

    def _cmd_set_catalog_dish_active(
        self, path_ids: dict[str, str], expect: dict, *, active: bool
    ) -> tuple[int, dict[str, object]]:
        dish_id = _v_catalog_uuid(path_ids["id"])
        current = self.catalog_dish_service.get_dish(dish_id)
        if current is None:
            raise ApiError(404, "not_found")
        if _v_datetime(expect["updated_at"]) != current.updated_at:
            raise ApiError(409, "stale_state")
        try:
            if active:
                dish = self.catalog_dish_write_service.activate_dish(
                    dish_id, expected_updated_at=current.updated_at
                )
            else:
                dish = self.catalog_dish_write_service.deactivate_dish(
                    dish_id, expected_updated_at=current.updated_at
                )
        except CatalogDishNotFoundError as exc:
            raise ApiError(404, "not_found") from exc
        except CatalogDishStaleError as exc:
            raise ApiError(409, "stale_state") from exc
        return 200, {
            "dish_id": dish.dish_id,
            "active": dish.active,
            "updated_at": dish.updated_at.isoformat(),
        }

    def cmd_activate_catalog_dish(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        return self._cmd_set_catalog_dish_active(path_ids, expect, active=True)

    def cmd_deactivate_catalog_dish(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        return self._cmd_set_catalog_dish_active(path_ids, expect, active=False)

    def list_emails(self) -> dict[str, object]:
        return {
            "emails": views.email_list_view(
                self.email_intake_projection_service.list_emails()
            )
        }

    def email_detail(self, inquiry_id: str) -> dict[str, object]:
        projection = self.email_intake_projection_service.email_detail(inquiry_id)
        if projection is None:
            raise ApiError(404, "not_found")
        return views.email_detail_view(projection)

    def list_tasks(self) -> dict[str, object]:
        return {
            "tasks": views.task_list_view(self.task_projection_service.list_tasks())
        }

    def list_manual_tasks(
        self,
        subject_type: ManualTaskSubjectType | None = None,
        subject_id: str | None = None,
    ) -> dict[str, object]:
        if subject_type is None:
            tasks = self.manual_task_service.list_open_tasks()
        else:
            if subject_id is None:
                raise _invalid()
            tasks = self.manual_task_service.list_tasks_for_subject(
                subject_type, subject_id
            )
        return {"manual_tasks": [_manual_task_shape(task) for task in tasks]}

    def manual_task_subjects(
        self, employee: AuthenticatedEmployee
    ) -> dict[str, object]:
        permissions = employee.effective_permissions
        inquiries = self.inquiries.list_all()
        inquiries_by_id = {inquiry.inquiry_id: inquiry for inquiry in inquiries}
        rows: list[dict[str, object]] = []

        def inquiry_label(inquiry) -> str:
            snapshot = inquiry.customer_snapshot
            customer = None
            if snapshot is not None:
                customer = snapshot.company_name or snapshot.contact_name
            primary = (
                customer
                or inquiry.intake_subject
                or inquiry.location_text
                or f"Anfrage {inquiry.inquiry_id[:8]}"
            )
            return f"{primary} · {inquiry.event_date.isoformat()}"

        if "customers.view" in permissions:
            contacts = sorted(
                self.contact_projection_service.list_contacts(),
                key=lambda contact: (
                    contact.display_name.casefold(),
                    contact.contact_key,
                ),
            )
            for contact in contacts:
                rows.append(
                    {
                        "subject_type": "CONTACT",
                        "subject_id": self.contact_profile_service.find_by_alias(
                            "contact_key", contact.contact_key
                        ),
                        "contact_key": contact.contact_key,
                        "label": f"Kontakt · {contact.display_name}",
                        "href": f"/kontakt/{quote(contact.contact_key, safe='')}",
                    }
                )
        if "inquiries.view" in permissions:
            for inquiry in sorted(
                inquiries, key=lambda item: (item.event_date, item.inquiry_id)
            ):
                rows.append(
                    {
                        "subject_type": "INQUIRY",
                        "subject_id": inquiry.inquiry_id,
                        "contact_key": None,
                        "label": f"Anfrage · {inquiry_label(inquiry)}",
                        "href": f"/inquiry/{inquiry.inquiry_id}",
                    }
                )
        if "offers.view" in permissions:
            for offer in self.offers.list_all():
                offer_inquiry = inquiries_by_id.get(offer.source_inquiry_id)
                suffix = (
                    inquiry_label(offer_inquiry)
                    if offer_inquiry is not None
                    else offer.offer_id[:8]
                )
                rows.append(
                    {
                        "subject_type": "OFFER",
                        "subject_id": offer.offer_id,
                        "contact_key": None,
                        "label": f"Angebot · {suffix}",
                        "href": f"/offer/{offer.offer_id}",
                    }
                )
        if "orders.view" in permissions:
            for order in self.orders.list_orders():
                order_inquiry = inquiries_by_id.get(order.source_inquiry_id)
                suffix = (
                    inquiry_label(order_inquiry)
                    if order_inquiry is not None
                    else order.order_id[:8]
                )
                rows.append(
                    {
                        "subject_type": "ORDER",
                        "subject_id": order.order_id,
                        "contact_key": None,
                        "label": f"Auftrag · {suffix}",
                        "href": f"/order/{order.order_id}",
                    }
                )
        rows.sort(
            key=lambda row: (
                str(row["subject_type"]),
                str(row["label"]).casefold(),
            )
        )
        return {"subjects": rows}

    def list_calendar(self, from_date: date, to_date: date) -> dict[str, object]:
        return {
            "entries": views.calendar_list_view(
                self.calendar_projection_service.list_entries(from_date, to_date)
            )
        }

    def recommendation_demand(self, event_date: date) -> dict[str, object]:
        rows = self.recommendation_demand_service.list_same_day(event_date)
        return {
            "event_date": event_date.isoformat(),
            "rows": [
                {
                    "catalog_item_id": row.catalog_item_id,
                    "lifecycle": row.lifecycle,
                }
                for row in rows
            ],
        }

    def recommendation_capacity(self, event_date: date) -> dict[str, object]:
        rows = self.recommendation_capacity_service.list_for_date(event_date)
        return {
            "event_date": event_date.isoformat(),
            "rows": [
                {
                    "catalog_item_id": row.catalog_item_id,
                    "feasible": row.feasible,
                    "overload_penalty": row.overload_penalty,
                    "reason_code": row.reason_code,
                }
                for row in rows
            ],
        }

    def list_inquiries(self, q: str, limit: int, offset: int) -> dict[str, object]:
        orders_by_inquiry: dict[str, list[Order]] = {}
        for order in self.orders.list_orders():
            orders_by_inquiry.setdefault(order.source_inquiry_id, []).append(order)
        matching = [i for i in self.inquiries.list_all() if views.inquiry_matches(i, q)]
        page = matching[offset : offset + limit]
        return {
            "inquiries": [
                views.inquiry_list_row(i, orders_by_inquiry.get(i.inquiry_id, []))
                for i in page
            ],
            "total_count": len(matching),
            "limit": limit,
            "offset": offset,
        }

    def list_orders(self, q: str, limit: int, offset: int) -> dict[str, object]:
        matching = [o for o in self.orders.list_orders() if views.order_matches(o, q)]
        page = matching[offset : offset + limit]
        return {
            "orders": [
                views.order_list_row(
                    o,
                    self.orders.list_order_versions(o.order_id),
                    self.core.evaluate_ready_to_send(o.order_id),
                    active_pause=self.core.get_active_operational_pause(o.order_id),
                )
                for o in page
            ],
            "total_count": len(matching),
            "limit": limit,
            "offset": offset,
        }

    def inquiry_detail(self, inquiry_id: str) -> dict[str, object]:
        inquiry = self.inquiries.get_by_id(inquiry_id)
        if inquiry is None:
            raise ApiError(404, "not_found")
        linked = [
            o for o in self.orders.list_orders() if o.source_inquiry_id == inquiry_id
        ]
        offer = self.offers.get_by_source_inquiry_id(inquiry_id)
        return views.inquiry_detail(
            inquiry, linked, offer=offer, today=views.berlin_today()
        )

    def order_detail(self, order_id: str) -> dict[str, object]:
        order = self.orders.get_order(order_id)
        if order is None:
            raise ApiError(404, "not_found")
        return views.order_detail(
            order,
            self.orders.list_order_versions(order_id),
            self.core.evaluate_ready_to_send(order_id),
            self.payment_reminder_service.view(order_id),
            self.confirmation_document_service.eligibility(order_id),
            pause_projection=self.core.get_operational_pause_projection(order_id),
        )

    def confirmation_document(
        self, order_id: str, document_snapshot_id: str | None = None
    ) -> dict[str, object]:
        try:
            if document_snapshot_id is None:
                snapshot = self.confirmation_document_service.get_latest_snapshot(
                    order_id
                )
                if snapshot is None:
                    raise ApiError(404, "not_found")
                document_snapshot_id = snapshot.document_snapshot_id
            snapshot = self.confirmation_document_service.get_snapshot(
                order_id, document_snapshot_id
            )
        except OrderConfirmationDocumentNotFoundError:
            raise ApiError(404, "not_found") from None
        summary = self.confirmation_document_service.summary_for_snapshot(snapshot)
        return {
            "snapshot": views.confirmation_document_summary_shape(summary),
            "document_snapshot_id": snapshot.document_snapshot_id,
        }

    def confirmation_preview(self, order_id: str) -> dict[str, object]:
        """Live CDP preview before document create — V1-D (no persistence)."""
        try:
            preview = self.customer_document_preview_service.preview_order_confirmation(
                order_id
            )
        except CustomerDocumentPreviewNotFoundError as exc:
            raise ApiError(404, "not_found") from exc
        return views.customer_document_preview_shape(preview)

    def confirmation_document_preview(
        self,
        order_id: str,
        document_snapshot_id: str | None = None,
        *,
        format: str = "json",
    ) -> dict[str, object] | str:
        if format not in {"json", "html"}:
            raise _invalid()
        try:
            if document_snapshot_id is None:
                snapshot = self.confirmation_document_service.get_latest_snapshot(
                    order_id
                )
                if snapshot is None:
                    raise ApiError(404, "not_found")
            else:
                snapshot = self.confirmation_document_service.get_snapshot(
                    order_id, document_snapshot_id
                )
        except OrderConfirmationDocumentNotFoundError:
            raise ApiError(404, "not_found") from None
        preview = build_preview(snapshot)
        if format == "html":
            return render_preview_html(preview)
        return {
            "document_snapshot_id": snapshot.document_snapshot_id,
            "preview": views.confirmation_document_preview_shape(preview),
        }

    def print_data(
        self,
        order_id: str,
        version_id: str,
        *,
        intent: str = "preview",
    ) -> dict[str, object]:
        if intent not in {"preview", "final"}:
            raise _invalid()
        order = self.orders.get_order(order_id)
        version = self.orders.get_order_version(version_id)
        if order is None or version is None or version.order_id != order_id:
            raise ApiError(404, "not_found")  # no unknown/unowned distinction
        try:
            projection = self.print_projection_service.resolve(
                order_id,
                version_id,
                intent=intent,  # type: ignore[arg-type]
            )
        except PrintFinalRequiresEffectiveError:
            raise ApiError(400, "invalid_request") from None
        except (PrintProjectionNotFoundError, MissingCommercialSnapshotError):
            raise ApiError(404, "not_found") from None
        return {
            "order": views.order_summary(order),
            "version": views.order_version_shape(version),
            "projection": views.order_print_projection_shape(projection),
        }

    def buffet_cards_data(self, order_id: str, version_id: str) -> dict[str, object]:
        try:
            view = self.buffet_cards_service.resolve(order_id, version_id)
        except (PrintProjectionNotFoundError, MissingCommercialSnapshotError):
            raise ApiError(404, "not_found") from None
        return views.buffet_cards_data_shape(view)

    # -- command helpers ---------------------------------------------------

    def _require_inquiry(self, inquiry_id: str):
        inquiry = self.inquiries.get_by_id(inquiry_id)
        if inquiry is None:
            raise ApiError(404, "not_found")
        return inquiry

    def _require_order(self, order_id: str) -> Order:
        order = self.orders.get_order(order_id)
        if order is None:
            raise ApiError(404, "not_found")
        return order

    def _require_active_order(self, order_id: str) -> Order:
        order = self._require_order(order_id)
        if order.cancelled_at is not None:
            # API-level gate codifying current UI behavior (pack §4.5)
            raise ApiError(422, "order_cancelled")
        return order

    def _owned_version(self, order_id: str, version_id: str) -> OrderVersion:
        version = self.orders.get_order_version(version_id)
        if version is None or version.order_id != order_id:
            raise ApiError(422, "version_not_owned")
        return version

    def _active_order_for_inquiry(self, inquiry_id: str) -> Order | None:
        for order in self.orders.list_orders():
            if order.source_inquiry_id == inquiry_id and order.cancelled_at is None:
                return order
        return None

    def _require_active_employee(self) -> AuthenticatedEmployee:
        if self._active_employee is None:
            raise ApiError(401, "unauthorized")
        return self._active_employee

    def cmd_create_manual_task(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        employee = self._require_active_employee()
        subject_type = _v_enum(
            args.get("subject_type", "NONE"), validate_manual_task_subject_type
        )
        assigned_to_employee_id = _v_optional_uuid4(args.get("assigned_to_employee_id"))
        subject_id = _v_optional_uuid4(args.get("subject_id"))
        subject_contact_key = _v_optional_str(args.get("subject_contact_key"), 1000)
        if subject_type == "CONTACT" and subject_contact_key is not None:
            if subject_id is not None:
                raise _invalid()
            projection = self.contact_projection_service.contact_detail(
                subject_contact_key
            )
            if projection is None:
                raise _invalid()
            subject_id = self.contact_profile_service.ensure_for_projection(
                projection.contact
            )
        elif subject_contact_key is not None:
            raise _invalid()
        try:
            task = self.manual_task_service.create_task(
                title=_v_str(args["title"], 200),
                description=_v_optional_str(args.get("description"), 4000) or "",
                due_at=_v_optional_datetime(args.get("due_at")),
                created_by_employee_id=employee.account.id,
                assigned_to_employee_id=assigned_to_employee_id,
                subject_type=subject_type,
                subject_id=subject_id,
                priority=_v_enum(
                    args.get("priority", "NORMAL"), validate_manual_task_priority
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ApiError(422, "invalid_request") from exc
        except (TypeError, ValueError) as exc:
            raise _invalid() from exc
        return 201, {"manual_task": _manual_task_shape(task)}

    def cmd_complete_manual_task(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        self._require_active_employee()
        task_id = _v_uuid(path_ids["task_id"])
        try:
            task = self.manual_task_service.complete_task(task_id)
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except (TypeError, ValueError) as exc:
            raise _invalid() from exc
        return 200, {"manual_task": _manual_task_shape(task)}

    def _employee_display_name(self, employee_id: str) -> str:
        account = self.employee_auth_repository.get_account_by_id(employee_id)
        if account is None:
            raise ApiError(500, "internal")
        return account.display_name

    def _chat_participants_shape(
        self, participants: tuple[ChatParticipant, ...]
    ) -> list[dict[str, object]]:
        return [
            _chat_participant_shape(
                participant, self._employee_display_name(participant.employee_id)
            )
            for participant in participants
        ]

    def _chat_thread_summary_shape(
        self, summary: ChatThreadSummary
    ) -> dict[str, object]:
        latest = summary.latest_message
        return {
            "thread": _chat_thread_shape(summary.thread),
            "participants": self._chat_participants_shape(summary.participants),
            "latest_message_preview": _chat_message_preview_shape(latest),
            "unread_count": summary.unread_count,
            "last_activity_at": (
                latest.created_at if latest is not None else summary.thread.created_at
            ).isoformat(),
        }

    def _chat_thread_detail_shape(
        self,
        actor: AuthenticatedEmployee,
        thread: ChatThread,
        messages: tuple[ChatMessageBundle, ...],
    ) -> dict[str, object]:
        participants = self.chat.list_participants(thread.thread_id)
        current = next(
            participant
            for participant in participants
            if participant.employee_id == actor.account.id
        )
        participant_names = {
            participant.employee_id: self._employee_display_name(
                participant.employee_id
            )
            for participant in participants
        }
        author_ids = {bundle.message.author_employee_id for bundle in messages}
        author_names = {
            employee_id: self._employee_display_name(employee_id)
            for employee_id in author_ids
        }
        return {
            "thread": _chat_thread_shape(thread),
            "participants": self._chat_participants_shape(participants),
            "current_participant": _chat_participant_shape(
                current, participant_names[current.employee_id]
            ),
            "messages": [
                _chat_message_shape(
                    bundle,
                    author_display_name=author_names[bundle.message.author_employee_id],
                    mention_display_names=participant_names,
                )
                for bundle in messages
            ],
        }

    def list_chat_threads(self, actor: AuthenticatedEmployee) -> dict[str, object]:
        return {
            "threads": [
                self._chat_thread_summary_shape(summary)
                for summary in self.chat_service.list_threads(actor)
            ]
        }

    def chat_thread_detail(
        self, actor: AuthenticatedEmployee, thread_id: str
    ) -> dict[str, object]:
        try:
            messages = self.chat_service.list_messages(actor, thread_id, limit=200)
            thread = self.chat.get_thread(thread_id)
            if thread is None:
                raise ChatNotFoundError(thread_id)
        except (ChatAccessDenied, ChatNotFoundError) as exc:
            raise _chat_error(exc) from exc
        return self._chat_thread_detail_shape(actor, thread, messages)

    def chat_thread_participants(
        self, actor: AuthenticatedEmployee, thread_id: str, q: str
    ) -> dict[str, object]:
        try:
            self.chat_service.list_messages(actor, thread_id, limit=1)
            participants = self.chat.list_participants(thread_id)
        except (ChatAccessDenied, ChatNotFoundError) as exc:
            raise _chat_error(exc) from exc
        needle = q.casefold()
        shaped = self._chat_participants_shape(participants)
        if needle:
            shaped = [
                row
                for row in shaped
                if needle in str(row["display_name"]).casefold()
                or needle in str(row["employee_id"]).casefold()
            ]
        return {"participants": shaped[:20]}

    def search_chat(self, actor: AuthenticatedEmployee, q: str) -> dict[str, object]:
        summaries = self.chat_service.list_threads(actor)
        if not q:
            return {"results": []}
        needle = q.casefold()
        matching_thread_ids: set[str] = set()
        like = f"%{needle}%"
        rows = self._conn.execute(
            """
            SELECT DISTINCT thread.thread_id
            FROM chat_threads thread
            JOIN chat_participants participant
              ON participant.thread_id = thread.thread_id
             AND participant.employee_id = ?
            LEFT JOIN chat_messages message
              ON message.thread_id = thread.thread_id
            WHERE lower(COALESCE(thread.title, '')) LIKE ?
               OR lower(COALESCE(message.body, '')) LIKE ?
            LIMIT 50
            """,
            (actor.account.id, like, like),
        ).fetchall()
        matching_thread_ids.update(str(row[0]) for row in rows)
        for summary in summaries:
            if summary.thread.thread_id in matching_thread_ids:
                continue
            participant_names = [
                self._employee_display_name(participant.employee_id).casefold()
                for participant in summary.participants
            ]
            if any(needle in name for name in participant_names):
                matching_thread_ids.add(summary.thread.thread_id)
        return {
            "results": [
                self._chat_thread_summary_shape(summary)
                for summary in summaries
                if summary.thread.thread_id in matching_thread_ids
            ][:50]
        }

    def search_chat_entities(
        self, actor: AuthenticatedEmployee, q: str, reference_type: ChatReferenceType
    ) -> dict[str, object]:
        if not actor.application_access_allowed:
            raise ApiError(403, "forbidden")
        if "chat.send" not in actor.effective_permissions:
            raise ApiError(403, "forbidden")
        entity_permission = {
            "ORDER": "orders.view",
            "INQUIRY": "inquiries.view",
            "CONTACT": "customers.view",
        }[reference_type]
        if entity_permission not in actor.effective_permissions:
            raise ApiError(403, "forbidden")
        if len(q) < 2:
            return {"results": []}
        needle = q.casefold()
        results: list[dict[str, object]] = []
        if reference_type == "CONTACT":
            for profile_id in self.contact_profiles.search_profile_ids(q)[:20]:
                profile = self.contact_profiles.get_profile(profile_id)
                if profile is None:
                    continue
                results.append(
                    {
                        "reference_type": "CONTACT",
                        "reference_id": profile.contact_profile_id,
                        "primary_label": profile.display_name,
                        "secondary_label": profile.email or profile.phone or "",
                        "meta": {"contact_profile_id": profile.contact_profile_id},
                    }
                )
            return {"results": results}
        if reference_type == "INQUIRY":
            for inquiry in self.inquiries.list_all():
                snapshot = inquiry.customer_snapshot
                company_name = snapshot.company_name if snapshot is not None else None
                contact_name = snapshot.contact_name if snapshot is not None else None
                contact_email = snapshot.email if snapshot is not None else None
                contact_phone = snapshot.phone if snapshot is not None else None
                haystack = " ".join(
                    str(value or "")
                    for value in (
                        inquiry.inquiry_id,
                        company_name,
                        contact_name,
                        contact_email,
                        contact_phone,
                        inquiry.location_text,
                        inquiry.intake_subject,
                    )
                ).casefold()
                if needle not in haystack:
                    continue
                results.append(
                    {
                        "reference_type": "INQUIRY",
                        "reference_id": inquiry.inquiry_id,
                        "primary_label": company_name
                        or contact_name
                        or f"Anfrage {inquiry.inquiry_id[:8]}",
                        "secondary_label": " · ".join(
                            part
                            for part in (
                                inquiry.event_date.isoformat(),
                                inquiry.location_text,
                            )
                            if part
                        ),
                        "meta": {"inquiry_id": inquiry.inquiry_id},
                    }
                )
                if len(results) >= 20:
                    break
            return {"results": results}
        for order in self.orders.list_orders():
            order_inquiry = self.inquiries.get_by_id(order.source_inquiry_id)
            snapshot = (
                order_inquiry.customer_snapshot if order_inquiry is not None else None
            )
            company_name = snapshot.company_name if snapshot is not None else None
            contact_name = snapshot.contact_name if snapshot is not None else None
            location_text = (
                order_inquiry.location_text if order_inquiry is not None else ""
            )
            haystack = " ".join(
                str(value or "")
                for value in (
                    order.order_id,
                    order.source_inquiry_id,
                    company_name,
                    contact_name,
                    location_text,
                )
            ).casefold()
            if needle not in haystack:
                continue
            results.append(
                {
                    "reference_type": "ORDER",
                    "reference_id": order.order_id,
                    "primary_label": f"Auftrag {order.order_id[:8]}",
                    "secondary_label": (company_name or contact_name or location_text),
                    "meta": {
                        "order_id": order.order_id,
                        "source_inquiry_id": order.source_inquiry_id,
                    },
                }
            )
            if len(results) >= 20:
                break
        return {"results": results}

    def search_chat_employees(
        self, actor: AuthenticatedEmployee, q: str
    ) -> dict[str, object]:
        if not actor.application_access_allowed:
            raise ApiError(403, "forbidden")
        if "chat.create" not in actor.effective_permissions:
            raise ApiError(403, "forbidden")
        needle = q.casefold()
        rows: list[tuple[str, str]] = []
        for account in self.employee_auth_repository.list_accounts():
            if not account.is_active:
                continue
            if needle and needle not in account.display_name.casefold():
                continue
            rows.append((account.display_name.casefold(), account.id))
        rows.sort()
        return {
            "employees": [
                _chat_employee_shape(
                    employee_id,
                    self._employee_display_name(employee_id),
                )
                for _display_name, employee_id in rows[:20]
            ]
        }

    # -- commands (run inside the executor transaction) --------------------

    def cmd_create_chat_thread(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        employee = self._require_active_employee()
        thread_type = _v_enum(args["thread_type"], validate_chat_thread_type)
        participant_ids = _chat_employee_ids(args["participant_employee_ids"])
        title = _v_optional_str(args.get("title"), 200)
        try:
            if thread_type == "DIRECT":
                unique_ids = tuple(
                    dict.fromkeys((employee.account.id, *participant_ids))
                )
                if len(unique_ids) != 2:
                    raise ValueError("DIRECT chat requires exactly two participants")
                other_id = next(
                    participant_id
                    for participant_id in unique_ids
                    if participant_id != employee.account.id
                )
                existing = self.chat.find_direct_thread(employee.account.id, other_id)
                thread = self.chat_service.create_direct_thread(employee, other_id)
                status = 200 if existing is not None else 201
            else:
                if title is None:
                    raise ValueError("GROUP chat title is required")
                thread = self.chat_service.create_group_thread(
                    employee,
                    title=title,
                    participant_employee_ids=participant_ids,
                )
                status = 201
        except (
            ChatAccessDenied,
            ChatNotFoundError,
            ChatReferenceNotFoundError,
            TypeError,
            ValueError,
            sqlite3.IntegrityError,
        ) as exc:
            raise _chat_error(exc) from exc
        participants = self.chat.list_participants(thread.thread_id)
        return status, {
            "thread": {
                **_chat_thread_shape(thread),
                "participants": self._chat_participants_shape(participants),
            }
        }

    def cmd_send_chat_message(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        employee = self._require_active_employee()
        thread_id = _v_uuid(path_ids["thread_id"])
        references = _chat_reference_args(args.get("references", []))
        mention_ids = _chat_employee_ids(args.get("mention_employee_ids", []))
        try:
            message = self.chat_service.send_message(
                employee,
                thread_id,
                body=_v_str(args["body"], 20000),
                reply_to_message_id=_v_optional_uuid4(args.get("reply_to_message_id")),
                mention_employee_ids=mention_ids,
                references=references,
            )
            bundles = self.chat.list_messages(thread_id, limit=200)
            bundle = next(
                bundle
                for bundle in bundles
                if bundle.message.message_id == message.message_id
            )
            participants = self.chat.list_participants(thread_id)
        except (
            ChatAccessDenied,
            ChatNotFoundError,
            ChatReferenceNotFoundError,
            StopIteration,
            TypeError,
            ValueError,
            sqlite3.IntegrityError,
        ) as exc:
            raise _chat_error(exc) from exc
        participant_names = {
            participant.employee_id: self._employee_display_name(
                participant.employee_id
            )
            for participant in participants
        }
        return 201, {
            "message": _chat_message_shape(
                bundle,
                author_display_name=self._employee_display_name(
                    message.author_employee_id
                ),
                mention_display_names=participant_names,
            )
        }

    def cmd_mark_chat_thread_read(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        employee = self._require_active_employee()
        thread_id = _v_uuid(path_ids["thread_id"])
        last_read_message_id = _v_optional_uuid4(args["last_read_message_id"])
        try:
            self.chat_service.mark_read(
                employee, thread_id, last_read_message_id=last_read_message_id
            )
        except (
            ChatAccessDenied,
            ChatNotFoundError,
            TypeError,
            ValueError,
            sqlite3.IntegrityError,
        ) as exc:
            raise _chat_error(exc) from exc
        return 200, {
            "thread_id": thread_id,
            "employee_id": employee.account.id,
            "last_read_message_id": last_read_message_id,
        }

    def cmd_create_customer_gastronomic_preference(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        try:
            preference = self.customer_gastronomic_preference_service.create(
                customer_id=path_ids["customer_id"],
                kind=validate_preference_kind(_v_str(args["kind"], 100)),
                value=_v_str(args["value"], 1000),
                source=validate_preference_source(_v_str(args["source"], 100)),
            )
        except CustomerNotFoundError as exc:
            raise ApiError(404, "customer_not_found") from exc
        except (TypeError, ValueError) as exc:
            raise ApiError(422, "invalid_gastronomic_preference") from exc
        return 201, {"preference": _gastronomic_preference_shape(preference)}

    def cmd_update_customer_gastronomic_preference(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        try:
            preference = self.customer_gastronomic_preference_service.update(
                customer_id=path_ids["customer_id"],
                preference_id=path_ids["preference_id"],
                kind=validate_preference_kind(_v_str(args["kind"], 100)),
                value=_v_str(args["value"], 1000),
                source=validate_preference_source(_v_str(args["source"], 100)),
            )
        except CustomerNotFoundError as exc:
            raise ApiError(404, "customer_not_found") from exc
        except CustomerGastronomicPreferenceNotFoundError as exc:
            raise ApiError(404, "gastronomic_preference_not_found") from exc
        except (TypeError, ValueError) as exc:
            raise ApiError(422, "invalid_gastronomic_preference") from exc
        return 200, {"preference": _gastronomic_preference_shape(preference)}

    def cmd_delete_customer_gastronomic_preference(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        preference_id = path_ids["preference_id"]
        try:
            self.customer_gastronomic_preference_service.delete(
                customer_id=path_ids["customer_id"],
                preference_id=preference_id,
            )
        except CustomerNotFoundError as exc:
            raise ApiError(404, "customer_not_found") from exc
        except CustomerGastronomicPreferenceNotFoundError as exc:
            raise ApiError(404, "gastronomic_preference_not_found") from exc
        return 200, {"deleted_preference_id": preference_id}

    def cmd_create_inquiry(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        required = _v_bool(args["call_verification_required"])
        try:
            inquiry = self.inquiry_service.create_inquiry(
                event_date=_v_date(args["event_date"]),
                inquiry_source=_v_enum(args["inquiry_source"], validate_inquiry_source),
                crm_stage=CRM_PIPELINE[0],
                customer_linkage={},
                time_window_text=_v_str(args["time_window_text"], 500),
                location_text=_v_str(args["location_text"], 500),
                guest_count_estimate=_v_guest_count(args["guest_count_estimate"]),
                planning_mode=_v_enum(args["planning_mode"], validate_planning_mode),
                call_verification_required=required,
                call_verification_status=("pending" if required else "not_required"),
                intake_subject=_v_intake(args, "intake_subject", 1000, ""),
                intake_message=_v_intake(args, "intake_message", 5000, ""),
                intake_summary=_v_intake(args, "intake_summary", 2000, ""),
                intake_external_ref=_v_intake(args, "intake_external_ref", 200, ""),
                contact_email=_v_optional_str(args.get("contact_email"), 320),
                contact_phone=_v_optional_str(args.get("contact_phone"), 100),
                contact_name=_v_optional_str(args.get("contact_name"), 200),
                company_name=_v_optional_str(args.get("company_name"), 200),
                event_start_local=_v_optional_local_time(args.get("event_start_local")),
                delivery_time_local=_v_optional_local_time(
                    args.get("delivery_time_local")
                ),
            )
        except DuplicateExternalReferenceError as exc:
            raise ApiError(409, "external_ref_conflict") from exc
        except ValueError as exc:
            message = str(exc)
            if "intake requires email and phone" in message:
                raise ApiError(400, "contact_information_required") from exc
            if "contact email is empty or invalid" in message:
                raise ApiError(400, "invalid_contact_email") from exc
            if "contact phone is empty or invalid" in message:
                raise ApiError(400, "invalid_contact_phone") from exc
            raise
        return 201, {
            "inquiry_id": inquiry.inquiry_id,
            "updated_at": inquiry.updated_at.isoformat(),
        }

    def cmd_contact_completion(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        current = self._require_inquiry(path_ids["id"])
        if _v_datetime(expect["updated_at"]) != current.updated_at:
            raise ApiError(409, "stale_state")
        email = _v_optional_str(args.get("email"), 320)
        phone = _v_optional_str(args.get("phone"), 100)
        if email is None and phone is None:
            raise _invalid()
        try:
            updated = self.inquiry_service.complete_inquiry_contact_information(
                current.inquiry_id,
                email=email,
                phone=phone,
            )
        except ValueError as exc:
            message = str(exc)
            if "already recorded and cannot change" in message:
                raise ApiError(409, "contact_conflict") from exc
            raise ApiError(400, "invalid_contact_value") from exc
        completeness = derive_inquiry_contact_completeness(updated)
        return 200, {
            "inquiry_id": updated.inquiry_id,
            "updated_at": updated.updated_at.isoformat(),
            "contact_completeness": completeness,
            "missing_contact_fields": list(missing_contact_fields(completeness)),
        }

    def cmd_customer_addresses(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        current = self._require_inquiry(path_ids["id"])
        if _v_datetime(expect["updated_at"]) != current.updated_at:
            raise ApiError(409, "stale_state")
        mode_raw = args["delivery_address_mode"]
        try:
            if not isinstance(mode_raw, str):
                raise TypeError("delivery_address_mode must be a str")
            mode = validate_delivery_address_mode(mode_raw)
            invoice_address = customer_address_from_mapping(args["invoice_address"])
            delivery_address = customer_address_from_mapping(args["delivery_address"])
            updated = self.inquiry_service.set_inquiry_customer_addresses(
                current.inquiry_id,
                invoice_address=invoice_address,
                delivery_address=delivery_address,
                delivery_address_mode=mode,
            )
        except (TypeError, ValueError) as exc:
            raise ApiError(422, "invalid_customer_addresses") from exc
        return 200, {
            "inquiry_id": updated.inquiry_id,
            "updated_at": updated.updated_at.isoformat(),
            "customer_snapshot": customer_snapshot_to_mapping(
                updated.customer_snapshot
            ),
        }

    def cmd_fulfillment_mode(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        current = self._require_inquiry(path_ids["id"])
        if _v_datetime(expect["updated_at"]) != current.updated_at:
            raise ApiError(409, "stale_state")
        mode_raw = args["fulfillment_mode"]
        try:
            if not isinstance(mode_raw, str):
                raise TypeError("fulfillment_mode must be a str")
            mode = validate_fulfillment_mode(mode_raw)
            updated = self.inquiry_service.set_inquiry_fulfillment_mode(
                current.inquiry_id,
                fulfillment_mode=mode,
            )
        except (TypeError, ValueError) as exc:
            raise ApiError(422, "invalid_fulfillment_mode") from exc
        return 200, {
            "inquiry_id": updated.inquiry_id,
            "updated_at": updated.updated_at.isoformat(),
            "fulfillment_mode": updated.fulfillment_mode,
        }

    def cmd_update_inquiry(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        current = self._require_inquiry(path_ids["id"])
        if _v_datetime(expect["updated_at"]) != current.updated_at:
            raise ApiError(409, "stale_state")
        crm_stage = _v_enum(args["crm_stage"], validate_crm_stage)
        if self._active_order_for_inquiry(current.inquiry_id) is not None and not (
            inquiry_crm_stage_is_compatible_with_active_order(crm_stage)
        ):
            raise ApiError(422, "active_order_crm_stage_conflict")
        try:
            updated = self.inquiry_service.update_inquiry(
                current.inquiry_id,
                event_date=_v_date(args["event_date"]),
                crm_stage=crm_stage,
                time_window_text=_v_str(args["time_window_text"], 500),
                location_text=_v_str(args["location_text"], 500),
                guest_count_estimate=_v_guest_count(args["guest_count_estimate"]),
                planning_mode=_v_enum(args["planning_mode"], validate_planning_mode),
                intake_subject=_v_intake(
                    args, "intake_subject", 1000, current.intake_subject
                ),
                intake_message=_v_intake(
                    args, "intake_message", 5000, current.intake_message
                ),
                intake_summary=_v_intake(
                    args, "intake_summary", 2000, current.intake_summary
                ),
                intake_external_ref=_v_intake(
                    args, "intake_external_ref", 200, current.intake_external_ref
                ),
                event_start_local=(
                    _v_optional_local_time(args.get("event_start_local"))
                    if "event_start_local" in args
                    else current.event_start_local
                ),
                delivery_time_local=(
                    _v_optional_local_time(args.get("delivery_time_local"))
                    if "delivery_time_local" in args
                    else current.delivery_time_local
                ),
            )
        except DuplicateExternalReferenceError as exc:
            raise ApiError(409, "external_ref_conflict") from exc
        return 200, {
            "inquiry_id": updated.inquiry_id,
            "updated_at": updated.updated_at.isoformat(),
        }

    def cmd_verify(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        self._require_inquiry(path_ids["id"])
        updated = self.inquiry_service.verify_customer_by_call(path_ids["id"])
        return 200, {
            "inquiry_id": updated.inquiry_id,
            "updated_at": updated.updated_at.isoformat(),
        }

    def cmd_convert(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        """Compatibility endpoint: return existing Order or refuse create.

        Order creation is only allowed via convert-accepted (Accepted Offer).
        """
        inquiry = self._require_inquiry(path_ids["id"])
        linked_orders = [
            order
            for order in self.orders.list_orders()
            if order.source_inquiry_id == inquiry.inquiry_id
        ]
        if linked_orders:
            order, version = self.order_service.convert_inquiry_to_order(inquiry)
            return 200, {
                "order_id": order.order_id,
                "order_version_id": version.order_version_id,
            }
        raise ApiError(422, "accepted_offer_required")

    def cmd_prepare_offer(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        snapshot = args.get("snapshot")
        if not isinstance(snapshot, dict):
            raise _invalid()
        try:
            offer = self.offer_service.prepare_offer_version(path_ids["id"], snapshot)
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except OfferPreparationBlockedError as exc:
            reasons = set(exc.reasons)
            if "inquiry_rejected" in reasons:
                raise ApiError(422, "inquiry_rejected") from exc
            if "inquiry_call_verification_unsatisfied" in reasons:
                raise ApiError(422, "inquiry_call_verification_unsatisfied") from exc
            if any(reason.startswith("inquiry_contact_missing_") for reason in reasons):
                raise ApiError(422, "contact_information_incomplete") from exc
            if "active_order_exists" in reasons:
                raise ApiError(409, "active_order_exists") from exc
            if "offer_already_exists" in reasons:
                existing = self.offers.get_by_source_inquiry_id(path_ids["id"])
                if existing is None:
                    raise ApiError(409, "offer_already_exists") from exc
                raise ApiError(
                    409,
                    "offer_already_exists",
                    offer_id=existing.offer_id,
                ) from exc
            raise ApiError(422, "offer_preparation_blocked") from exc
        except ValueError as exc:
            message = str(exc)
            if "snapshot inquiry_id mismatch" in message:
                raise ApiError(422, "inquiry_id_mismatch") from exc
            raise ApiError(422, "invalid_snapshot") from exc
        except sqlite3.IntegrityError:
            existing = self.offers.get_by_source_inquiry_id(path_ids["id"])
            if existing is not None:
                raise ApiError(
                    409,
                    "offer_already_exists",
                    offer_id=existing.offer_id,
                ) from None
            raise
        version = offer.versions[0]
        return 201, {
            "offer_id": offer.offer_id,
            "offer_version_id": version.offer_version_id,
            "snapshot_id": version.snapshot_id,
        }

    def cmd_offer_document(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        """Freeze the customer ANGEBOT / AUFTRAGSBESTÄTIGUNG for one version."""
        offer_id = path_ids["offer_id"]
        offer_version_id = _v_uuid(args["offer_version_id"])
        offer_variant_id = _v_uuid(args["offer_variant_id"])
        created_by = _v_str(args["created_by"], 200)
        existing = self.offer_document_service.get_by_offer_version_id(offer_version_id)
        try:
            snapshot = self.offer_document_service.prepare_offer_document(
                offer_id,
                offer_version_id,
                offer_variant_id,
                created_by,
            )
        except OfferDocumentNotFoundError:
            raise ApiError(404, "not_found") from None
        except OfferDocumentVariantConflictError as exc:
            raise ApiError(409, "offer_document_variant_conflict") from exc
        except OfferDocumentCreationBlocked as exc:
            raise ApiError(422, "offer_document_blocked", reasons=exc.codes) from exc
        status = 200 if existing is not None else 201
        return status, {
            "offer_id": snapshot.offer_id,
            "offer_document_snapshot_id": snapshot.offer_document_snapshot_id,
            "snapshot": views.offer_document_snapshot_summary(snapshot),
        }

    def offer_document(
        self, offer_id: str, offer_version_id: str | None
    ) -> dict[str, object]:
        """Read the frozen document for one OfferVersion (snapshot only)."""
        if offer_version_id is None:
            raise _invalid()
        snapshot = self.offer_document_service.get_by_offer_version_id(offer_version_id)
        if snapshot is None or snapshot.offer_id != offer_id:
            raise ApiError(404, "not_found")
        return {
            "offer_id": snapshot.offer_id,
            "offer_document_snapshot_id": snapshot.offer_document_snapshot_id,
            "snapshot": views.offer_document_snapshot_summary(snapshot),
        }

    def offer_document_pdf(
        self, offer_id: str, offer_version_id: str | None
    ) -> tuple[bytes, str]:
        """Render the already-persisted immutable snapshot to PDF.

        Read-only: never creates a snapshot, never touches Inquiry/Offer/
        catalog. Same ownership check as the JSON read (offer_document)."""
        if offer_version_id is None:
            raise _invalid()
        snapshot = self.offer_document_service.get_by_offer_version_id(offer_version_id)
        if snapshot is None or snapshot.offer_id != offer_id:
            raise ApiError(404, "not_found")
        try:
            pdf_bytes = render_offer_document_pdf(
                snapshot, self.offer_pdf_static_content
            )
        except OfferPdfUnsupportedCharacterError as exc:
            raise ApiError(422, "offer_pdf_unsupported_character") from exc
        except OfferPdfRenderError as exc:
            # Reachable case is configured static content that does not fit
            # the reserved footer area — an operator-fixable validation
            # failure, not an unexpected internal fault. The renderer's own
            # messages never carry paths or library internals, and only the
            # stable code below is returned to the client.
            raise ApiError(422, "offer_pdf_render_failed") from exc
        return pdf_bytes, offer_document_pdf_filename(snapshot)

    def cmd_prepare_next_version(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        snapshot = args.get("snapshot")
        if not isinstance(snapshot, dict):
            raise _invalid()
        offer_id = path_ids["offer_id"]
        try:
            offer = self.offer_service.prepare_next_offer_version(
                offer_id,
                snapshot,
                expected_latest_version_number=_v_int(expect["latest_version_number"]),
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "version conflict" in message:
                raise ApiError(409, "version_conflict") from exc
            if "snapshot inquiry_id mismatch" in message:
                raise ApiError(422, "inquiry_id_mismatch") from exc
            if "active order blocks offer preparation" in message:
                raise ApiError(409, "active_order_exists") from exc
            if "prepare next version blocked" in message:
                raise ApiError(422, "prepare_next_blocked") from exc
            if "contact information incomplete" in message:
                raise ApiError(422, "contact_information_incomplete") from exc
            if "version_number must be" in message:
                raise ApiError(409, "version_conflict") from exc
            raise ApiError(422, "invalid_snapshot") from exc
        except sqlite3.IntegrityError:
            # Do not re-read the Offer in the aborted write transaction.
            raise ApiError(409, "version_conflict") from None
        version = max(offer.versions, key=lambda item: item.version_number)
        return 201, {
            "offer_id": offer.offer_id,
            "offer_version_id": version.offer_version_id,
            "version_number": version.version_number,
            "snapshot_id": version.snapshot_id,
        }

    def cmd_mark_sent(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        offer_id = path_ids["offer_id"]
        offer_version_id = path_ids["version_id"]
        try:
            offer = self.offer_service.record_sent_evidence(
                offer_id,
                offer_version_id,
                sent_at=_v_datetime(args["sent_at"]),
                channel=_v_sent_channel(args["channel"]),
                recipient_reference=_v_str(args["recipient_reference"], 500),
                evidence_reference=_v_str(args["evidence_reference"], 1000),
                recorded_by=CLIENT_ID,
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "sent evidence already exists" in message:
                raise ApiError(409, "sent_evidence_exists") from exc
            if "not a version of offer" in message:
                raise ApiError(422, "version_not_owned") from exc
            if "acceptance blocks sent recording" in message:
                raise ApiError(422, "sent_recording_blocked") from exc
            if "sent recording blocked" in message:
                raise ApiError(422, "sent_recording_blocked") from exc
            if "contact information incomplete" in message:
                raise ApiError(422, "contact_information_incomplete") from exc
            raise ApiError(422, "invalid_sent_evidence") from exc
        except sqlite3.IntegrityError:
            if self.offers.get(offer_id) is None:
                raise ApiError(404, "not_found") from None
            raise ApiError(409, "sent_evidence_exists") from None
        evidence = next(
            item
            for item in offer.sent_evidence
            if item.offer_version_id == offer_version_id
        )
        return 200, {
            "offer_id": offer.offer_id,
            "offer_version_id": offer_version_id,
            "sent_at": evidence.sent_at.isoformat(),
        }

    def cmd_record_acceptance(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        offer_id = path_ids["offer_id"]
        offer_version_id = path_ids["version_id"]
        try:
            offer = self.offer_service.record_acceptance_evidence(
                offer_id,
                offer_version_id,
                _v_uuid(args["accepted_variant_id"]),
                accepted_at=_v_datetime(args["accepted_at"]),
                channel=_v_acceptance_channel(args["channel"]),
                evidence_reference=_v_str(args["evidence_reference"], 1000),
                recorded_by=CLIENT_ID,
                note=_v_optional_str(args.get("note"), 20000),
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "acceptance already exists" in message:
                raise ApiError(409, "acceptance_already_exists") from exc
            if "not a version of offer" in message:
                raise ApiError(422, "version_not_owned") from exc
            if "accepted variant does not belong" in message:
                raise ApiError(422, "invalid_variant") from exc
            if "conversion link blocks acceptance" in message:
                raise ApiError(422, "acceptance_blocked") from exc
            if "acceptance_blocked_newer_version_exists" in message:
                raise ApiError(422, "acceptance_blocked_newer_version_exists") from exc
            if "acceptance blocked" in message:
                raise ApiError(422, "acceptance_blocked") from exc
            if "contact information incomplete" in message:
                raise ApiError(422, "contact_information_incomplete") from exc
            raise ApiError(422, "invalid_acceptance_evidence") from exc
        except sqlite3.IntegrityError:
            if self.offers.get(offer_id) is None:
                raise ApiError(404, "not_found") from None
            raise ApiError(409, "acceptance_already_exists") from None
        assert offer.acceptance_evidence is not None
        acceptance = offer.acceptance_evidence
        return 200, {
            "offer_id": offer.offer_id,
            "offer_version_id": offer_version_id,
            "accepted_variant_id": acceptance.accepted_variant_id,
            "acceptance_id": acceptance.acceptance_id,
        }

    def cmd_record_rejection(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        offer_id = path_ids["offer_id"]
        offer_version_id = path_ids["version_id"]
        try:
            offer = self.offer_service.record_rejection_evidence(
                offer_id,
                offer_version_id,
                rejected_at=_v_datetime(args["rejected_at"]),
                recorded_by=CLIENT_ID,
                evidence_reference=_v_optional_str(
                    args.get("evidence_reference"), 1000
                ),
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "rejection evidence already exists" in message:
                raise ApiError(409, "rejection_evidence_exists") from exc
            if "not a version of offer" in message:
                raise ApiError(422, "version_not_owned") from exc
            if "acceptance blocks rejection" in message:
                raise ApiError(422, "rejection_blocked") from exc
            if "rejection blocked" in message:
                raise ApiError(422, "rejection_blocked") from exc
            if "contact information incomplete" in message:
                raise ApiError(422, "contact_information_incomplete") from exc
            raise ApiError(422, "invalid_rejection_evidence") from exc
        except sqlite3.IntegrityError:
            if self.offers.get(offer_id) is None:
                raise ApiError(404, "not_found") from None
            raise ApiError(409, "rejection_evidence_exists") from None
        evidence = next(
            item
            for item in offer.rejection_evidence
            if item.offer_version_id == offer_version_id
        )
        return 200, {
            "offer_id": offer.offer_id,
            "offer_version_id": offer_version_id,
            "rejected_at": evidence.rejected_at.isoformat(),
        }

    def cmd_record_withdrawal(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        offer_id = path_ids["offer_id"]
        offer_version_id = path_ids["version_id"]
        try:
            offer = self.offer_service.record_withdrawal_evidence(
                offer_id,
                offer_version_id,
                recorded_by=CLIENT_ID,
                reason=_v_optional_str(args.get("reason"), 20000),
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "withdrawal evidence already exists" in message:
                raise ApiError(409, "withdrawal_evidence_exists") from exc
            if "not a version of offer" in message:
                raise ApiError(422, "version_not_owned") from exc
            if "acceptance blocks withdrawal" in message:
                raise ApiError(422, "withdrawal_blocked") from exc
            if "withdrawal blocked" in message:
                raise ApiError(422, "withdrawal_blocked") from exc
            if "contact information incomplete" in message:
                raise ApiError(422, "contact_information_incomplete") from exc
            raise ApiError(422, "invalid_withdrawal_evidence") from exc
        except sqlite3.IntegrityError:
            if self.offers.get(offer_id) is None:
                raise ApiError(404, "not_found") from None
            raise ApiError(409, "withdrawal_evidence_exists") from None
        evidence = next(
            item
            for item in offer.withdrawal_evidence
            if item.offer_version_id == offer_version_id
        )
        return 200, {
            "offer_id": offer.offer_id,
            "offer_version_id": offer_version_id,
            "withdrawn_at": evidence.withdrawn_at.isoformat(),
        }

    def cmd_convert_accepted(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        offer_id = path_ids["offer_id"]
        offer_version_id = path_ids["version_id"]
        accepted_variant_id = _v_uuid(args["accepted_variant_id"])
        acceptance_id = _v_uuid(args["acceptance_id"])
        payment_method = _v_enum(args["payment_method"], validate_payment_method)
        existing = self.offers.get(offer_id)
        if existing is None:
            raise ApiError(404, "not_found")
        replay = existing.conversion_link is not None
        try:
            offer, order, order_version = self.offer_service.convert_accepted_offer(
                offer_id,
                offer_version_id,
                accepted_variant_id,
                acceptance_id,
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "active order blocks conversion" in message:
                raise ApiError(409, "already_converted") from exc
            if "conversion link already exists" in message:
                raise ApiError(409, "conversion_already_exists") from exc
            if "not a version of offer" in message:
                raise ApiError(422, "version_not_owned") from exc
            if "accepted variant does not belong" in message:
                raise ApiError(422, "invalid_variant") from exc
            if "inquiry delivery context unresolved" in message:
                raise ApiError(422, "delivery_context_unresolved") from exc
            if "inquiry conversion blocked" in message:
                raise ApiError(422, "verification_gate_blocked") from exc
            if "contact information incomplete" in message:
                raise ApiError(422, "contact_information_incomplete") from exc
            if "conversion blocked" in message:
                raise ApiError(422, "conversion_blocked") from exc
            raise ApiError(422, "conversion_blocked") from exc
        except sqlite3.IntegrityError:
            offer_check = self.offers.get(offer_id)
            if offer_check is None:
                raise ApiError(404, "not_found") from None
            link = offer_check.conversion_link
            if link is not None:
                if (
                    link.offer_version_id == offer_version_id
                    and link.variant_id == accepted_variant_id
                    and link.acceptance_id == acceptance_id
                ):
                    loaded_order = self.orders.get_order(link.order_id)
                    versions = self.orders.list_order_versions(link.order_id)
                    loaded_version = next(
                        (item for item in versions if item.version_number == 1), None
                    )
                    if loaded_order is None or loaded_version is None:
                        raise ApiError(409, "conversion_already_exists") from None
                    offer = offer_check
                    order = loaded_order
                    order_version = loaded_version
                    replay = True
                else:
                    raise ApiError(409, "conversion_already_exists") from None
            elif (
                self._active_order_for_inquiry(offer_check.source_inquiry_id)
                is not None
            ):
                raise ApiError(409, "already_converted") from None
            else:
                raise
        try:
            self.payment_reminder_service.seed_from_conversion(
                order.order_id,
                payment_method,
            )
        except ValueError as exc:
            if "conflicts with existing conversion selection" in str(exc):
                raise ApiError(409, "payment_method_conflict") from exc
            raise
        self.inquiry_service.update_inquiry(
            offer.source_inquiry_id,
            crm_stage=ACTIVE_ORDER_CRM_STAGE,
        )
        status = 200 if replay else 201
        return status, {
            "offer_id": offer.offer_id,
            "offer_version_id": offer_version_id,
            "accepted_variant_id": accepted_variant_id,
            "acceptance_id": acceptance_id,
            "order_id": order.order_id,
            "order_version_id": order_version.order_version_id,
        }

    def cmd_create_version(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        versions = self.orders.list_order_versions(order.order_id)
        latest = max((v.version_number for v in versions), default=0)
        if (
            _v_int(expect["latest_version_number"]) != latest
            or expect["current_effective_order_version_id"]
            != order.effective_order_version_id
            or expect["current_candidate_order_version_id"]
            != order.candidate_order_version_id
        ):
            raise ApiError(409, "stale_state")
        has_delivery_change = (
            "parent_order_version_id" in args or "delivery_address" in args
        )
        try:
            actor_reference = (
                _v_str(args["actor_reference"], 200)
                if "actor_reference" in args
                else CLIENT_ID
            )
            change_reason = (
                _v_str(args["change_reason"], 1000)
                if "change_reason" in args
                else "Operational order change"
            )
            if has_delivery_change:
                if (
                    "parent_order_version_id" not in args
                    or "delivery_address" not in args
                ):
                    raise _invalid()
                version = self.order_service.propose_delivery_address_change(
                    order.order_id,
                    parent_order_version_id=_v_uuid(args["parent_order_version_id"]),
                    delivery_address=customer_address_from_mapping(
                        args["delivery_address"]
                    ),
                    actor_reference=actor_reference,
                    change_reason=change_reason,
                )
            else:
                required = {
                    "event_date",
                    "time_window_text",
                    "location_text",
                    "guest_count_estimate",
                    "planning_mode",
                }
                if not required <= set(args):
                    raise _invalid()
                version = self.order_service.propose_order_version_change(
                    order.order_id,
                    event_date=_v_date(args["event_date"]),
                    time_window_text=_v_str(args["time_window_text"], 500),
                    location_text=_v_str(args["location_text"], 500),
                    guest_count_estimate=_v_guest_count(args["guest_count_estimate"]),
                    planning_mode=_v_enum(
                        args["planning_mode"], validate_planning_mode
                    ),
                    actor_reference=actor_reference,
                    change_reason=change_reason,
                )
        except OperationalContextMissingError as exc:
            raise ApiError(422, "operational_context_missing") from exc
        except TypeError as exc:
            raise ApiError(422, "validation_error") from exc
        except ValueError as exc:
            message = str(exc)
            if "cancelled" in message:
                raise ApiError(422, "order_cancelled") from exc
            if "not a version of order" in message:
                raise ApiError(422, "version_not_owned") from exc
            raise ApiError(422, "validation_error") from exc
        return 201, {
            "order_version_id": version.order_version_id,
            "version_number": version.version_number,
            "candidate_order_version_id": version.order_version_id,
            "parent_order_version_id": version.parent_order_version_id,
            "changed_fields": list(version.changed_fields),
        }

    def cmd_print_confirm(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        version = self._owned_version(order.order_id, _v_uuid(args["order_version_id"]))
        job = self._ensure_kitchen_print_job(order.order_id, version.order_version_id)
        current_version = self.orders.get_order_version(version.order_version_id)
        assert current_version is not None
        return 200, {
            "order_id": order.order_id,
            "order_version_id": version.order_version_id,
            "print_job_id": job.print_job_id,
            "kitchen_print_confirmed_at": (
                current_version.kitchen_print_confirmed_at.isoformat()
                if current_version.kitchen_print_confirmed_at is not None
                else None
            ),
        }

    def _ensure_kitchen_print_job(self, order_id: str, order_version_id: str):
        attempts = self.kitchen_print_service.list_print_jobs_for_version(
            order_version_id
        )
        if not attempts:
            return self.kitchen_print_service.request_print(order_id, order_version_id)
        latest = attempts[-1]
        if latest.acknowledged_at is not None:
            return latest
        if (
            latest.rejected_at is not None
            or latest.superseded_at is not None
            or self.kitchen_print_service.is_ack_overdue(latest)
        ):
            return self.kitchen_print_service.reprint(latest.print_job_id)
        return latest

    def cmd_effective(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        expected_pointer = expect["current_effective_order_version_id"]
        expected_candidate = expect["current_candidate_order_version_id"]
        if (expected_pointer is not None and not isinstance(expected_pointer, str)) or (
            expected_candidate is not None and not isinstance(expected_candidate, str)
        ):
            raise _invalid()
        if (
            expected_pointer != order.effective_order_version_id
            or expected_candidate != order.candidate_order_version_id
        ):
            raise ApiError(409, "stale_state")
        version = self._owned_version(order.order_id, _v_uuid(args["order_version_id"]))
        try:
            updated = self.core.make_order_version_effective(
                order.order_id, version.order_version_id
            )
        except ValueError as exc:
            code = (
                "order_version_not_current_candidate"
                if "not current candidate" in str(exc)
                else "kitchen_print_not_confirmed"
            )
            raise ApiError(422, code) from exc
        return 200, {
            "order_id": updated.order_id,
            "effective_order_version_id": updated.effective_order_version_id,
            "candidate_order_version_id": updated.candidate_order_version_id,
            "updated_at": updated.updated_at.isoformat(),
        }

    def cmd_ready(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        # Unknown order is NOT 404 here: the service reports it as a reason
        # (current behavior, pack §4.4).
        evaluation = self.core.request_ready_to_send(path_ids["id"])
        return 200, {
            "evaluation": {
                "ready": evaluation.ready,
                "reasons": list(evaluation.reasons),
            }
        }

    def _pause_actor_reference(self, args: dict[str, object]) -> str:
        if "actor_reference" in args:
            return _v_str(args["actor_reference"], 200)
        return CLIENT_ID

    def _validate_pause_expect(
        self, expect: dict, projection: dict[str, object]
    ) -> None:
        expected_active = expect["operational_pause_active"]
        if not isinstance(expected_active, bool):
            raise _invalid()
        if expected_active != projection["active"]:
            raise ApiError(409, "stale_state")
        if "latest_pause_event_id" not in expect:
            raise _invalid()
        expected_latest = _v_optional_uuid4(expect["latest_pause_event_id"])
        actual_latest = projection.get("latest_pause_event_id")
        if expected_latest != actual_latest:
            raise ApiError(409, "stale_state")

    def _validate_resume_expect(
        self, expect: dict, projection: dict[str, object]
    ) -> None:
        expected_active = expect["operational_pause_active"]
        if not isinstance(expected_active, bool):
            raise _invalid()
        if not projection["active"]:
            raise ApiError(409, "order_not_paused")
        if not expected_active:
            raise ApiError(409, "stale_state")
        for key in ("current_pause_event_id", "latest_pause_event_id"):
            if key not in expect:
                raise _invalid()
        expected_current = _v_uuid(expect["current_pause_event_id"])
        expected_latest = _v_uuid(expect["latest_pause_event_id"])
        if expected_current != projection.get("current_pause_event_id"):
            raise ApiError(409, "stale_state")
        if expected_latest != projection.get("latest_pause_event_id"):
            raise ApiError(409, "stale_state")

    def _map_pause_error(self, exc: ValueError) -> ApiError:
        message = str(exc)
        if message.startswith("no order with id"):
            return ApiError(404, "not_found")
        if "is cancelled" in message:
            return ApiError(422, "order_cancelled")
        if "is already paused" in message:
            return ApiError(409, "order_already_paused")
        if "is not paused" in message:
            return ApiError(409, "order_not_paused")
        if message == "stale operational pause state":
            return ApiError(409, "stale_state")
        if (
            "invalid pause reason_code" in message
            or "invalid resume reason_code" in message
        ):
            return ApiError(422, "invalid_request")
        if "exceeds length limit" in message:
            return ApiError(422, "invalid_request")
        return ApiError(422, "invalid_request")

    def cmd_pause(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        projection = self.core.get_operational_pause_projection(order.order_id)
        self._validate_pause_expect(expect, projection)
        command_id = self._active_command_id
        if command_id is None:
            raise ApiError(500, "internal")
        latest_raw = projection.get("latest_pause_event_id")
        expected_latest = (
            latest_raw if isinstance(latest_raw, str) or latest_raw is None else None
        )
        try:
            event = self.core.pause_order(
                order.order_id,
                reason_code=_v_str(args["reason_code"], 100),
                note=_v_optional_str(args["note"], 2000) if "note" in args else None,
                actor_reference=self._pause_actor_reference(args),
                command_id=command_id,
                expected_latest_pause_event_id=expected_latest,
            )
        except ValueError as exc:
            raise self._map_pause_error(exc) from exc
        updated = self.core.get_operational_pause_projection(order.order_id)
        return 200, {
            "order_id": order.order_id,
            "pause_event_id": event.pause_event_id,
            "operational_pause": updated,
        }

    def cmd_resume(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        projection = self.core.get_operational_pause_projection(order.order_id)
        self._validate_resume_expect(expect, projection)
        command_id = self._active_command_id
        if command_id is None:
            raise ApiError(500, "internal")
        current_pause_event_id = projection.get("current_pause_event_id")
        latest_pause_event_id = projection.get("latest_pause_event_id")
        assert isinstance(current_pause_event_id, str)
        assert isinstance(latest_pause_event_id, str)
        try:
            event = self.core.resume_order(
                order.order_id,
                reason_code=_v_str(args["reason_code"], 100),
                note=_v_optional_str(args["note"], 2000) if "note" in args else None,
                actor_reference=self._pause_actor_reference(args),
                command_id=command_id,
                expected_current_pause_event_id=current_pause_event_id,
                expected_latest_pause_event_id=latest_pause_event_id,
            )
        except ValueError as exc:
            raise self._map_pause_error(exc) from exc
        updated = self.core.get_operational_pause_projection(order.order_id)
        return 200, {
            "order_id": order.order_id,
            "pause_event_id": event.pause_event_id,
            "operational_pause": updated,
        }

    def cmd_cancel(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_order(path_ids["id"])
        if _v_datetime(expect["updated_at"]) != order.updated_at:
            raise ApiError(409, "stale_state")
        cancelled = self.core.cancel_order(order.order_id)
        assert cancelled.cancelled_at is not None
        return 200, {
            "order_id": cancelled.order_id,
            "cancelled_at": cancelled.cancelled_at.isoformat(),
            "updated_at": cancelled.updated_at.isoformat(),
        }

    def cmd_delete_order(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_order(path_ids["id"])
        versions = self.orders.list_order_versions(order.order_id)
        target = next(
            (
                version
                for version in versions
                if version.order_version_id == order.candidate_order_version_id
            ),
            None,
        )
        if target is None:
            target = max(versions, key=lambda item: item.version_number, default=None)
        if target is None:
            raise ApiError(422, "order_delete_name_unavailable")
        operational = self.orders.get_operational_context(target.order_version_id)
        if operational is None:
            raise ApiError(422, "order_delete_name_unavailable")
        expected_name = (
            operational.recipient_company or operational.recipient_name or ""
        ).strip()
        if not expected_name:
            raise ApiError(422, "order_delete_name_unavailable")
        submitted_name = _v_str(args["confirmation_name"], 500).strip()
        if not hmac.compare_digest(submitted_name, expected_name):
            raise ApiError(422, "order_delete_confirmation_mismatch")
        purge_order_with_dependencies(self.orders, order.order_id)
        return 200, {"order_id": order.order_id}

    def cmd_payment_reminder(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        current = self.payment_reminders.get(order.order_id)
        expected_at = expect["updated_at"]
        if expected_at is not None and not isinstance(expected_at, str):
            raise _invalid()
        actual_at = (
            current.updated_at.isoformat()
            if current is not None and current.updated_at is not None
            else None
        )
        if expected_at != actual_at:
            raise ApiError(409, "stale_state")
        try:
            actor_reference = (
                _v_optional_str(args.get("actor_reference"), 200) or CLIENT_ID
            )
            view = self.payment_reminder_service.save(
                OrderPaymentReminder(
                    order_id=order.order_id,
                    payment_method=_v_enum(
                        args["payment_method"], validate_payment_method
                    ),
                    invoice_created=_v_bool(args["invoice_created"]),
                    invoice_number=_v_optional_str(args["invoice_number"], 200),
                    sent_on=_v_optional_date(args["sent_on"]),
                    due_on=None,
                    paid_on=_v_optional_date(args["paid_on"]),
                    cash_received=_v_bool(args["cash_received"]),
                    quittung_printed=_v_bool(args.get("quittung_printed", False)),
                ),
                actor_reference=actor_reference,
                mark_payment_reminder_sent=_v_bool(
                    args.get("payment_reminder_sent", False)
                ),
                mark_mahnung_sent=_v_bool(args.get("mahnung_sent", False)),
            )
        except ValueError as exc:
            raise ApiError(422, "invalid_payment_reminder") from exc
        assert view.updated_at is not None
        return 200, {
            "order_id": order.order_id,
            "updated_at": view.updated_at.isoformat(),
        }

    def cmd_payment_method_change(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        current = self.payment_reminders.get(order.order_id)
        expected_at = expect["updated_at"]
        if expected_at is not None and not isinstance(expected_at, str):
            raise _invalid()
        actual_at = (
            current.updated_at.isoformat()
            if current is not None and current.updated_at is not None
            else None
        )
        if expected_at != actual_at:
            raise ApiError(409, "stale_state")
        try:
            actor_reference = (
                _v_optional_str(args.get("actor_reference"), 200) or CLIENT_ID
            )
            view = self.payment_reminder_service.change_payment_method(
                order.order_id,
                new_payment_method=_v_enum(
                    args["new_payment_method"], validate_payment_method
                ),
                reason=_v_str(args["reason"], 500),
                actor_reference=actor_reference,
            )
        except ValueError as exc:
            if str(exc) in {
                "payment method cannot change after payment",
                "new payment method must differ",
            }:
                raise ApiError(409, "payment_method_change_conflict") from exc
            raise ApiError(422, "invalid_payment_method_change") from exc
        assert view.updated_at is not None
        return 200, {
            "order_id": order.order_id,
            "updated_at": view.updated_at.isoformat(),
        }

    def cmd_payment_completion_correction(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_order(path_ids["id"])
        current = self.payment_reminders.get(order.order_id)
        expected_at = expect["updated_at"]
        if expected_at is not None and not isinstance(expected_at, str):
            raise _invalid()
        actual_at = (
            current.updated_at.isoformat()
            if current is not None and current.updated_at is not None
            else None
        )
        if expected_at != actual_at:
            raise ApiError(409, "stale_state")
        command_id = self._active_command_id
        if command_id is None:
            raise ApiError(500, "internal")
        try:
            actor_reference = (
                _v_optional_str(args.get("actor_reference"), 200) or CLIENT_ID
            )
            view = self.payment_reminder_service.correct_payment_completion(
                order.order_id,
                correction_id=command_id,
                reason=_v_str(args["reason"], 500),
                actor_reference=actor_reference,
            )
        except ValueError as exc:
            if str(exc) in {
                "payment completion is not recorded",
                "payment correction id conflict",
            }:
                raise ApiError(409, "payment_correction_conflict") from exc
            raise ApiError(422, "invalid_payment_correction") from exc
        assert view.updated_at is not None
        return 200, {
            "order_id": order.order_id,
            "updated_at": view.updated_at.isoformat(),
        }

    def cmd_confirmation_document(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        expected = expect["current_effective_order_version_id"]
        if expected is not None and not isinstance(expected, str):
            raise _invalid()
        if expected != order.effective_order_version_id:
            raise ApiError(409, "stale_state")
        assert order.effective_order_version_id is not None
        existing = self.confirmation_documents.get_by_order_version_id(
            order.effective_order_version_id
        )
        replay = existing is not None
        try:
            snapshot = self.confirmation_document_service.prepare_snapshot(
                order.order_id,
                order.effective_order_version_id,
                _v_str(args["created_by"], 200),
            )
        except OrderConfirmationDocumentStaleVersionError as exc:
            raise ApiError(409, "stale_state") from exc
        except CustomerDocumentCreationBlocked as exc:
            raise ApiError(
                422,
                "confirmation_document_blocked",
                reasons=exc.codes,
            ) from exc
        except OrderConfirmationDocumentBlockedError as exc:
            message = str(exc)
            if message == "commercial_totals_invalid":
                raise ApiError(422, "commercial_totals_invalid") from exc
            raise ApiError(422, "confirmation_document_blocked") from exc
        summary = self.confirmation_document_service.summary_for_snapshot(snapshot)
        status = 200 if replay else 201
        return status, {
            "order_id": order.order_id,
            "document_snapshot_id": snapshot.document_snapshot_id,
            "snapshot": views.confirmation_document_summary_shape(summary),
        }

    def confirmation_document_send_status(self, order_id: str) -> dict[str, object]:
        try:
            return self.confirmation_outbound_service.send_status(order_id)
        except OrderConfirmationOutboundNotFoundError as exc:
            raise ApiError(404, "not_found") from exc

    def confirmation_document_fake_outbox(
        self, order_id: str, *, document_snapshot_id: str | None = None
    ) -> dict[str, object]:
        try:
            message = self.confirmation_outbound_service.fake_outbox_message(
                order_id, document_snapshot_id=document_snapshot_id
            )
        except OrderConfirmationOutboundNotFoundError as exc:
            raise ApiError(404, "not_found") from exc
        return {
            "test_transport": True,
            "real_delivery": False,
            "fake_outbox_message_id": message.fake_outbox_message_id,
            "send_attempt_id": message.send_attempt_id,
            "document_snapshot_id": message.document_snapshot_id,
            "recipient_email": message.recipient_email,
            "subject": message.subject,
            "text_body": message.text_body,
            "html_body": message.html_body,
            "payload_hash": message.payload_hash,
        }

    def cmd_confirmation_document_send(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        expected = expect["current_effective_order_version_id"]
        if expected is not None and not isinstance(expected, str):
            raise _invalid()
        if expected != order.effective_order_version_id:
            raise ApiError(409, "stale_state")
        document_snapshot_id = _v_uuid(args["document_snapshot_id"])
        try:
            result = self.confirmation_outbound_service.send_to_fake_outbox(
                order.order_id,
                document_snapshot_id,
                order.effective_order_version_id or "",
                _v_str(args["requested_by"], 200),
            )
        except OrderConfirmationOutboundStaleVersionError as exc:
            raise ApiError(409, "stale_state") from exc
        except OrderConfirmationOutboundNotFoundError as exc:
            raise ApiError(404, "not_found") from exc
        except OrderConfirmationOutboundRecipientMissingError as exc:
            raise ApiError(422, "confirmation_document_recipient_missing") from exc
        except OrderConfirmationOutboundAlreadySentError as exc:
            raise ApiError(409, "confirmation_document_already_sent") from exc
        except OrderConfirmationOutboundPayloadInvalidError as exc:
            raise ApiError(422, "outbound_payload_invalid") from exc
        except OrderConfirmationOutboundBlockedError as exc:
            if exc.blocker_code == "pending_order_version_change":
                raise ApiError(422, "pending_order_version_change") from exc
            if exc.blocker_code == "kitchen_print_not_confirmed":
                raise ApiError(422, "kitchen_print_not_confirmed") from exc
            if exc.blocker_code == "order_storniert":
                raise ApiError(422, "order_storniert") from exc
            if exc.blocker_code == "order_not_ready_to_send":
                raise ApiError(
                    422,
                    "order_not_ready_to_send",
                    reasons=exc.reasons,
                ) from exc
            if exc.blocker_code == "confirmation_document_not_current":
                raise ApiError(409, "confirmation_document_not_current") from exc
            raise ApiError(422, "confirmation_document_blocked") from exc
        summary = result.summary
        body = {
            "order_id": order.order_id,
            "send_attempt_id": summary.send_attempt_id,
            "send_evidence_id": summary.send_evidence_id,
            "fake_outbox_message_id": summary.fake_outbox_message_id,
            "document_snapshot_id": summary.document_snapshot_id,
            "document_hash": summary.document_hash,
            "payload_hash": summary.payload_hash,
            "recipient_email_masked": summary.recipient_email_masked,
            "transport_kind": summary.transport_kind,
            "outcome": summary.outcome,
            "accepted_at": summary.accepted_at,
            "real_delivery": False,
        }
        return 201, body


# --- command specs: exact args/expect keys per route (pack §4.4) --------------


@dataclass(frozen=True)
class _ArgKeys:
    required: frozenset[str]
    optional: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _CommandSpec:
    handler: str
    args_keys: _ArgKeys
    expect_keys: set[str]


_INTAKE_OPTIONAL = frozenset(
    {"intake_subject", "intake_message", "intake_summary", "intake_external_ref"}
)
_STRUCTURED_CONTACT_OPTIONAL = frozenset(
    {"contact_email", "contact_phone", "contact_name", "company_name"}
)
_CREATE_ARGS = _ArgKeys(
    required=frozenset(
        {
            "event_date",
            "inquiry_source",
            "time_window_text",
            "location_text",
            "guest_count_estimate",
            "planning_mode",
            "call_verification_required",
        }
    ),
    optional=(
        _INTAKE_OPTIONAL
        | _STRUCTURED_CONTACT_OPTIONAL
        | frozenset({"event_start_local", "delivery_time_local"})
    ),
)
_CONTACT_COMPLETION_ARGS = _ArgKeys(
    required=frozenset(),
    optional=frozenset({"email", "phone"}),
)
_CUSTOMER_ADDRESSES_ARGS = _ArgKeys(
    required=frozenset(
        {
            "invoice_address",
            "delivery_address_mode",
            "delivery_address",
        }
    ),
)
_FULFILLMENT_MODE_ARGS = _ArgKeys(
    required=frozenset({"fulfillment_mode"}),
)
_UPDATE_ARGS = _ArgKeys(
    required=frozenset(
        {
            "event_date",
            "crm_stage",
            "time_window_text",
            "location_text",
            "guest_count_estimate",
            "planning_mode",
        }
    ),
    optional=_INTAKE_OPTIONAL
    | frozenset({"event_start_local", "delivery_time_local"}),
)
_VERSION_ARGS = _ArgKeys(
    required=frozenset(),
    optional=frozenset(
        {
            "event_date",
            "time_window_text",
            "location_text",
            "guest_count_estimate",
            "planning_mode",
            "actor_reference",
            "change_reason",
            "parent_order_version_id",
            "delivery_address",
        }
    ),
)
_NO_ARGS = _ArgKeys(required=frozenset())
_SNAPSHOT_ARGS = _ArgKeys(required=frozenset({"snapshot"}))
_OFFER_DOCUMENT_ARGS = _ArgKeys(
    required=frozenset({"offer_version_id", "offer_variant_id", "created_by"})
)
_MARK_SENT_ARGS = _ArgKeys(
    required=frozenset(
        {
            "sent_at",
            "channel",
            "recipient_reference",
            "evidence_reference",
        }
    )
)
_RECORD_ACCEPTANCE_ARGS = _ArgKeys(
    required=frozenset(
        {
            "accepted_variant_id",
            "accepted_at",
            "channel",
            "evidence_reference",
        }
    ),
    optional=frozenset({"note"}),
)
_RECORD_REJECTION_ARGS = _ArgKeys(
    required=frozenset({"rejected_at"}),
    optional=frozenset({"evidence_reference"}),
)
_RECORD_WITHDRAWAL_ARGS = _ArgKeys(
    required=frozenset(),
    optional=frozenset({"reason"}),
)
_CONVERT_ACCEPTED_ARGS = _ArgKeys(
    required=frozenset({"accepted_variant_id", "acceptance_id", "payment_method"})
)
_VERSION_ID_ARGS = _ArgKeys(required=frozenset({"order_version_id"}))
_ORDER_DELETE_ARGS = _ArgKeys(required=frozenset({"confirmation_name"}))
_PAYMENT_REMINDER_ARGS = _ArgKeys(
    required=frozenset(
        {
            "payment_method",
            "invoice_created",
            "invoice_number",
            "sent_on",
            "due_on",
            "paid_on",
            "cash_received",
        }
    ),
    optional=frozenset(
        {
            "quittung_printed",
            "payment_reminder_sent",
            "mahnung_sent",
            "actor_reference",
        }
    ),
)
_PAYMENT_METHOD_CHANGE_ARGS = _ArgKeys(
    required=frozenset({"new_payment_method", "reason"}),
    optional=frozenset({"actor_reference"}),
)
_PAYMENT_CORRECTION_ARGS = _ArgKeys(
    required=frozenset({"reason"}),
    optional=frozenset({"actor_reference"}),
)
_CONFIRMATION_DOCUMENT_ARGS = _ArgKeys(required=frozenset({"created_by"}))
_CONFIRMATION_DOCUMENT_SEND_ARGS = _ArgKeys(
    required=frozenset({"document_snapshot_id", "requested_by"})
)
_MANUAL_TASK_CREATE_ARGS = _ArgKeys(
    required=frozenset({"title"}),
    optional=frozenset(
        {
            "description",
            "due_at",
            "assigned_to_employee_id",
            "subject_type",
            "subject_id",
            "subject_contact_key",
            "priority",
        }
    ),
)
_PAUSE_ARGS = _ArgKeys(
    required=frozenset({"reason_code"}),
    optional=frozenset({"note", "actor_reference"}),
)
_RESUME_ARGS = _ArgKeys(
    required=frozenset({"reason_code"}),
    optional=frozenset({"note", "actor_reference"}),
)
_CATALOG_DISH_UPDATE_ARGS = _ArgKeys(
    required=frozenset(
        {
            "name",
            "current_unit_net_cents",
            "allergens",
            "active",
        }
    ),
    optional=frozenset({"description", "composition", "notes", "effective_from"}),
)
_CATALOG_DISH_CREATE_ARGS = _ArgKeys(
    required=frozenset(
        {
            "name",
            "category",
            "pricing_unit",
            "current_unit_net_cents",
            "vat_rate_percent",
        }
    ),
    optional=frozenset({"description", "composition", "notes", "allergens"}),
)
_CHAT_THREAD_CREATE_ARGS = _ArgKeys(
    required=frozenset({"thread_type", "participant_employee_ids"}),
    optional=frozenset({"title"}),
)
_CHAT_MESSAGE_CREATE_ARGS = _ArgKeys(
    required=frozenset({"body"}),
    optional=frozenset({"reply_to_message_id", "mention_employee_ids", "references"}),
)
_CHAT_READ_ARGS = _ArgKeys(required=frozenset({"last_read_message_id"}))

_GASTRONOMIC_PREFERENCE_ARGS = _ArgKeys(required=frozenset({"kind", "value", "source"}))

_COMMANDS: dict[str, _CommandSpec] = {
    "create_customer_gastronomic_preference": _CommandSpec(
        "cmd_create_customer_gastronomic_preference",
        _GASTRONOMIC_PREFERENCE_ARGS,
        set(),
    ),
    "update_customer_gastronomic_preference": _CommandSpec(
        "cmd_update_customer_gastronomic_preference",
        _GASTRONOMIC_PREFERENCE_ARGS,
        set(),
    ),
    "delete_customer_gastronomic_preference": _CommandSpec(
        "cmd_delete_customer_gastronomic_preference", _NO_ARGS, set()
    ),
    "create_inquiry": _CommandSpec("cmd_create_inquiry", _CREATE_ARGS, set()),
    "update_inquiry": _CommandSpec("cmd_update_inquiry", _UPDATE_ARGS, {"updated_at"}),
    "contact-completion": _CommandSpec(
        "cmd_contact_completion", _CONTACT_COMPLETION_ARGS, {"updated_at"}
    ),
    "customer-addresses": _CommandSpec(
        "cmd_customer_addresses", _CUSTOMER_ADDRESSES_ARGS, {"updated_at"}
    ),
    "fulfillment-mode": _CommandSpec(
        "cmd_fulfillment_mode", _FULFILLMENT_MODE_ARGS, {"updated_at"}
    ),
    "verify": _CommandSpec("cmd_verify", _NO_ARGS, set()),
    "convert": _CommandSpec("cmd_convert", _NO_ARGS, set()),
    "prepare-offer": _CommandSpec("cmd_prepare_offer", _SNAPSHOT_ARGS, set()),
    "prepare-next-version": _CommandSpec(
        "cmd_prepare_next_version",
        _SNAPSHOT_ARGS,
        {"latest_version_number"},
    ),
    "offer-document": _CommandSpec("cmd_offer_document", _OFFER_DOCUMENT_ARGS, set()),
    "mark-sent": _CommandSpec("cmd_mark_sent", _MARK_SENT_ARGS, set()),
    "record-acceptance": _CommandSpec(
        "cmd_record_acceptance", _RECORD_ACCEPTANCE_ARGS, set()
    ),
    "record-rejection": _CommandSpec(
        "cmd_record_rejection", _RECORD_REJECTION_ARGS, set()
    ),
    "record-withdrawal": _CommandSpec(
        "cmd_record_withdrawal", _RECORD_WITHDRAWAL_ARGS, set()
    ),
    "convert-accepted": _CommandSpec(
        "cmd_convert_accepted", _CONVERT_ACCEPTED_ARGS, set()
    ),
    "versions": _CommandSpec(
        "cmd_create_version",
        _VERSION_ARGS,
        {
            "latest_version_number",
            "current_effective_order_version_id",
            "current_candidate_order_version_id",
        },
    ),
    "print-confirm": _CommandSpec("cmd_print_confirm", _VERSION_ID_ARGS, set()),
    "effective": _CommandSpec(
        "cmd_effective",
        _VERSION_ID_ARGS,
        {
            "current_effective_order_version_id",
            "current_candidate_order_version_id",
        },
    ),
    "ready": _CommandSpec("cmd_ready", _NO_ARGS, set()),
    "pause": _CommandSpec(
        "cmd_pause",
        _PAUSE_ARGS,
        {"operational_pause_active", "latest_pause_event_id"},
    ),
    "resume": _CommandSpec(
        "cmd_resume",
        _RESUME_ARGS,
        {
            "operational_pause_active",
            "current_pause_event_id",
            "latest_pause_event_id",
        },
    ),
    "cancel": _CommandSpec("cmd_cancel", _NO_ARGS, {"updated_at"}),
    "delete-order": _CommandSpec("cmd_delete_order", _ORDER_DELETE_ARGS, set()),
    "payment-reminder": _CommandSpec(
        "cmd_payment_reminder", _PAYMENT_REMINDER_ARGS, {"updated_at"}
    ),
    "payment-method": _CommandSpec(
        "cmd_payment_method_change",
        _PAYMENT_METHOD_CHANGE_ARGS,
        {"updated_at"},
    ),
    "payment-correction": _CommandSpec(
        "cmd_payment_completion_correction",
        _PAYMENT_CORRECTION_ARGS,
        {"updated_at"},
    ),
    "confirmation-document": _CommandSpec(
        "cmd_confirmation_document",
        _CONFIRMATION_DOCUMENT_ARGS,
        {"current_effective_order_version_id"},
    ),
    "confirmation-document-send": _CommandSpec(
        "cmd_confirmation_document_send",
        _CONFIRMATION_DOCUMENT_SEND_ARGS,
        {"current_effective_order_version_id"},
    ),
    "create_manual_task": _CommandSpec(
        "cmd_create_manual_task", _MANUAL_TASK_CREATE_ARGS, set()
    ),
    "complete_manual_task": _CommandSpec("cmd_complete_manual_task", _NO_ARGS, set()),
    "update_catalog_dish": _CommandSpec(
        "cmd_update_catalog_dish", _CATALOG_DISH_UPDATE_ARGS, {"updated_at"}
    ),
    "create_catalog_dish": _CommandSpec(
        "cmd_create_catalog_dish", _CATALOG_DISH_CREATE_ARGS, set()
    ),
    "activate_catalog_dish": _CommandSpec(
        "cmd_activate_catalog_dish", _NO_ARGS, {"updated_at"}
    ),
    "deactivate_catalog_dish": _CommandSpec(
        "cmd_deactivate_catalog_dish", _NO_ARGS, {"updated_at"}
    ),
    "create_chat_thread": _CommandSpec(
        "cmd_create_chat_thread", _CHAT_THREAD_CREATE_ARGS, set()
    ),
    "send_chat_message": _CommandSpec(
        "cmd_send_chat_message", _CHAT_MESSAGE_CREATE_ARGS, set()
    ),
    "mark_chat_thread_read": _CommandSpec(
        "cmd_mark_chat_thread_read",
        _CHAT_READ_ARGS,
        set(),
    ),
}

# route table: (regex, template, {method: kind})
_ROUTES: tuple[tuple[re.Pattern[str], str, dict[str, str]], ...] = (
    (
        re.compile(r"^/office/v1/auth/configurator-handoff/exchange$"),
        "/office/v1/auth/configurator-handoff/exchange",
        {"POST": "configurator-handoff-exchange"},
    ),
    (re.compile(r"^/office/v1/queue$"), "/office/v1/queue", {"GET": "queue"}),
    (
        re.compile(r"^/office/v1/work-center$"),
        "/office/v1/work-center",
        {"GET": "work_center"},
    ),
    (
        re.compile(r"^/office/v1/chat/threads$"),
        "/office/v1/chat/threads",
        {"GET": "list_chat_threads", "POST": "create_chat_thread"},
    ),
    (
        re.compile(r"^/office/v1/chat/search$"),
        "/office/v1/chat/search",
        {"GET": "search_chat"},
    ),
    (
        re.compile(r"^/office/v1/chat/entity-search$"),
        "/office/v1/chat/entity-search",
        {"GET": "search_chat_entities"},
    ),
    (
        re.compile(r"^/office/v1/chat/employees$"),
        "/office/v1/chat/employees",
        {"GET": "search_chat_employees"},
    ),
    (
        re.compile(r"^/office/v1/chat/threads/(?P<thread_id>[^/]+)$"),
        "/office/v1/chat/threads/{thread_id}",
        {"GET": "chat_thread_detail"},
    ),
    (
        re.compile(r"^/office/v1/chat/threads/(?P<thread_id>[^/]+)/messages$"),
        "/office/v1/chat/threads/{thread_id}/messages",
        {"POST": "send_chat_message"},
    ),
    (
        re.compile(r"^/office/v1/chat/threads/(?P<thread_id>[^/]+)/read$"),
        "/office/v1/chat/threads/{thread_id}/read",
        {"POST": "mark_chat_thread_read"},
    ),
    (
        re.compile(r"^/office/v1/chat/threads/(?P<thread_id>[^/]+)/participants$"),
        "/office/v1/chat/threads/{thread_id}/participants",
        {"GET": "chat_thread_participants"},
    ),
    (
        re.compile(r"^/office/v1/customers/(?P<customer_id>[^/]+)/order-history$"),
        "/office/v1/customers/{customer_id}/order-history",
        {"GET": "customer_order_history"},
    ),
    (
        re.compile(
            r"^/office/v1/customers/(?P<customer_id>[^/]+)/gastronomic-preferences$"
        ),
        "/office/v1/customers/{customer_id}/gastronomic-preferences",
        {"GET": "list_customer_gastronomic_preferences"},
    ),
    (
        re.compile(
            r"^/office/v1/customers/(?P<customer_id>[^/]+)/gastronomic-preferences/create$"
        ),
        "/office/v1/customers/{customer_id}/gastronomic-preferences/create",
        {"POST": "create_customer_gastronomic_preference"},
    ),
    (
        re.compile(
            r"^/office/v1/customers/(?P<customer_id>[^/]+)/gastronomic-preferences/"
            r"(?P<preference_id>[^/]+)/update$"
        ),
        "/office/v1/customers/{customer_id}/gastronomic-preferences/{preference_id}/update",
        {"POST": "update_customer_gastronomic_preference"},
    ),
    (
        re.compile(
            r"^/office/v1/customers/(?P<customer_id>[^/]+)/gastronomic-preferences/"
            r"(?P<preference_id>[^/]+)/delete$"
        ),
        "/office/v1/customers/{customer_id}/gastronomic-preferences/{preference_id}/delete",
        {"POST": "delete_customer_gastronomic_preference"},
    ),
    (
        re.compile(r"^/office/v1/inquiries$"),
        "/office/v1/inquiries",
        {"GET": "list_inquiries", "POST": "create_inquiry"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)$"),
        "/office/v1/inquiries/{id}",
        {"GET": "inquiry_detail"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/update$"),
        "/office/v1/inquiries/{id}/update",
        {"POST": "update_inquiry"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/contact-completion$"),
        "/office/v1/inquiries/{id}/contact-completion",
        {"POST": "contact-completion"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/customer-addresses$"),
        "/office/v1/inquiries/{id}/customer-addresses",
        {"POST": "customer-addresses"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/fulfillment-mode$"),
        "/office/v1/inquiries/{id}/fulfillment-mode",
        {"POST": "fulfillment-mode"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/verify$"),
        "/office/v1/inquiries/{id}/verify",
        {"POST": "verify"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/convert$"),
        "/office/v1/inquiries/{id}/convert",
        {"POST": "convert"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/prepare-offer$"),
        "/office/v1/inquiries/{id}/prepare-offer",
        {"POST": "prepare-offer"},
    ),
    (
        re.compile(r"^/office/v1/offers/(?P<offer_id>[^/]+)/prepare-next-version$"),
        "/office/v1/offers/{offer_id}/prepare-next-version",
        {"POST": "prepare-next-version"},
    ),
    (
        re.compile(r"^/office/v1/offers/(?P<offer_id>[^/]+)/offer-document$"),
        "/office/v1/offers/{offer_id}/offer-document",
        {"POST": "offer-document", "GET": "offer_document"},
    ),
    (
        re.compile(r"^/office/v1/offers/(?P<offer_id>[^/]+)/offer-document/pdf$"),
        "/office/v1/offers/{offer_id}/offer-document/pdf",
        {"GET": "offer_document_pdf"},
    ),
    (
        re.compile(r"^/office/v1/tasks$"),
        "/office/v1/tasks",
        {"GET": "list_tasks"},
    ),
    (
        re.compile(r"^/office/v1/manual-task-subjects$"),
        "/office/v1/manual-task-subjects",
        {"GET": "list_manual_task_subjects"},
    ),
    (
        re.compile(r"^/office/v1/manual-tasks$"),
        "/office/v1/manual-tasks",
        {"GET": "list_manual_tasks", "POST": "create_manual_task"},
    ),
    (
        re.compile(r"^/office/v1/manual-tasks/(?P<task_id>[^/]+)/complete$"),
        "/office/v1/manual-tasks/{task_id}/complete",
        {"POST": "complete_manual_task"},
    ),
    (
        re.compile(r"^/office/v1/calendar$"),
        "/office/v1/calendar",
        {"GET": "list_calendar"},
    ),
    (
        re.compile(r"^/office/v1/recommendation-demand$"),
        "/office/v1/recommendation-demand",
        {"GET": "recommendation_demand"},
    ),
    (
        re.compile(r"^/office/v1/recommendation-capacity$"),
        "/office/v1/recommendation-capacity",
        {"GET": "recommendation_capacity"},
    ),
    (
        re.compile(r"^/office/v1/emails$"),
        "/office/v1/emails",
        {"GET": "list_emails"},
    ),
    (
        re.compile(r"^/office/v1/emails/(?P<inquiry_id>[^/]+)$"),
        "/office/v1/emails/{inquiry_id}",
        {"GET": "email_detail"},
    ),
    (
        re.compile(r"^/office/v1/contacts$"),
        "/office/v1/contacts",
        {"GET": "list_contacts"},
    ),
    (
        re.compile(r"^/office/v1/contacts/(?P<contact_key>[^/]+)$"),
        "/office/v1/contacts/{contact_key}",
        {"GET": "contact_detail"},
    ),
    (
        re.compile(r"^/office/v1/catalog/dishes$"),
        "/office/v1/catalog/dishes",
        {"GET": "list_catalog_dishes", "POST": "create_catalog_dish"},
    ),
    (
        re.compile(r"^/office/v1/catalog/dishes/(?P<id>[^/]+)$"),
        "/office/v1/catalog/dishes/{id}",
        {"GET": "catalog_dish_detail"},
    ),
    (
        re.compile(r"^/office/v1/catalog/allergen-codes$"),
        "/office/v1/catalog/allergen-codes",
        {"GET": "list_allergen_codes"},
    ),
    (
        re.compile(r"^/office/v1/catalog/dishes/(?P<id>[^/]+)/update$"),
        "/office/v1/catalog/dishes/{id}/update",
        {"POST": "update_catalog_dish"},
    ),
    (
        re.compile(r"^/office/v1/catalog/dishes/(?P<id>[^/]+)/activate$"),
        "/office/v1/catalog/dishes/{id}/activate",
        {"POST": "activate_catalog_dish"},
    ),
    (
        re.compile(r"^/office/v1/catalog/dishes/(?P<id>[^/]+)/deactivate$"),
        "/office/v1/catalog/dishes/{id}/deactivate",
        {"POST": "deactivate_catalog_dish"},
    ),
    (
        re.compile(r"^/office/v1/offers$"),
        "/office/v1/offers",
        {"GET": "list_offers"},
    ),
    (
        re.compile(r"^/office/v1/offer-queue$"),
        "/office/v1/offer-queue",
        {"GET": "offer_queue"},
    ),
    (
        re.compile(r"^/office/v1/offers/(?P<offer_id>[^/]+)$"),
        "/office/v1/offers/{offer_id}",
        {"GET": "offer_detail"},
    ),
    (
        re.compile(
            r"^/office/v1/offers/(?P<offer_id>[^/]+)/versions/"
            r"(?P<version_id>[^/]+)/mark-sent$"
        ),
        "/office/v1/offers/{offer_id}/versions/{version_id}/mark-sent",
        {"POST": "mark-sent"},
    ),
    (
        re.compile(
            r"^/office/v1/offers/(?P<offer_id>[^/]+)/versions/"
            r"(?P<version_id>[^/]+)/record-acceptance$"
        ),
        "/office/v1/offers/{offer_id}/versions/{version_id}/record-acceptance",
        {"POST": "record-acceptance"},
    ),
    (
        re.compile(
            r"^/office/v1/offers/(?P<offer_id>[^/]+)/versions/"
            r"(?P<version_id>[^/]+)/record-rejection$"
        ),
        "/office/v1/offers/{offer_id}/versions/{version_id}/record-rejection",
        {"POST": "record-rejection"},
    ),
    (
        re.compile(
            r"^/office/v1/offers/(?P<offer_id>[^/]+)/versions/"
            r"(?P<version_id>[^/]+)/record-withdrawal$"
        ),
        "/office/v1/offers/{offer_id}/versions/{version_id}/record-withdrawal",
        {"POST": "record-withdrawal"},
    ),
    (
        re.compile(
            r"^/office/v1/offers/(?P<offer_id>[^/]+)/versions/"
            r"(?P<version_id>[^/]+)/convert-accepted$"
        ),
        "/office/v1/offers/{offer_id}/versions/{version_id}/convert-accepted",
        {"POST": "convert-accepted"},
    ),
    (
        re.compile(r"^/office/v1/orders$"),
        "/office/v1/orders",
        {"GET": "list_orders"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)$"),
        "/office/v1/orders/{id}",
        {"GET": "order_detail"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/print-data$"),
        "/office/v1/orders/{id}/print-data",
        {"GET": "print_data"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/buffet-cards-data$"),
        "/office/v1/orders/{id}/buffet-cards-data",
        {"GET": "buffet_cards_data"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/versions$"),
        "/office/v1/orders/{id}/versions",
        {"POST": "versions"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/print-confirm$"),
        "/office/v1/orders/{id}/print-confirm",
        {"POST": "print-confirm"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/effective$"),
        "/office/v1/orders/{id}/effective",
        {"POST": "effective"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/ready$"),
        "/office/v1/orders/{id}/ready",
        {"POST": "ready"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/pause$"),
        "/office/v1/orders/{id}/pause",
        {"POST": "pause"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/resume$"),
        "/office/v1/orders/{id}/resume",
        {"POST": "resume"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/cancel$"),
        "/office/v1/orders/{id}/cancel",
        {"POST": "cancel"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/delete$"),
        "/office/v1/orders/{id}/delete",
        {"POST": "delete-order"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/payment-reminder$"),
        "/office/v1/orders/{id}/payment-reminder",
        {"POST": "payment-reminder"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/payment-method$"),
        "/office/v1/orders/{id}/payment-method",
        {"POST": "payment-method"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/payment-correction$"),
        "/office/v1/orders/{id}/payment-correction",
        {"POST": "payment-correction"},
    ),
    (
        re.compile(
            r"^/office/v1/orders/(?P<id>[^/]+)/confirmation-document/fake-outbox$"
        ),
        "/office/v1/orders/{id}/confirmation-document/fake-outbox",
        {"GET": "confirmation_document_fake_outbox"},
    ),
    (
        re.compile(
            r"^/office/v1/orders/(?P<id>[^/]+)/confirmation-document/send-status$"
        ),
        "/office/v1/orders/{id}/confirmation-document/send-status",
        {"GET": "confirmation_document_send_status"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/confirmation-document/send$"),
        "/office/v1/orders/{id}/confirmation-document/send",
        {"POST": "confirmation-document-send"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/confirmation-preview$"),
        "/office/v1/orders/{id}/confirmation-preview",
        {"GET": "confirmation_preview"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/confirmation-document/preview$"),
        "/office/v1/orders/{id}/confirmation-document/preview",
        {"GET": "confirmation_document_preview"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/confirmation-document$"),
        "/office/v1/orders/{id}/confirmation-document",
        {"GET": "confirmation_document", "POST": "confirmation-document"},
    ),
)


def _resolve_route(path: str) -> tuple[str, dict[str, str], dict[str, str]] | None:
    for pattern, template, methods in _ROUTES:
        match = pattern.match(path)
        if match:
            return template, dict(match.groupdict()), methods
    return None


def make_office_api_handler(
    api: OfficeApi,
    token: str,
    *,
    introspection_service_tokens: dict[str, str] | None = None,
    courier_cash_service_token: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    expected_auth = f"Bearer {token}"
    expected_courier_cash_auth = (
        f"Bearer {courier_cash_service_token}" if courier_cash_service_token else None
    )
    service_auth = OfficeApiServiceAuth(
        office_panel_token=token,
        introspection_clients=introspection_service_tokens or {},
    )

    class OfficeApiHandler(BaseHTTPRequestHandler):
        server_version = "CoreOfficeAPI/1.0"
        # HTTP/1.0 on purpose: auth-first responses may leave a request body
        # undrained, which under keep-alive corrupts the next request on the
        # same connection (observed in the courier repo); 1.0 closes it.

        def log_message(self, format: str, *args: object) -> None:
            pass

        # -- plumbing --------------------------------------------------

        def _respond(
            self,
            status: int,
            body: dict[str, object],
            *,
            retry_after: bool = False,
            suppress_body: bool = False,
        ) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            # pack §4.0: hard 512 KiB response cap. Pagination and embedded-list
            # caps keep it constructively unreachable, but long legacy Core texts
            # could still bloat a read past it — fail closed rather than emit an
            # oversized body. Checked before any byte is sent, so the caller's
            # try/except turns it into a clean 500 internal.
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise ApiError(500, "internal")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if retry_after:
                self.send_header("Retry-After", "1")
            self.end_headers()
            if not suppress_body:
                self.wfile.write(payload)

        def _respond_text(
            self,
            status: int,
            body: str,
            *,
            content_type: str = "text/html; charset=utf-8",
        ) -> None:
            payload = body.encode("utf-8")
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise ApiError(500, "internal")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def _respond_bytes(
            self,
            status: int,
            payload: bytes,
            *,
            content_type: str,
            filename: str | None = None,
        ) -> None:
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise ApiError(500, "internal")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if filename is not None:
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{filename}"'
                )
            self.end_headers()
            self.wfile.write(payload)

        def _error(
            self,
            status: int,
            code: str,
            *,
            retry_after: bool = False,
            reasons: tuple[str, ...] | None = None,
            offer_id: str | None = None,
        ) -> None:
            body: dict[str, object] = {"error": code}
            if reasons is not None:
                body["reasons"] = list(reasons)
            if offer_id is not None:
                body["offer_id"] = offer_id
            self._respond(status, body, retry_after=retry_after)

        def _authorized(self) -> bool:
            presented = self.headers.get("Authorization", "")
            return hmac.compare_digest(presented, expected_auth)

        def _configurator_service_auth(self) -> tuple[bool, bool]:
            result = service_auth.authenticate_introspection(
                self.headers.get("Authorization")
            )
            if result.outcome != "allowed":
                return False, False
            return True, result.client_id == CONFIGURATOR_HANDOFF_SERVICE_ID

        def _auth_or_401(self) -> bool:
            if self._authorized():
                return True
            self._error(401, "unauthorized")
            return False

        def _courier_cash_auth_or_respond(self) -> bool:
            if expected_courier_cash_auth is None:
                self._error(404, "not_found")
                return False
            presented = self.headers.get("Authorization", "")
            if not hmac.compare_digest(presented, expected_courier_cash_auth):
                self._error(401, "unauthorized")
                return False
            return True

        def _is_introspect_path(self, path: str) -> bool:
            return path == EMPLOYEE_INTROSPECT_PATH

        def _employee_introspect(self) -> None:
            status, response, error_code = perform_employee_introspection(
                service_auth=service_auth,
                authorization=self.headers.get("Authorization"),
                content_length=self.headers.get("Content-Length"),
                transfer_encoding=self.headers.get("Transfer-Encoding"),
                session_header_values=self.headers.get_all("X-Employee-Session"),
                employee_auth=api.employee_auth_service,
            )
            if error_code is not None:
                self._error(status, error_code)
                return
            assert response is not None
            self._respond(status, response.to_json())

        def _introspect_service_auth_or_respond(self) -> bool:
            result = service_auth.authenticate_introspection(
                self.headers.get("Authorization")
            )
            if result.outcome == "allowed":
                return True
            if result.outcome in {"forbidden", "ambiguous"}:
                self._error(403, "forbidden")
            else:
                self._error(401, "unauthorized")
            return False

        def _read_command_body(self, max_bytes: int) -> bytes:
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";")[0].strip() != "application/json":
                raise ApiError(415, "unsupported_media_type")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise _invalid()
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise _invalid() from exc
            if length <= 0:
                raise _invalid()
            if length > max_bytes:
                raise ApiError(413, "body_too_large")
            body = self.rfile.read(length)
            if len(body) != length:
                raise _invalid()
            return body

        def _reject_get_body(self) -> None:
            raw_length = self.headers.get("Content-Length")
            if raw_length is not None and raw_length not in ("", "0"):
                raise _invalid()

        def _query(self, allowed: set[str]) -> dict[str, str]:
            raw = urlparse(self.path).query
            pairs = parse_qsl(raw, keep_blank_values=True)
            seen: dict[str, str] = {}
            for key, value in pairs:
                if key not in allowed or key in seen:
                    raise _invalid()
                seen[key] = value
            return seen

        def _employee_with_permission(
            self, permission_code: str
        ) -> AuthenticatedEmployee:
            session_token = parse_employee_session_header_values(
                self.headers.get_all("X-Employee-Session")
            )
            if session_token == "malformed":
                raise _invalid()
            if session_token is None:
                raise ApiError(401, "unauthorized")
            try:
                employee = api.employee_auth_service.authenticate_session(session_token)
            except AuthenticationError as exc:
                raise ApiError(401, "unauthorized") from exc
            if not employee.application_access_allowed:
                raise ApiError(403, "forbidden")
            if permission_code not in employee.effective_permissions:
                raise ApiError(403, "forbidden")
            return employee

        def _chat_employee(self, kind: str) -> AuthenticatedEmployee:
            if kind == "create_chat_thread":
                return self._employee_with_permission("chat.create")
            if kind == "send_chat_message":
                return self._employee_with_permission("chat.send")
            if kind in {
                "list_chat_threads",
                "chat_thread_detail",
                "chat_thread_participants",
                "search_chat",
                "mark_chat_thread_read",
            }:
                return self._employee_with_permission("chat.view")
            if kind == "search_chat_entities":
                return self._employee_with_permission("chat.send")
            if kind == "search_chat_employees":
                return self._employee_with_permission("chat.create")
            raise ApiError(500, "internal")

        def _manual_task_employee(
            self, kind: str, args: dict[str, object] | None = None
        ) -> AuthenticatedEmployee:
            if kind in {"list_manual_tasks", "list_manual_task_subjects"}:
                return self._employee_with_permission("tasks.view")
            if kind == "create_manual_task":
                employee = self._employee_with_permission("tasks.create")
                if (
                    args is not None
                    and args.get("assigned_to_employee_id") is not None
                    and "tasks.assign" not in employee.effective_permissions
                ):
                    raise ApiError(403, "forbidden")
                subject_permission = {
                    "CONTACT": "customers.view",
                    "INQUIRY": "inquiries.view",
                    "OFFER": "offers.view",
                    "ORDER": "orders.view",
                }.get(str((args or {}).get("subject_type", "NONE")))
                if (
                    subject_permission is not None
                    and subject_permission not in employee.effective_permissions
                ):
                    raise ApiError(403, "forbidden")
                return employee
            if kind == "complete_manual_task":
                return self._employee_with_permission("tasks.complete")
            raise ApiError(500, "internal")

        def _pagination(self, params: dict[str, str]) -> tuple[int, int]:
            try:
                limit = int(params.get("limit", str(views.LIST_LIMIT_DEFAULT)))
                offset = int(params.get("offset", "0"))
            except ValueError as exc:
                raise _invalid() from exc
            if not 1 <= limit <= views.LIST_LIMIT_MAX or offset < 0:
                raise _invalid()
            return limit, offset

        # -- HTTP methods ----------------------------------------------

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def do_PUT(self) -> None:
            self._method_not_allowed_or_404()

        def do_DELETE(self) -> None:
            self._method_not_allowed_or_404()

        def do_PATCH(self) -> None:
            self._method_not_allowed_or_404()

        def do_HEAD(self) -> None:
            # Explicit handler (pack §4.0): auth first, then 405/404 with
            # full headers; body suppressed but Content-Length preserved.
            path = urlparse(self.path).path
            if path == _COURIER_CASH_PATH:
                if expected_courier_cash_auth is None:
                    self._respond(404, {"error": "not_found"}, suppress_body=True)
                    return
                presented = self.headers.get("Authorization", "")
                if not hmac.compare_digest(presented, expected_courier_cash_auth):
                    self._respond(401, {"error": "unauthorized"}, suppress_body=True)
                    return
                self._respond(405, {"error": "method_not_allowed"}, suppress_body=True)
                return
            if self._is_introspect_path(path):
                if not self._introspect_service_auth_or_respond():
                    return
                payload = json.dumps(
                    {
                        "authenticated": False,
                        "application_access_allowed": False,
                        "principal": None,
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return
            if not self._authorized():
                payload = json.dumps({"error": "unauthorized"}).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return
            path = urlparse(self.path).path
            code = 405 if _resolve_route(path) is not None else 404
            error = "method_not_allowed" if code == 405 else "not_found"
            self._respond(code, {"error": error}, suppress_body=True)

        def do_OPTIONS(self) -> None:
            path = urlparse(self.path).path
            if path == _COURIER_CASH_PATH:
                if not self._courier_cash_auth_or_respond():
                    return
                self._error(405, "method_not_allowed")
                return
            if self._is_introspect_path(path):
                if not self._introspect_service_auth_or_respond():
                    return
                self._error(405, "method_not_allowed")
                return
            if not self._auth_or_401():
                return
            path = urlparse(self.path).path
            if _resolve_route(path) is not None:
                self._error(405, "method_not_allowed")
            else:
                self._error(404, "not_found")

        def _method_not_allowed_or_404(self) -> None:
            path = urlparse(self.path).path
            if path == _COURIER_CASH_PATH:
                if not self._courier_cash_auth_or_respond():
                    return
                self._error(405, "method_not_allowed")
                return
            if not self._auth_or_401():
                return
            if _resolve_route(path) is not None:
                self._error(405, "method_not_allowed")
            else:
                self._error(404, "not_found")

        def _handle(self, method: str) -> None:
            path = urlparse(self.path).path
            if path == _COURIER_CASH_PATH:
                self._handle_courier_cash(method)
                return
            if path == "/office/v1/auth/configurator-handoff/exchange":
                self._handle_configurator_handoff_exchange(method)
            if self._is_introspect_path(path):
                if method != "POST":
                    self._error(405, "method_not_allowed")
                    return
                self._employee_introspect()
                return
            if not self._auth_or_401():
                return
            resolved = _resolve_route(path)
            if resolved is None:
                self._error(404, "not_found")
                return
            template, path_ids, methods = resolved
            kind = methods.get(method)
            if kind is None:
                self._error(405, "method_not_allowed")
                return
            try:
                if method == "GET":
                    self._get(kind, path_ids)
                else:
                    self._command(template, kind, path_ids)
            except CoreBusyError:
                _log.info("command busy route=%s", template)
                self._error(503, "core_busy", retry_after=True)
            except ApiError as exc:
                self._error(
                    exc.status,
                    exc.code,
                    reasons=exc.reasons,
                    offer_id=exc.offer_id,
                )
            except Exception:  # noqa: BLE001
                _log.exception("internal error route=%s", template)
                self._error(500, "internal")

        def _handle_courier_cash(self, method: str) -> None:
            if not self._courier_cash_auth_or_respond():
                return
            if method != "POST":
                self._error(405, "method_not_allowed")
                return
            try:
                if urlparse(self.path).query:
                    raise ValueError("query not allowed")
                raw = self._read_command_body(_MAX_COURIER_CASH_BODY_BYTES)
                body = strict_json_loads(raw)
                command = CourierCashCommand.from_json(body)
            except UnsupportedCourierCashContractVersion:
                self._error(400, "unsupported_contract_version")
                return
            except (ApiError, ValueError, TypeError):
                self._error(400, "invalid_request")
                return

            try:
                result = api.executor.run(
                    lambda: api.courier_cash_service.process(command)
                )
            except CourierCashCommandError as exc:
                self._error(exc.status, exc.code)
                return
            except CoreBusyError:
                self._error(503, "core_unavailable")
                return
            except Exception:  # noqa: BLE001
                _log.exception("courier cash Core write failed")
                self._error(503, "core_unavailable")
                return
            self._respond(200, result.to_json())

        def _handle_configurator_handoff_exchange(self, method: str) -> None:
            service_authenticated, correct_service = self._configurator_service_auth()
            if not service_authenticated:
                self._error(401, "unauthorized")
                return
            if not correct_service:
                self._error(403, "forbidden")
                return
            if method != "POST":
                self._error(405, "method_not_allowed")
                return
            try:
                raw = self._read_command_body(_MAX_BODY_BYTES)
                body = strict_json_loads(raw)
                _exact_keys(body, {"code"})
                code = _v_str(body["code"], 1024).strip()
                if not code:
                    raise _invalid()
                employee_session_token = parse_employee_session_header_values(
                    self.headers.get_all("X-Employee-Session")
                )
                if employee_session_token == "malformed":
                    raise _invalid()
                if employee_session_token is None:
                    self._error(401, "unauthorized")
                    return
                payload = api.exchange_configurator_handoff(
                    code=code,
                    employee_session_token=employee_session_token,
                )
                self._respond(200, payload)
            except CoreBusyError:
                self._error(503, "core_busy", retry_after=True)
            except ApiError as exc:
                self._error(
                    exc.status,
                    exc.code,
                    reasons=exc.reasons,
                    offer_id=exc.offer_id,
                )
            except Exception:  # noqa: BLE001
                _log.exception(
                    "internal error route=/office/v1/auth/configurator-handoff/exchange"
                )
                self._error(500, "internal")

        def _get(self, kind: str, path_ids: dict[str, str]) -> None:
            self._reject_get_body()
            if kind == "queue":
                self._query(set())
                self._respond(200, api.queue_view())
            elif kind == "work_center":
                self._query(set())
                self._respond(200, api.work_center())
            elif kind == "customer_order_history":
                self._query(set())
                self._respond(200, api.customer_order_history(path_ids["customer_id"]))
            elif kind == "list_customer_gastronomic_preferences":
                self._query(set())
                self._respond(
                    200,
                    api.list_customer_gastronomic_preferences(path_ids["customer_id"]),
                )
            elif kind == "list_inquiries":
                params = self._query({"q", "limit", "offset"})
                q = _v_str(params.get("q", ""), _MAX_Q_CHARS).strip().lower()
                limit, offset = self._pagination(params)
                self._respond(200, api.list_inquiries(q, limit, offset))
            elif kind == "list_orders":
                params = self._query({"q", "limit", "offset"})
                q = _v_str(params.get("q", ""), _MAX_Q_CHARS).strip().lower()
                limit, offset = self._pagination(params)
                self._respond(200, api.list_orders(q, limit, offset))
            elif kind == "list_offers":
                self._query(set())
                self._respond(200, api.list_offers())
            elif kind == "offer_queue":
                params = self._query({"group", "limit", "offset"})
                group_raw = params.get("group")
                group: str | None = None
                if group_raw is not None:
                    if group_raw not in {
                        "action_required",
                        "overdue",
                        "history",
                    }:
                        raise _invalid()
                    group = group_raw
                limit, offset = self._pagination(params)
                self._respond(
                    200, api.offer_queue(group=group, limit=limit, offset=offset)
                )
            elif kind == "list_contacts":
                self._query(set())
                self._respond(200, api.list_contacts())
            elif kind == "contact_detail":
                self._query(set())
                self._respond(200, api.contact_detail(path_ids["contact_key"]))
            elif kind == "list_catalog_dishes":
                params = self._query({"active", "active_only", "q", "limit", "offset"})
                active = _catalog_active_filter(params)
                catalog_q_raw = params.get("q")
                catalog_q = (
                    _v_str(catalog_q_raw, _MAX_Q_CHARS).strip()
                    if catalog_q_raw is not None
                    else None
                )
                if catalog_q == "":
                    catalog_q = None
                limit, offset = self._pagination(params)
                self._respond(
                    200,
                    api.list_catalog_dishes(
                        active=active,
                        q=catalog_q,
                        limit=limit,
                        offset=offset,
                    ),
                )
            elif kind == "catalog_dish_detail":
                self._query(set())
                self._respond(
                    200, api.catalog_dish_detail(_v_catalog_uuid(path_ids["id"]))
                )
            elif kind == "list_allergen_codes":
                self._query(set())
                self._respond(200, api.list_allergen_codes())
            elif kind == "list_emails":
                self._query(set())
                self._respond(200, api.list_emails())
            elif kind == "list_tasks":
                self._query(set())
                self._respond(200, api.list_tasks())
            elif kind == "list_manual_task_subjects":
                self._query(set())
                employee = self._manual_task_employee(kind)
                self._respond(200, api.manual_task_subjects(employee))
            elif kind == "list_manual_tasks":
                params = self._query({"subject_type", "subject_id"})
                self._manual_task_employee(kind)
                subject_type: ManualTaskSubjectType | None = None
                subject_id: str | None = None
                if "subject_type" in params or "subject_id" in params:
                    if "subject_type" not in params or "subject_id" not in params:
                        raise _invalid()
                    subject_type = _v_enum(
                        params["subject_type"], validate_manual_task_subject_type
                    )
                    if subject_type == "NONE":
                        raise _invalid()
                    subject_id = _v_uuid(params["subject_id"])
                self._respond(200, api.list_manual_tasks(subject_type, subject_id))
            elif kind == "list_chat_threads":
                self._query(set())
                employee = self._chat_employee(kind)
                self._respond(200, api.list_chat_threads(employee))
            elif kind == "chat_thread_detail":
                self._query(set())
                employee = self._chat_employee(kind)
                self._respond(
                    200,
                    api.chat_thread_detail(employee, _v_uuid(path_ids["thread_id"])),
                )
            elif kind == "chat_thread_participants":
                params = self._query({"q"})
                employee = self._chat_employee(kind)
                q = _v_str(params.get("q", ""), _MAX_Q_CHARS).strip()
                self._respond(
                    200,
                    api.chat_thread_participants(
                        employee, _v_uuid(path_ids["thread_id"]), q
                    ),
                )
            elif kind == "search_chat":
                params = self._query({"q"})
                employee = self._chat_employee(kind)
                q = _v_str(params.get("q", ""), _MAX_Q_CHARS).strip()
                self._respond(200, api.search_chat(employee, q))
            elif kind == "search_chat_entities":
                params = self._query({"q", "type"})
                employee = self._chat_employee(kind)
                q = _v_str(params.get("q", ""), _MAX_Q_CHARS).strip()
                if "type" not in params:
                    raise _invalid()
                reference_type = _v_enum(params["type"], validate_chat_reference_type)
                self._respond(
                    200, api.search_chat_entities(employee, q, reference_type)
                )
            elif kind == "search_chat_employees":
                params = self._query({"q"})
                employee = self._chat_employee(kind)
                q = _v_str(params.get("q", ""), _MAX_Q_CHARS).strip()
                self._respond(200, api.search_chat_employees(employee, q))
            elif kind == "list_calendar":
                params = self._query({"from", "to"})
                if "from" not in params or "to" not in params:
                    raise _invalid()
                self._respond(
                    200,
                    api.list_calendar(
                        _v_date(params["from"]),
                        _v_date(params["to"]),
                    ),
                )
            elif kind == "recommendation_demand":
                params = self._query({"date"})
                if "date" not in params:
                    raise _invalid()
                self._respond(200, api.recommendation_demand(_v_date(params["date"])))
            elif kind == "recommendation_capacity":
                params = self._query({"date"})
                if "date" not in params:
                    raise _invalid()
                self._respond(200, api.recommendation_capacity(_v_date(params["date"])))
            elif kind == "email_detail":
                self._query(set())
                self._respond(200, api.email_detail(path_ids["inquiry_id"]))
            elif kind == "offer_detail":
                self._query(set())
                self._respond(200, api.offer_detail(path_ids["offer_id"]))
            elif kind == "offer_document":
                params = self._query({"offer_version_id"})
                version_id = (
                    _v_uuid(params["offer_version_id"])
                    if "offer_version_id" in params
                    else None
                )
                self._respond(200, api.offer_document(path_ids["offer_id"], version_id))
            elif kind == "offer_document_pdf":
                params = self._query({"offer_version_id"})
                version_id = (
                    _v_uuid(params["offer_version_id"])
                    if "offer_version_id" in params
                    else None
                )
                pdf_bytes, filename = api.offer_document_pdf(
                    path_ids["offer_id"], version_id
                )
                self._respond_bytes(
                    200, pdf_bytes, content_type="application/pdf", filename=filename
                )
            elif kind == "inquiry_detail":
                self._query(set())
                self._respond(200, api.inquiry_detail(path_ids["id"]))
            elif kind == "order_detail":
                self._query(set())
                self._respond(200, api.order_detail(path_ids["id"]))
            elif kind == "print_data":
                params = self._query({"version"})
                if "version" not in params:
                    raise _invalid()
                self._respond(
                    200, api.print_data(path_ids["id"], _v_uuid(params["version"]))
                )
            elif kind == "buffet_cards_data":
                params = self._query({"version"})
                if "version" not in params:
                    raise _invalid()
                self._respond(
                    200,
                    api.buffet_cards_data(path_ids["id"], _v_uuid(params["version"])),
                )
            elif kind == "confirmation_document":
                params = self._query({"document_snapshot_id"})
                snapshot_id = (
                    _v_uuid(params["document_snapshot_id"])
                    if "document_snapshot_id" in params
                    else None
                )
                self._respond(
                    200, api.confirmation_document(path_ids["id"], snapshot_id)
                )
            elif kind == "confirmation_preview":
                self._query(set())
                self._respond(200, api.confirmation_preview(path_ids["id"]))
            elif kind == "confirmation_document_preview":
                params = self._query({"document_snapshot_id", "format"})
                snapshot_id = (
                    _v_uuid(params["document_snapshot_id"])
                    if "document_snapshot_id" in params
                    else None
                )
                format_value = params.get("format", "json")
                if format_value not in {"json", "html"}:
                    raise _invalid()
                result = api.confirmation_document_preview(
                    path_ids["id"],
                    snapshot_id,
                    format=format_value,
                )
                if isinstance(result, str):
                    self._respond_text(200, result)
                else:
                    self._respond(200, result)
            elif kind == "confirmation_document_send_status":
                self._respond(
                    200, api.confirmation_document_send_status(path_ids["id"])
                )
            elif kind == "confirmation_document_fake_outbox":
                params = self._query({"document_snapshot_id"})
                snapshot_id = (
                    _v_uuid(params["document_snapshot_id"])
                    if "document_snapshot_id" in params
                    else None
                )
                self._respond(
                    200,
                    api.confirmation_document_fake_outbox(
                        path_ids["id"], document_snapshot_id=snapshot_id
                    ),
                )

        def _command(self, template: str, kind: str, path_ids: dict[str, str]) -> None:
            spec = _COMMANDS[kind]
            max_body = (
                _MAX_PREPARE_OFFER_BODY_BYTES
                if kind in {"prepare-offer", "prepare-next-version"}
                else _MAX_BODY_BYTES
            )
            raw = self._read_command_body(max_body)
            envelope = strict_json_loads(raw)
            _exact_keys(envelope, {"command_id", "expect", "args"})
            command_id = _v_uuid(envelope["command_id"])
            expect = envelope["expect"]
            args = envelope["args"]
            if not isinstance(expect, dict) or not isinstance(args, dict):
                raise _invalid()
            _exact_keys(expect, spec.expect_keys)
            arg_spec = spec.args_keys
            provided = set(args)
            if not arg_spec.required <= provided:
                raise _invalid()
            if provided - arg_spec.required - arg_spec.optional:
                raise _invalid()
            employee = (
                self._chat_employee(kind)
                if kind
                in {"create_chat_thread", "send_chat_message", "mark_chat_thread_read"}
                else self._manual_task_employee(kind, args)
                if kind in {"create_manual_task", "complete_manual_task"}
                else self._employee_with_permission("orders.delete")
                if kind == "delete-order"
                else None
            )

            fingerprint = command_fingerprint(
                template, path_ids, args, expect, CLIENT_ID
            )
            handler = getattr(api, spec.handler)

            def work() -> tuple[int, str]:
                recorded = api.ledger.get(command_id)
                if recorded is not None:
                    if not hmac.compare_digest(recorded.fingerprint, fingerprint):
                        raise ApiError(409, "command_id_conflict")
                    return recorded.result_status, recorded.result_body
                api._active_command_id = command_id
                api._active_employee = employee
                try:
                    status, result = handler(path_ids, args, expect)
                finally:
                    api._active_command_id = None
                    api._active_employee = None
                body = json.dumps(
                    {"command_id": command_id, **result}, ensure_ascii=False
                )
                api.ledger.record(command_id, fingerprint, status, body)
                return status, body

            status, body = api.executor.run(work)
            _log.info(
                "command committed route=%s status=%s command_id=%s",
                template,
                status,
                command_id,
            )
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

    return OfficeApiHandler


def create_office_api_server(
    db_path: str,
    token: str,
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    offer_pdf_static_content: OfferPdfStaticContent,
    introspection_service_tokens: dict[str, str] | None = None,
    employee_auth_service_tokens: dict[str, str] | None = None,
    employee_auth_now: Callable[[], datetime] | None = None,
    courier_cash_service_token: str | None = None,
) -> HTTPServer:
    """Build connection, repositories and server in the calling thread —
    single-threaded on purpose (sqlite3 thread affinity, Entry 048)."""
    api = OfficeApi(
        open_core_connection(db_path),
        offer_pdf_static_content=offer_pdf_static_content,
        employee_auth_now=employee_auth_now,
    )
    effective_introspection_tokens = introspection_service_tokens
    if (
        effective_introspection_tokens is None
        and employee_auth_service_tokens is not None
    ):
        effective_introspection_tokens = employee_auth_service_tokens
    return HTTPServer(
        (host, port),
        make_office_api_handler(
            api,
            token,
            introspection_service_tokens=effective_introspection_tokens,
            courier_cash_service_token=courier_cash_service_token,
        ),
    )


def main() -> None:
    import os

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Core Office API (PROXMOX pack, Phase 1 — dormant)"
    )
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    parser.add_argument("--host", default="100.109.6.74")
    parser.add_argument("--port", type=int, default=8084)
    args = parser.parse_args()

    token = os.environ.get("OFFICE_API_TOKEN", "")
    if not token:
        raise SystemExit(
            "OFFICE_API_TOKEN is required (root-owned EnvironmentFile, pack §5); "
            "refusing to start unauthenticated"
        )

    from catering_system.ui.offer_pdf_static_content_env import (
        offer_pdf_static_content_from_env,
    )

    offer_pdf_static_content = offer_pdf_static_content_from_env()
    introspection_tokens = read_introspection_service_tokens_from_env(
        office_panel_token=token,
    )
    courier_cash_token = os.environ.get("COURIER_CASH_SERVICE_TOKEN", "") or None

    server = create_office_api_server(
        args.db,
        token,
        args.host,
        args.port,
        offer_pdf_static_content=offer_pdf_static_content,
        introspection_service_tokens=introspection_tokens,
        courier_cash_service_token=courier_cash_token,
    )
    print(f"Core Office API on http://{args.host}:{args.port}/office/v1/")
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Office panel — primary office write surface (OFFICE_PANEL_EXECUTION_PACK_V1).

Thin server-rendered skin over existing Core services; adds no domain semantics
(pack §1). LAN-only write surface with mandatory basic auth (§3, §7). Blocked
reasons are rendered from two separate vocabularies that are never merged (§5):
progression (B7) on inquiry views, operational gate on order views.
"""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import quote, urlencode
from uuid import uuid4

from catering_system.domain.catalog import (
    ALLERGEN_CODES,
    AllergenCode,
    CatalogDishAlreadyExistsError,
    CatalogDishCreatePayload,
    CatalogDishNotFoundError,
    CatalogDishStaleError,
    CatalogDishUpdatePayload,
    validate_category,
    validate_pricing_unit,
)
from catering_system.domain.customer_document_projection import (
    CustomerAddress,
    canonicalize_customer_address,
)
from catering_system.domain.inquiry import (
    ACTIVE_ORDER_CRM_STAGE,
    CRM_PIPELINE,
    PLANNING_MODES,
    Inquiry,
    InquiryOfficeState,
    inquiry_allows_convert_accepted_command,
    inquiry_crm_stage_is_compatible_with_active_order,
    inquiry_shows_convert_accepted_button,
    validate_crm_stage,
)
from catering_system.domain.inquiry_contact_completeness import (
    CONTACT_COMPLETION_NEXT_ACTION,
    contact_completeness_blocker_text,
    derive_inquiry_contact_completeness,
    missing_contact_fields,
)
from catering_system.domain.offer import (
    ACCEPTANCE_CHANNELS,
    SENT_CHANNELS,
    AcceptanceChannel,
    SentChannel,
)
from catering_system.domain.offer_pdf import (
    OfferPdfRenderError,
    OfferPdfStaticContent,
    OfferPdfUnsupportedCharacterError,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_payment_reminder import (
    PAYMENT_METHOD_LABELS,
    PAYMENT_METHODS,
    OrderPaymentReminder,
    validate_payment_method,
)
from catering_system.domain.work_center import WorkCenterSnapshot
from catering_system.repositories.catalog_repository import CatalogRepository
from catering_system.repositories.contact_internal_note_repository import (
    ContactInternalNoteRepository,
)
from catering_system.repositories.contact_profile_repository import (
    ContactProfileRepository,
)
from catering_system.repositories.in_memory_catalog_repository import (
    InMemoryCatalogRepository,
)
from catering_system.repositories.in_memory_contact_internal_note_repository import (
    InMemoryContactInternalNoteRepository,
)
from catering_system.repositories.in_memory_contact_profile_repository import (
    InMemoryContactProfileRepository,
)
from catering_system.repositories.in_memory_kitchen_print_job_repository import (
    InMemoryKitchenPrintJobRepository,
)
from catering_system.repositories.in_memory_offer_document_snapshot_repository import (
    InMemoryOfferDocumentSnapshotRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_confirmation_document_repository import (
    InMemoryOrderConfirmationDocumentRepository,
)
from catering_system.repositories.in_memory_order_confirmation_outbound_repository import (
    InMemoryOrderConfirmationOutboundRepository,
)
from catering_system.repositories.in_memory_order_operational_pause_repository import (
    InMemoryOrderOperationalPauseRepository,
)
from catering_system.repositories.in_memory_payment_reminder_repository import (
    InMemoryPaymentReminderRepository,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.kitchen_print_job_repository import (
    KitchenPrintJobRepository,
)
from catering_system.repositories.offer_document_snapshot_repository import (
    OfferDocumentSnapshotRepository,
)
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_confirmation_document_repository import (
    OrderConfirmationDocumentRepository,
)
from catering_system.repositories.order_confirmation_outbound_repository import (
    OrderConfirmationOutboundRepository,
)
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.payment_reminder_repository import (
    PaymentReminderRepository,
)
from catering_system.services.calendar_projection_service import (
    CalendarProjectionService,
)
from catering_system.services.catalog_dish_service import CatalogDishService
from catering_system.services.catalog_dish_write_service import CatalogDishWriteService
from catering_system.services.configurator_handoff_service import (
    ConfiguratorHandoffService,
)
from catering_system.services.contact_internal_note_service import (
    ContactInternalNoteService,
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
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.kitchen_print_service import KitchenPrintService
from catering_system.services.offer_document_snapshot_service import (
    OfferDocumentSnapshotService,
)
from catering_system.services.offer_pdf_renderer import (
    offer_document_pdf_filename,
    render_offer_document_pdf,
)
from catering_system.services.offer_service import OfferService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentService,
)
from catering_system.services.order_confirmation_outbound_service import (
    OrderConfirmationOutboundAlreadySentError,
    OrderConfirmationOutboundService,
)
from catering_system.services.order_service import OrderService
from catering_system.services.payment_reminder_service import PaymentReminderService
from catering_system.services.progression_service import ProgressionService
from catering_system.services.task_projection_service import TaskProjectionService
from catering_system.services.wochenuebersicht_service import WochenuebersichtService
from catering_system.services.work_center_service import WorkCenterService
from catering_system.ui import office_api_views as api_views
from catering_system.ui.callback_contact_resolution import (
    enrich_missed_board_with_core_contacts,
)
from catering_system.ui.office_panel_calendar_list import render_kalender_list
from catering_system.ui.office_panel_catalog_detail import render_gericht_detail
from catering_system.ui.office_panel_catalog_edit import render_gericht_edit
from catering_system.ui.office_panel_catalog_list import render_gerichte_list
from catering_system.ui.office_panel_catalog_new import render_gericht_new
from catering_system.ui.office_panel_contact_detail import render_kontakt_detail
from catering_system.ui.office_panel_contacts_list import render_kontakte_list
from catering_system.ui.office_panel_dashboard import (
    ArbeitszentraleData,
    render_arbeitszentrale,
)
from catering_system.ui.office_panel_email_detail import render_email_detail
from catering_system.ui.office_panel_emails_list import render_email_list
from catering_system.ui.office_panel_inquiry_detail import (
    InquiryDetailFormFields,
    render_inquiry_detail,
)
from catering_system.ui.office_panel_offer_detail import (
    OfferDetailFormFields,
    render_offer_detail,
    surface_version_id,
)
from catering_system.ui.office_panel_offer_prefill import (
    build_configurator_handoff_url,
    build_offer_prefill_url,
    normalize_configurator_url,
)
from catering_system.ui.office_panel_offers_list import render_angebote_queue
from catering_system.ui.office_panel_order_detail import (
    _DOCUMENT_BLOCKER_LABELS,
    ConfirmationLivePreviewView,
    OrderDetailFormFields,
    render_confirmation_card,
    render_confirmation_outbound_card,
    render_customer_addresses_card,
    render_fulfillment_mode_card,
    render_operational_pause_card,
    render_order_detail,
    version_change_prefill,
)
from catering_system.ui.office_panel_tasks_list import render_aufgaben_list
from catering_system.ui.office_panel_views import (
    _EMPTY_PAGE_CONTEXT,
    CALL_VERIFICATION_STATUS_LABELS,
    PROGRESSION_BLOCKER_LABELS,
    READY_TO_SEND_BLOCKER_LABELS,
    SOURCE_LABELS,
    OfficePageContext,
    _crm_stage_select,
    _csrf_input,
    _e,
    _page,
    _planning_mode_select,
    _progression_blocker_label,
    _ready_to_send_blocker_label,
    _verification_label,
    format_datetime_utc_iso,
    parse_datetime_local_berlin,
    render_buffet_cards,
    render_print_sheet,
)

if TYPE_CHECKING:
    from catering_system.repositories.core_transaction import CoreCommandExecutor
    from catering_system.ui.remote_core_client import RemoteCoreClient

__all__ = [
    "CALL_VERIFICATION_STATUS_LABELS",
    "PROGRESSION_BLOCKER_LABELS",
    "READY_TO_SEND_BLOCKER_LABELS",
    "SOURCE_LABELS",
    "render_buffet_cards",
    "render_print_sheet",
]

# -- Rückrufe: read-only pull from the separate auerswald-sync call-log
# service (own repo/server, NOT Core, NOT EspoCRM). Pre-inquiry office signal
# only — never writes into Core, never creates an Inquiry automatically. The
# only write this makes is the office-initiated "erledigt" resolve, which
# goes to auerswald-sync's own /missed/resolve, not to Core.


def fetch_rueckruf_count(url: str, user: str, password: str) -> int | None:
    """Sidebar badge count via integration.auerswald_sync (same missed-board source)."""
    from catering_system.integration.auerswald_sync import (
        fetch_rueckruf_count as _count,
    )

    return _count(url, user, password)


_RUECKRUF_SUBTITLE = (
    '<p class="subtitle">Verpasste Anrufe sowie Anrufe außerhalb der Bürozeiten, '
    "die einen Rückruf erfordern.</p>"
)


def _format_rueckruf_contact_cell(item: dict) -> str:
    """Prefer Core-resolved contact display over Auerswald callback metadata."""

    label = item.get("core_contact_label")
    if label is not None:
        href = item.get("core_contact_href")
        if href:
            return f'<a href="{_e(href)}">{_e(label)}</a>'
        return _e(label)
    if item.get("contact_found"):
        return _e(item["contact_name"])
    return "Unbekannt"


def render_rueckruf(
    items: list[dict] | None,
    error: str | None,
    *,
    context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
) -> str:
    if error:
        body = _RUECKRUF_SUBTITLE + (
            f'<p class="blocked">Rückrufliste nicht erreichbar: {_e(error)}</p>'
            "<p>Prüfe AUERSWALD_SYNC_URL / erreichbarkeit des auerswald-sync Servers.</p>"
        )
        return _page(
            "Offene Rückrufe", body, active_section="callbacks", context=context
        )
    if not items:
        body = _RUECKRUF_SUBTITLE + "<p>Keine offenen Rückrufe.</p>"
        return _page(
            "Offene Rückrufe", body, active_section="callbacks", context=context
        )
    rows = []
    for it in items:
        contact = _format_rueckruf_contact_cell(it)
        resolve_cell = ""
        if context.can("queue.resolve"):
            resolve_cell = (
                '<form class="inline" method="post" action="/rueckruf/resolve">'
                f"{_csrf_input(context)}"
                f'<input type="hidden" name="call_id" value="{_e(it.get("call_id", ""))}">'
                "<button>Erledigt</button></form>"
            )
        rows.append(
            "<tr>"
            f"<td>{_e(it.get('date', ''))}</td>"
            f"<td>{_e(it.get('time', ''))}</td>"
            f"<td>{_e(it.get('phone', ''))}</td>"
            f"<td>{_e(it.get('reason', ''))}</td>"
            f"<td>{contact}</td>"
            f"<td>{resolve_cell}</td></tr>"
        )
    body = _RUECKRUF_SUBTITLE + (
        "<table><tr><th>Datum</th><th>Zeit</th><th>Nummer</th>"
        "<th>Grund</th><th>Kontakt</th><th></th></tr>" + "".join(rows) + "</table>"
    )
    return _page("Offene Rückrufe", body, active_section="callbacks", context=context)


class OfferPdfUnavailableError(Exception):
    """Raised when a PDF snapshot exists but cannot be rendered (renderer or
    static content validation failure) — mapped by the HTTP layer to a clear
    German 422 message, never a stack trace."""


# CATALOG_ADMIN_PANEL_V1: the Aktiv/Inaktiv selector's accepted values;
# anything else falls back to "all" rather than erroring, matching how the
# existing Kontakte status filter treats an unknown query string.
_CATALOG_STATUS_FILTERS = ("all", "active", "inactive")

# Selector value -> the neutral `active` filter carried down to the query.
_CATALOG_ACTIVE_BY_FILTER: dict[str, bool | None] = {
    "all": None,
    "active": True,
    "inactive": False,
}


class CatalogCommandError(ValueError):
    """A catalog write rejected for a reason the operator should see.

    Carries the HTTP status alongside the message key so direct and remote
    mode answer identically *and* keep the meaning of the failure. Collapsing
    everything onto 400 would tell a caller that a missing dish, a concurrent
    edit and a malformed price are the same kind of problem — and would
    regress the remote path, which already surfaced the API's real status.

    Stays a ValueError so any caller that only knows the old contract still
    catches it.
    """

    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


# Catalog failure -> (message key, HTTP status). The keys are deliberately
# catalog-prefixed: the API's own codes (not_found, stale_state, …) are
# generic across every command, so an unprefixed entry in the shared label
# table would put "Das Gericht …" in front of an unrelated inquiry error.
_CATALOG_NOT_FOUND = ("catalog_not_found", 404)
_CATALOG_STALE = ("catalog_stale_state", 409)
_CATALOG_EXISTS = ("catalog_already_exists", 409)
_CATALOG_INVALID_DOMAIN = ("catalog_validation_error", 422)
_CATALOG_INVALID_INPUT = ("catalog_invalid_input", 400)
_CATALOG_INVALID_PRICE = ("catalog_invalid_price", 400)

# Remote Office API error codes -> the same (key, status) pairs, so a remote
# rejection is indistinguishable from the direct-mode one it mirrors.
_CATALOG_REMOTE_ERRORS: dict[str, tuple[str, int]] = {
    "not_found": _CATALOG_NOT_FOUND,
    "stale_state": _CATALOG_STALE,
    "already_exists": _CATALOG_EXISTS,
    "validation_error": _CATALOG_INVALID_DOMAIN,
    "invalid_request": _CATALOG_INVALID_INPUT,
}

# A price the operator typed: digits, then at most one separator followed by
# one or two digits. No sign (a negative price is not a catalog price), no
# exponent, no thousands separator — "1.000,50" is ambiguous, so it is
# rejected rather than guessed at. Anything with a third decimal is refused
# instead of being quietly rounded into a price nobody entered.
_CATALOG_PRICE_RE = re.compile(r"^\d+(?:[.,]\d{1,2})?$")


def parse_catalog_price_input(raw: str) -> int:
    """CATALOG_ADMIN_PANEL_V1: gate in front of the shared
    ``parse_catalog_price_cents``. That helper quantizes, so "1,999" would
    become 2,00 € with no warning; this refuses the input instead. Shape is
    checked here, the Decimal conversion stays there — no float anywhere.

    A separator-less amount is normalised to euros first. The shared helper
    reads a bare integer as *cents*, which would make "12" 0,12 € while
    "12,00" is 12,00 € — a hundredfold difference between two spellings of
    the same number, in a field labelled €. Every rendered form pre-fills
    "12,00", so this only affects a hand-typed value, and euros is the only
    reading consistent with the label. The shared helper is left untouched
    for any other caller.
    """
    text = raw.strip()
    if text.endswith("€"):
        text = text[:-1].strip()
    if not _CATALOG_PRICE_RE.fullmatch(text):
        raise CatalogCommandError(*_CATALOG_INVALID_PRICE)
    if "." not in text and "," not in text:
        text = f"{text}.00"
    return api_views.parse_catalog_price_cents(text)


class OfficePanel:
    """Route handling and rendering; kept separate from the HTTP handler for testability."""

    def __init__(
        self,
        inquiry_repo: InquiryRepository,
        order_repo: OrderRepository,
        kiosk_url: str = "",
        configurator_url: str = "",
        *,
        configurator_handoff_service: ConfiguratorHandoffService | None = None,
        remote: RemoteCoreClient | None = None,
        command_executor: CoreCommandExecutor | None = None,
        payment_reminder_repo: PaymentReminderRepository | None = None,
        confirmation_document_repo: OrderConfirmationDocumentRepository | None = None,
        confirmation_outbound_repo: OrderConfirmationOutboundRepository | None = None,
        pause_repository: OrderOperationalPauseRepository | None = None,
        contact_note_repo: ContactInternalNoteRepository | None = None,
        contact_profile_repo: ContactProfileRepository | None = None,
        offer_repo: OfferRepository | None = None,
        catalog_repo: CatalogRepository | None = None,
        commercial_snapshot_repo: OrderCommercialSnapshotRepository | None = None,
        offer_document_repo: OfferDocumentSnapshotRepository | None = None,
        offer_pdf_static_content: OfferPdfStaticContent | None = None,
        kitchen_print_job_repo: KitchenPrintJobRepository | None = None,
        ui_version: str = "legacy",
    ) -> None:
        if ui_version not in {"legacy", "v2"}:
            raise ValueError("ui_version must be 'legacy' or 'v2'")
        self._inquiries = inquiry_repo
        self._orders = order_repo
        self._offers = offer_repo or InMemoryOfferRepository()
        self._offer_documents = (
            offer_document_repo or InMemoryOfferDocumentSnapshotRepository()
        )
        self.offer_pdf_static_content = offer_pdf_static_content
        self._commercial_snapshots = (
            commercial_snapshot_repo or InMemoryOrderCommercialSnapshotRepository()
        )
        self._catalog = catalog_repo or InMemoryCatalogRepository()
        self._pause_repository: OrderOperationalPauseRepository | None
        self.catalog_dish_write_service = CatalogDishWriteService(self._catalog)
        # Phase 2 dual mode (PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §7): when
        # `remote` is given, `inquiry_repo`/`order_repo` are the same
        # RemoteCoreClient instance, used here only for its repo-shaped reads
        # (list_all, get_by_id, list_orders, get_order, list_order_versions,
        # get_order_version — everything render_queue/render_inquiry/
        # render_order already call directly). Writes must never run
        # InquiryService/OrderService/OperationalCoreService business logic
        # against the remote client (that would reproduce Core's business
        # rules — id minting, defaults, timestamps — on Proxmox); instead we
        # swap in the client's own command-backed facades, which call the
        # frozen Core Office API's named commands. Direct mode (remote=None)
        # is completely unchanged — same objects, same construction, byte-
        # identical behavior.
        self.contact_profile_service = ContactProfileService(
            contact_profile_repo or InMemoryContactProfileRepository()
        )
        self.contact_note_service = ContactInternalNoteService(
            contact_note_repo or InMemoryContactInternalNoteRepository(),
            self.contact_profile_service,
            created_by="office-panel",
        )
        if remote is None:
            pause_repo = pause_repository or InMemoryOrderOperationalPauseRepository()
            self.inquiry_service = InquiryService(inquiry_repo)
            self.order_service = OrderService(order_repo)
            self.core = OperationalCoreService(order_repo, pause_repository=pause_repo)
            self.kitchen_print_service: KitchenPrintService | None = (
                KitchenPrintService(
                    order_repo,
                    kitchen_print_job_repo
                    or InMemoryKitchenPrintJobRepository(order_repo),
                )
            )
            self._pause_repository = pause_repo
            self.payment_reminder_service = PaymentReminderService(
                payment_reminder_repo or InMemoryPaymentReminderRepository(),
                order_repo,
                today=api_views.berlin_today,
            )
            document_repo = (
                confirmation_document_repo
                or InMemoryOrderConfirmationDocumentRepository()
            )
            outbound_repo = (
                confirmation_outbound_repo
                or InMemoryOrderConfirmationOutboundRepository()
            )
            self.confirmation_document_service = OrderConfirmationDocumentService(
                order_repo,
                inquiry_repo,
                document_repo,
                self._commercial_snapshots,
            )
            self.customer_document_preview_service = CustomerDocumentPreviewService(
                order_repo,
                inquiry_repo,
                self._commercial_snapshots,
            )
            self.confirmation_outbound_service = OrderConfirmationOutboundService(
                order_repo,
                document_repo,
                outbound_repo,
                self.core,
            )
            self.offer_document_service = OfferDocumentSnapshotService(
                self._offers, self._inquiries, self._offer_documents
            )
        else:
            # Structurally duck-typed, not the same concrete class — the
            # remote facades implement exactly the method surface this
            # module and office_panel_http.py call (create_inquiry,
            # update_inquiry, verify_customer_by_call, convert_inquiry_to_
            # order, create_relevant_order_change_version, evaluate_ready_
            # to_send, request_ready_to_send, confirm_kitchen_print,
            # make_order_version_effective, cancel_order), verified by the
            # remote-mode behavioral test suite.
            self.inquiry_service = remote.inquiry_service  # type: ignore[assignment]
            self.order_service = remote.order_service  # type: ignore[assignment]
            self.core = remote.core  # type: ignore[assignment]
            self.payment_reminder_service = remote.payment_reminder_service  # type: ignore[assignment]
            self.confirmation_document_service = remote.confirmation_document_service  # type: ignore[assignment]
            self.customer_document_preview_service = cast(
                CustomerDocumentPreviewService,
                remote.confirmation_document_service,
            )
            self.confirmation_outbound_service = remote.confirmation_outbound_service  # type: ignore[assignment]
            self.catalog_dish_write_service = remote.catalog_dish_write_service  # type: ignore[assignment]
            self.kitchen_print_service = None
            self._pause_repository = None
        self._remote = remote
        self._command_executor = command_executor
        self._ui_version = ui_version
        # Pure-read derivations: safe to run over the remote client's repo-
        # shaped reads in both modes, since they only ever call
        # get_order/get_order_version/list_orders/list_order_versions —
        # never a write.
        self.progression = ProgressionService(order_repo)
        self.wochenuebersicht = WochenuebersichtService(
            order_repo, pause_repository=self._pause_repository
        )
        # Single source of truth for the "full week" deep link — the kitchen
        # kiosk (catering_system.ui.kiosk_server) already owns that view via
        # the same WochenuebersichtService (OFFICE_PANEL_EXECUTION_PACK_V1
        # §6: Wochenübersicht stays derived-only, panel may at most link to
        # it). Empty -> no link shown, same graceful-degrade convention as
        # the Rückrufe integration.
        self.kiosk_url = kiosk_url
        # Optional read-only handoff to the separate proposal-phase editor.
        # The payload travels in a URL fragment (never an HTTP request) and
        # opening it performs no Core write.
        self.configurator_url = normalize_configurator_url(configurator_url)
        self._configurator_handoff_service = configurator_handoff_service

    def _build_first_offer_url(
        self, inquiry: Inquiry, context: OfficePageContext
    ) -> str:
        if (
            self._configurator_handoff_service is not None
            and context.employee_account_id
            and not context.legacy_shared_access
            and context.can("offers.prepare")
        ):
            minted = self._configurator_handoff_service.mint_first_offer(
                inquiry_id=inquiry.inquiry_id,
                issued_for_account_id=context.employee_account_id,
            )
            return build_configurator_handoff_url(self.configurator_url, minted.code)
        return build_offer_prefill_url(self.configurator_url, inquiry)

    def _operational_pause_view(self, order_id: str) -> dict[str, object]:
        getter = getattr(self.core, "get_operational_pause_projection", None)
        if getter is not None:
            return getter(order_id)
        active = self.core.get_active_operational_pause(order_id)
        if active is None:
            return {"active": False, "latest_pause_event_id": None}
        if isinstance(active, dict):
            return active
        return api_views.operational_pause_projection_from_active(active)

    @staticmethod
    def _optional_expect_uuid(form: dict[str, str], key: str) -> str | None:
        raw = form.get(f"_expect_{key}")
        if raw is None:
            return None
        stripped = raw.strip()
        return stripped or None

    def _pause_expect_fields(self, pause_view: dict[str, object]) -> dict[str, str]:
        latest = pause_view.get("latest_pause_event_id")
        return {
            "operational_pause_active": "false",
            "latest_pause_event_id": str(latest or ""),
        }

    def _resume_expect_fields(self, pause_view: dict[str, object]) -> dict[str, str]:
        return {
            "operational_pause_active": "true",
            "current_pause_event_id": str(pause_view["current_pause_event_id"]),
            "latest_pause_event_id": str(pause_view["latest_pause_event_id"]),
        }

    def pause_order(self, order_id: str, form: dict[str, str]) -> None:
        note = form.get("note", "").strip() or None
        command_id = form.get("_command_id") or str(uuid4())
        expected_latest = self._optional_expect_uuid(form, "latest_pause_event_id")
        if expected_latest is None and self._remote is None:
            projection_latest = self._operational_pause_view(order_id).get(
                "latest_pause_event_id"
            )
            expected_latest = (
                projection_latest if isinstance(projection_latest, str) else None
            )
        self.core.pause_order(
            order_id,
            reason_code=form["reason_code"],
            note=note,
            actor_reference="office-panel",
            command_id=command_id,
            expected_latest_pause_event_id=expected_latest,
        )

    def resume_order(self, order_id: str, form: dict[str, str]) -> None:
        note = form.get("note", "").strip() or None
        command_id = form.get("_command_id") or str(uuid4())
        expected_current = self._optional_expect_uuid(form, "current_pause_event_id")
        expected_latest = self._optional_expect_uuid(form, "latest_pause_event_id")
        if expected_current is None or expected_latest is None:
            projection = self._operational_pause_view(order_id)
            expected_current = str(projection["current_pause_event_id"])
            expected_latest = str(projection["latest_pause_event_id"])
        self.core.resume_order(
            order_id,
            reason_code=form["reason_code"],
            note=note,
            actor_reference="office-panel",
            command_id=command_id,
            expected_current_pause_event_id=expected_current,
            expected_latest_pause_event_id=expected_latest,
        )

    def request_kitchen_print(self, order_id: str, form: dict[str, str]) -> None:
        version_id = form["order_version_id"]
        if self.kitchen_print_service is None:
            if self._remote is not None:
                self.core.confirm_kitchen_print(order_id, version_id)
                return
            raise ValueError("kitchen print queue unavailable")

        kitchen_print_service = self.kitchen_print_service

        def work() -> None:
            version = self._orders.get_order_version(version_id)
            if version is None or version.order_id != order_id:
                raise ValueError("order version does not belong to order")
            attempts = kitchen_print_service.list_print_jobs_for_version(version_id)
            if not attempts:
                kitchen_print_service.request_print(order_id, version_id)
                return
            latest = attempts[-1]
            if latest.acknowledged_at is not None:
                return
            if (
                latest.rejected_at is not None
                or latest.superseded_at is not None
                or kitchen_print_service.is_ack_overdue(latest)
            ):
                kitchen_print_service.reprint(latest.print_job_id)

        if self._command_executor is not None:
            self._command_executor.run(work)
            return
        work()

    def _kitchen_print_action_label(self, order_version_id: str) -> str:
        if self.kitchen_print_service is None:
            return "Küchendruck starten"
        attempts = self.kitchen_print_service.list_print_jobs_for_version(
            order_version_id
        )
        if not attempts:
            return "Küchendruck starten"
        latest = attempts[-1]
        if latest.acknowledged_at is not None:
            return "Küchendruck starten"
        if (
            latest.rejected_at is not None
            or latest.superseded_at is not None
            or self.kitchen_print_service.is_ack_overdue(latest)
        ):
            return "Erneut drucken"
        return "Küchendruck starten"

    @staticmethod
    def _missed_calls_open(
        rueckruf_items: list[dict] | None, rueckruf_error: str | None
    ) -> int:
        if rueckruf_error or rueckruf_items is None:
            return 0
        return len(rueckruf_items)

    def build_work_center_snapshot(self, missed_calls_open: int) -> WorkCenterSnapshot:
        if self._remote is not None:
            raw = self._remote.work_center()
            return WorkCenterSnapshot(
                rueckrufe_open=cast(int, raw["rueckrufe_open"]),
                missed_calls_open=missed_calls_open,
                offers_waiting=cast(int, raw["offers_waiting"]),
                offers_accepted=cast(int, raw["offers_accepted"]),
                upcoming_orders=cast(int, raw["upcoming_orders"]),
                open_tasks=cast(int, raw["open_tasks"]),
                today_calendar_entries=cast(int, raw["today_calendar_entries"]),
                pending_order_changes=cast(int, raw["pending_order_changes"]),
            )
        return WorkCenterService(
            self._inquiries,
            self._offers,
            self._orders,
            today=api_views.berlin_today,
            missed_calls_open=lambda: missed_calls_open,
            task_projection_service=self._task_projection_service(),
            calendar_projection_service=self._calendar_projection_service(),
        ).snapshot()

    def _calendar_projection_service(self) -> CalendarProjectionService:
        return CalendarProjectionService(
            self._inquiries,
            self._offers,
            self._orders,
            today=api_views.berlin_today,
        )

    def _task_projection_service(self) -> TaskProjectionService:
        return TaskProjectionService(
            self._inquiries,
            self._offers,
            self._orders,
            self.payment_reminder_service,
            today=api_views.berlin_today,
        )

    def _task_list_rows(self) -> list[dict[str, object]]:
        if self._remote is not None:
            body = self._remote.list_tasks()
            return cast(list[dict[str, object]], body["tasks"])
        return api_views.task_list_view(self._task_projection_service().list_tasks())

    def render_aufgaben(
        self, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        return render_aufgaben_list(self._task_list_rows(), context=context)

    def _calendar_list_rows(self) -> list[dict[str, object]]:
        operating_today = api_views.berlin_today()
        from_date = operating_today
        to_date = operating_today + timedelta(days=90)
        if self._remote is not None:
            body = self._remote.list_calendar(from_date, to_date)
            return cast(list[dict[str, object]], body["entries"])
        return api_views.calendar_list_view(
            self._calendar_projection_service().list_entries(from_date, to_date)
        )

    def render_kalender(
        self, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        return render_kalender_list(self._calendar_list_rows(), context=context)

    def _converted_inquiry_ids(self) -> set[str]:
        """Inquiry IDs that already have any linked Order (active or cancelled)."""
        return {order.source_inquiry_id for order in self._orders.list_orders()}

    def _open_inquiries_count(self) -> int:
        """Open inquiries without a linked active order (direct and remote)."""
        converted = self._converted_inquiry_ids()
        return sum(
            1
            for inquiry in self._inquiries.list_all()
            if inquiry.crm_stage != "Abgelehnt / verloren"
            and inquiry.inquiry_id not in converted
        )

    def _contact_check_open_count(self) -> int:
        """Inquiries with pending call verification (Kundenprüfung)."""
        converted = self._converted_inquiry_ids()
        return sum(
            1
            for inquiry in self._inquiries.list_all()
            if inquiry.crm_stage != "Abgelehnt / verloren"
            and inquiry.inquiry_id not in converted
            and inquiry.call_verification_required
            and inquiry.call_verification_status != "verified"
        )

    def _render_v2_arbeitszentrale(
        self,
        *,
        missed_calls_open: int,
        context: OfficePageContext,
        kalender_view: str = "woche",
    ) -> str:
        operating_today = api_views.berlin_today()
        snapshot = self.build_work_center_snapshot(missed_calls_open)
        calendar_entries = (
            self._calendar_list_rows() if context.can("calendar.view") else []
        )
        return render_arbeitszentrale(
            ArbeitszentraleData(
                context=context,
                today=operating_today,
                snapshot=snapshot,
                tasks=self._task_list_rows(),
                calendar_entries=calendar_entries,
                contact_check_open=self._contact_check_open_count(),
                open_inquiries_open=self._open_inquiries_count(),
                kalender_view=kalender_view,
            )
        )

    def _offer_list_rows(self) -> list[dict[str, object]]:
        if self._remote is not None:
            body = self._remote.list_offers()
            return cast(list[dict[str, object]], body["offers"])
        inquiries_by_id = {
            inquiry.inquiry_id: inquiry for inquiry in self._inquiries.list_all()
        }
        return api_views.offer_list_view(
            self._offers.list_all(),
            inquiries_by_id,
            today=api_views.berlin_today(),
        )

    def _offer_queue_snapshot(self) -> dict[str, object]:
        if self._remote is not None:
            return self._remote.offer_queue()
        from catering_system.services.offer_queue_projection_service import (
            OfferQueueProjectionService,
        )

        service = OfferQueueProjectionService(
            self._offers,
            self._inquiries,
            today=api_views.berlin_today,
        )
        return api_views.offer_queue_view(service.snapshot())

    def render_angebote(
        self, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        return render_angebote_queue(
            self._offer_queue_snapshot(),
            context=context,
        )

    def render_offer(
        self, offer_id: str, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str | None:
        if self._remote is not None:
            detail = self._remote.offer_detail(offer_id)
            if detail is None:
                return None
        else:
            offer = self._offers.get(offer_id)
            if offer is None:
                return None
            detail = api_views.offer_detail(offer, today=api_views.berlin_today())
        forms = OfferDetailFormFields(
            csrf_input=_csrf_input(context),
            command_fields=self._command_fields(),
        )
        revision_prefill_url: str | None = None
        if (
            str(detail["commercial_state"])
            in {"Sent", "Expired", "Rejected", "Withdrawn"}
            and self.configurator_url
        ):
            inquiry = self._inquiries.get_by_id(str(detail["inquiry_id"]))
            if inquiry is not None:
                revision_prefill_url = build_offer_prefill_url(
                    self.configurator_url, inquiry
                )
        version_id = surface_version_id(detail)
        pdf_download_url: str | None = None
        if (
            version_id
            and context.can("offers.pdf.generate")
            and self.offer_document_exists(offer_id, version_id)
        ):
            pdf_download_url = (
                f"/offer/{quote(offer_id, safe='')}/offer-document/pdf"
                f"?{urlencode({'offer_version_id': version_id})}"
            )
        if revision_prefill_url is not None and not context.can(
            "offers.version.create"
        ):
            revision_prefill_url = None
        return render_offer_detail(
            detail,
            context=context,
            forms=forms,
            revision_prefill_url=revision_prefill_url or None,
            pdf_download_url=pdf_download_url,
        )

    def offer_document_exists(self, offer_id: str, offer_version_id: str) -> bool:
        """Read-only existence check used only to decide whether the PDF
        download link is shown — same ownership check as offer_document_pdf,
        without doing any rendering work."""
        if self._remote is not None:
            return self._remote.offer_document_exists(offer_id, offer_version_id)
        snapshot = self.offer_document_service.get_by_offer_version_id(offer_version_id)
        return snapshot is not None and snapshot.offer_id == offer_id

    def offer_document_pdf(
        self, offer_id: str, offer_version_id: str
    ) -> tuple[bytes, str] | None:
        """Render the already-persisted immutable snapshot to PDF bytes for
        download. Read-only: never creates a snapshot. Returns None when no
        snapshot exists for this offer/version (404 case); raises
        OfferPdfUnavailableError on renderer/static-content failure (422
        case)."""
        from catering_system.ui.remote_core_client import RemoteCoreError

        if self._remote is not None:
            try:
                pdf_bytes, filename = self._remote.offer_document_pdf(
                    offer_id, offer_version_id
                )
            except RemoteCoreError as exc:
                if exc.status == 404:
                    return None
                if exc.status == 422:
                    raise OfferPdfUnavailableError(exc.code) from exc
                raise
            return pdf_bytes, filename or f"{offer_id}.pdf"
        snapshot = self.offer_document_service.get_by_offer_version_id(offer_version_id)
        if snapshot is None or snapshot.offer_id != offer_id:
            return None
        if self.offer_pdf_static_content is None:
            raise OfferPdfUnavailableError("offer PDF static content not configured")
        try:
            pdf_bytes = render_offer_document_pdf(
                snapshot, self.offer_pdf_static_content
            )
        except (OfferPdfUnsupportedCharacterError, OfferPdfRenderError) as exc:
            raise OfferPdfUnavailableError(str(exc)) from exc
        return pdf_bytes, offer_document_pdf_filename(snapshot)

    def _offer_detail_dict(self, offer_id: str) -> dict[str, object]:
        if self._remote is not None:
            detail = self._remote.offer_detail(offer_id)
            if detail is None:
                raise KeyError(offer_id)
            return detail
        offer = self._offers.get(offer_id)
        if offer is None:
            raise KeyError(offer_id)
        return api_views.offer_detail(offer, today=api_views.berlin_today())

    @staticmethod
    def _require_form_text(form: dict[str, str], key: str, *, max_len: int) -> str:
        value = form.get(key, "").strip()
        if not value:
            raise ValueError(f"{key} is required")
        if len(value) > max_len:
            raise ValueError(f"{key} exceeds length limit")
        return value

    @staticmethod
    def _require_channel(
        form: dict[str, str], key: str, allowed: tuple[str, ...]
    ) -> str:
        channel = form.get(key, "").strip()
        if channel not in allowed:
            raise ValueError(f"invalid {key}")
        return channel

    def mark_offer_sent(self, offer_id: str, form: dict[str, str]) -> None:
        detail = self._offer_detail_dict(offer_id)
        if str(detail["commercial_state"]) != "Prepared":
            raise ValueError("sent recording blocked")
        offer_version_id = str(detail["offer_version_id"])
        sent_at = parse_datetime_local_berlin(form.get("sent_at", ""))
        channel = self._require_channel(form, "channel", SENT_CHANNELS)
        recipient_reference = self._require_form_text(
            form, "recipient_reference", max_len=500
        )
        evidence_reference = self._require_form_text(
            form, "evidence_reference", max_len=1000
        )

        def work() -> None:
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                self._commercial_snapshots,
                today=api_views.berlin_today,
            )
            offer_service.record_sent_evidence(
                offer_id,
                offer_version_id,
                sent_at=sent_at,
                channel=cast(SentChannel, channel),
                recipient_reference=recipient_reference,
                evidence_reference=evidence_reference,
                recorded_by="office-panel",
            )

        if self._remote is not None:
            self._remote.mark_offer_sent(
                offer_id,
                offer_version_id,
                sent_at=format_datetime_utc_iso(sent_at),
                channel=channel,
                recipient_reference=recipient_reference,
                evidence_reference=evidence_reference,
            )
            return
        if self._command_executor is not None:
            self._command_executor.run(work)
            return
        work()

    def record_offer_acceptance(self, offer_id: str, form: dict[str, str]) -> None:
        detail = self._offer_detail_dict(offer_id)
        if str(detail["commercial_state"]) != "Sent":
            raise ValueError("acceptance blocked")
        offer_version_id = str(detail["offer_version_id"])
        accepted_variant_id = self._require_form_text(
            form, "accepted_variant_id", max_len=36
        )
        accepted_at = parse_datetime_local_berlin(form.get("accepted_at", ""))
        channel = self._require_channel(form, "channel", ACCEPTANCE_CHANNELS)
        evidence_reference = self._require_form_text(
            form, "evidence_reference", max_len=1000
        )
        note_raw = form.get("note", "").strip()
        note = note_raw or None
        if note is not None and len(note) > 20000:
            raise ValueError("note exceeds length limit")

        def work() -> None:
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                self._commercial_snapshots,
                today=api_views.berlin_today,
            )
            offer_service.record_acceptance_evidence(
                offer_id,
                offer_version_id,
                accepted_variant_id,
                accepted_at=accepted_at,
                channel=cast(AcceptanceChannel, channel),
                evidence_reference=evidence_reference,
                recorded_by="office-panel",
                note=note,
            )

        if self._remote is not None:
            self._remote.record_offer_acceptance(
                offer_id,
                offer_version_id,
                accepted_variant_id=accepted_variant_id,
                accepted_at=format_datetime_utc_iso(accepted_at),
                channel=channel,
                evidence_reference=evidence_reference,
                note=note,
            )
            return
        if self._command_executor is not None:
            self._command_executor.run(work)
            return
        work()

    def record_offer_rejection(self, offer_id: str, form: dict[str, str]) -> None:
        detail = self._offer_detail_dict(offer_id)
        if str(detail["commercial_state"]) != "Sent":
            raise ValueError("rejection blocked")
        offer_version_id = str(detail["offer_version_id"])
        rejected_at = parse_datetime_local_berlin(form.get("rejected_at", ""))
        evidence_raw = form.get("evidence_reference", "").strip()
        evidence_reference = evidence_raw or None
        if evidence_reference is not None and len(evidence_reference) > 1000:
            raise ValueError("evidence_reference exceeds length limit")

        def work() -> None:
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                self._commercial_snapshots,
                today=api_views.berlin_today,
            )
            offer_service.record_rejection_evidence(
                offer_id,
                offer_version_id,
                rejected_at=rejected_at,
                recorded_by="office-panel",
                evidence_reference=evidence_reference,
            )

        if self._remote is not None:
            self._remote.record_offer_rejection(
                offer_id,
                offer_version_id,
                rejected_at=format_datetime_utc_iso(rejected_at),
                evidence_reference=evidence_reference,
            )
            return
        if self._command_executor is not None:
            self._command_executor.run(work)
            return
        work()

    def record_offer_withdrawal(self, offer_id: str, form: dict[str, str]) -> None:
        detail = self._offer_detail_dict(offer_id)
        if str(detail["commercial_state"]) != "Sent":
            raise ValueError("withdrawal blocked")
        offer_version_id = str(detail["offer_version_id"])
        reason_raw = form.get("reason", "").strip()
        reason = reason_raw or None
        if reason is not None and len(reason) > 20000:
            raise ValueError("reason exceeds length limit")

        def work() -> None:
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                self._commercial_snapshots,
                today=api_views.berlin_today,
            )
            offer_service.record_withdrawal_evidence(
                offer_id,
                offer_version_id,
                recorded_by="office-panel",
                reason=reason,
            )

        if self._remote is not None:
            self._remote.record_offer_withdrawal(
                offer_id,
                offer_version_id,
                reason=reason,
            )
            return
        if self._command_executor is not None:
            self._command_executor.run(work)
            return
        work()

    def convert_accepted_offer(
        self, offer_id: str, form: dict[str, str]
    ) -> tuple[Order, OrderVersion]:
        detail = self._offer_detail_dict(offer_id)
        if str(detail["commercial_state"]) != "Accepted":
            raise ValueError("conversion blocked")
        offer_version_id = str(detail["offer_version_id"])
        accepted_variant_id = form.get("accepted_variant_id", "").strip()
        acceptance_id = form.get("acceptance_id", "").strip()
        if not accepted_variant_id or not acceptance_id:
            raise ValueError("conversion blocked")

        def work() -> tuple[Order, OrderVersion]:
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                self._commercial_snapshots,
                today=api_views.berlin_today,
            )
            converted, order, order_version = offer_service.convert_accepted_offer(
                offer_id,
                offer_version_id,
                accepted_variant_id,
                acceptance_id,
            )
            commercial_version = next(
                item
                for item in converted.versions
                if item.offer_version_id == offer_version_id
            )
            self.payment_reminder_service.seed_from_conversion(
                order.order_id,
                commercial_version.payment_method,
            )
            self.inquiry_service.update_inquiry(
                str(detail["inquiry_id"]),
                crm_stage=ACTIVE_ORDER_CRM_STAGE,
            )
            return order, order_version

        if self._remote is not None:
            order_id, order_version_id = self._remote.convert_accepted_offer(
                offer_id,
                offer_version_id,
                accepted_variant_id=accepted_variant_id,
                acceptance_id=acceptance_id,
            )
            order = self._orders.get_order(order_id)
            order_version = self._orders.get_order_version(order_version_id)
            if order is None or order_version is None:
                raise ValueError("accepted offer conversion response incomplete")
            return order, order_version
        if self._command_executor is not None:
            return self._command_executor.run(work)
        return work()

    def _contact_list_rows(self) -> list[dict[str, object]]:
        if self._remote is not None:
            body = self._remote.list_contacts()
            return cast(list[dict[str, object]], body["contacts"])
        service = ContactProjectionService(
            self._inquiries,
            self._offers,
            self._orders,
            today=api_views.berlin_today,
        )
        return api_views.contact_list_view(service.list_contacts())

    def enrich_rueckruf_items(self, items: list[dict]) -> list[dict]:
        return enrich_missed_board_with_core_contacts(items, self._contact_list_rows())

    def render_kontakte(
        self,
        q: str = "",
        status: str = "all",
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str:
        from catering_system.domain.contact_projection import (
            parse_contact_status_filter,
        )

        rows = self._contact_list_rows()
        query = q.strip()
        status_filter = parse_contact_status_filter(status)
        # Profiles must exist (with denormalized name/email/phone) before search.
        ensured: list[tuple[dict[str, object], str]] = [
            (row, self._ensure_profile_for_contact_row(row)) for row in rows
        ]
        if query:
            matching_ids = set(self.contact_profile_service.search_profile_ids(query))
            rows = [row for row, profile_id in ensured if profile_id in matching_ids]
        else:
            rows = [row for row, _profile_id in ensured]
        counts = {
            "all": len(rows),
            "interessent": sum(
                1 for row in rows if str(row.get("contact_status")) == "interessent"
            ),
            "kunde": sum(
                1 for row in rows if str(row.get("contact_status")) == "kunde"
            ),
        }
        if status_filter != "all":
            rows = [
                row for row in rows if str(row.get("contact_status")) == status_filter
            ]
        return render_kontakte_list(
            rows,
            q=query,
            status=status_filter,
            counts=counts,
            context=context,
        )

    def _ensure_profile_for_contact_row(self, row: dict[str, object]) -> str:
        from datetime import datetime

        from catering_system.domain.contact_projection import ContactProjection

        raw_activity = row["last_activity"]
        if isinstance(raw_activity, datetime):
            last_activity = raw_activity
        else:
            last_activity = datetime.fromisoformat(str(raw_activity))
        projection = ContactProjection(
            contact_key=str(row["contact_key"]),
            identity_source=str(row["identity_source"]),  # type: ignore[arg-type]
            display_name=str(row["display_name"]),
            email=str(row["email"]) if row.get("email") is not None else None,
            phone=str(row["phone"]) if row.get("phone") is not None else None,
            inquiry_count=int(str(row["inquiry_count"])),
            open_inquiries=int(str(row["open_inquiries"])),
            active_orders=int(str(row["active_orders"])),
            last_activity=last_activity,
            linked_order_count=int(
                str(row.get("linked_order_count", row["active_orders"]))
            ),
            contact_status=str(  # type: ignore[arg-type]
                row.get("contact_status")
                or (
                    "kunde"
                    if int(str(row.get("linked_order_count", row["active_orders"]))) > 0
                    else "interessent"
                )
            ),
            inquiry_ids=tuple(),
        )
        return self.contact_profile_service.ensure_for_projection(projection)

    def render_kontakt(
        self, contact_key: str, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str | None:
        profile_id: str
        if self._remote is not None:
            detail = self._remote.contact_detail(contact_key)
            if detail is None:
                return None
            profile_id = self._ensure_profile_for_contact_row(
                {
                    "contact_key": contact_key,
                    "identity_source": detail.get("identity_source", "inquiry"),
                    "display_name": detail.get("display_name", "–"),
                    "email": detail.get("email"),
                    "phone": detail.get("phone"),
                    "inquiry_count": 0,
                    "open_inquiries": 0,
                    "active_orders": 0,
                    "last_activity": detail.get("last_activity")
                    or api_views.berlin_today().isoformat(),
                }
            )
        else:
            service = ContactProjectionService(
                self._inquiries,
                self._offers,
                self._orders,
                today=api_views.berlin_today,
            )
            projection = service.contact_detail(contact_key)
            if projection is None:
                # Stale UI key after linkage upgrade: resolve via profile aliases.
                resolved_id = self.contact_profile_service.find_by_alias(
                    "contact_key", contact_key
                )
                if resolved_id is None:
                    return None
                current_key = self._current_contact_key_for_profile(resolved_id)
                if current_key is None:
                    return None
                projection = service.contact_detail(current_key)
                if projection is None:
                    return None
                contact_key = current_key
            detail = api_views.contact_detail_view(
                projection.contact,
                list(projection.inquiries),
                list(projection.offers),
                list(projection.orders),
                today=api_views.berlin_today(),
            )
            for inquiry in projection.inquiries:
                self.contact_profile_service.ensure_for_inquiry(inquiry)
            profile_id = self.contact_profile_service.ensure_for_projection(
                projection.contact
            )
            self.contact_profile_service.bind_contact_key(contact_key, profile_id)
        detail = dict(detail)
        detail["internal_notes"] = self._contact_note_rows(profile_id)
        return render_kontakt_detail(detail, context=context)

    def _current_contact_key_for_profile(self, profile_id: str) -> str | None:
        root = self.contact_profile_service.resolve_root_profile_id(profile_id)
        for row in self._contact_list_rows():
            if self._ensure_profile_for_contact_row(row) == root:
                return str(row["contact_key"])
        return None

    def _contact_note_rows(self, contact_profile_id: str) -> list[dict[str, object]]:
        return [
            {
                "note_id": note.note_id,
                "contact_profile_id": note.contact_profile_id,
                "category": note.category,
                "note_text": note.note_text,
                "created_at": note.created_at.isoformat(),
                "created_by": note.created_by,
            }
            for note in self.contact_note_service.list_for_profile(contact_profile_id)
        ]

    def add_contact_note(self, contact_key: str, form: dict[str, str]) -> None:
        page = self.render_kontakt(contact_key)
        if page is None:
            raise KeyError(contact_key)
        profile_id = self.contact_profile_service.find_by_alias(
            "contact_key", contact_key
        )
        if profile_id is None:
            raise KeyError(contact_key)
        self.contact_note_service.add_note(
            profile_id,
            category=form.get("category", ""),
            note_text=form.get("note_text", ""),
        )

    def _catalog_list_payload(
        self, *, q: str | None = None, active: bool | None = None
    ) -> dict[str, object]:
        if self._remote is not None:
            return self._remote.list_catalog_dishes(q=q, active=active)
        service = CatalogDishService(self._catalog)
        return api_views.catalog_dish_list_view(service.list_dishes(q=q, active=active))

    def render_gerichte(
        self,
        q: str = "",
        status: str = "all",
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str:
        """CATALOG_ADMIN_PANEL_V1: both the search and the Aktiv/Inaktiv
        filter are pushed all the way down to the query (SQL WHERE in direct
        mode, `q`/`active` on the read endpoint in remote mode), so they
        narrow the rows *before* the 100-row page limit. Filtering here
        instead would answer "Keine Gerichte gefunden" whenever the excluded
        dishes happened to fill the first page."""
        query = q.strip()
        status_filter = status if status in _CATALOG_STATUS_FILTERS else "all"
        payload = self._catalog_list_payload(
            q=query or None,
            active=_CATALOG_ACTIVE_BY_FILTER[status_filter],
        )
        return render_gerichte_list(
            payload,
            search_query=query,
            status_filter=status_filter,
            context=context,
        )

    def render_gericht_new(
        self,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
        form: dict[str, str] | None = None,
        error_message: str | None = None,
    ) -> str:
        return render_gericht_new(
            command_fields=_csrf_input(context) + self._command_fields(),
            context=context,
            form=form or {},
            error_message=error_message,
        )

    def render_gericht(
        self,
        dish_id: str,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
        error_message: str | None = None,
    ) -> str | None:
        if self._remote is not None:
            detail = self._remote.catalog_dish_detail(dish_id)
            if detail is None:
                return None
        else:
            service = CatalogDishService(self._catalog)
            dish = service.get_dish(dish_id)
            if dish is None:
                return None
            history = service.list_price_history(dish_id)
            detail = api_views.catalog_dish_detail_view(dish, history)
        return render_gericht_detail(
            detail,
            context=context,
            command_fields=self._catalog_update_command_fields(
                str(detail["updated_at"]), context=context
            ),
            error_message=error_message,
        )

    def _catalog_detail_payload(self, dish_id: str) -> dict[str, object] | None:
        if self._remote is not None:
            return self._remote.catalog_dish_detail(dish_id)
        service = CatalogDishService(self._catalog)
        dish = service.get_dish(dish_id)
        if dish is None:
            return None
        history = service.list_price_history(dish_id)
        return api_views.catalog_dish_detail_view(dish, history)

    def _catalog_update_command_fields(
        self, updated_at: str, *, context: OfficePageContext
    ) -> str:
        # CATALOG_EDIT_CSRF_FIX_V1: every other mutating form pairs
        # _csrf_input(context) with _command_fields(...) — this one didn't,
        # so a real browser submit of the rendered page was rejected by
        # do_POST's global CSRF check (office_panel_http.py) with 403.
        expect = {"updated_at": updated_at}
        fields = _csrf_input(context) + self._command_fields(expect)
        if self._remote is None:
            fields += (
                f'<input type="hidden" name="_expect_updated_at" '
                f'value="{_e(updated_at)}">'
            )
        return fields

    def render_gericht_edit(
        self,
        dish_id: str,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
        error_message: str | None = None,
    ) -> str | None:
        detail = self._catalog_detail_payload(dish_id)
        if detail is None:
            return None
        detail = dict(detail)
        detail["effective_from_default"] = api_views.berlin_today().isoformat()
        return render_gericht_edit(
            detail,
            command_fields=self._catalog_update_command_fields(
                str(detail["updated_at"]), context=context
            ),
            context=context,
            error_message=error_message,
        )

    @staticmethod
    def _catalog_allergens_from_form(
        form: dict[str, str],
    ) -> tuple[AllergenCode, ...]:
        return tuple(
            code for code in ALLERGEN_CODES if form.get(f"allergen_{code}") == "1"
        )

    def _run_catalog_write(self, work: Callable[[], None]) -> None:
        if self._remote is not None:
            work()
        elif self._command_executor is not None:
            self._command_executor.run(work)
        else:
            work()

    @contextmanager
    def _catalog_write_errors(self) -> Iterator[None]:
        """CATALOG_ADMIN_PANEL_V1: maps direct-mode domain exceptions and
        remote-mode RemoteCoreError codes onto the same CatalogCommandError,
        so both modes produce the same German message *and* the same HTTP
        status — a missing dish stays 404, a concurrent edit stays 409, a
        domain rejection stays 422.

        Unavailability is re-raised untouched: "Core nicht erreichbar" is a
        degradation, not a business rejection, and the HTTP layer renders it
        through its own 503 path.

        Order matters — RemoteCoreError, CatalogDishStaleError and
        CatalogDishAlreadyExistsError are all ValueError subclasses, so the
        catch-all domain branch has to come last, and an already-classified
        CatalogCommandError has to pass through untouched before it.
        """
        from catering_system.ui.remote_core_client import RemoteCoreError

        try:
            yield
        except CatalogCommandError:
            raise
        except RemoteCoreError as exc:
            if exc.unavailable:
                raise
            mapped = _CATALOG_REMOTE_ERRORS.get(exc.code)
            if mapped is None:
                raise
            raise CatalogCommandError(*mapped) from exc
        except CatalogDishStaleError as exc:
            raise CatalogCommandError(*_CATALOG_STALE) from exc
        except CatalogDishAlreadyExistsError as exc:
            raise CatalogCommandError(*_CATALOG_EXISTS) from exc
        except CatalogDishNotFoundError as exc:
            raise CatalogCommandError(*_CATALOG_NOT_FOUND) from exc
        except ValueError as exc:
            raise CatalogCommandError(*_CATALOG_INVALID_DOMAIN) from exc

    def create_catalog_dish(self, form: dict[str, str]) -> str:
        """CATALOG_ADMIN_PANEL_V1: builds the domain payload from the form and
        delegates; the dish_id is minted by Core (direct service or Office
        API), never here, and `active` is not part of the payload at all —
        a new dish is always created inactive and is activated by the
        separate Aktivieren command."""
        created_id = ""
        with self._catalog_write_errors():
            price_cents = parse_catalog_price_input(form.get("price_net", ""))
            vat_raw = form.get("vat_rate_percent", "").strip()
            if not vat_raw.isdigit():
                raise CatalogCommandError(*_CATALOG_INVALID_DOMAIN)
            payload = CatalogDishCreatePayload(
                name=form.get("name", "").strip(),
                category=validate_category(form.get("category", "")),
                pricing_unit=validate_pricing_unit(
                    form.get("pricing_unit", "").strip()
                ),
                current_unit_net_cents=price_cents,
                vat_rate_percent=int(vat_raw),
                description=form.get("description", "").strip() or None,
                composition=form.get("composition", "").strip() or None,
                notes=form.get("notes", "").strip() or None,
                allergens=self._catalog_allergens_from_form(form),
            )

            def work() -> None:
                nonlocal created_id
                if self._remote is not None:
                    created_id = self._remote.catalog_dish_write_service.create_dish(
                        payload
                    ).dish_id
                    return
                created_id = self.catalog_dish_write_service.create_dish(
                    payload
                ).dish_id

            self._run_catalog_write(work)
        return created_id

    def set_catalog_dish_active(
        self, dish_id: str, form: dict[str, str], *, active: bool
    ) -> None:
        """CATALOG_ADMIN_PANEL_V1: status is its own command in both modes —
        activate_dish/deactivate_dish, never a field of the edit form — so the
        optimistic-concurrency token has to travel with it exactly as the
        update form's does."""
        expected_raw = form.get("_expect_updated_at", "").strip()
        if not expected_raw:
            raise CatalogCommandError(*_CATALOG_INVALID_INPUT)
        with self._catalog_write_errors():
            try:
                expected_updated_at = datetime.fromisoformat(expected_raw)
            except ValueError as exc:
                # A malformed precondition is a bad request, not a domain
                # rejection — it never reached the dish.
                raise CatalogCommandError(*_CATALOG_INVALID_INPUT) from exc

            def work() -> None:
                if self._remote is not None:
                    remote_service = self._remote.catalog_dish_write_service
                    if active:
                        remote_service.activate_dish(
                            dish_id, expected_updated_at=expected_raw
                        )
                    else:
                        remote_service.deactivate_dish(
                            dish_id, expected_updated_at=expected_raw
                        )
                    return
                if active:
                    self.catalog_dish_write_service.activate_dish(
                        dish_id, expected_updated_at=expected_updated_at
                    )
                else:
                    self.catalog_dish_write_service.deactivate_dish(
                        dish_id, expected_updated_at=expected_updated_at
                    )

            self._run_catalog_write(work)

    def update_catalog_dish(self, dish_id: str, form: dict[str, str]) -> None:
        expected_raw = form.get("_expect_updated_at", "").strip()
        if not expected_raw:
            raise CatalogCommandError(*_CATALOG_INVALID_INPUT)
        with self._catalog_write_errors():
            try:
                expected_updated_at = datetime.fromisoformat(expected_raw)
            except ValueError as exc:
                # A malformed precondition is a bad request, not a domain
                # rejection — it never reached the dish.
                raise CatalogCommandError(*_CATALOG_INVALID_INPUT) from exc
            current = self._catalog_detail_payload(dish_id)
            if current is None:
                raise CatalogCommandError(*_CATALOG_NOT_FOUND)
            # Same price rule as the create form: reject a third decimal
            # rather than let the shared parser quantize it away.
            new_cents = parse_catalog_price_input(form.get("price_net", ""))
            effective_raw = form.get("effective_from", "").strip()
            try:
                effective_from = (
                    date.fromisoformat(effective_raw) if effective_raw else None
                )
            except ValueError as exc:
                raise CatalogCommandError(*_CATALOG_INVALID_INPUT) from exc
            if (
                new_cents != int(str(current["current_unit_net_cents"]))
                and effective_from is None
            ):
                effective_from = api_views.berlin_today()
            name = form.get("name", "").strip()
            description = form.get("description", "").strip() or None
            composition = form.get("composition", "").strip() or None
            notes = form.get("notes", "").strip() or None
            allergens = self._catalog_allergens_from_form(form)
            # CATALOG_ADMIN_PANEL_V1: the edit form no longer carries an Aktiv
            # checkbox (status is its own command now), so `active` must be
            # read back from the dish's current state. Deriving it from the
            # form here would silently deactivate every dish on each save,
            # since a missing checkbox is indistinguishable from an
            # unchecked one.
            active = bool(current["active"])
            args: dict[str, object] = {
                "name": name,
                "description": description,
                "composition": composition,
                "notes": notes,
                "current_unit_net_cents": new_cents,
                "allergens": list(allergens),
                "active": active,
            }
            if effective_from is not None:
                args["effective_from"] = effective_from.isoformat()

            def work() -> None:
                if self._remote is not None:
                    self._remote.catalog_dish_write_service.update(
                        dish_id,
                        args=args,
                        expected_updated_at=expected_raw,
                    )
                    return
                self.catalog_dish_write_service.update_dish(
                    dish_id,
                    update=CatalogDishUpdatePayload(
                        name=name,
                        description=description,
                        composition=composition,
                        notes=notes,
                        current_unit_net_cents=new_cents,
                        allergens=allergens,
                        active=active,
                        effective_from=effective_from,
                    ),
                    expected_updated_at=expected_updated_at,
                )

            self._run_catalog_write(work)

    def _email_list_rows(self) -> list[dict[str, object]]:
        if self._remote is not None:
            body = self._remote.list_emails()
            return cast(list[dict[str, object]], body["emails"])
        service = EmailIntakeProjectionService(
            self._inquiries,
            self._offers,
            self._orders,
        )
        return api_views.email_list_view(service.list_emails())

    def render_email(self, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT) -> str:
        return render_email_list(self._email_list_rows(), context=context)

    def render_email_detail(
        self, inquiry_id: str, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str | None:
        if self._remote is not None:
            detail = self._remote.email_detail(inquiry_id)
            if detail is None:
                return None
        else:
            service = EmailIntakeProjectionService(
                self._inquiries,
                self._offers,
                self._orders,
            )
            projection = service.email_detail(inquiry_id)
            if projection is None:
                return None
            detail = api_views.email_detail_view(projection)
        return render_email_detail(detail, context=context)

    def begin_request(self, form: dict[str, str] | None = None) -> None:
        """No-op in direct mode. In remote mode, resets the RemoteCoreClient's
        per-request read caches and stashes the submitted form (if any) so the
        write facades can read back `_command_id`/`_expect_*` hidden fields
        (pack §6.1/§6.3). The HTTP handler calls this once per request, before
        any panel render/write method, for both GET (empty form) and POST."""
        if self._remote is not None:
            self._remote.begin_request(form)

    def _command_fields(self, expect: dict[str, str] | None = None) -> str:
        """Hidden idempotency fields for a rendered mutating form. Empty in
        direct mode — direct-mode HTML must stay byte-identical (pack §7). In
        remote mode, mints a fresh command_id for this render (baked into the
        served page, so a resubmission of the SAME loaded form — a double
        click, or a retry after an indeterminate network failure — always
        carries the same id and the same preconditions) plus one
        `_expect_<key>` field per precondition the command route requires."""
        if self._remote is None:
            return ""
        command_id = self._remote.new_page_command_id()
        fields = f'<input type="hidden" name="_command_id" value="{_e(command_id)}">'
        for key, value in (expect or {}).items():
            fields += f'<input type="hidden" name="_expect_{key}" value="{_e(value)}">'
        return fields

    def _next_step_action(
        self,
        order: Order,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str:
        """UI action-target resolution for existing routes only — not new
        order semantics. Picks the target OrderVersion (candidate_order_
        version_id if set and real, else the highest version_number — a
        display fallback, not new truth; documented in domain/order.py as
        exactly this: an "office-side progression hint") and returns
        whichever of the two existing, ordered actions applies. Order
        matters: operational_core_service.make_order_version_effective()
        itself refuses a version whose kitchen print isn't confirmed yet
        (raises ValueError) — so print-confirm must be offered first, never
        "Wirksam machen" for an unprinted version, even if that version's
        READY_TO_SEND reason would otherwise be reported as
        no_effective_version rather than kitchen_print_not_confirmed."""
        versions = self._orders.list_order_versions(order.order_id)
        if not versions:
            return ""
        version = next(
            (
                v
                for v in versions
                if v.order_version_id == order.candidate_order_version_id
            ),
            None,
        )
        if version is None:
            version = max(versions, key=lambda v: v.version_number)
        expect: dict[str, str] = {}
        if version.kitchen_print_confirmed_at is None:
            if not context.can("orders.print.confirm"):
                return ""
            label, action = (
                self._kitchen_print_action_label(version.order_version_id),
                "print-confirm",
            )
        elif version.order_version_id != order.effective_order_version_id:
            if not context.can("orders.effective.set"):
                return ""
            label, action = "Wirksam machen", "effective"
            expect = {
                "effective_version_id": order.effective_order_version_id or "",
                "candidate_version_id": order.candidate_order_version_id or "",
            }
        else:
            return ""
        return (
            f'<form class="inline" method="post" action="/order/{_e(order.order_id)}/{action}">'
            f"{_csrf_input(context)}{self._command_fields(expect)}"
            f'<input type="hidden" name="order_version_id" value="{_e(version.order_version_id)}">'
            f"<button>{label}</button></form>"
        )

    def _inquiry_office_state(
        self,
        inquiry: Inquiry,
        linked_orders: list[Order],
        *,
        inquiry_id: str | None = None,
    ) -> InquiryOfficeState:
        inquiry_id = inquiry_id or inquiry.inquiry_id
        if self._remote is not None:
            meta = self._remote.inquiry_detail_meta(inquiry_id)
            if (
                meta.next_action is not None
                or meta.offer is not None
                or meta.offer_preparation_blockers
            ):
                from catering_system.domain.inquiry import InquiryOfferProjection

                offer_projection = None
                if meta.offer is not None:
                    raw_offer = meta.offer
                    offer_projection = InquiryOfferProjection(
                        offer_id=str(raw_offer["offer_id"]),
                        offer_version_id=str(raw_offer["offer_version_id"]),
                        commercial_state=raw_offer["commercial_state"],  # type: ignore[arg-type]
                        accepted_variant_id=(
                            str(raw_offer["accepted_variant_id"])
                            if raw_offer.get("accepted_variant_id") is not None
                            else None
                        ),
                        acceptance_id=(
                            str(raw_offer["acceptance_id"])
                            if raw_offer.get("acceptance_id") is not None
                            else None
                        ),
                    )
                has_order = bool(linked_orders)
                has_active_order = any(
                    order.cancelled_at is None for order in linked_orders
                )
                if has_active_order and not has_order:
                    raise ValueError("an active order is also an existing order")
                if inquiry.crm_stage == "Abgelehnt / verloren" or has_active_order:
                    is_open = False
                else:
                    is_open = True
                return InquiryOfficeState(
                    is_open=is_open,
                    next_action=meta.next_action,
                    offer=offer_projection,
                    offer_preparation_blockers=meta.offer_preparation_blockers,
                )
        offer = self._offers.get_by_source_inquiry_id(inquiry_id)
        return api_views.inquiry_office_state(
            inquiry,
            linked_orders,
            offer=offer,
            today=api_views.berlin_today(),
        )

    def _inquiry_primary_action_html(
        self,
        inquiry_id: str,
        state: InquiryOfficeState,
        *,
        context: OfficePageContext,
    ) -> str:
        if state.next_action == "verify":
            if not context.can("inquiries.verify"):
                return ""
            return (
                f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/verify">'
                f"{_csrf_input(context)}{self._command_fields()}"
                "<button>Telefonisch verifiziert</button></form>"
            )
        if state.next_action == "prepare-offer":
            if not context.can("offers.prepare"):
                return ""
            return '<span class="muted">Angebot vorbereiten</span>'
        if state.next_action == "prepare-next-version":
            if not context.can("offers.version.create"):
                return ""
            return '<span class="muted">Neue Version vorbereiten</span>'
        if state.next_action == "offer-pending":
            return '<span class="muted">Angebot ausstehend</span>'
        if state.next_action == "convert-accepted":
            return '<span class="muted">Angebot angenommen</span>'
        return ""

    # -- queue -----------------------------------------------------------

    def render_queue(
        self,
        rueckruf_items: list[dict] | None,
        *,
        rueckruf_error: str | None = None,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
        kalender_view: str = "woche",
    ) -> str:
        missed_calls_open = self._missed_calls_open(rueckruf_items, rueckruf_error)
        if self._ui_version == "v2":
            return self._render_v2_arbeitszentrale(
                missed_calls_open=missed_calls_open,
                context=context,
                kalender_view=kalender_view,
            )
        if self._remote is not None:
            return self._render_remote_queue(
                self._remote.queue_view(),
                rueckruf_items,
                rueckruf_error=rueckruf_error,
                context=context,
            )
        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for o in orders:
            orders_by_inquiry.setdefault(o.source_inquiry_id, []).append(o)

        # -- Heute / Aufmerksamkeit: counts from data already loaded above,
        # no new service calls. Every number here maps onto an existing,
        # already-accepted concept (progression B7 / operational gate) —
        # this is a summary view, not a new domain concept.
        all_inquiries = self._inquiries.list_all()
        open_inquiries = []
        for inquiry in all_inquiries:
            linked = orders_by_inquiry.get(inquiry.inquiry_id, [])
            state = self._inquiry_office_state(inquiry, linked)
            if state.is_open:
                open_inquiries.append((inquiry, state))
        active_orders = [o for o in orders if o.cancelled_at is None]
        ohne_druck = [
            o
            for o in active_orders
            if not any(
                v.kitchen_print_confirmed_at is not None
                for v in self._orders.list_order_versions(o.order_id)
            )
        ]
        nicht_wirksam = [
            o for o in active_orders if o.effective_order_version_id is None
        ]
        evaluations = {
            o.order_id: self.core.evaluate_ready_to_send(o.order_id)
            for o in active_orders
        }
        blockiert = [o for o in active_orders if not evaluations[o.order_id].ready]
        paused = [
            o
            for o in active_orders
            if self._operational_pause_view(o.order_id).get("active")
        ]
        pending_changes = [
            o
            for o in active_orders
            if o.candidate_order_version_id is not None
            and o.candidate_order_version_id != o.effective_order_version_id
            and (
                candidate := self._orders.get_order_version(
                    o.candidate_order_version_id
                )
            )
            is not None
            and candidate.kitchen_print_confirmed_at is None
        ]
        storniert = [o for o in orders if o.cancelled_at is not None]
        # Reuses the same request-local count already fetched for the sidebar
        # badge — no second auerswald-sync request. None = not configured/unreachable -> card omitted, same
        # as the sidebar badge; unlike the other cards, 0 is a real fetched
        # value here (they never depend on an external service, so 0 always
        # means "confirmed empty").
        rueckruf_card = (
            f'<a href="/rueckruf"><strong>{context.rueckruf_count}</strong> Rückrufe offen</a>'
            if context.rueckruf_count is not None
            else ""
        )
        storniert_card = (
            f"<span><strong>{len(storniert)}</strong> Stornierte Aufträge prüfen</span>"
            if storniert
            else ""
        )
        attention = (
            "<h2>Was braucht Aufmerksamkeit?</h2>"
            '<div class="attention">'
            + rueckruf_card
            + f'<a href="#anfragen"><strong>{len(open_inquiries)}</strong> Offene Anfragen prüfen</a>'
            f'<a href="#auftraege"><strong>{len(ohne_druck)}</strong> Druckbestätigung fehlt</a>'
            f'<a href="#auftraege"><strong>{len(nicht_wirksam)}</strong> Aufträge noch nicht wirksam</a>'
            f'<a href="#auftraege"><strong>{len(pending_changes)}</strong> Änderungen warten auf Küchendruck</a>'
            f'<a href="#auftraege"><strong>{len(blockiert)}</strong> Versandfreigabe blockiert</a>'
            f'<a href="#auftraege"><strong>{len(paused)}</strong> Betrieblich pausiert</a>'
            + storniert_card
            + "</div>"
        )

        operating_today = api_views.berlin_today()
        iso = operating_today.isocalendar()
        week = self.wochenuebersicht.get_week_overview(iso.year, iso.week)
        week_rows = [
            f"<tr><td>{_e(e.event_date.isoformat())}</td><td>{_e(e.time_window_text)}</td>"
            f"<td>{_e(e.location_text)}</td>"
            f"<td>{_e(str(e.guest_count_estimate) if e.guest_count_estimate is not None else '–')}</td>"
            f'<td><a href="/order/{_e(e.order_id)}">{_e(e.order_id[:8])}</a></td></tr>'
            for e in week.entries
        ]
        kiosk_link = (
            f' <a href="{_e(self.kiosk_url)}">Vollständige Wochenübersicht (Küche)</a>'
            if self.kiosk_url
            else ""
        )
        diese_woche = ""
        if context.can("calendar.view"):
            diese_woche = (
                f'<h2 id="diese-woche">Diese Woche (KW {iso.week}/{iso.year})</h2>'
                "<table><tr><th>Datum</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th><th>Auftrag</th></tr>"
                + "".join(
                    week_rows
                    or [
                        '<tr><td colspan="5">keine wirksamen Aufträge diese Woche</td></tr>'
                    ]
                )
                + "</table>"
                + kiosk_link
            )

        # -- three action queues (§11 addendum): top 5 rows each, one
        # primary action per row, full lists live at /rueckruf, /anfragen,
        # /auftraege. rueckruf_items is None when auerswald-sync is
        # unconfigured/unreachable -> the whole queue is omitted, same
        # graceful-degrade convention as the sidebar badge (not an error
        # page, the rest of the Startseite still renders).
        rueckruf_section = ""
        if rueckruf_items is not None:
            rows = []
            for it in rueckruf_items[:5]:
                contact = _format_rueckruf_contact_cell(it)
                phone = it.get("phone", "")
                resolve_form = ""
                if context.can("queue.resolve"):
                    resolve_form = (
                        '<form class="inline" method="post" action="/rueckruf/resolve">'
                        f"{_csrf_input(context)}"
                        f'<input type="hidden" name="call_id" value="{_e(it.get("call_id", ""))}">'
                        "<button>Erledigt</button></form> "
                    )
                rows.append(
                    f"<li>{_e(it.get('date', ''))} {_e(it.get('time', ''))} — "
                    f"{_e(phone)} ({contact}) "
                    f"{resolve_form}"
                    f'<a href="/inquiry/new?phone={quote(phone)}">Anfrage erfassen</a></li>'
                )
            rueckruf_section = (
                "<h2>Rückruf nötig</h2>"
                + (
                    f"<ul>{''.join(rows)}</ul>"
                    if rows
                    else "<p>keine offenen Rückrufe.</p>"
                )
                + '<p><a href="/rueckruf">Alle anzeigen</a></p>'
            )

        offene_anfragen_rows = []
        for inq, state in open_inquiries[:5]:
            action = self._inquiry_primary_action_html(
                inq.inquiry_id, state, context=context
            )
            offene_anfragen_rows.append(
                f'<li><a href="/inquiry/{_e(inq.inquiry_id)}">{_e(inq.event_date.isoformat())} · '
                f"{_e(inq.location_text)}</a> — {_e(inq.crm_stage)} {action}</li>"
            )
        offene_anfragen_section = (
            "<h2>Offene Anfragen</h2>"
            + (
                f"<ul>{''.join(offene_anfragen_rows)}</ul>"
                if offene_anfragen_rows
                else "<p>keine offenen Anfragen.</p>"
            )
            + '<p><a href="/anfragen">Alle anzeigen</a></p>'
        )

        auftraege_rows = []
        for o in blockiert[:5]:
            ev = evaluations[o.order_id]
            reason = (
                _e(_ready_to_send_blocker_label(ev.reasons[0])) if ev.reasons else "–"
            )
            action = self._next_step_action(o, context=context)
            auftraege_rows.append(
                f'<li><a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a> — {reason} {action}</li>'
            )
        auftraege_section = (
            "<h2>Aufträge mit nächstem Schritt</h2>"
            + (
                f"<ul>{''.join(auftraege_rows)}</ul>"
                if auftraege_rows
                else "<p>keine offenen Schritte.</p>"
            )
            + '<p><a href="/auftraege">Alle anzeigen</a></p>'
        )

        body = (
            attention
            + diese_woche
            + rueckruf_section
            + offene_anfragen_section
            + auftraege_section
            + (
                '<p><a href="/inquiry/new">+ Neue Anfrage erfassen</a></p>'
                if context.can("inquiries.create")
                else ""
            )
        )
        return _page("Büro-Übersicht", body, active_section="home", context=context)

    def _render_remote_queue(
        self,
        view: dict[str, object],
        rueckruf_items: list[dict] | None,
        *,
        rueckruf_error: str | None = None,
        context: OfficePageContext,
    ) -> str:
        """Render the frozen QueueView without recomputing Core semantics.

        In remote mode the authoritative Berlin operating day, attention
        counts and next actions are supplied by Core in one read.  This keeps
        the Proxmox panel from recreating business rules or issuing an N+1
        graph of list/detail calls.
        """
        attention_view = cast(dict[str, int], view["attention"])
        rueckruf_card = (
            f'<a href="/rueckruf"><strong>{context.rueckruf_count}</strong> Rückrufe offen</a>'
            if context.rueckruf_count is not None
            else ""
        )
        storniert = attention_view["storniert"]
        storniert_card = (
            f"<span><strong>{storniert}</strong> Stornierte Aufträge prüfen</span>"
            if storniert
            else ""
        )
        attention = (
            "<h2>Was braucht Aufmerksamkeit?</h2>"
            '<div class="attention">'
            + rueckruf_card
            + f'<a href="#anfragen"><strong>{attention_view["neue_anfragen"]}</strong> Offene Anfragen prüfen</a>'
            f'<a href="#auftraege"><strong>{attention_view["druck_fehlt"]}</strong> Druckbestätigung fehlt</a>'
            f'<a href="#auftraege"><strong>{attention_view["nicht_wirksam"]}</strong> Aufträge noch nicht wirksam</a>'
            f'<a href="#auftraege"><strong>{attention_view["aenderungen_warten_auf_kuechendruck"]}</strong> Änderungen warten auf Küchendruck</a>'
            f'<a href="#auftraege"><strong>{attention_view["versand_blockiert"]}</strong> Versandfreigabe blockiert</a>'
            f'<a href="#auftraege"><strong>{attention_view["pausiert"]}</strong> Betrieblich pausiert</a>'
            + storniert_card
            + "</div>"
        )

        week = cast(dict[str, Any], view["week"])
        week_rows = [
            f"<tr><td>{_e(entry['event_date'])}</td><td>{_e(entry['time_window_text'])}</td>"
            f"<td>{_e(entry['location_text'])}</td>"
            f"<td>{_e(str(entry['guest_count_estimate']) if entry['guest_count_estimate'] is not None else '–')}</td>"
            f'<td><a href="/order/{_e(entry["order_id"])}">{_e(entry["order_id"][:8])}</a></td></tr>'
            for entry in cast(list[dict[str, Any]], week["entries"])
        ]
        kiosk_link = (
            f' <a href="{_e(self.kiosk_url)}">Vollständige Wochenübersicht (Küche)</a>'
            if self.kiosk_url
            else ""
        )
        truncation_warning = (
            '<p class="blocked"><strong>Unvollständige Ansicht:</strong> '
            f"Diese Woche zeigt {len(week_rows)} von {week['total_count']} Aufträgen. "
            "Bitte die vollständige Wochenübersicht öffnen.</p>"
            if week["truncated"]
            else ""
        )
        diese_woche = (
            f'<h2 id="diese-woche">Diese Woche (KW {week["iso_week"]}/{week["iso_year"]})</h2>'
            + truncation_warning
            + "<table><tr><th>Datum</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th><th>Auftrag</th></tr>"
            + "".join(
                week_rows
                or [
                    '<tr><td colspan="5">keine wirksamen Aufträge diese Woche</td></tr>'
                ]
            )
            + "</table>"
            + kiosk_link
        )

        rueckruf_section = ""
        if rueckruf_items is not None:
            rows = []
            for item in rueckruf_items[:5]:
                contact = _format_rueckruf_contact_cell(item)
                phone = item.get("phone", "")
                resolve_form = ""
                if context.can("queue.resolve"):
                    resolve_form = (
                        '<form class="inline" method="post" action="/rueckruf/resolve">'
                        f"{_csrf_input(context)}"
                        f'<input type="hidden" name="call_id" value="{_e(item.get("call_id", ""))}">'
                        "<button>Erledigt</button></form> "
                    )
                rows.append(
                    f"<li>{_e(item.get('date', ''))} {_e(item.get('time', ''))} — "
                    f"{_e(phone)} ({contact}) "
                    f"{resolve_form}"
                    f'<a href="/inquiry/new?phone={quote(phone)}">Anfrage erfassen</a></li>'
                )
            rueckruf_section = (
                "<h2>Rückruf nötig</h2>"
                + (
                    f"<ul>{''.join(rows)}</ul>"
                    if rows
                    else "<p>keine offenen Rückrufe.</p>"
                )
                + '<p><a href="/rueckruf">Alle anzeigen</a></p>'
            )

        inquiry_rows = []
        for inquiry in cast(list[dict[str, Any]], view["neue_anfragen_top"]):
            action_name = inquiry["next_action"]
            inquiry_id = str(inquiry["inquiry_id"])
            if action_name == "verify":
                action = (
                    f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/verify">'
                    f"{_csrf_input(context)}{self._command_fields()}"
                    "<button>Telefonisch verifiziert</button></form>"
                )
            elif action_name == "prepare-offer":
                action = '<span class="muted">Angebot vorbereiten</span>'
            elif action_name == "prepare-next-version":
                action = '<span class="muted">Neue Version vorbereiten</span>'
            elif action_name == "offer-pending":
                action = '<span class="muted">Angebot ausstehend</span>'
            elif action_name == "convert-accepted":
                action = '<span class="muted">Angebot angenommen</span>'
            else:
                action = ""
            inquiry_rows.append(
                f'<li><a href="/inquiry/{_e(inquiry["inquiry_id"])}">{_e(inquiry["event_date"])} · '
                f"{_e(inquiry['location_text'])}</a> — {_e(inquiry['crm_stage'])} {action}</li>"
            )
        offene_anfragen_section = (
            "<h2>Offene Anfragen</h2>"
            + (
                f"<ul>{''.join(inquiry_rows)}</ul>"
                if inquiry_rows
                else "<p>keine offenen Anfragen.</p>"
            )
            + '<p><a href="/anfragen">Alle anzeigen</a></p>'
        )

        order_rows = []
        for order in cast(list[dict[str, Any]], view["auftraege_top"]):
            reason = (
                _e(_ready_to_send_blocker_label(order["blocker_reason"]))
                if order["blocker_reason"] is not None
                else "–"
            )
            action_view = cast(dict[str, str] | None, order["next_action"])
            action = ""
            if action_view is not None:
                action_name = action_view["action"]
                label = (
                    "Küchendruck starten"
                    if action_name == "print-confirm"
                    else "Wirksam machen"
                )
                expect = (
                    {
                        "effective_version_id": (
                            order["effective_order_version_id"] or ""
                        ),
                        "candidate_version_id": (
                            order["candidate_order_version_id"] or ""
                        ),
                    }
                    if action_name == "effective"
                    else None
                )
                action = (
                    f'<form class="inline" method="post" action="/order/{_e(order["order_id"])}/{action_name}">'
                    f"{_csrf_input(context)}{self._command_fields(expect)}"
                    f'<input type="hidden" name="order_version_id" value="{_e(action_view["order_version_id"])}">'
                    f"<button>{label}</button></form>"
                )
            order_rows.append(
                f'<li><a href="/order/{_e(order["order_id"])}">{_e(order["order_id"][:8])}</a> — {reason} {action}</li>'
            )
        auftraege_section = (
            "<h2>Aufträge mit nächstem Schritt</h2>"
            + (
                f"<ul>{''.join(order_rows)}</ul>"
                if order_rows
                else "<p>keine offenen Schritte.</p>"
            )
            + '<p><a href="/auftraege">Alle anzeigen</a></p>'
        )
        body = (
            attention
            + diese_woche
            + rueckruf_section
            + offene_anfragen_section
            + auftraege_section
            + '<p><a href="/inquiry/new">+ Neue Anfrage erfassen</a></p>'
        )
        return _page("Büro-Übersicht", body, active_section="home", context=context)

    # -- full lists (moved out of the Startseite, §11 addendum §13) ------

    def render_anfragen(
        self, q: str = "", *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        needle = q.strip().lower()

        def _matches(*fields: str) -> bool:
            if not needle:
                return True
            return any(needle in f.lower() for f in fields)

        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for o in orders:
            orders_by_inquiry.setdefault(o.source_inquiry_id, []).append(o)

        search_box = (
            '<form method="get" action="/anfragen" class="searchbox">'
            f'<input type="text" name="q" value="{_e(q)}" placeholder="Suche: ID, Ort, Datum…">'
            '<button type="submit">Suchen</button>'
            + (' <a href="/anfragen">Zurücksetzen</a>' if q else "")
            + "</form>"
        )

        rows = []
        for inq in self._inquiries.list_all():
            linked_orders = orders_by_inquiry.get(inq.inquiry_id, [])
            has_order = (
                f'<a href="/order/{_e(linked_orders[0].order_id)}">Auftrag öffnen</a>'
                if linked_orders
                else "–"
            )
            if not _matches(
                inq.inquiry_id,
                inq.location_text,
                inq.event_date.isoformat(),
                inq.crm_stage,
                inq.intake_subject or "",
            ):
                continue
            betreff_raw = inq.intake_subject or ""
            betreff = (
                betreff_raw[:40] + "…" if len(betreff_raw) > 40 else betreff_raw
            ) or "–"
            verif_text = _e(_verification_label(inq.call_verification_status))
            verif_cell = (
                f'<span class="blocked">{verif_text}</span>'
                if inq.call_verification_required
                and inq.call_verification_status != "verified"
                else verif_text
            )
            # Calm contact badge (INQUIRY_CONTACT_COMPLETENESS_V1 §9) — same
            # .blocked convention as the verification marker above.
            if derive_inquiry_contact_completeness(inq) != "complete":
                verif_cell += ' <span class="blocked">Kontaktdaten fehlen</span>'
            rows.append(
                f"<tr><td>{_e(inq.event_date.isoformat())}</td><td>{_e(inq.location_text)}</td>"
                f"<td>{_e(betreff)}</td><td>{_e(inq.crm_stage)}</td><td>{verif_cell}</td>"
                f"<td>{has_order}</td>"
                f'<td><a href="/inquiry/{_e(inq.inquiry_id)}">{_e(inq.inquiry_id[:8])}</a></td></tr>'
            )

        body = (
            search_box + '<p><a href="/inquiry/new">+ Neue Anfrage erfassen</a></p>'
            "<table><tr><th>Datum</th><th>Ort</th><th>Betreff</th>"
            "<th>CRM-Stufe</th><th>Verifizierung</th><th>Auftrag</th><th>ID</th></tr>"
            + "".join(rows or ['<tr><td colspan="7">keine</td></tr>'])
            + "</table>"
        )
        return _page("Anfragen", body, active_section="inquiries", context=context)

    def render_auftraege(
        self, q: str = "", *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        needle = q.strip().lower()

        def _matches(*fields: str) -> bool:
            if not needle:
                return True
            return any(needle in f.lower() for f in fields)

        search_box = (
            '<form method="get" action="/auftraege" class="searchbox">'
            f'<input type="text" name="q" value="{_e(q)}" placeholder="Suche: ID, Ort, Datum…">'
            '<button type="submit">Suchen</button>'
            + (' <a href="/auftraege">Zurücksetzen</a>' if q else "")
            + "</form>"
        )

        rows = []
        for o in self._orders.list_orders():
            if not _matches(o.order_id, o.source_inquiry_id):
                continue
            if o.cancelled_at is not None:
                status = '<span class="cancelled">STORNIERT</span>'
                blocker = "–"
            else:
                ev = self.core.evaluate_ready_to_send(o.order_id)
                if ev.ready:
                    status = '<span class="ok">bereit</span>'
                    blocker = "–"
                else:
                    status = '<span class="blocked">blockiert</span>'
                    blocker = (
                        _e(_ready_to_send_blocker_label(ev.reasons[0]))
                        if ev.reasons
                        else "–"
                    )
            eff = (
                "bestätigt" if o.effective_order_version_id else "noch nicht bestätigt"
            )
            rows.append(
                f"<tr><td>{status}</td><td>{blocker}</td>"
                f"<td>{_e(o.source_inquiry_id[:8])}</td><td>{_e(eff)}</td>"
                f'<td><a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a></td></tr>'
            )

        body = (
            search_box + "<table><tr><th>Freigabe</th><th>Blocker</th>"
            "<th>Anfrage</th><th>Bestätigt</th><th>ID</th></tr>"
            + "".join(rows or ['<tr><td colspan="5">keine</td></tr>'])
            + "</table>"
        )
        return _page("Aufträge", body, active_section="orders", context=context)

    _ORDERS_ZEITRAUM_LABELS = (
        ("heute", "Heute"),
        ("woche", "Diese Woche"),
        ("monat", "Dieser Monat"),
        ("", "Alle"),
    )

    def _orders_row_data(self, order: Order) -> dict[str, object]:
        """Operative row facts for one order — repo-shaped reads only."""
        versions = self._orders.list_order_versions(order.order_id)
        target = next(
            (
                v
                for v in versions
                if v.order_version_id == order.candidate_order_version_id
            ),
            None,
        )
        if target is None and versions:
            target = max(versions, key=lambda v: v.version_number)
        inquiry = self._inquiries.get_by_id(order.source_inquiry_id)
        kunde = "–"
        if inquiry is not None:
            kunde = (
                (inquiry.intake_subject or "").strip()
                or inquiry.location_text.strip()
                or order.order_id[:8]
            )
        if order.cancelled_at is not None:
            schritt = "Storniert"
        else:
            action = api_views.resolve_next_action(order, versions)
            if action is not None and action["action"] == "print-confirm":
                schritt = "Küchendruck erforderlich"
            elif action is not None and action["action"] == "effective":
                schritt = "Version wirksam setzen"
            else:
                evaluation = self.core.evaluate_ready_to_send(order.order_id)
                if evaluation.ready:
                    schritt = "Bereit zum Versand"
                else:
                    schritt = (
                        _ready_to_send_blocker_label(evaluation.reasons[0])
                        if evaluation.reasons
                        else "–"
                    )
        return {
            "order_id": order.order_id,
            "event_date": target.event_date if target is not None else None,
            "uhrzeit": target.time_window_text if target is not None else "–",
            "kunde": kunde,
            "gaeste": target.guest_count_estimate if target is not None else None,
            "schritt": schritt,
        }

    @staticmethod
    def _orders_zeitraum_match(
        event_date: date | None, zeitraum: str, today: date
    ) -> bool:
        if not zeitraum:
            return True
        if event_date is None:
            return False
        if zeitraum == "heute":
            return event_date == today
        if zeitraum == "woche":
            return event_date.isocalendar()[:2] == today.isocalendar()[:2]
        if zeitraum == "monat":
            return (event_date.year, event_date.month) == (today.year, today.month)
        return True

    def render_orders(
        self,
        q: str = "",
        zeitraum: str = "",
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str:
        """Alle Aufträge — operative list, deliberately not a CRM table."""
        if zeitraum not in {"", "heute", "woche", "monat"}:
            zeitraum = ""
        today = api_views.berlin_today()
        needle = q.strip().lower()

        rows_data = []
        for order in self._orders.list_orders():
            row = self._orders_row_data(order)
            if not self._orders_zeitraum_match(
                cast("date | None", row["event_date"]), zeitraum, today
            ):
                continue
            if needle and not any(
                needle in str(row[key]).lower()
                for key in ("kunde", "order_id", "uhrzeit")
            ):
                continue
            rows_data.append(row)
        rows_data.sort(
            key=lambda row: (
                cast("date | None", row["event_date"]) or date.max,
                str(row["uhrzeit"]),
                str(row["order_id"]),
            )
        )

        filter_links = "".join(
            f'<a href="/orders?{urlencode({"zeitraum": key, "q": q} if key else {"q": q})}"'
            + (' aria-current="true"' if key == zeitraum else "")
            + f">{_e(label)}</a>"
            for key, label in self._ORDERS_ZEITRAUM_LABELS
        )
        search_box = (
            '<form method="get" action="/orders" class="searchbox">'
            + (
                f'<input type="hidden" name="zeitraum" value="{_e(zeitraum)}">'
                if zeitraum
                else ""
            )
            + f'<input type="text" name="q" value="{_e(q)}" '
            'placeholder="Suche: Kunde / Auftrag">'
            '<button type="submit">Suchen</button>'
            + (
                f' <a href="/orders?{urlencode({"zeitraum": zeitraum})}">Zurücksetzen</a>'
                if q
                else ""
            )
            + "</form>"
        )

        table_rows = []
        for row in rows_data:
            event_date = cast("date | None", row["event_date"])
            datum = event_date.strftime("%d.%m.%Y") if event_date else "–"
            gaeste = f"{row['gaeste']} Gäste" if row["gaeste"] else "–"
            table_rows.append(
                f"<tr><td>{_e(datum)}</td><td>{_e(str(row['uhrzeit']))}</td>"
                f"<td>{_e(str(row['kunde']))}</td><td>{_e(gaeste)}</td>"
                f"<td>{_e(str(row['schritt']))}</td>"
                f'<td><a href="/order/{_e(str(row["order_id"]))}">Öffnen</a></td></tr>'
            )

        body = (
            '<nav class="dashboard-calendar-toggle" aria-label="Zeitraum">'
            + filter_links
            + "</nav>"
            + search_box
            + "<table><tr><th>Datum</th><th>Uhrzeit</th><th>Kunde</th>"
            "<th>Gäste</th><th>Nächster Schritt</th><th>Aktion</th></tr>"
            + "".join(table_rows or ['<tr><td colspan="6">keine Aufträge</td></tr>'])
            + "</table>"
        )
        return _page("Alle Aufträge", body, active_section="orders", context=context)

    # -- inquiries -------------------------------------------------------

    def render_inquiry_form(
        self,
        phone: str = "",
        event_date: str = "",
        guest_count_estimate: str = "",
        intake_subject: str = "",
        intake_message: str = "",
        intake_summary: str = "",
        intake_external_ref: str = "",
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str:
        # Rückruf -> Inquiry hint only (§11 addendum §14): Inquiry has no
        # phone/contact field at all (domain/inquiry.py), so this is never
        # written anywhere — it's page context for the office worker, shown
        # once, not a prefilled form field bound to any Inquiry attribute.
        phone_hint = f'<p class="subtitle">Anruf von: {_e(phone)}</p>' if phone else ""
        if not context.can("inquiries.create"):
            return _page(
                "Neue Anfrage",
                phone_hint
                + '<p class="blocked">Ihre Berechtigung reicht für diese Aktion nicht aus.</p>',
                active_section="inquiries",
                context=context,
            )
        # event_date / guest_count_estimate / intake_*: optional prefill hints.
        body = (
            phone_hint
            + f"""<form method="post" action="/inquiry/new">{_csrf_input(context)}{self._command_fields()}<fieldset>
<p><label>Datum*</label><input type="date" name="event_date" value="{_e(event_date)}" required></p>
<p><label>Zeitfenster</label><input name="time_window_text"></p>
<p><label>Ort</label><input name="location_text"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" inputmode="numeric" value="{_e(guest_count_estimate)}"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(PLANNING_MODES[0])}</p>
<p><label>Rückruf-Verifizierung nötig</label><input type="checkbox" name="call_verification_required" value="1"></p>
<p class="subtitle">Kontaktdaten — für Website/Konfigurator Pflicht, sonst als Blocker sichtbar.</p>
<p><label>E-Mail</label><input type="email" name="contact_email"></p>
<p><label>Telefon</label><input type="tel" name="contact_phone"></p>
<p><label>Name</label><input name="contact_name"></p>
<p><label>Firma</label><input name="company_name"></p>
<p class="subtitle">Intake-Kontext — keine Auftrags-/Küchenfreigabe.</p>
<p><label>Betreff</label><input name="intake_subject" value="{_e(intake_subject)}"></p>
<p><label>Nachricht</label><textarea name="intake_message" rows="4">{_e(intake_message)}</textarea></p>
<p><label>Zusammenfassung</label><textarea name="intake_summary" rows="3">{_e(intake_summary)}</textarea></p>
<p><label>Externe Referenz</label><input name="intake_external_ref" value="{_e(intake_external_ref)}"></p>
<p><button type="submit">Anfrage anlegen</button></p>
</fieldset></form>"""
        )
        return _page("Neue Anfrage", body, active_section="inquiries", context=context)

    def _render_contact_section(self, inq: Inquiry, context: OfficePageContext) -> str:
        """Legacy-UI Kontaktdaten block (INQUIRY_CONTACT_COMPLETENESS_V1 §9)."""
        snapshot = inq.customer_snapshot
        completeness = derive_inquiry_contact_completeness(inq)
        missing = missing_contact_fields(completeness)
        email = (snapshot.email if snapshot is not None else None) or ""
        phone = (snapshot.phone if snapshot is not None else None) or ""
        name = (snapshot.contact_name if snapshot is not None else None) or ""
        company = (snapshot.company_name if snapshot is not None else None) or ""
        rows = (
            f"<tr><th>E-Mail</th><td>{_e(email) if email else '<span class=blocked>fehlt</span>'}</td></tr>"
            f"<tr><th>Telefon</th><td>{_e(phone) if phone else '<span class=blocked>fehlt</span>'}</td></tr>"
        )
        if name:
            rows += f"<tr><th>Name</th><td>{_e(name)}</td></tr>"
        if company:
            rows += f"<tr><th>Firma</th><td>{_e(company)}</td></tr>"
        if completeness == "complete":
            status = '<p class="ok">Kontaktdaten vollständig.</p>'
            form = ""
        else:
            blocker = contact_completeness_blocker_text(completeness) or ""
            status = (
                f'<p class="blocked">{_e(blocker)} — '
                f"{_e(CONTACT_COMPLETION_NEXT_ACTION)}. "
                "Ohne vollständige Kontaktdaten sind Angebot und Auftrag blockiert.</p>"
            )
            form = ""
            if context.can("inquiries.edit"):
                inputs = ""
                if "email" in missing:
                    inputs += '<p><label>E-Mail</label><input type="email" name="contact_email"></p>'
                if "phone" in missing:
                    inputs += '<p><label>Telefon</label><input type="tel" name="contact_phone"></p>'
                form = (
                    f'<form method="post" action="/inquiry/{_e(inq.inquiry_id)}/contact-completion" '
                    'onsubmit="return confirm('
                    "'Fehlende Kontaktdaten werden ergänzt. "
                    "Vorhandene Angaben werden nicht überschrieben.'"
                    ');">'
                    f"{_csrf_input(context)}"
                    f"{self._command_fields({'updated_at': inq.updated_at.isoformat()})}"
                    f"<fieldset>{inputs}"
                    '<p><button type="submit">Kontaktdaten ergänzen</button></p>'
                    "</fieldset></form>"
                )
        return f"<h2>Kontaktdaten</h2>{status}<table>{rows}</table>{form}"

    def create_inquiry(self, form: dict[str, str]) -> Inquiry:
        required = form.get("call_verification_required") == "1"
        return self.inquiry_service.create_inquiry(
            event_date=date.fromisoformat(form["event_date"]),
            inquiry_source="phone_by_office",
            crm_stage=CRM_PIPELINE[0],
            customer_linkage={},
            time_window_text=form.get("time_window_text", ""),
            location_text=form.get("location_text", ""),
            guest_count_estimate=_opt_int(form.get("guest_count_estimate", "")),
            planning_mode=form.get("planning_mode", PLANNING_MODES[0]),
            call_verification_required=required,
            call_verification_status="pending" if required else "not_required",
            intake_subject=form.get("intake_subject", ""),
            intake_message=form.get("intake_message", ""),
            intake_summary=form.get("intake_summary", ""),
            intake_external_ref=form.get("intake_external_ref", ""),
            contact_email=_opt_contact(form, "contact_email"),
            contact_phone=_opt_contact(form, "contact_phone"),
            contact_name=_opt_contact(form, "contact_name"),
            company_name=_opt_contact(form, "company_name"),
        )

    def complete_inquiry_contacts(
        self, inquiry_id: str, form: dict[str, str]
    ) -> Inquiry:
        """Append-only contact completion — only missing fields may be filled."""
        email = _opt_contact(form, "contact_email")
        phone = _opt_contact(form, "contact_phone")
        return self.inquiry_service.complete_inquiry_contact_information(
            inquiry_id,
            email=email,
            phone=phone,
        )

    def set_inquiry_customer_addresses(
        self, inquiry_id: str, form: dict[str, str]
    ) -> Inquiry:
        """Persist Rechnungs-/Lieferadresse via customer-addresses write path."""
        mode = form.get("delivery_address_mode", "").strip()
        invoice = canonicalize_customer_address(
            CustomerAddress(
                street=_opt_contact(form, "invoice_street"),
                postal_code=_opt_contact(form, "invoice_postal_code"),
                city=_opt_contact(form, "invoice_city"),
                country=_opt_contact(form, "invoice_country"),
            )
        )
        delivery = canonicalize_customer_address(
            CustomerAddress(
                street=_opt_contact(form, "delivery_street"),
                postal_code=_opt_contact(form, "delivery_postal_code"),
                city=_opt_contact(form, "delivery_city"),
                country=_opt_contact(form, "delivery_country"),
            )
        )
        return self.inquiry_service.set_inquiry_customer_addresses(
            inquiry_id,
            invoice_address=invoice,
            delivery_address=delivery,
            delivery_address_mode=mode,
        )

    def set_inquiry_fulfillment_mode(
        self, inquiry_id: str, form: dict[str, str]
    ) -> Inquiry:
        """Persist Auftragsart (Lieferung/Abholung) — never inferred, only set."""
        mode = form.get("fulfillment_mode", "").strip()
        return self.inquiry_service.set_inquiry_fulfillment_mode(
            inquiry_id,
            fulfillment_mode=mode,
        )

    def render_inquiry(
        self,
        inquiry_id: str,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str | None:
        inq = self._inquiries.get_by_id(inquiry_id)
        if inq is None:
            return None
        inquiry_truncation_warning = ""
        linked_orders_total_count: int | None = None
        linked_orders_truncated = False
        if self._remote is not None:
            linked_orders_total_count, linked_orders_truncated = (
                self._remote.inquiry_orders_meta(inquiry_id)
            )
            if linked_orders_truncated:
                inquiry_truncation_warning = (
                    '<p class="blocked"><strong>Unvollständige Ansicht:</strong> '
                    f"Die API-Detailansicht enthält nicht alle "
                    f"{linked_orders_total_count} "
                    "verknüpften Aufträge.</p>"
                )
        existing = [
            o for o in self._orders.list_orders() if o.source_inquiry_id == inquiry_id
        ]
        has_active_order = any(order.cancelled_at is None for order in existing)
        state = self._inquiry_office_state(
            inq,
            existing,
            inquiry_id=inquiry_id,
        )
        ev = self.progression.evaluate_inquiry_to_order_progression(inq)
        if self._ui_version == "v2":
            offer_url = (
                self._build_first_offer_url(inq, context)
                if self.configurator_url and state.next_action == "prepare-offer"
                else None
            )
            detail = render_inquiry_detail(
                inq,
                existing,
                state,
                state.offer_preparation_blockers,
                forms=InquiryDetailFormFields(
                    csrf_input=_csrf_input(context),
                    primary_command_fields=(
                        self._command_fields()
                        if state.next_action == "verify"
                        or inquiry_shows_convert_accepted_button(state)
                        else ""
                    ),
                    update_command_fields=self._command_fields(
                        {"updated_at": inq.updated_at.isoformat()}
                    ),
                    contact_completion_command_fields=self._command_fields(
                        {"updated_at": inq.updated_at.isoformat()}
                    ),
                ),
                linked_orders_total_count=linked_orders_total_count,
                linked_orders_truncated=linked_orders_truncated,
                offer_url=offer_url,
                context=context,
            )
            return _page(
                detail.title,
                detail.body,
                active_section="inquiries",
                context=context,
                show_title=False,
            )
        if has_active_order:
            prog = '<p class="ok">Bereits in Auftrag umgewandelt.</p>'
        elif existing and state.next_action == "prepare-offer":
            prog = (
                '<p class="ok">Der historische Auftrag ist storniert. '
                "Ein Angebot kann vorbereitet werden.</p>"
            )
        elif ev.blocked:
            reasons = "".join(
                f"<li>{_e(_progression_blocker_label(r))}</li>" for r in ev.reasons
            )
            prog = f'<p class="blocked">Konvertierung blockiert:</p><ul>{reasons}</ul>'
        else:
            prog = '<p class="ok">Angebot kann vorbereitet werden.</p>'
        verify_btn = ""
        if state.next_action == "verify" and context.can("inquiries.verify"):
            verify_btn = (
                f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/verify">'
                f"{_csrf_input(context)}{self._command_fields()}"
                "<button>Telefonisch verifiziert</button></form> "
            )
        convert = ""
        if existing:
            links = ", ".join(
                f'<a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a>'
                + (" (storniert)" if o.cancelled_at is not None else "")
                for o in existing
            )
            convert += (
                f"<p>Auftrag vorhanden: {links} — "
                f'<a href="/order/{_e(existing[0].order_id)}">Auftrag öffnen</a></p>'
            )
        if state.next_action == "prepare-offer":
            convert += '<p class="muted">Auftrag nur aus angenommenem Angebot.</p>'
        elif state.next_action == "prepare-next-version":
            convert += '<p class="muted">Neue Angebotsversion vorbereiten.</p>'
        elif state.next_action == "offer-pending":
            convert += '<p class="muted">Angebot ausstehend</p>'
        elif state.next_action == "convert-accepted":
            if state.offer is not None and state.offer.commercial_state == "Converted":
                convert += (
                    '<p class="muted">Auftrag bereits erstellt — '
                    "verknüpften Auftrag unten öffnen.</p>"
                )
            elif (
                inquiry_shows_convert_accepted_button(state)
                and context.can("offers.view")
                and context.can("orders.version.create")
            ):
                convert += (
                    f'<form class="inline" method="post" '
                    f'action="/inquiry/{_e(inquiry_id)}/convert-accepted" '
                    'onsubmit="return confirm('
                    "'Dieses angenommene Angebot wird jetzt in einen Auftrag umgewandelt.'"
                    ');">'
                    f"{_csrf_input(context)}{self._command_fields()}"
                    "<button>Angenommenes Angebot in Auftrag überführen</button>"
                    "</form>"
                )
        guests = (
            str(inq.guest_count_estimate)
            if inq.guest_count_estimate is not None
            else ""
        )
        # Intake context: only shown as table rows when present, so an old
        # Inquiry from before this pack doesn't grow four "–" rows for
        # nothing (INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1 §6).
        intake_rows = "".join(
            f"<tr><th>{label}</th><td>{_e(value)}</td></tr>"
            for label, value in (
                ("Betreff", inq.intake_subject),
                ("Nachricht", inq.intake_message),
                ("Zusammenfassung", inq.intake_summary),
                ("Externe Referenz", inq.intake_external_ref),
            )
            if value
        )
        offer_prefill = ""
        if state.offer is not None:
            offer_prefill = (
                "<h2>Angebot</h2>"
                f'<p><a href="/offer/{_e(state.offer.offer_id)}"><strong>'
                "Angebot öffnen →</strong></a></p>"
            )
        elif self.configurator_url and state.next_action == "prepare-offer":
            offer_url = self._build_first_offer_url(inq, context)
            offer_prefill = (
                "<h2>Angebot</h2>"
                f'<p><a href="{_e(offer_url)}"><strong>Angebot mit '
                "Anfragedaten vorbereiten →</strong></a></p>"
                '<p class="subtitle">Füllt nur einen bearbeitbaren '
                "Angebotsentwurf vor. Kein Auftrag, keine Freigabe und keine "
                "Nachricht an den Kunden.</p>"
            )
        elif state.next_action == "prepare-offer":
            offer_prefill = (
                "<h2>Angebot</h2>"
                '<p class="blocked">Der Angebotskonfigurator ist derzeit '
                "nicht verfügbar.</p>"
            )
        crm_stage_field = (
            f'{_e(ACTIVE_ORDER_CRM_STAGE)}<input type="hidden" name="crm_stage" '
            f'value="{_e(ACTIVE_ORDER_CRM_STAGE)}">'
            if has_active_order
            else _crm_stage_select(inq.crm_stage)
        )
        contact_section = self._render_contact_section(inq, context)
        update_form = ""
        if context.can("inquiries.edit"):
            update_form = f"""<h2>Anfrage bearbeiten</h2>
<form method="post" action="/inquiry/{_e(inquiry_id)}/update">{_csrf_input(context)}{self._command_fields({"updated_at": inq.updated_at.isoformat()})}<fieldset>
<p><label>Datum</label><input type="date" name="event_date" value="{_e(inq.event_date.isoformat())}"></p>
<p><label>Zeitfenster</label><input name="time_window_text" value="{_e(inq.time_window_text)}"></p>
<p><label>Ort</label><input name="location_text" value="{_e(inq.location_text)}"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" value="{_e(guests)}"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(inq.planning_mode)}</p>
<p><label>CRM-Stufe</label>{crm_stage_field}</p>
<p class="subtitle">Intake-Kontext — keine Auftrags-/Küchenfreigabe.</p>
<p><label>Betreff</label><input name="intake_subject" value="{_e(inq.intake_subject or "")}"></p>
<p><label>Nachricht</label><textarea name="intake_message" rows="4">{_e(inq.intake_message or "")}</textarea></p>
<p><label>Zusammenfassung</label><textarea name="intake_summary" rows="3">{_e(inq.intake_summary or "")}</textarea></p>
<p><label>Externe Referenz</label><input name="intake_external_ref" value="{_e(inq.intake_external_ref or "")}"></p>
<p><button type="submit">Speichern</button></p>
</fieldset></form>"""
        body = (
            inquiry_truncation_warning
            + f"""<table>
<tr><th>Datum</th><td>{_e(inq.event_date.isoformat())}</td></tr>
<tr><th>Zeitfenster</th><td>{_e(inq.time_window_text)}</td></tr>
<tr><th>Ort</th><td>{_e(inq.location_text)}</td></tr>
<tr><th>Gäste</th><td>{_e(guests or "–")}</td></tr>
<tr><th>CRM-Stufe</th><td>{_e(inq.crm_stage)}</td></tr>
<tr><th>Verifizierung</th><td>{_e(_verification_label(inq.call_verification_status))}</td></tr>
{intake_rows}</table>
{contact_section}
<h2>Vorgangsprüfung (Progression)</h2>{prog}
<p>{verify_btn}{convert}</p>
{offer_prefill}
{update_form}"""
        )
        return _page(
            f"Anfrage {inq.inquiry_id[:8]}",
            body,
            active_section="inquiries",
            context=context,
        )

    def update_inquiry(self, inquiry_id: str, form: dict[str, str]) -> None:
        crm_stage = validate_crm_stage(form.get("crm_stage", CRM_PIPELINE[0]))
        has_active_order = any(
            order.source_inquiry_id == inquiry_id and order.cancelled_at is None
            for order in self._orders.list_orders()
        )
        if (
            self._remote is None
            and has_active_order
            and not inquiry_crm_stage_is_compatible_with_active_order(crm_stage)
        ):
            raise ValueError("active order requires Bestätigt / Auftrag CRM stage")
        self.inquiry_service.update_inquiry(
            inquiry_id,
            event_date=date.fromisoformat(form["event_date"]),
            time_window_text=form.get("time_window_text", ""),
            location_text=form.get("location_text", ""),
            guest_count_estimate=_opt_int(form.get("guest_count_estimate", "")),
            planning_mode=form.get("planning_mode", PLANNING_MODES[0]),
            crm_stage=crm_stage,
            intake_subject=form.get("intake_subject", ""),
            intake_message=form.get("intake_message", ""),
            intake_summary=form.get("intake_summary", ""),
            intake_external_ref=form.get("intake_external_ref", ""),
        )

    def convert_inquiry_to_order(self, inquiry_id: str) -> tuple[Order, OrderVersion]:
        """Compatibility lookup: return linked Order or refuse create.

        Remote mode delegates to Core Office API (same hard-block contract).
        """

        def work() -> tuple[Order, OrderVersion]:
            inquiry = self._inquiries.get_by_id(inquiry_id)
            if inquiry is None:
                raise KeyError(inquiry_id)
            return self.order_service.convert_inquiry_to_order(inquiry)

        if self._remote is not None:
            inquiry = self._inquiries.get_by_id(inquiry_id)
            if inquiry is None:
                raise KeyError(inquiry_id)
            return self.order_service.convert_inquiry_to_order(inquiry)
        if self._command_executor is not None:
            return self._command_executor.run(work)
        return work()

    def convert_accepted_offer_for_inquiry(
        self, inquiry_id: str
    ) -> tuple[Order, OrderVersion]:
        """Run the accepted-offer conversion through the existing Core command path."""

        def work() -> tuple[Order, OrderVersion]:
            inquiry = self._inquiries.get_by_id(inquiry_id)
            if inquiry is None:
                raise KeyError(inquiry_id)
            linked_orders = [
                order
                for order in self._orders.list_orders()
                if order.source_inquiry_id == inquiry_id
            ]
            state = self._inquiry_office_state(
                inquiry,
                linked_orders,
                inquiry_id=inquiry_id,
            )
            if not inquiry_allows_convert_accepted_command(state):
                offer = self._offers.get_by_source_inquiry_id(inquiry_id)
                link = offer.conversion_link if offer is not None else None
                if link is not None:
                    order = self._orders.get_order(link.order_id)
                    versions = self._orders.list_order_versions(link.order_id)
                    order_version = next(
                        (item for item in versions if item.version_number == 1),
                        None,
                    )
                    if order is not None and order_version is not None:
                        return order, order_version
                raise ValueError("accepted offer conversion gate is not satisfied")
            assert state.offer is not None
            projection = state.offer
            if (
                projection.accepted_variant_id is None
                or projection.acceptance_id is None
            ):
                raise ValueError("accepted offer conversion gate is not satisfied")
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                self._commercial_snapshots,
                today=api_views.berlin_today,
            )
            converted, order, order_version = offer_service.convert_accepted_offer(
                projection.offer_id,
                projection.offer_version_id,
                projection.accepted_variant_id,
                projection.acceptance_id,
            )
            commercial_version = next(
                item
                for item in converted.versions
                if item.offer_version_id == projection.offer_version_id
            )
            self.payment_reminder_service.seed_from_conversion(
                order.order_id,
                commercial_version.payment_method,
            )
            self.inquiry_service.update_inquiry(
                inquiry_id,
                crm_stage=ACTIVE_ORDER_CRM_STAGE,
            )
            return order, order_version

        if self._remote is not None:
            inquiry = self._inquiries.get_by_id(inquiry_id)
            if inquiry is None:
                raise KeyError(inquiry_id)
            linked_orders = [
                order
                for order in self._orders.list_orders()
                if order.source_inquiry_id == inquiry_id
            ]
            state = self._inquiry_office_state(
                inquiry,
                linked_orders,
                inquiry_id=inquiry_id,
            )
            if not inquiry_allows_convert_accepted_command(state):
                offer = self._offers.get_by_source_inquiry_id(inquiry_id)
                link = offer.conversion_link if offer is not None else None
                if link is not None:
                    order = self._orders.get_order(link.order_id)
                    versions = self._orders.list_order_versions(link.order_id)
                    order_version = next(
                        (item for item in versions if item.version_number == 1),
                        None,
                    )
                    if order is not None and order_version is not None:
                        return order, order_version
                raise ValueError("accepted offer conversion gate is not satisfied")
            assert state.offer is not None
            projection = state.offer
            if (
                projection.accepted_variant_id is None
                or projection.acceptance_id is None
            ):
                raise ValueError("accepted offer conversion gate is not satisfied")
            order_id, order_version_id = self._remote.convert_accepted_offer(
                projection.offer_id,
                projection.offer_version_id,
                accepted_variant_id=projection.accepted_variant_id,
                acceptance_id=projection.acceptance_id,
            )
            order = self._orders.get_order(order_id)
            order_version = self._orders.get_order_version(order_version_id)
            if order is None or order_version is None:
                raise ValueError("accepted offer conversion response incomplete")
            return order, order_version
        if self._command_executor is not None:
            return self._command_executor.run(work)
        return work()

    # -- orders ----------------------------------------------------------

    def render_order(
        self,
        order_id: str,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str | None:
        order = self._orders.get_order(order_id)
        if order is None:
            return None
        versions = self._orders.list_order_versions(order_id)
        versions_total_count = len(versions)
        versions_truncated = False
        if self._remote is not None:
            versions_total_count, versions_truncated = self._remote.order_versions_meta(
                order_id
            )
        cancelled = order.cancelled_at is not None
        pause_view = self._operational_pause_view(order_id)
        ev = self.core.evaluate_ready_to_send(order_id)
        payment = self.payment_reminder_service.view(order_id)
        confirmation = self.confirmation_document_service.eligibility(order_id)
        live_preview = self._live_confirmation_preview(order_id)
        source_inquiry = self._inquiries.get_by_id(order.source_inquiry_id)
        snapshot_id = (
            confirmation.snapshot.document_snapshot_id
            if confirmation.snapshot is not None
            else None
        )
        outbound = self.confirmation_outbound_service.send_eligibility(
            order_id,
            document_snapshot_id=snapshot_id,
        )
        if self._ui_version == "v2":
            print_confirm_fields: dict[str, str] = {}
            print_confirm_labels: dict[str, str] = {}
            effective_fields: dict[str, str] = {}
            target = next(
                (
                    version
                    for version in versions
                    if version.order_version_id == order.candidate_order_version_id
                ),
                None,
            )
            if target is None:
                target = max(
                    versions, key=lambda item: item.version_number, default=None
                )
            if not cancelled:
                for version in versions:
                    if (
                        target is not None
                        and version.order_version_id == target.order_version_id
                        and version.kitchen_print_confirmed_at is None
                        and context.can("orders.print.confirm")
                    ):
                        print_confirm_fields[version.order_version_id] = (
                            self._command_fields()
                        )
                        print_confirm_labels[version.order_version_id] = (
                            self._kitchen_print_action_label(version.order_version_id)
                        )
                    if (
                        target is not None
                        and version.order_version_id == target.order_version_id
                        and version.kitchen_print_confirmed_at is not None
                        and version.order_version_id != order.effective_order_version_id
                        and context.can("orders.effective.set")
                    ):
                        effective_fields[version.order_version_id] = (
                            self._command_fields(
                                {
                                    "effective_version_id": (
                                        order.effective_order_version_id or ""
                                    ),
                                    "candidate_version_id": (
                                        order.candidate_order_version_id or ""
                                    ),
                                }
                            )
                        )
            latest_version_number = versions_total_count or max(
                (version.version_number for version in versions), default=0
            )
            change_prefill = version_change_prefill(
                order,
                versions,
                latest_version_number=latest_version_number,
            )
            detail = render_order_detail(
                order,
                versions,
                ev,
                payment,
                api_views.resolve_next_action(order, versions),
                forms=OrderDetailFormFields(
                    csrf_input=_csrf_input(context),
                    print_confirm_command_fields=print_confirm_fields,
                    effective_command_fields=effective_fields,
                    ready_command_fields=(
                        self._command_fields()
                        if not cancelled and context.can("orders.ready.release")
                        else ""
                    ),
                    cancel_command_fields=(
                        self._command_fields(
                            {"updated_at": order.updated_at.isoformat()}
                        )
                        if not cancelled and context.can("orders.cancel")
                        else ""
                    ),
                    version_command_fields=(
                        self._command_fields(
                            {
                                "latest_version_number": str(latest_version_number),
                                "current_effective_order_version_id": (
                                    order.effective_order_version_id or ""
                                ),
                                "current_candidate_order_version_id": (
                                    order.candidate_order_version_id or ""
                                ),
                            }
                        )
                        if not cancelled and context.can("orders.version.create")
                        else ""
                    ),
                    payment_command_fields=(
                        self._command_fields(
                            {
                                "payment_reminder_updated_at": (
                                    payment.updated_at.isoformat()
                                    if payment.updated_at
                                    else ""
                                )
                            }
                        )
                        if not cancelled and context.can("orders.payment.reminder")
                        else ""
                    ),
                    confirmation_command_fields=(
                        self._command_fields(
                            {
                                "current_effective_order_version_id": (
                                    order.effective_order_version_id or ""
                                ),
                            }
                        )
                        if not cancelled
                        else ""
                    ),
                    send_command_fields=(
                        self._command_fields(
                            {
                                "current_effective_order_version_id": (
                                    order.effective_order_version_id or ""
                                ),
                            }
                        )
                        if not cancelled
                        else ""
                    ),
                    pause_command_fields=(
                        self._command_fields(self._pause_expect_fields(pause_view))
                        if (
                            not cancelled
                            and not pause_view.get("active")
                            and context.can("orders.pause")
                        )
                        else ""
                    ),
                    resume_command_fields=(
                        self._command_fields(self._resume_expect_fields(pause_view))
                        if (
                            not cancelled
                            and pause_view.get("active")
                            and context.can("orders.pause")
                        )
                        else ""
                    ),
                    customer_addresses_command_fields=(
                        self._command_fields(
                            {
                                "updated_at": source_inquiry.updated_at.isoformat(),
                            }
                        )
                        if not cancelled and source_inquiry is not None
                        else ""
                    ),
                    fulfillment_mode_command_fields=(
                        self._command_fields(
                            {
                                "updated_at": source_inquiry.updated_at.isoformat(),
                            }
                        )
                        if not cancelled and source_inquiry is not None
                        else ""
                    ),
                    version_change_prefill=change_prefill if not cancelled else None,
                    print_confirm_button_labels=print_confirm_labels,
                ),
                confirmation=confirmation,
                live_preview=live_preview,
                outbound=outbound,
                source_inquiry=source_inquiry,
                operational_pause=pause_view,
                versions_total_count=versions_total_count,
                versions_truncated=versions_truncated,
                context=context,
            )
            return _page(
                detail.title,
                detail.body,
                active_section="orders",
                context=context,
                show_title=False,
            )
        rows = []
        for v in versions:
            printed = (
                v.kitchen_print_confirmed_at.isoformat()
                if v.kitchen_print_confirmed_at
                else "–"
            )
            marks = []
            if v.order_version_id == order.effective_order_version_id:
                marks.append("wirksam")
            if v.order_version_id == order.candidate_order_version_id:
                marks.append("Kandidat")
            actions = [
                f'<a href="/order/{_e(order_id)}/print?version={_e(v.order_version_id)}">Küchenzettel</a>',
                f'<a href="/order/{_e(order_id)}/buffet-cards?version={_e(v.order_version_id)}">Buffetschilder</a>',
            ]
            action_target = next(
                (
                    version
                    for version in versions
                    if version.order_version_id == order.candidate_order_version_id
                ),
                None,
            )
            if action_target is None:
                action_target = max(
                    versions, key=lambda item: item.version_number, default=None
                )
            if not cancelled:
                if (
                    v.kitchen_print_confirmed_at is None
                    and action_target is not None
                    and v.order_version_id == action_target.order_version_id
                    and context.can("orders.print.confirm")
                ):
                    button_label = self._kitchen_print_action_label(v.order_version_id)
                    actions.append(
                        f'<form class="inline" method="post" action="/order/{_e(order_id)}/print-confirm">'
                        f"{_csrf_input(context)}{self._command_fields()}"
                        f'<input type="hidden" name="order_version_id" value="{_e(v.order_version_id)}">'
                        f"<button>{_e(button_label)}</button></form>"
                    )
                if (
                    v.kitchen_print_confirmed_at is not None
                    and v.order_version_id != order.effective_order_version_id
                    and action_target is not None
                    and v.order_version_id == action_target.order_version_id
                    and context.can("orders.effective.set")
                ):
                    actions.append(
                        f'<form class="inline" method="post" action="/order/{_e(order_id)}/effective">'
                        f"{_csrf_input(context)}"
                        f"{self._command_fields({'effective_version_id': order.effective_order_version_id or '', 'candidate_version_id': order.candidate_order_version_id or ''})}"
                        f'<input type="hidden" name="order_version_id" value="{_e(v.order_version_id)}">'
                        "<button>Wirksam machen</button></form>"
                    )
            rows.append(
                f"<tr><td>v{v.version_number}</td><td>{_e(v.event_date.isoformat())}</td>"
                f"<td>{_e(v.time_window_text)}</td><td>{_e(v.location_text)}</td>"
                f"<td>{_e(str(v.guest_count_estimate) if v.guest_count_estimate is not None else '–')}</td>"
                f"<td>{_e(printed)}</td><td>{_e(', '.join(marks) or '–')}</td>"
                f"<td>{' '.join(actions)}</td></tr>"
            )
        if ev.ready:
            release = '<p class="ok">READY_TO_SEND: bereit.</p>'
        else:
            reasons = "".join(
                f"<li>{_e(_ready_to_send_blocker_label(r))}</li>" for r in ev.reasons
            )
            release = (
                f'<p class="blocked">Versandfreigabe blockiert:</p><ul>{reasons}</ul>'
            )
        payment_rows = [
            f"<p><strong>Zahlungsart:</strong> {_e(payment.payment_method_label)}</p>"
        ]
        if payment.invoice_state_label is not None:
            payment_rows.append(
                f"<p><strong>Rechnung:</strong> {_e(payment.invoice_state_label)}</p>"
            )
        if payment.invoice_number:
            payment_rows.append(
                f"<p><strong>Rechnungsnummer:</strong> {_e(payment.invoice_number)}</p>"
            )
        for label, value in (
            ("Versendet am", payment.sent_on),
            ("Fällig am", payment.due_on),
            ("Bezahlt am", payment.paid_on),
        ):
            if value is not None:
                payment_rows.append(
                    f"<p><strong>{label}:</strong> {_e(value.isoformat())}</p>"
                )
        payment_rows.append(
            f"<p><strong>Zahlungsstatus:</strong> {_e(payment.payment_state_label)}</p>"
        )
        if payment.next_step:
            payment_rows.append(
                f"<p><strong>Nächster Schritt:</strong> {_e(payment.next_step)}</p>"
            )
        payment_form = ""
        if not cancelled and context.can("orders.payment.reminder"):
            options = ['<option value="">Bitte wählen</option>']
            for method in PAYMENT_METHODS:
                selected = " selected" if payment.payment_method == method else ""
                options.append(
                    f'<option value="{method}"{selected}>'
                    f"{_e(PAYMENT_METHOD_LABELS[method])}</option>"
                )
            expect = {
                "payment_reminder_updated_at": (
                    payment.updated_at.isoformat() if payment.updated_at else ""
                )
            }
            payment_form = f"""
<form method="post" action="/order/{_e(order_id)}/payment-reminder">{_csrf_input(context)}{self._command_fields(expect)}<fieldset>
<p><label>Zahlungsart*</label><select name="payment_method" required>{"".join(options)}</select></p>
<p><label><input type="checkbox" name="invoice_created" value="1"{" checked" if payment.invoice_created else ""}> Rechnung in der Buchhaltung erstellt</label></p>
<p><label>Rechnungsnummer</label><input name="invoice_number" maxlength="200" value="{_e(payment.invoice_number or "")}"></p>
<p><label>Versendet am</label><input type="date" name="sent_on" value="{payment.sent_on.isoformat() if payment.sent_on else ""}"></p>
<p><label>Fällig am</label><input type="date" name="due_on" value="{payment.due_on.isoformat() if payment.due_on else ""}"></p>
<p><label>Bezahlt am</label><input type="date" name="paid_on" value="{payment.paid_on.isoformat() if payment.paid_on else ""}"></p>
<p><label><input type="checkbox" name="cash_received" value="1"{" checked" if payment.cash_received else ""}> Barzahlung erhalten</label></p>
<p><button type="submit">Zahlungshinweis speichern</button></p>
</fieldset></form>"""
        header = '<p class="cancelled">STORNIERT</p>' if cancelled else ""
        actions_block = ""
        if not cancelled:
            latest_version_number = versions_total_count or max(
                (v.version_number for v in versions), default=0
            )
            prefill = version_change_prefill(
                order,
                versions,
                latest_version_number=latest_version_number,
            )
            assert prefill is not None
            action_parts: list[str] = []
            inline_forms: list[str] = []
            if context.can("orders.ready.release"):
                inline_forms.append(
                    f'<form class="inline" method="post" action="/order/{_e(order_id)}/ready">'
                    f"{_csrf_input(context)}{self._command_fields()}"
                    "<button>Freigabe anfordern</button></form>"
                )
            if context.can("orders.cancel"):
                inline_forms.append(
                    f'<form class="inline" method="post" action="/order/{_e(order_id)}/cancel">'
                    f"{_csrf_input(context)}{self._command_fields({'updated_at': order.updated_at.isoformat()})}"
                    "<button>Auftrag stornieren</button></form>"
                )
            if inline_forms:
                action_parts.append(f"<p>{''.join(inline_forms)}</p>")
            if context.can("orders.version.create"):
                action_parts.append(
                    f"""<h2>Neue Version</h2>
<form method="post" action="/order/{_e(order_id)}/version">{_csrf_input(context)}{self._command_fields({"latest_version_number": str(latest_version_number), "current_effective_order_version_id": order.effective_order_version_id or "", "current_candidate_order_version_id": order.candidate_order_version_id or ""})}<input type="hidden" name="latest_version_number" value="{_e(prefill.latest_version_number)}"><fieldset>
<p><label>Datum*</label><input type="date" name="event_date" required value="{_e(prefill.event_date)}"></p>
<p><label>Zeitfenster</label><input name="time_window_text" value="{_e(prefill.time_window_text)}"></p>
<p><label>Ort</label><input name="location_text" value="{_e(prefill.location_text)}"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" inputmode="numeric" value="{_e(prefill.guest_count_estimate)}"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(prefill.planning_mode)}</p>
<p>Die Änderung wird erst nach Küchendruck und Bestätigung wirksam.</p>
<p><label>Änderungsgrund*</label><textarea name="change_reason" maxlength="1000" required></textarea></p>
<p><button type="submit">Version anlegen</button></p>
</fieldset></form>"""
                )
            actions_block = "".join(action_parts)
        truncation_warning = (
            '<p class="blocked"><strong>Unvollständige Ansicht:</strong> '
            f"Es werden {len(versions)} von {versions_total_count} Versionen "
            "angezeigt.</p>"
            if versions_truncated
            else ""
        )
        detail_forms = OrderDetailFormFields(
            csrf_input=_csrf_input(context),
            print_confirm_command_fields={},
            effective_command_fields={},
            ready_command_fields="",
            cancel_command_fields="",
            version_command_fields="",
            payment_command_fields="",
            confirmation_command_fields=(
                self._command_fields(
                    {
                        "current_effective_order_version_id": (
                            order.effective_order_version_id or ""
                        ),
                    }
                )
                if not cancelled
                else ""
            ),
            send_command_fields=(
                self._command_fields(
                    {
                        "current_effective_order_version_id": (
                            order.effective_order_version_id or ""
                        ),
                    }
                )
                if not cancelled
                else ""
            ),
            pause_command_fields=(
                self._command_fields(self._pause_expect_fields(pause_view))
                if (
                    not cancelled
                    and not pause_view.get("active")
                    and context.can("orders.pause")
                )
                else ""
            ),
            resume_command_fields=(
                self._command_fields(self._resume_expect_fields(pause_view))
                if (
                    not cancelled
                    and pause_view.get("active")
                    and context.can("orders.pause")
                )
                else ""
            ),
            customer_addresses_command_fields=(
                self._command_fields(
                    {
                        "updated_at": source_inquiry.updated_at.isoformat(),
                    }
                )
                if not cancelled and source_inquiry is not None
                else ""
            ),
            fulfillment_mode_command_fields=(
                self._command_fields(
                    {
                        "updated_at": source_inquiry.updated_at.isoformat(),
                    }
                )
                if not cancelled and source_inquiry is not None
                else ""
            ),
        )
        fulfillment_card = render_fulfillment_mode_card(
            source_inquiry,
            order,
            detail_forms,
            context=context,
        )
        addresses_card = render_customer_addresses_card(
            source_inquiry,
            order,
            detail_forms,
            context=context,
        )
        confirmation_card = render_confirmation_card(
            order,
            confirmation,
            detail_forms,
            live_preview,
            context=context,
        )
        outbound_card = render_confirmation_outbound_card(
            order,
            confirmation,
            outbound,
            detail_forms,
            operational_pause=pause_view,
            context=context,
        )
        pause_card = render_operational_pause_card(
            order, pause_view, detail_forms, context=context
        )
        paused_header = (
            '<p class="blocked"><strong>Auftrag pausiert</strong></p>'
            if pause_view.get("active")
            else ""
        )
        body = f"""{header}{paused_header}{truncation_warning}
<p>Anfrage: <a href="/inquiry/{_e(order.source_inquiry_id)}">{_e(order.source_inquiry_id[:8])}</a></p>
<h2>Versionen</h2>
<table><tr><th>Nr</th><th>Datum</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th>
<th>Druck bestätigt</th><th>Status</th><th>Aktionen</th></tr>{"".join(rows)}</table>
<h2>Zahlung</h2>{"".join(payment_rows)}{payment_form}
{fulfillment_card}
{addresses_card}
{confirmation_card}
{outbound_card}
{pause_card}
<h2>Freigabe (READY_TO_SEND)</h2>{release}
{actions_block}"""
        return _page(
            f"Auftrag {order.order_id[:8]}",
            body,
            active_section="orders",
            context=context,
        )

    def save_payment_reminder(self, order_id: str, form: dict[str, str]) -> None:
        def optional_date(name: str) -> date | None:
            raw = form.get(name, "").strip()
            return date.fromisoformat(raw) if raw else None

        reminder = OrderPaymentReminder(
            order_id=order_id,
            payment_method=validate_payment_method(form.get("payment_method", "")),
            invoice_created=form.get("invoice_created") == "1",
            invoice_number=form.get("invoice_number", "").strip() or None,
            sent_on=optional_date("sent_on"),
            due_on=optional_date("due_on"),
            paid_on=optional_date("paid_on"),
            cash_received=form.get("cash_received") == "1",
        )

        def work() -> None:
            self.payment_reminder_service.save(reminder)

        if self._remote is not None:
            work()
        elif self._command_executor is not None:
            self._command_executor.run(work)
        else:
            work()

    def send_confirmation_test(self, order_id: str, form: dict[str, str]) -> None:
        order = self._orders.get_order(order_id)
        if order is None or order.cancelled_at is not None:
            raise ValueError(f"no active order with id {order_id!r}")
        expected = form.get("_expect_current_effective_order_version_id")
        if (
            expected is not None
            and (expected or None) != order.effective_order_version_id
        ):
            raise ValueError(
                "Der Auftrag wurde zwischenzeitlich geändert. "
                "Bitte laden Sie die Seite neu."
            )
        document_snapshot_id = form.get("document_snapshot_id", "").strip()
        if not document_snapshot_id:
            raise ValueError("document snapshot is required for test send")
        effective_version_id = order.effective_order_version_id
        assert effective_version_id is not None

        def work() -> None:
            try:
                self.confirmation_outbound_service.send_to_fake_outbox(
                    order_id,
                    document_snapshot_id,
                    effective_version_id,
                    "office-panel",
                )
            except OrderConfirmationOutboundAlreadySentError:
                return

        if self._remote is not None:
            work()
        elif self._command_executor is not None:
            self._command_executor.run(work)
        else:
            work()

    def _live_confirmation_preview(self, order_id: str) -> ConfirmationLivePreviewView:
        """Load live CDP preview for create-gate diagnostics (V1-E)."""
        from catering_system.ui.remote_core_client import RemoteCoreError

        try:
            preview = self.customer_document_preview_service.preview_order_confirmation(
                order_id
            )
        except CustomerDocumentPreviewNotFoundError:
            return ConfirmationLivePreviewView(state="not_found")
        except RemoteCoreError as exc:
            if exc.status == 404:
                return ConfirmationLivePreviewView(state="not_found")
            if exc.code == "invalid_response":
                return ConfirmationLivePreviewView(state="parse_error")
            return ConfirmationLivePreviewView(state="unavailable")
        return ConfirmationLivePreviewView(state="ready", preview=preview)

    def prepare_confirmation_document(
        self, order_id: str, form: dict[str, str]
    ) -> None:
        from catering_system.domain.customer_document_eligibility import (
            CustomerDocumentCreationBlocked,
        )

        order = self._orders.get_order(order_id)
        if order is None or order.cancelled_at is not None:
            raise ValueError(f"no active order with id {order_id!r}")
        expected = form.get("_expect_current_effective_order_version_id")
        if (
            expected is not None
            and (expected or None) != order.effective_order_version_id
        ):
            raise ValueError(
                "Der Auftrag wurde zwischenzeitlich geändert. "
                "Bitte laden Sie die Seite neu."
            )
        effective_version_id = order.effective_order_version_id
        assert effective_version_id is not None

        def work() -> None:
            try:
                self.confirmation_document_service.prepare_snapshot(
                    order_id,
                    effective_version_id,
                    "office-panel",
                )
            except CustomerDocumentCreationBlocked as exc:
                labels = [
                    _DOCUMENT_BLOCKER_LABELS.get(code, code) for code in exc.codes
                ]
                raise ValueError("; ".join(labels)) from exc

        if self._remote is not None:
            work()
        elif self._command_executor is not None:
            self._command_executor.run(work)
        else:
            work()

    def create_version(self, order_id: str, form: dict[str, str]) -> None:
        order = self._orders.get_order(order_id)
        if order is None:
            raise ValueError(f"no order with id {order_id!r}")
        if self._remote is None:
            versions = self._orders.list_order_versions(order_id)
            latest = max((version.version_number for version in versions), default=0)
            expected_raw = (
                form.get("_expect_latest_version_number", "").strip()
                or form.get("latest_version_number", "").strip()
            )
            if expected_raw and int(expected_raw) != latest:
                raise ValueError(
                    "Der Auftrag wurde zwischenzeitlich geändert. "
                    "Bitte laden Sie die Seite neu."
                )
            expected_effective = form.get("_expect_current_effective_order_version_id")
            expected_candidate = form.get("_expect_current_candidate_order_version_id")
            if (
                expected_effective is not None
                and (expected_effective or None) != order.effective_order_version_id
            ) or (
                expected_candidate is not None
                and (expected_candidate or None) != order.candidate_order_version_id
            ):
                raise ValueError(
                    "Der Auftrag wurde zwischenzeitlich geändert. "
                    "Bitte laden Sie die Seite neu."
                )

        def work() -> None:
            self.order_service.propose_order_version_change(
                order_id,
                event_date=date.fromisoformat(form["event_date"]),
                time_window_text=form.get("time_window_text", ""),
                location_text=form.get("location_text", ""),
                guest_count_estimate=_opt_int(form.get("guest_count_estimate", "")),
                planning_mode=form.get("planning_mode", PLANNING_MODES[0]),
                actor_reference="office-panel",
                change_reason=form.get("change_reason", "").strip()
                or "Operational order change",
            )

        if self._remote is not None:
            work()
        elif self._command_executor is not None:
            self._command_executor.run(work)
        else:
            work()


def _opt_int(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    return int(raw)


def _opt_contact(form: dict[str, str], key: str) -> str | None:
    value = form.get(key, "").strip()
    return value or None


def make_office_panel_handler(
    inquiry_repo: InquiryRepository,
    order_repo: OrderRepository,
    password: str,
    auerswald_url: str = "",
    auerswald_user: str = "",
    auerswald_password: str = "",
    kiosk_url: str = "",
    configurator_url: str = "",
    *,
    remote: RemoteCoreClient | None = None,
    command_executor: CoreCommandExecutor | None = None,
    payment_reminder_repo: PaymentReminderRepository | None = None,
    confirmation_document_repo: OrderConfirmationDocumentRepository | None = None,
    confirmation_outbound_repo: OrderConfirmationOutboundRepository | None = None,
    pause_repository: OrderOperationalPauseRepository | None = None,
    contact_note_repo: ContactInternalNoteRepository | None = None,
    contact_profile_repo: ContactProfileRepository | None = None,
    offer_repo: OfferRepository | None = None,
    catalog_repo: CatalogRepository | None = None,
    commercial_snapshot_repo: OrderCommercialSnapshotRepository | None = None,
    kitchen_print_job_repo: KitchenPrintJobRepository | None = None,
    ui_version: str = "legacy",
) -> type[BaseHTTPRequestHandler]:
    """Compatibility wrapper; HTTP routing lives in office_panel_http."""
    from catering_system.ui.office_panel_http import (
        make_office_panel_handler as make_handler,
    )

    return make_handler(
        inquiry_repo,
        order_repo,
        password,
        auerswald_url,
        auerswald_user,
        auerswald_password,
        kiosk_url,
        configurator_url,
        remote=remote,
        command_executor=command_executor,
        payment_reminder_repo=payment_reminder_repo,
        confirmation_document_repo=confirmation_document_repo,
        confirmation_outbound_repo=confirmation_outbound_repo,
        pause_repository=pause_repository,
        contact_note_repo=contact_note_repo,
        contact_profile_repo=contact_profile_repo,
        offer_repo=offer_repo,
        catalog_repo=catalog_repo,
        commercial_snapshot_repo=commercial_snapshot_repo,
        kitchen_print_job_repo=kitchen_print_job_repo,
        ui_version=ui_version,
    )


def create_office_panel_server(
    inquiry_repo: InquiryRepository,
    order_repo: OrderRepository,
    password: str,
    host: str = "0.0.0.0",
    port: int = 8081,
    auerswald_url: str = "",
    auerswald_user: str = "",
    auerswald_password: str = "",
    kiosk_url: str = "",
    configurator_url: str = "",
    *,
    remote: RemoteCoreClient | None = None,
    command_executor: CoreCommandExecutor | None = None,
    payment_reminder_repo: PaymentReminderRepository | None = None,
    confirmation_document_repo: OrderConfirmationDocumentRepository | None = None,
    confirmation_outbound_repo: OrderConfirmationOutboundRepository | None = None,
    pause_repository: OrderOperationalPauseRepository | None = None,
    contact_note_repo: ContactInternalNoteRepository | None = None,
    contact_profile_repo: ContactProfileRepository | None = None,
    offer_repo: OfferRepository | None = None,
    catalog_repo: CatalogRepository | None = None,
    commercial_snapshot_repo: OrderCommercialSnapshotRepository | None = None,
    offer_document_repo: OfferDocumentSnapshotRepository | None = None,
    offer_pdf_static_content: OfferPdfStaticContent | None = None,
    kitchen_print_job_repo: KitchenPrintJobRepository | None = None,
    ui_version: str = "legacy",
    auth_mode: Literal["basic", "migration", "employee"] = "basic",
    auth_service: Any | None = None,
    secure_cookie: bool = True,
) -> HTTPServer:
    """Compatibility wrapper; server construction lives in office_panel_http."""
    from catering_system.ui.office_panel_http import (
        create_office_panel_server as create_server,
    )

    return create_server(
        inquiry_repo,
        order_repo,
        password,
        host,
        port,
        auerswald_url,
        auerswald_user,
        auerswald_password,
        kiosk_url,
        configurator_url,
        remote=remote,
        command_executor=command_executor,
        payment_reminder_repo=payment_reminder_repo,
        confirmation_document_repo=confirmation_document_repo,
        confirmation_outbound_repo=confirmation_outbound_repo,
        pause_repository=pause_repository,
        contact_note_repo=contact_note_repo,
        contact_profile_repo=contact_profile_repo,
        offer_repo=offer_repo,
        catalog_repo=catalog_repo,
        commercial_snapshot_repo=commercial_snapshot_repo,
        offer_document_repo=offer_document_repo,
        offer_pdf_static_content=offer_pdf_static_content,
        kitchen_print_job_repo=kitchen_print_job_repo,
        ui_version=ui_version,
        auth_mode=auth_mode,
        auth_service=auth_service,
        secure_cookie=secure_cookie,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Office panel (LAN-only write surface)"
    )
    parser.add_argument(
        "--db",
        default="",
        help="Path to the Core SQLite database (direct mode only; omit when "
        "CORE_OFFICE_API_URL/CORE_OFFICE_API_TOKEN select remote mode)",
    )
    parser.add_argument(
        "--core-office-api-url",
        default=os.environ.get("CORE_OFFICE_API_URL", ""),
        help="Base URL of the frozen Core Office API (or set "
        "CORE_OFFICE_API_URL) — Phase 2 remote mode: set together with "
        "CORE_OFFICE_API_TOKEN (env only, never a flag) to run the panel "
        "without ever opening core.db",
    )
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument(
        "--host",
        default=os.environ.get("OFFICE_PANEL_HOST", "0.0.0.0"),
    )
    parser.add_argument(
        "--auth-mode",
        default=os.environ.get("OFFICE_PANEL_AUTH_MODE", "basic"),
        help="Office auth mode: basic, migration, employee",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("OFFICE_PANEL_PASSWORD", ""),
        help="Office password (or set OFFICE_PANEL_PASSWORD)",
    )
    parser.add_argument(
        "--allow-insecure-cookie",
        action="store_true",
        default=os.environ.get("OFFICE_PANEL_ALLOW_INSECURE_COOKIE", "") == "1",
        help="Allow non-Secure employee cookies for local HTTP development only",
    )
    parser.add_argument(
        "--auerswald-url",
        default=os.environ.get("AUERSWALD_SYNC_URL", ""),
        help="Base URL of the separate auerswald-sync call-log service "
        "(or set AUERSWALD_SYNC_URL) — read-only Rückrufe list, optional",
    )
    parser.add_argument(
        "--auerswald-user",
        default=os.environ.get("AUERSWALD_SYNC_USER", ""),
        help="Basic auth user for auerswald-sync (or set AUERSWALD_SYNC_USER)",
    )
    parser.add_argument(
        "--auerswald-password",
        default=os.environ.get("AUERSWALD_SYNC_PASSWORD", ""),
        help="Basic auth password for auerswald-sync (or set AUERSWALD_SYNC_PASSWORD)",
    )
    parser.add_argument(
        "--kiosk-url",
        default=os.environ.get("KIOSK_URL", ""),
        help="Base URL of the separate kitchen kiosk (or set KIOSK_URL) — "
        "single source of truth for the optional 'full week' deep link, optional",
    )
    parser.add_argument(
        "--configurator-url",
        default=os.environ.get("CONFIGURATOR_URL", ""),
        help="Base URL of the separate offer configurator (or set "
        "CONFIGURATOR_URL); empty keeps Inquiry-to-offer prefill dormant",
    )
    parser.add_argument(
        "--ui-version",
        choices=("legacy", "v2"),
        default=os.environ.get("OFFICE_UI_VERSION", "legacy"),
        help="Office presentation version (or set OFFICE_UI_VERSION); "
        "legacy is the safe rollout default",
    )
    args = parser.parse_args()
    from catering_system.ui.office_panel_http import validate_office_panel_auth_mode

    auth_mode = validate_office_panel_auth_mode(args.auth_mode)
    if auth_mode in {"basic", "migration"} and not args.password:
        raise SystemExit(
            "office panel refuses to start without a password "
            "(--password or OFFICE_PANEL_PASSWORD): it is a write surface (pack §7)"
        )
    secure_cookie = not args.allow_insecure_cookie

    # Phase 2 dual mode (pack §7): CORE_OFFICE_API_URL and CORE_OFFICE_API_TOKEN
    # must be set together (remote mode) or both left empty (direct mode) — a
    # half-configured pair is refused before anything else opens: no core.db,
    # no socket bound. The token is env-only, never a CLI flag, so it never
    # appears in argv/process listings (matching the Core Office API server's
    # own OFFICE_API_TOKEN convention).
    core_api_url = args.core_office_api_url
    core_api_token = os.environ.get("CORE_OFFICE_API_TOKEN", "")
    if bool(core_api_url) != bool(core_api_token):
        raise SystemExit(
            "CORE_OFFICE_API_URL and CORE_OFFICE_API_TOKEN must be set together "
            "(remote mode) or both left empty (direct mode)"
        )

    auth_runtime = None
    auth_service = None
    if auth_mode in {"migration", "employee"}:
        if not args.db:
            raise SystemExit(
                "--db is required when OFFICE_PANEL_AUTH_MODE is migration or employee"
            )
        from catering_system.repositories.employee_auth_runtime import (
            open_managed_employee_auth_runtime,
        )

        auth_runtime = open_managed_employee_auth_runtime(args.db)
        auth_service = auth_runtime.service

    if core_api_url:
        from catering_system.ui.remote_core_client import RemoteCoreClient

        remote = RemoteCoreClient(core_api_url, core_api_token)
        server = create_office_panel_server(
            remote,
            remote,
            args.password,
            args.host,
            args.port,
            args.auerswald_url,
            args.auerswald_user,
            args.auerswald_password,
            args.kiosk_url,
            args.configurator_url,
            remote=remote,
            ui_version=args.ui_version,
            auth_mode=auth_mode,
            auth_service=auth_service,
            secure_cookie=secure_cookie,
        )
        print(
            "Office panel on "
            f"http://{args.host}:{args.port}/ — remote mode against {core_api_url} "
            f"(auth_mode={auth_mode}, secure_cookie={secure_cookie}, "
            f"basic_fallback_active={auth_mode in {'basic', 'migration'}})"
        )
    else:
        if not args.db:
            raise SystemExit(
                "--db is required in direct mode (or set CORE_OFFICE_API_URL "
                "and CORE_OFFICE_API_TOKEN for remote mode)"
            )
        from catering_system.ui.offer_pdf_static_content_env import (
            offer_pdf_static_content_from_env,
        )

        # Validated before core.db is ever opened (issue #41): an invalid
        # PDF configuration must fail closed with no database side effect —
        # no file created, no migration applied, no repository constructed.
        offer_pdf_static_content = offer_pdf_static_content_from_env()

        from catering_system.repositories.bootstrap_customer_identity_schema import (
            bootstrap_customer_identity_schema,
        )
        from catering_system.repositories.core_transaction import (
            CoreCommandExecutor,
            open_core_connection,
        )
        from catering_system.repositories.sqlite_catalog_repository import (
            SQLiteCatalogRepository,
        )
        from catering_system.repositories.sqlite_contact_internal_note_repository import (
            SQLiteContactInternalNoteRepository,
        )
        from catering_system.repositories.sqlite_contact_profile_repository import (
            SQLiteContactProfileRepository,
        )
        from catering_system.repositories.sqlite_inquiry_repository import (
            SQLiteInquiryRepository,
        )
        from catering_system.repositories.sqlite_kitchen_print_job_repository import (
            SQLiteKitchenPrintJobRepository,
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
        from catering_system.repositories.sqlite_order_repository import (
            SQLiteOrderRepository,
        )
        from catering_system.repositories.sqlite_payment_reminder_repository import (
            SQLitePaymentReminderRepository,
        )

        connection = open_core_connection(args.db)
        inquiry_repo = SQLiteInquiryRepository.from_connection(connection)
        bootstrap_customer_identity_schema(connection)
        order_repo = SQLiteOrderRepository.from_connection(connection)
        offer_repo = SQLiteOfferRepository.from_connection(connection)
        catalog_repo = SQLiteCatalogRepository.from_connection(connection)
        commercial_snapshot_repo = (
            SQLiteOrderCommercialSnapshotRepository.from_connection(connection)
        )
        offer_document_repo = SQLiteOfferDocumentSnapshotRepository.from_connection(
            connection
        )
        payment_reminder_repo = SQLitePaymentReminderRepository.from_connection(
            connection
        )
        confirmation_document_repo = (
            SQLiteOrderConfirmationDocumentRepository.from_connection(connection)
        )
        confirmation_outbound_repo = (
            SQLiteOrderConfirmationOutboundRepository.from_connection(connection)
        )
        pause_repository = SQLiteOrderOperationalPauseRepository.from_connection(
            connection
        )
        contact_profile_repo = SQLiteContactProfileRepository.from_connection(
            connection
        )
        contact_note_repo = SQLiteContactInternalNoteRepository.from_connection(
            connection
        )
        kitchen_print_job_repo = SQLiteKitchenPrintJobRepository.from_connection(
            connection
        )

        server = create_office_panel_server(
            inquiry_repo,
            order_repo,
            args.password,
            args.host,
            args.port,
            args.auerswald_url,
            args.auerswald_user,
            args.auerswald_password,
            args.kiosk_url,
            args.configurator_url,
            command_executor=CoreCommandExecutor(connection),
            payment_reminder_repo=payment_reminder_repo,
            confirmation_document_repo=confirmation_document_repo,
            confirmation_outbound_repo=confirmation_outbound_repo,
            pause_repository=pause_repository,
            contact_note_repo=contact_note_repo,
            contact_profile_repo=contact_profile_repo,
            offer_repo=offer_repo,
            catalog_repo=catalog_repo,
            commercial_snapshot_repo=commercial_snapshot_repo,
            offer_document_repo=offer_document_repo,
            offer_pdf_static_content=offer_pdf_static_content,
            kitchen_print_job_repo=kitchen_print_job_repo,
            ui_version=args.ui_version,
            auth_mode=auth_mode,
            auth_service=auth_service,
            secure_cookie=secure_cookie,
        )
        print(
            "Office panel on "
            f"http://{args.host}:{args.port}/ "
            f"(auth_mode={auth_mode}, secure_cookie={secure_cookie}, "
            f"basic_fallback_active={auth_mode in {'basic', 'migration'}})"
        )
    try:
        server.serve_forever()
    finally:
        if auth_runtime is not None:
            auth_runtime.close()


if __name__ == "__main__":
    main()

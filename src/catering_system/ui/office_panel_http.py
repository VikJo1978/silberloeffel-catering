"""HTTP transport and routing for the office panel.

The UI composition and Core orchestration live in ``office_panel``. This module
owns only Basic Auth, request parsing, route dispatch and the HTTPServer wiring.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import sqlite3
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import parse_qs, quote, unquote, urlparse

from catering_system.domain.employee_auth import AuthenticatedEmployee, validate_role
from catering_system.domain.offer_pdf import OfferPdfStaticContent
from catering_system.domain.order_commercial_snapshot import (
    MissingCommercialSnapshotError,
)
from catering_system.integration.auerswald_sync import (
    fetch_missed_board,
    resolve_missed_call,
)
from catering_system.repositories.catalog_repository import CatalogRepository
from catering_system.repositories.contact_internal_note_repository import (
    ContactInternalNoteRepository,
)
from catering_system.repositories.contact_profile_repository import (
    ContactProfileRepository,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.in_memory_order_confirmation_document_repository import (
    InMemoryOrderConfirmationDocumentRepository,
)
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
from catering_system.repositories.order_purge import purge_order_with_dependencies
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.payment_reminder_repository import (
    PaymentReminderRepository,
)
from catering_system.repositories.sqlite_configurator_handoff_repository import (
    SQLiteConfiguratorHandoffRepository,
)
from catering_system.services.buffet_cards_service import BuffetCardsService
from catering_system.services.configurator_handoff_service import (
    ConfiguratorHandoffService,
)
from catering_system.services.employee_auth_service import (
    AccountConflictError,
    AccountNotFoundError,
    AuthenticationError,
    AuthorizationError,
    CsrfValidationError,
    EmployeeAuthService,
    LastActiveSuperadminError,
)
from catering_system.services.order_confirmation_document_preview import (
    build_preview,
    render_preview_html,
)
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentNotFoundError,
)
from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
    PrintProjectionNotFoundError,
)
from catering_system.ui.employee_auth_http import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    clear_cookie_header,
    csrf_cookie_header,
    csrf_token_from_headers,
    session_cookie_header,
    session_token_from_headers,
)
from catering_system.ui.office_panel import (
    CatalogCommandError,
    OfferPdfUnavailableError,
    OfficePageContext,
    OfficePanel,
    _csrf_input,
    _e,
    _page,
    fetch_rueckruf_count,
    render_buffet_cards,
    render_print_sheet,
    render_rueckruf,
)
from catering_system.ui.office_panel_authz import (
    DYNAMIC_CATALOG_UPDATE_AUTH,
    BusinessAccessDenied,
    DynamicCatalogUpdateAuth,
    authorize_catalog_update,
    require_all_business_permissions,
    require_all_business_permissions_post,
    require_any_business_permissions,
    require_any_business_permissions_post,
    require_business_permission,
    require_business_permission_post,
)
from catering_system.ui.office_panel_chat import (
    render_chat_detail,
    render_chat_list,
    render_chat_new,
)
from catering_system.ui.office_panel_settings_users import (
    SettingsUsersAccessDenied,
    parse_selected_permissions,
    permission_matrix_state,
    render_user_deactivate_confirm,
    render_user_detail,
    render_user_new,
    render_users_list,
    settings_users_error_message,
    show_users_nav_for,
)
from catering_system.ui.office_panel_shell import OfficeSection
from catering_system.ui.remote_core_client import RemoteCoreError

if TYPE_CHECKING:
    from catering_system.repositories.core_transaction import CoreCommandExecutor
    from catering_system.ui.remote_core_client import RemoteCoreClient

_CSRF_CONTEXT = b"catering-office-panel-csrf-v1"
_MAX_FORM_BODY_BYTES = 256 * 1024
_UNAVAILABLE_MESSAGE = "Core nicht erreichbar — nichts wurde gespeichert."
_RUECKRUF_COUNT_UNSET = object()

OfficePanelAuthMode = Literal["basic", "migration", "employee"]

_ROLE_LABELS = {
    "SUPERADMIN": "Superadmin",
    "ADMIN": "Administrator",
    "USER": "Benutzer",
    "VIEWER": "Leser",
}


def _int_value(value: object) -> int:
    return value if isinstance(value, int) else 0


_INQUIRY_COMMAND_ERROR_LABELS: dict[str, str] = {
    "conversion_blocked": (
        "Das angenommene Angebot kann derzeit nicht in einen Auftrag umgewandelt werden."
    ),
    "already_converted": "Für diese Anfrage existiert bereits ein Auftrag.",
    "accepted_offer_required": (
        "Auftrag nur aus angenommenem Angebot — "
        "direkte Umwandlung aus der Anfrage ist nicht möglich."
    ),
    "verification_gate_blocked": (
        "Die Rückrufprüfung ist noch nicht erfüllt — "
        "eine Umwandlung ist noch nicht möglich."
    ),
    "offer_blocks_conversion": (
        "Der Angebotsprozess blockiert die direkte Umwandlung in einen Auftrag."
    ),
    "contact_information_incomplete": (
        "Kontaktdaten unvollständig — E-Mail-Adresse und Telefonnummer "
        "müssen vor dem nächsten Schritt vorliegen."
    ),
    "contact_conflict": (
        "Vorhandene Kontaktdaten können nicht ersetzt werden — "
        "es dürfen nur fehlende Angaben ergänzt werden."
    ),
    "invalid_contact_value": (
        "Die eingegebenen Kontaktdaten sind ungültig — bitte E-Mail-Adresse "
        "oder Telefonnummer prüfen."
    ),
    "operational_context_missing": (
        "Der gewählte Auftragsstand hat keinen eingefrorenen Empfängerkontext. "
        "Bitte Support kontaktieren; es wurde nichts gespeichert."
    ),
    "order_delete_confirmation_mismatch": (
        "Der eingegebene Kunden-/Firmenname stimmt nicht überein. "
        "Der Auftrag wurde nicht gelöscht."
    ),
    "order_delete_name_unavailable": (
        "Der Auftrag kann nicht gelöscht werden, weil kein Kunden-/Firmenname "
        "für die Sicherheitsbestätigung verfügbar ist."
    ),
    "order_delete_unavailable": (
        "Auftrag löschen ist in dieser Betriebsart nicht verfügbar."
    ),
}


_OFFER_COMMAND_ERROR_LABELS: dict[str, str] = {
    "sent_evidence_exists": (
        "Für diese Angebotsversion ist bereits ein Versand vermerkt."
    ),
    "acceptance_already_exists": "Für dieses Angebot ist bereits eine Annahme erfasst.",
    "invalid_variant": "Die gewählte Variante gehört nicht zu dieser Angebotsversion.",
    "acceptance_blocked": "Die Annahme kann in diesem Angebotsstatus nicht erfasst werden.",
    "acceptance_blocked_newer_version_exists": (
        "Annahme nicht möglich: Eine neuere Angebotsversion ist bereits vorbereitet."
    ),
    "sent_recording_blocked": (
        "Der Versand kann in diesem Angebotsstatus nicht vermerkt werden."
    ),
    "invalid_sent_evidence": (
        "Der Versandnachweis ist ungültig. Bitte prüfen Sie Zeitpunkt, Kanal, "
        "Empfänger und Referenz; der Versandzeitpunkt darf nicht in der Zukunft liegen."
    ),
    "conversion_already_exists": "Dieses Angebot wurde bereits in einen Auftrag umgewandelt.",
    "conversion_blocked": (
        "Das angenommene Angebot kann derzeit nicht in einen Auftrag umgewandelt werden."
    ),
    "rejection_evidence_exists": (
        "Für diese Angebotsversion ist bereits eine Ablehnung erfasst."
    ),
    "withdrawal_evidence_exists": (
        "Für diese Angebotsversion ist bereits ein Rückzug erfasst."
    ),
    "rejection_blocked": (
        "Die Ablehnung kann in diesem Angebotsstatus nicht erfasst werden."
    ),
    "withdrawal_blocked": (
        "Der Rückzug kann in diesem Angebotsstatus nicht erfasst werden."
    ),
}


# CATALOG_ADMIN_PANEL_V1: catalog-specific keys, deliberately prefixed rather
# than reusing the raw Office API codes (validation_error/already_exists/
# stale_state/not_found). Those codes are generic across every command in the
# API, so a bare "not_found" entry here would put "Das Gericht ..." in front of
# an unrelated inquiry or order failure. OfficePanel's catalog write methods
# translate both direct-mode domain exceptions and remote-mode RemoteCoreError
# codes into these prefixed keys, which is what makes the two modes show the
# same German text.
_CATALOG_COMMAND_ERROR_LABELS: dict[str, str] = {
    "catalog_validation_error": (
        "Die eingegebenen Gerichtdaten sind ungültig — bitte Name, Kategorie, "
        "Preiseinheit, Preis und MwSt prüfen."
    ),
    "catalog_invalid_price": (
        "Der Preis ist ungültig. Bitte geben Sie einen Betrag mit höchstens "
        "zwei Nachkommastellen an, zum Beispiel 12,50."
    ),
    "catalog_invalid_input": (
        "Die Anfrage war unvollständig oder fehlerhaft. "
        "Bitte laden Sie die Seite neu und versuchen Sie es erneut."
    ),
    "catalog_already_exists": "Dieses Gericht existiert bereits.",
    "catalog_stale_state": (
        "Das Gericht wurde zwischenzeitlich geändert. Bitte laden Sie die Seite neu."
    ),
    "catalog_not_found": "Das Gericht wurde nicht gefunden.",
}


def office_command_error_message(code_or_text: str) -> str:
    if code_or_text in _INQUIRY_COMMAND_ERROR_LABELS:
        return _INQUIRY_COMMAND_ERROR_LABELS[code_or_text]
    if code_or_text in _OFFER_COMMAND_ERROR_LABELS:
        return _OFFER_COMMAND_ERROR_LABELS[code_or_text]
    if code_or_text in _CATALOG_COMMAND_ERROR_LABELS:
        return _CATALOG_COMMAND_ERROR_LABELS[code_or_text]
    lowered = code_or_text.lower()
    if "sent evidence already exists" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["sent_evidence_exists"]
    if "acceptance already exists" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["acceptance_already_exists"]
    if "accepted variant does not belong" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["invalid_variant"]
    if "acceptance_blocked_newer_version_exists" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["acceptance_blocked_newer_version_exists"]
    if "acceptance blocked" in lowered or "acceptance blocks sent" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["acceptance_blocked"]
    if "sent recording blocked" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["sent_recording_blocked"]
    if (
        "recorded_at cannot precede sent_at" in lowered
        or "sentevidence cannot predate its offerversion" in lowered
    ):
        return _OFFER_COMMAND_ERROR_LABELS["invalid_sent_evidence"]
    if "rejection blocked" in lowered or "rejection evidence already exists" in lowered:
        if "already exists" in lowered:
            return _OFFER_COMMAND_ERROR_LABELS["rejection_evidence_exists"]
        return _OFFER_COMMAND_ERROR_LABELS["rejection_blocked"]
    if (
        "withdrawal blocked" in lowered
        or "withdrawal evidence already exists" in lowered
    ):
        if "already exists" in lowered:
            return _OFFER_COMMAND_ERROR_LABELS["withdrawal_evidence_exists"]
        return _OFFER_COMMAND_ERROR_LABELS["withdrawal_blocked"]
    if "conversion link already exists" in lowered or "conversion already" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["conversion_already_exists"]
    if "accepted offer conversion gate" in lowered or "conversion blocked" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["conversion_blocked"]
    if "accepted offer required" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["accepted_offer_required"]
    if "offer blocks conversion" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["offer_blocks_conversion"]
    if "contact information incomplete" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["contact_information_incomplete"]
    if "already recorded and cannot change" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["contact_conflict"]
    if "contact email is empty or invalid" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["invalid_contact_value"]
    if "contact phone is empty or invalid" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["invalid_contact_value"]
    if "contact completion requires email or phone" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["invalid_contact_value"]
    if "unsupported delivery_address_mode" in lowered:
        return "Liefermodus ist ungültig."
    if "SEPARATE mode requires delivery_address" in lowered:
        return (
            "Bei abweichender Lieferadresse muss eine Lieferadresse angegeben werden."
        )
    if "delivery_address must be None" in lowered:
        return "Lieferadresse und Liefermodus passen nicht zusammen."
    if "intake requires email and phone" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["contact_information_incomplete"]
    if "inquiry conversion gate" in lowered or "verification" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["verification_gate_blocked"]
    if "already converted" in lowered or "active order blocks" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["already_converted"]
    return code_or_text


def inquiry_command_error_message(code_or_text: str) -> str:
    return office_command_error_message(code_or_text)


class FormBodyTooLargeError(ValueError):
    pass


def csrf_token_for_password(password: str) -> str:
    """Derive a stable form token without exposing the Basic Auth password."""
    return hmac.new(password.encode("utf-8"), _CSRF_CONTEXT, hashlib.sha256).hexdigest()


def validate_office_panel_auth_mode(value: str) -> OfficePanelAuthMode:
    if value not in {"basic", "migration", "employee"}:
        raise ValueError(f"unknown office auth mode: {value}")
    return cast(OfficePanelAuthMode, value)


def _safe_redirect_target(raw: str) -> str:
    candidate = raw.strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return "/"
    return candidate or "/"


@dataclass(frozen=True)
class OfficePanelRequestAuth:
    kind: Literal["basic", "employee"]
    current_user_name: str
    current_user_role_label: str
    csrf_token: str
    show_transition_banner: bool
    legacy_shared_access: bool
    password_change_path: str = ""
    logout_path: str = ""
    employee: AuthenticatedEmployee | None = None


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
    offer_document_repo: OfferDocumentSnapshotRepository | None = None,
    offer_pdf_static_content: OfferPdfStaticContent | None = None,
    kitchen_print_job_repo: KitchenPrintJobRepository | None = None,
    ui_version: str = "legacy",
    auth_mode: OfficePanelAuthMode = "basic",
    auth_service: EmployeeAuthService | None = None,
    secure_cookie: bool = True,
) -> type[BaseHTTPRequestHandler]:
    validated_auth_mode = validate_office_panel_auth_mode(auth_mode)
    if validated_auth_mode in {"migration", "employee"} and auth_service is None:
        raise ValueError(
            "employee auth service is required for migration/employee mode"
        )
    configurator_handoff_service: ConfiguratorHandoffService | None = None
    if validated_auth_mode in {"migration", "employee"} and auth_service is not None:
        repository = getattr(auth_service.repository, "_conn", None)
        if isinstance(repository, sqlite3.Connection):
            configurator_handoff_service = ConfiguratorHandoffService(
                SQLiteConfiguratorHandoffRepository.from_connection(repository)
            )
    local_confirmation_document_repo = (
        confirmation_document_repo or InMemoryOrderConfirmationDocumentRepository()
    )
    panel = OfficePanel(
        inquiry_repo,
        order_repo,
        kiosk_url,
        configurator_url,
        configurator_handoff_service=configurator_handoff_service,
        remote=remote,
        command_executor=command_executor,
        payment_reminder_repo=payment_reminder_repo,
        confirmation_document_repo=local_confirmation_document_repo,
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
    )
    expected = "Basic " + base64.b64encode(f"office:{password}".encode()).decode()
    csrf_token = csrf_token_for_password(password)

    class OfficePanelHandler(BaseHTTPRequestHandler):
        server_version = "OfficePanel/1.0"

        def _legacy_authorized(self) -> bool:
            return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

        def _employee_from_session(self) -> AuthenticatedEmployee | None:
            if auth_service is None:
                return None
            session_token = session_token_from_headers(self.headers)
            if session_token is None:
                return None
            return auth_service.authenticate_session(session_token)

        def _resolve_request_auth(self) -> OfficePanelRequestAuth | None:
            employee: AuthenticatedEmployee | None = None
            employee_auth_failed = False
            if validated_auth_mode in {"migration", "employee"}:
                try:
                    employee = self._employee_from_session()
                except AuthenticationError:
                    employee_auth_failed = True
                if employee is not None:
                    return OfficePanelRequestAuth(
                        kind="employee",
                        current_user_name=employee.account.display_name,
                        current_user_role_label=_ROLE_LABELS.get(
                            employee.account.role, employee.account.role
                        ),
                        csrf_token=csrf_token_from_headers(self.headers) or "",
                        show_transition_banner=validated_auth_mode == "migration",
                        legacy_shared_access=False,
                        password_change_path="/password-change",
                        logout_path="/logout",
                        employee=employee,
                    )
            if (
                validated_auth_mode in {"basic", "migration"}
                and self._legacy_authorized()
            ):
                return OfficePanelRequestAuth(
                    kind="basic",
                    current_user_name="Gemeinsamer Office-Zugang",
                    current_user_role_label="Legacy-Zugang",
                    csrf_token=csrf_token,
                    show_transition_banner=validated_auth_mode == "migration",
                    legacy_shared_access=True,
                )
            if employee_auth_failed:
                return None
            return None

        def _render_login_page(
            self, *, next_path: str, error_message: str = "", status: int = 200
        ) -> None:
            body = [
                "<fieldset><legend>Anmeldung</legend>",
                "<p>Bitte mit Ihrem Mitarbeiterkonto anmelden.</p>",
            ]
            if error_message:
                body.append(f'<p class="blocked">{_e(error_message)}</p>')
            body.extend(
                [
                    '<form method="post" action="/login">',
                    f'<input type="hidden" name="next" value="{_e(next_path)}">',
                    '<p><label for="username">Benutzername oder E-Mail</label><br>',
                    '<input id="username" name="username" autocomplete="username"></p>',
                    '<p><label for="password">Passwort</label><br>',
                    '<input id="password" name="password" type="password" '
                    'autocomplete="current-password"></p>',
                    '<p><button type="submit">Anmelden</button></p>',
                    "</form></fieldset>",
                ]
            )
            self._html(
                _page(
                    "Anmeldung",
                    "".join(body),
                    active_section="home",
                    context=OfficePageContext(),
                ),
                status=status,
            )

        def _render_password_change_page(
            self,
            auth: OfficePanelRequestAuth,
            *,
            error_message: str = "",
            status: int = 200,
        ) -> None:
            body = [
                "<fieldset><legend>Passwort ändern</legend>",
                "<p>Ihr Konto ist angemeldet, der Zugriff bleibt aber bis zur Passwortänderung eingeschränkt.</p>",
            ]
            if error_message:
                body.append(f'<p class="blocked">{_e(error_message)}</p>')
            body.extend(
                [
                    '<form method="post" action="/password-change">',
                    f"{_csrf_input(self._page_context(auth))}",
                    '<p><label for="current_password">Aktuelles Passwort</label><br>',
                    '<input id="current_password" name="current_password" type="password" '
                    'autocomplete="current-password"></p>',
                    '<p><label for="new_password">Neues Passwort</label><br>',
                    '<input id="new_password" name="new_password" type="password" '
                    'autocomplete="new-password"></p>',
                    '<p><button type="submit">Passwort speichern</button></p>',
                    "</form></fieldset>",
                ]
            )
            self._html(
                _page(
                    "Passwort ändern",
                    "".join(body),
                    active_section="home",
                    context=self._page_context(auth),
                ),
                status=status,
            )

        def _redirect_to_login(self) -> None:
            next_path = _safe_redirect_target(self.path)
            location = "/login"
            if next_path != "/":
                location = f"/login?next={quote(next_path, safe='')}"
            self._redirect(location)

        def _page_context(
            self,
            auth: OfficePanelRequestAuth | None = None,
            *,
            rueckruf_count: int | None | object = _RUECKRUF_COUNT_UNSET,
            chat_unread_count: int | None | object = _RUECKRUF_COUNT_UNSET,
        ) -> OfficePageContext:
            if auth is None:
                auth = getattr(self, "_request_auth", None)
            if auth is None:
                auth = self._resolve_request_auth()
            if rueckruf_count is _RUECKRUF_COUNT_UNSET:
                resolved_rueckruf_count = fetch_rueckruf_count(
                    auerswald_url,
                    auerswald_user,
                    auerswald_password,
                )
            elif isinstance(rueckruf_count, int) or rueckruf_count is None:
                resolved_rueckruf_count = rueckruf_count
            else:
                resolved_rueckruf_count = None
            show_users_nav = False
            employee_effective_permissions: frozenset[str] = frozenset()
            if (
                auth is not None
                and auth.kind == "employee"
                and auth.employee is not None
                and not auth.legacy_shared_access
            ):
                show_users_nav = show_users_nav_for(auth.employee)
                employee_effective_permissions = auth.employee.effective_permissions
            return OfficePageContext(
                rueckruf_count=resolved_rueckruf_count,
                csrf_token=auth.csrf_token if auth is not None else "",
                current_user_name=auth.current_user_name if auth is not None else "",
                current_user_role_label=(
                    auth.current_user_role_label if auth is not None else ""
                ),
                password_change_path=auth.password_change_path
                if auth is not None
                else "",
                logout_path=auth.logout_path if auth is not None else "",
                show_transition_banner=(
                    auth.show_transition_banner if auth is not None else False
                ),
                legacy_shared_access=auth.legacy_shared_access
                if auth is not None
                else False,
                show_users_nav=show_users_nav,
                employee_effective_permissions=employee_effective_permissions,
                employee_account_id=(
                    auth.employee.account.id
                    if auth is not None
                    and auth.kind == "employee"
                    and auth.employee is not None
                    and not auth.legacy_shared_access
                    else ""
                ),
                chat_unread_count=(
                    self._chat_unread_count(auth)
                    if chat_unread_count is _RUECKRUF_COUNT_UNSET
                    else chat_unread_count
                    if isinstance(chat_unread_count, int) or chat_unread_count is None
                    else None
                ),
            )

        def _chat_unread_count(self, auth: OfficePanelRequestAuth | None) -> int | None:
            if (
                remote is None
                or auth is None
                or auth.kind != "employee"
                or auth.employee is None
                or auth.legacy_shared_access
                or "chat.view" not in auth.employee.effective_permissions
            ):
                return None
            session_token = session_token_from_headers(self.headers)
            if session_token is None:
                return None
            try:
                threads = remote.list_chat_threads(employee_session_token=session_token)
            except RemoteCoreError:
                return None
            return sum(_int_value(thread.get("unread_count")) for thread in threads)

        def _require_settings_users_actor(
            self, auth: OfficePanelRequestAuth | None
        ) -> AuthenticatedEmployee:
            if auth is None:
                raise SettingsUsersAccessDenied()
            if auth.kind != "employee" or auth.employee is None:
                raise SettingsUsersAccessDenied()
            if auth.legacy_shared_access:
                raise SettingsUsersAccessDenied()
            if not auth.employee.application_access_allowed:
                raise SettingsUsersAccessDenied()
            if "users.view" not in auth.employee.effective_permissions:
                raise SettingsUsersAccessDenied()
            return auth.employee

        def _forbidden_page_context(
            self, auth: OfficePanelRequestAuth | None = None
        ) -> OfficePageContext:
            """Minimal shell context for 403 pages — no Auerswald or badge fetch."""
            return self._page_context(auth, rueckruf_count=None)

        def _business_forbidden(
            self, *, active_section: OfficeSection = "home"
        ) -> None:
            self._html(
                _page(
                    "Zugriff verweigert",
                    '<p class="blocked">Ihre Berechtigung reicht für diese Aktion nicht aus.</p>',
                    active_section=active_section,
                    context=self._forbidden_page_context(),
                ),
                403,
            )

        def _require_business_permission_get(
            self,
            auth: OfficePanelRequestAuth | None,
            permission_code: str,
            *,
            active_section: OfficeSection = "home",
        ) -> bool:
            try:
                require_business_permission(auth, permission_code)
            except BusinessAccessDenied:
                self._business_forbidden(active_section=active_section)
                return False
            return True

        def _require_all_business_permissions_get(
            self,
            auth: OfficePanelRequestAuth | None,
            permission_codes: tuple[str, ...],
            *,
            active_section: OfficeSection = "home",
        ) -> bool:
            try:
                require_all_business_permissions(auth, permission_codes)
            except BusinessAccessDenied:
                self._business_forbidden(active_section=active_section)
                return False
            return True

        def _require_any_business_permission_get(
            self,
            auth: OfficePanelRequestAuth | None,
            permission_codes: tuple[str, ...],
            *,
            active_section: OfficeSection = "home",
        ) -> bool:
            try:
                require_any_business_permissions(auth, permission_codes)
            except BusinessAccessDenied:
                self._business_forbidden(active_section=active_section)
                return False
            return True

        def _post_active_section(self, parts: list[str]) -> OfficeSection:
            if parts == ["inquiry", "new"] or (
                len(parts) == 3 and parts[0] == "inquiry"
            ):
                return "inquiries"
            if len(parts) == 3 and parts[0] == "kontakt":
                return "contacts"
            if len(parts) == 3 and parts[0] == "offer":
                return "offers"
            if len(parts) == 3 and parts[0] == "order":
                return "orders"
            if (
                len(parts) == 4
                and parts[0] == "order"
                and parts[2] == "confirmation-document"
            ):
                return "orders"
            if parts == ["rueckruf"] or parts == ["rueckruf", "resolve"]:
                return "callbacks"
            if parts and parts[0] == "chat":
                return "chat"
            if parts == ["gerichte", "new"] or (
                len(parts) >= 2 and parts[0] == "gerichte"
            ):
                return "catalog"
            return "home"

        def _auth2d2_post_permission_requirements(
            self, parts: list[str]
        ) -> tuple[str, ...] | DynamicCatalogUpdateAuth | None:
            if parts == ["inquiry", "new"]:
                return ("inquiries.create",)
            if len(parts) == 3 and parts[0] == "inquiry":
                action = parts[2]
                if action == "update":
                    return ("inquiries.edit",)
                if action == "contact-completion":
                    return ("inquiries.edit",)
                if action == "fulfillment-mode":
                    return ("inquiries.edit",)
                if action == "customer-addresses":
                    return ("inquiries.view", "customers.edit")
                if action == "verify":
                    return ("inquiries.verify",)
                if action == "convert":
                    return ("inquiries.view", "orders.version.create")
                if action == "convert-accepted":
                    return ("offers.view", "orders.version.create")
                return None
            if len(parts) == 3 and parts[0] == "kontakt" and parts[2] == "notizen":
                return ("customers.edit",)
            if len(parts) == 3 and parts[0] == "offer":
                action = parts[2]
                if action == "mark-sent":
                    return ("offers.send",)
                if action in (
                    "record-acceptance",
                    "record-rejection",
                    "record-withdrawal",
                ):
                    return ("offers.status.change",)
                if action == "convert":
                    return ("offers.view", "orders.version.create")
                return None
            if len(parts) == 3 and parts[0] == "order":
                action = parts[2]
                order_post_permissions: dict[str, tuple[str, ...]] = {
                    "version": ("orders.version.create",),
                    "delivery-address": ("orders.version.create",),
                    "print-confirm": ("orders.print.confirm",),
                    "effective": ("orders.effective.set",),
                    "ready": ("orders.ready.release",),
                    "pause": ("orders.pause",),
                    "resume": ("orders.pause",),
                    "cancel": ("orders.cancel",),
                    "delete": ("orders.cancel",),
                    "payment-reminder": ("orders.payment.reminder",),
                    "confirmation-document": ("documents.prepare",),
                }
                return order_post_permissions.get(action)
            if (
                len(parts) == 4
                and parts[0] == "order"
                and parts[2] == "confirmation-document"
                and parts[3] == "send"
            ):
                return ("documents.send",)
            if parts == ["rueckruf", "resolve"]:
                return ("queue.resolve",)
            if parts == ["chat", "threads"]:
                return ("chat.create",)
            if len(parts) == 3 and parts[0] == "chat" and parts[2] == "messages":
                return ("chat.send",)
            if len(parts) == 3 and parts[0] == "chat" and parts[2] == "read":
                return ("chat.view",)
            if parts == ["gerichte", "new"]:
                return ("catalog.edit", "prices.edit")
            if len(parts) == 3 and parts[0] == "gerichte":
                action = parts[2]
                if action in ("activate", "deactivate"):
                    return ("catalog.edit",)
                if action == "update":
                    return DYNAMIC_CATALOG_UPDATE_AUTH
            return None

        def _require_auth2d2_post_permissions(
            self,
            parts: list[str],
            auth: OfficePanelRequestAuth | None,
        ) -> bool:
            requirements = self._auth2d2_post_permission_requirements(parts)
            if requirements is None:
                return True
            if auth is None or auth.legacy_shared_access:
                return True
            if auth.kind != "employee" or auth.employee is None:
                return True
            try:
                if isinstance(requirements, DynamicCatalogUpdateAuth):
                    require_any_business_permissions_post(
                        auth, ("catalog.edit", "prices.edit")
                    )
                else:
                    require_all_business_permissions_post(auth, requirements)
            except BusinessAccessDenied:
                self._business_forbidden(
                    active_section=self._post_active_section(parts)
                )
                return False
            return True

        def _require_business_permission_post(
            self,
            auth: OfficePanelRequestAuth | None,
            permission_code: str,
            *,
            active_section: OfficeSection = "home",
        ) -> bool:
            try:
                require_business_permission_post(auth, permission_code)
            except BusinessAccessDenied:
                self._business_forbidden(active_section=active_section)
                return False
            return True

        def _settings_users_forbidden(self) -> None:
            self._business_forbidden(active_section="settings")

        def _settings_users_actor_or_forbidden(
            self, auth: OfficePanelRequestAuth | None
        ) -> AuthenticatedEmployee | None:
            try:
                return self._require_settings_users_actor(auth)
            except SettingsUsersAccessDenied:
                self._settings_users_forbidden()
                return None

        def _settings_users_audit(
            self, actor: AuthenticatedEmployee, account_id: str
        ) -> list:
            assert auth_service is not None
            if "audit.view" not in actor.effective_permissions:
                return []
            try:
                return auth_service.list_account_audit_events(actor, account_id)
            except AuthorizationError:
                return []

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")

        def end_headers(self) -> None:
            self._security_headers()
            super().end_headers()

        def _deny(self) -> None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Office"')
            self.end_headers()

        def _html(
            self,
            page: str,
            status: int = 200,
            *,
            cookie_headers: tuple[str, ...] = (),
        ) -> None:
            payload = page.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            for cookie_header in cookie_headers:
                self.send_header("Set-Cookie", cookie_header)
            self.end_headers()
            self.wfile.write(payload)

        def _pdf_bytes(self, payload: bytes, filename: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
            self.end_headers()
            self.wfile.write(payload)

        def _redirect(
            self, location: str, *, cookie_headers: tuple[str, ...] = ()
        ) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            for cookie_header in cookie_headers:
                self.send_header("Set-Cookie", cookie_header)
            self.end_headers()

        def _fetch_enriched_missed_board(self) -> tuple[list[dict] | None, str | None]:
            items, error = fetch_missed_board(
                auerswald_url, auerswald_user, auerswald_password
            )
            if items is not None:
                items = panel.enrich_rueckruf_items(items)
            return items, error

        def _error_page(self, message: str, status: int = 400) -> None:
            self._html(
                _page(
                    "Fehler",
                    f'<p class="blocked">{_e(message)}</p>',
                    active_section="home",
                    context=self._page_context(),
                ),
                status,
            )

        def _chat_employee_session_or_forbidden(
            self, auth: OfficePanelRequestAuth | None
        ) -> str | None:
            if (
                remote is None
                or auth is None
                or auth.kind != "employee"
                or auth.employee is None
                or auth.legacy_shared_access
            ):
                self._business_forbidden(active_section="chat")
                return None
            session_token = session_token_from_headers(self.headers)
            if session_token is None:
                self._business_forbidden(active_section="chat")
                return None
            return session_token

        def _remote_error_page(self, exc: RemoteCoreError) -> None:
            """Pack §6.5 degradation: an unreachable/malformed Core Office API
            response must show this exact German message, never an empty or
            partial page — no read has returned by this point (the exception
            fired before any render function could build a body), and no
            write has happened either (§6.1: a command either returns 2xx or
            never took effect). Genuine remote business rejections (409/422 —
            not "unavailable") fall back to the same generic error rendering
            direct-mode ValueErrors already use."""
            if exc.unavailable:
                self._html(
                    _page(
                        "Fehler",
                        f'<p class="blocked">{_e(_UNAVAILABLE_MESSAGE)}</p>',
                        active_section="home",
                        context=self._page_context(),
                    ),
                    503,
                )
            else:
                self._error_page(
                    inquiry_command_error_message(exc.code),
                    status=exc.status,
                )

        def _form(self) -> dict[str, str]:
            cached = getattr(self, "_form_cache", None)
            if cached is not None:
                return cached
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length < 0:
                raise ValueError("invalid Content-Length")
            if length > _MAX_FORM_BODY_BYTES:
                raise FormBodyTooLargeError("form body too large")
            raw = self.rfile.read(length).decode("utf-8")
            parsed_lists = parse_qs(raw, keep_blank_values=True)
            parsed = {key: values[0] for key, values in parsed_lists.items()}
            self._form_cache = parsed
            self._form_lists_cache = parsed_lists
            return parsed

        def _form_list(self, key: str) -> list[str]:
            self._form()
            lists = getattr(self, "_form_lists_cache", {})
            return lists.get(key, [])

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            auth = self._resolve_request_auth()
            self._request_auth = auth
            if parts == ["login"]:
                if validated_auth_mode == "basic":
                    self.send_error(404)
                    return
                if auth is not None and auth.kind == "employee":
                    if (
                        auth.employee is not None
                        and not auth.employee.application_access_allowed
                    ):
                        self._redirect("/password-change")
                    else:
                        self._redirect(
                            _safe_redirect_target(
                                parse_qs(parsed.query).get("next", ["/"])[0]
                            )
                        )
                    return
                self._render_login_page(
                    next_path=_safe_redirect_target(
                        parse_qs(parsed.query).get("next", ["/"])[0]
                    )
                )
                return
            if parts == ["password-change"]:
                if auth is None or auth.kind != "employee":
                    if validated_auth_mode == "basic":
                        self._deny()
                    else:
                        self._redirect_to_login()
                    return
                if (
                    auth.employee is not None
                    and auth.employee.application_access_allowed
                ):
                    self._redirect("/")
                    return
                self._render_password_change_page(auth)
                return
            if auth is None:
                if validated_auth_mode == "basic":
                    self._deny()
                else:
                    self._redirect_to_login()
                return
            if (
                auth.kind == "employee"
                and auth.employee is not None
                and not auth.employee.application_access_allowed
            ):
                self._redirect("/password-change")
                return
            panel.begin_request()
            try:
                self._route_get()
            except RemoteCoreError as exc:
                self._remote_error_page(exc)

        def _route_get(self) -> None:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            auth = self._request_auth
            if parts == ["rueckruf"]:
                if not self._require_business_permission_get(
                    auth, "queue.view", active_section="callbacks"
                ):
                    return
                if remote is not None and not auerswald_url:
                    self._html(
                        render_rueckruf(
                            None,
                            "Rückruf-Liste: nur vor Ort verfügbar",
                            context=self._page_context(),
                        )
                    )
                    return
                items, error = self._fetch_enriched_missed_board()
                context = self._page_context(
                    rueckruf_count=len(items) if items is not None else None
                )
                self._html(render_rueckruf(items, error, context=context))
                return
            if not parts:
                if not self._require_business_permission_get(
                    auth, "queue.view", active_section="home"
                ):
                    return
                items, error = self._fetch_enriched_missed_board()
                context = self._page_context(
                    rueckruf_count=len(items) if items is not None else None
                )
                kalender_view = parse_qs(parsed.query).get("kalender", ["woche"])[0]
                self._html(
                    panel.render_queue(
                        items,
                        rueckruf_error=error,
                        context=context,
                        kalender_view=kalender_view,
                    )
                )
                return
            if parts == ["anfragen"]:
                if not self._require_business_permission_get(
                    auth, "inquiries.view", active_section="inquiries"
                ):
                    return
                context = self._page_context()
                search_query = parse_qs(parsed.query).get("q", [""])[0]
                self._html(panel.render_anfragen(search_query, context=context))
            elif parts == ["angebote"]:
                if not self._require_business_permission_get(
                    auth, "offers.view", active_section="offers"
                ):
                    return
                context = self._page_context()
                self._html(panel.render_angebote(context=context))
            elif parts == ["kontakte"]:
                if not self._require_business_permission_get(
                    auth, "customers.view", active_section="contacts"
                ):
                    return
                context = self._page_context()
                query = parse_qs(parsed.query)
                search_query = query.get("q", [""])[0]
                status_filter = query.get("status", ["all"])[0]
                self._html(
                    panel.render_kontakte(search_query, status_filter, context=context)
                )
            elif parts == ["gerichte"]:
                if not self._require_business_permission_get(
                    auth, "catalog.view", active_section="catalog"
                ):
                    return
                context = self._page_context()
                query = parse_qs(parsed.query)
                self._html(
                    panel.render_gerichte(
                        query.get("q", [""])[0],
                        query.get("status", ["all"])[0],
                        context=context,
                    )
                )
            elif parts == ["gerichte", "new"]:
                if not self._require_all_business_permissions_get(
                    auth,
                    ("catalog.edit", "prices.edit"),
                    active_section="catalog",
                ):
                    return
                context = self._page_context()
                self._html(panel.render_gericht_new(context=context))
            elif parts == ["emails"] or parts == ["email"]:
                if not self._require_business_permission_get(
                    auth, "inquiries.view", active_section="email"
                ):
                    return
                context = self._page_context()
                self._html(panel.render_email(context=context))
            elif parts == ["chat"]:
                if not self._require_business_permission_get(
                    auth, "chat.view", active_section="chat"
                ):
                    return
                session_token = self._chat_employee_session_or_forbidden(auth)
                if session_token is None:
                    return
                assert remote is not None
                query = parse_qs(parsed.query)
                search_query = query.get("q", [""])[0].strip()
                threads = remote.list_chat_threads(employee_session_token=session_token)
                search_results = (
                    remote.search_chat(
                        employee_session_token=session_token,
                        q=search_query,
                    )
                    if search_query
                    else None
                )
                context = self._page_context(
                    auth,
                    rueckruf_count=None,
                    chat_unread_count=sum(
                        _int_value(thread.get("unread_count")) for thread in threads
                    ),
                )
                self._html(
                    render_chat_list(
                        threads,
                        search_results=search_results,
                        q=search_query,
                        context=context,
                    )
                )
            elif parts == ["chat", "new"]:
                if not self._require_business_permission_get(
                    auth, "chat.create", active_section="chat"
                ):
                    return
                session_token = self._chat_employee_session_or_forbidden(auth)
                if session_token is None:
                    return
                assert remote is not None
                query = parse_qs(parsed.query)
                search_query = query.get("q", [""])[0].strip()
                employees = remote.search_chat_employees(
                    employee_session_token=session_token,
                    q=search_query,
                )
                self._html(
                    render_chat_new(
                        employees,
                        q=search_query,
                        context=self._page_context(auth, rueckruf_count=None),
                        command_fields=panel._command_fields(),
                    )
                )
            elif parts == ["aufgaben"]:
                if not self._require_business_permission_get(
                    auth, "queue.view", active_section="tasks"
                ):
                    return
                context = self._page_context()
                self._html(panel.render_aufgaben(context=context))
            elif parts == ["kalender"]:
                if not self._require_business_permission_get(
                    auth, "calendar.view", active_section="calendar"
                ):
                    return
                context = self._page_context()
                self._html(panel.render_kalender(context=context))
            elif parts == ["auftraege"]:
                if not self._require_business_permission_get(
                    auth, "orders.view", active_section="orders"
                ):
                    return
                context = self._page_context()
                search_query = parse_qs(parsed.query).get("q", [""])[0]
                self._html(panel.render_auftraege(search_query, context=context))
            elif parts == ["orders"]:
                if not self._require_business_permission_get(
                    auth, "orders.view", active_section="orders"
                ):
                    return
                context = self._page_context()
                query = parse_qs(parsed.query)
                self._html(
                    panel.render_orders(
                        query.get("q", [""])[0],
                        query.get("zeitraum", [""])[0],
                        context=context,
                    )
                )
            elif parts == ["inquiry", "new"]:
                if not self._require_business_permission_get(
                    auth, "inquiries.create", active_section="inquiries"
                ):
                    return
                context = self._page_context()
                form_defaults = parse_qs(parsed.query)
                self._html(
                    panel.render_inquiry_form(
                        phone=form_defaults.get("phone", [""])[0],
                        event_date=form_defaults.get("event_date", [""])[0],
                        guest_count_estimate=form_defaults.get(
                            "guest_count_estimate", [""]
                        )[0],
                        context=context,
                    )
                )
            elif len(parts) == 2 and parts[0] == "inquiry":
                if not self._require_business_permission_get(
                    auth, "inquiries.view", active_section="inquiries"
                ):
                    return
                context = self._page_context()
                page = panel.render_inquiry(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] == "order":
                if not self._require_business_permission_get(
                    auth, "orders.view", active_section="orders"
                ):
                    return
                context = self._page_context()
                page = panel.render_order(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] == "offer":
                if not self._require_business_permission_get(
                    auth, "offers.view", active_section="offers"
                ):
                    return
                context = self._page_context()
                page = panel.render_offer(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif (
                len(parts) == 4
                and parts[0] == "offer"
                and parts[2] == "offer-document"
                and parts[3] == "pdf"
            ):
                if not self._require_business_permission_get(
                    auth, "offers.pdf.generate", active_section="offers"
                ):
                    return
                self._offer_document_pdf_download(parts[1], parsed.query)
            elif len(parts) == 2 and parts[0] == "kontakt":
                if not self._require_business_permission_get(
                    auth, "customers.view", active_section="contacts"
                ):
                    return
                context = self._page_context()
                page = panel.render_kontakt(unquote(parts[1]), context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] == "gerichte":
                if not self._require_business_permission_get(
                    auth, "catalog.view", active_section="catalog"
                ):
                    return
                context = self._page_context()
                page = panel.render_gericht(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 3 and parts[0] == "gerichte" and parts[2] == "edit":
                if not self._require_any_business_permission_get(
                    auth,
                    ("catalog.edit", "prices.edit"),
                    active_section="catalog",
                ):
                    return
                context = self._page_context()
                page = panel.render_gericht_edit(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] in ("emails", "email"):
                if not self._require_business_permission_get(
                    auth, "inquiries.view", active_section="email"
                ):
                    return
                context = self._page_context()
                page = panel.render_email_detail(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] == "chat":
                if not self._require_business_permission_get(
                    auth, "chat.view", active_section="chat"
                ):
                    return
                session_token = self._chat_employee_session_or_forbidden(auth)
                if session_token is None:
                    return
                assert remote is not None
                query = parse_qs(parsed.query)
                thread_id = unquote(parts[1])
                mention_q = query.get("mention_q", [""])[0].strip()
                reference_q = query.get("reference_q", [""])[0].strip()
                reference_type = query.get("reference_type", ["ORDER"])[0]
                if reference_type not in {"ORDER", "INQUIRY", "CONTACT"}:
                    reference_type = "ORDER"
                chat_detail = remote.get_chat_thread(
                    thread_id,
                    employee_session_token=session_token,
                )
                participant_results = remote.autocomplete_chat_participants(
                    thread_id,
                    employee_session_token=session_token,
                    q=mention_q,
                )
                entity_results = (
                    remote.search_chat_entities(
                        employee_session_token=session_token,
                        q=reference_q,
                        reference_type=reference_type,
                    )
                    if reference_q
                    else []
                )
                self._html(
                    render_chat_detail(
                        chat_detail,
                        context=self._page_context(auth, rueckruf_count=None),
                        read_command_fields=panel._command_fields(),
                        send_command_fields=panel._command_fields(),
                        participant_results=participant_results,
                        mention_q=mention_q,
                        entity_results=entity_results,
                        reference_q=reference_q,
                        reference_type=reference_type,
                        reply_to_message_id=query.get("reply_to", [""])[0],
                    )
                )
            elif len(parts) == 3 and parts[0] == "order" and parts[2] == "print":
                if not self._require_business_permission_get(
                    auth, "orders.view", active_section="orders"
                ):
                    return
                self._print_sheet(parts[1], parsed.query)
            elif len(parts) == 3 and parts[0] == "order" and parts[2] == "buffet-cards":
                if not self._require_business_permission_get(
                    auth, "orders.view", active_section="orders"
                ):
                    return
                self._buffet_cards(parts[1], parsed.query)
            elif (
                len(parts) == 4
                and parts[0] == "order"
                and parts[2] == "confirmation-document"
                and parts[3] == "preview"
            ):
                if not self._require_business_permission_get(
                    auth, "documents.view", active_section="orders"
                ):
                    return
                self._confirmation_document_preview(parts[1])
            elif (
                len(parts) == 4
                and parts[0] == "order"
                and parts[2] == "confirmation-document"
                and parts[3] == "fake-outbox"
            ):
                if not self._require_business_permission_get(
                    auth, "documents.view", active_section="orders"
                ):
                    return
                self._confirmation_fake_outbox(parts[1])
            elif parts == ["settings", "users"]:
                actor = self._settings_users_actor_or_forbidden(auth)
                if actor is None:
                    return
                assert auth_service is not None
                query = parse_qs(parsed.query)
                self._html(
                    render_users_list(
                        auth_service.list_accounts(actor),
                        status_filter=query.get("status", ["all"])[0],
                        role_filter=query.get("role", ["all"])[0],
                        flash=query.get("msg", [""])[0],
                        context=self._page_context(),
                    )
                )
            elif parts == ["settings", "users", "new"]:
                actor = self._settings_users_actor_or_forbidden(auth)
                if actor is None:
                    return
                self._html(
                    render_user_new(
                        actor=actor,
                        form={},
                        context=self._page_context(),
                    )
                )
            elif (
                len(parts) == 4
                and parts[0] == "settings"
                and parts[1] == "users"
                and parts[3] == "deactivate"
            ):
                actor = self._settings_users_actor_or_forbidden(auth)
                if actor is None:
                    return
                assert auth_service is not None
                account_id = unquote(parts[2])
                try:
                    detail = auth_service.get_account(actor, account_id)
                except (AuthorizationError, AccountNotFoundError):
                    self._settings_users_forbidden()
                    return
                self._html(
                    render_user_deactivate_confirm(
                        detail=detail,
                        context=self._page_context(),
                    )
                )
            elif len(parts) == 3 and parts[0] == "settings" and parts[1] == "users":
                actor = self._settings_users_actor_or_forbidden(auth)
                if actor is None:
                    return
                assert auth_service is not None
                account_id = unquote(parts[2])
                query = parse_qs(parsed.query)
                removed = [
                    item for item in query.get("removed", [""])[0].split(",") if item
                ]
                try:
                    detail = auth_service.get_account(actor, account_id)
                except (AuthorizationError, AccountNotFoundError):
                    self._settings_users_forbidden()
                    return
                self._html(
                    render_user_detail(
                        actor=actor,
                        detail=detail,
                        audit_events=self._settings_users_audit(actor, account_id),
                        flash=query.get("msg", [""])[0],
                        role_change_removed=removed or None,
                        context=self._page_context(),
                    )
                )
            else:
                self.send_error(404)

        def _resolve_print_projection(self, order_id: str, version_id: str):
            if remote is not None:
                return remote.print_data(order_id, version_id)
            return OrderPrintProjectionService(
                order_repo,
                panel._commercial_snapshots,
                local_confirmation_document_repo,
            ).resolve(order_id, version_id, intent="preview")

        def _resolve_buffet_cards_view(self, order_id: str, version_id: str):
            if remote is not None:
                return remote.buffet_cards_data(order_id, version_id)
            return BuffetCardsService(
                order_repo,
                OrderPrintProjectionService(
                    order_repo,
                    panel._commercial_snapshots,
                    local_confirmation_document_repo,
                ),
            ).resolve(order_id, version_id)

        def _print_sheet(self, order_id: str, query: str) -> None:
            version_id = parse_qs(query).get("version", [""])[0]
            if not version_id:
                self.send_error(404)
                return
            try:
                projection = self._resolve_print_projection(order_id, version_id)
            except (PrintProjectionNotFoundError, MissingCommercialSnapshotError):
                self.send_error(404)
                return
            if projection is None:
                self.send_error(404)
                return
            self._html(render_print_sheet(projection))

        def _buffet_cards(self, order_id: str, query: str) -> None:
            version_id = parse_qs(query).get("version", [""])[0]
            if not version_id:
                self.send_error(404)
                return
            try:
                view = self._resolve_buffet_cards_view(order_id, version_id)
            except (PrintProjectionNotFoundError, MissingCommercialSnapshotError):
                self.send_error(404)
                return
            if view is None:
                self.send_error(404)
                return
            self._html(
                render_buffet_cards(
                    view.projection,
                    view.cards,
                    effective_version_number=view.effective_version_number,
                )
            )

        def _confirmation_document_preview(self, order_id: str) -> None:
            try:
                if remote is not None:
                    html = remote.confirmation_document_service.preview_html(order_id)
                else:
                    snapshot = panel.confirmation_document_service.get_latest_snapshot(
                        order_id
                    )
                    if snapshot is None:
                        raise OrderConfirmationDocumentNotFoundError(order_id)
                    html = render_preview_html(build_preview(snapshot))
            except OrderConfirmationDocumentNotFoundError:
                self.send_error(404)
                return
            self._html(html)

        def _offer_document_pdf_download(self, offer_id: str, query: str) -> None:
            """Proxy the immutable ANGEBOT PDF to the browser. The Office API
            Bearer token is attached (remote mode) or never involved (direct
            mode) entirely server-side — this handler only ever forwards PDF
            bytes, never the token, to the client."""
            version_id = parse_qs(query).get("offer_version_id", [""])[0]
            if not version_id:
                self.send_error(404)
                return
            try:
                result = panel.offer_document_pdf(offer_id, version_id)
            except OfferPdfUnavailableError:
                self._error_page(
                    "Das PDF konnte nicht erzeugt werden — bitte Support kontaktieren.",
                    status=422,
                )
                return
            if result is None:
                self.send_error(404)
                return
            pdf_bytes, filename = result
            self._pdf_bytes(pdf_bytes, filename)

        def _confirmation_fake_outbox(self, order_id: str) -> None:
            try:
                message = panel.confirmation_outbound_service.fake_outbox_message(
                    order_id
                )
            except Exception:
                self.send_error(404)
                return
            body = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Testnachricht Fake Outbox</title></head><body>"
                "<p><strong>Testtransport — keine echte Zustellung.</strong></p>"
                f"<p>Betreff: {_e(message.subject)}</p>"
                "<h2>Text</h2>"
                f"<pre>{_e(message.text_body)}</pre>"
                "<h2>HTML</h2>"
                f"{message.html_body}"
                "</body></html>"
            )
            self._html(body)

        def do_POST(self) -> None:  # noqa: N802
            parts = [part for part in urlparse(self.path).path.split("/") if part]
            auth = self._resolve_request_auth()
            self._request_auth = auth
            if parts == ["login"]:
                try:
                    form = self._form()
                except FormBodyTooLargeError as exc:
                    self._error_page(str(exc), status=413)
                    return
                except (UnicodeDecodeError, ValueError) as exc:
                    self._error_page(str(exc), status=400)
                    return
                if validated_auth_mode == "basic":
                    self.send_error(404)
                    return
                assert auth_service is not None
                next_path = _safe_redirect_target(form.get("next", "/"))
                try:
                    result = auth_service.authenticate(
                        username=form.get("username", ""),
                        password=form.get("password", ""),
                    )
                except AuthenticationError:
                    self._render_login_page(
                        next_path=next_path,
                        error_message="Anmeldung fehlgeschlagen.",
                        status=401,
                    )
                    return
                self._redirect(
                    next_path,
                    cookie_headers=(
                        session_cookie_header(
                            result.session_token, secure=secure_cookie
                        ),
                        csrf_cookie_header(result.csrf_token, secure=secure_cookie),
                    ),
                )
                return
            if parts == ["logout"]:
                try:
                    form = self._form()
                except FormBodyTooLargeError as exc:
                    self._error_page(str(exc), status=413)
                    return
                except (UnicodeDecodeError, ValueError) as exc:
                    self._error_page(str(exc), status=400)
                    return
                if auth is None or auth.kind != "employee" or auth.employee is None:
                    if validated_auth_mode == "basic":
                        self._deny()
                    else:
                        self._redirect_to_login()
                    return
                try:
                    assert auth_service is not None
                    auth_service.validate_csrf(
                        auth.employee.session, form.get("_csrf_token", "")
                    )
                    auth_service.logout(auth.employee)
                except CsrfValidationError:
                    self._error_page(
                        "Ungültiger oder fehlender CSRF-Sicherheitstoken.", status=403
                    )
                    return
                self._redirect(
                    "/login",
                    cookie_headers=(
                        clear_cookie_header(
                            SESSION_COOKIE_NAME,
                            secure=secure_cookie,
                            http_only=True,
                        ),
                        clear_cookie_header(
                            CSRF_COOKIE_NAME,
                            secure=secure_cookie,
                            http_only=True,
                        ),
                    ),
                )
                return
            if parts == ["password-change"]:
                try:
                    form = self._form()
                except FormBodyTooLargeError as exc:
                    self._error_page(str(exc), status=413)
                    return
                except (UnicodeDecodeError, ValueError) as exc:
                    self._error_page(str(exc), status=400)
                    return
                if auth is None or auth.kind != "employee" or auth.employee is None:
                    if validated_auth_mode == "basic":
                        self._deny()
                    else:
                        self._redirect_to_login()
                    return
                try:
                    assert auth_service is not None
                    auth_service.validate_csrf(
                        auth.employee.session, form.get("_csrf_token", "")
                    )
                    auth_service.change_password(
                        auth.employee,
                        current_password=form.get("current_password", ""),
                        new_password=form.get("new_password", ""),
                    )
                except CsrfValidationError:
                    self._error_page(
                        "Ungültiger oder fehlender CSRF-Sicherheitstoken.", status=403
                    )
                    return
                except (AuthenticationError, ValueError):
                    self._render_password_change_page(
                        auth,
                        error_message="Passwort konnte nicht geändert werden.",
                        status=401,
                    )
                    return
                self._redirect(
                    "/login",
                    cookie_headers=(
                        clear_cookie_header(
                            SESSION_COOKIE_NAME,
                            secure=secure_cookie,
                            http_only=True,
                        ),
                        clear_cookie_header(
                            CSRF_COOKIE_NAME,
                            secure=secure_cookie,
                            http_only=True,
                        ),
                    ),
                )
                return
            if auth is None:
                if validated_auth_mode == "basic":
                    self._deny()
                else:
                    self._redirect_to_login()
                return
            if (
                auth.kind == "employee"
                and auth.employee is not None
                and not auth.employee.application_access_allowed
            ):
                self._redirect("/password-change")
                return
            if not self._require_auth2d2_post_permissions(parts, auth):
                return
            try:
                form = self._form()
            except FormBodyTooLargeError as exc:
                self._error_page(str(exc), status=413)
                return
            except (UnicodeDecodeError, ValueError) as exc:
                self._error_page(str(exc), status=400)
                return
            submitted_token = form.get("_csrf_token", "")
            if auth.kind == "employee":
                try:
                    assert auth.employee is not None
                    assert auth_service is not None
                    auth_service.validate_csrf(auth.employee.session, submitted_token)
                except CsrfValidationError:
                    self._error_page(
                        "Ungültiger oder fehlender CSRF-Sicherheitstoken.", status=403
                    )
                    return
            elif not hmac.compare_digest(submitted_token, csrf_token):
                self._error_page(
                    "Ungültiger oder fehlender CSRF-Sicherheitstoken.", status=403
                )
                return
            panel.begin_request(form)
            try:
                self._route_post(parts)
            except CatalogCommandError as exc:
                # CATALOG_ADMIN_PANEL_V1: carries its own status (404/409/422/
                # 400) so a catalog rejection keeps its meaning instead of
                # being flattened into the generic 400 below. Must precede the
                # ValueError branch — it is a ValueError subclass.
                self._error_page(
                    office_command_error_message(exc.code), status=exc.status
                )
            except RemoteCoreError as exc:
                self._remote_error_page(exc)
            except (ValueError, KeyError) as exc:
                self._error_page(inquiry_command_error_message(str(exc)))

        def _route_post(self, parts: list[str]) -> None:
            auth = self._request_auth
            if parts == ["inquiry", "new"]:
                inquiry = panel.create_inquiry(self._form())
                self._redirect(f"/inquiry/{inquiry.inquiry_id}")
            elif len(parts) == 3 and parts[0] == "inquiry":
                self._inquiry_action(parts[1], parts[2])
            elif len(parts) == 3 and parts[0] == "offer":
                self._offer_action(parts[1], parts[2])
            elif len(parts) == 3 and parts[0] == "order":
                self._order_action(parts[1], parts[2])
            elif (
                len(parts) == 4
                and parts[0] == "order"
                and parts[2] == "confirmation-document"
                and parts[3] == "send"
            ):
                panel.send_confirmation_test(parts[1], self._form())
                self._redirect(f"/order/{parts[1]}")
            elif parts == ["rueckruf", "resolve"]:
                call_id = self._form()["call_id"]
                resolve_missed_call(
                    auerswald_url,
                    auerswald_user,
                    auerswald_password,
                    call_id,
                )
                self._redirect("/rueckruf")
            elif parts == ["chat", "threads"]:
                self._create_chat_thread(auth)
            elif len(parts) == 3 and parts[0] == "chat" and parts[2] == "messages":
                self._send_chat_message(auth, unquote(parts[1]))
            elif len(parts) == 3 and parts[0] == "chat" and parts[2] == "read":
                self._mark_chat_read(auth, unquote(parts[1]))
            elif parts == ["gerichte", "new"]:
                self._create_catalog_dish()
            elif len(parts) == 3 and parts[0] == "gerichte" and parts[2] == "update":
                dish_id = parts[1]
                form = self._form()
                current = panel._catalog_detail_payload(dish_id)
                if current is None:
                    self.send_error(404)
                    return
                try:
                    authorize_catalog_update(
                        auth,
                        current=current,
                        form=form,
                    )
                except BusinessAccessDenied:
                    self._business_forbidden(active_section="catalog")
                    return
                panel.update_catalog_dish(dish_id, form)
                self._redirect(f"/gerichte/{dish_id}")
            elif (
                len(parts) == 3
                and parts[0] == "gerichte"
                and parts[2] in ("activate", "deactivate")
            ):
                panel.set_catalog_dish_active(
                    parts[1],
                    self._form(),
                    active=parts[2] == "activate",
                )
                self._redirect(f"/gerichte/{parts[1]}")
            elif len(parts) == 3 and parts[0] == "kontakt" and parts[2] == "notizen":
                contact_key = unquote(parts[1])
                panel.add_contact_note(contact_key, self._form())
                self._redirect(f"/kontakt/{quote(contact_key, safe='')}")
            elif parts == ["settings", "users"]:
                self._settings_users_create(auth)
            elif (
                len(parts) == 4
                and parts[0] == "settings"
                and parts[1] == "users"
                and parts[3] == "profile"
            ):
                self._settings_users_profile(auth, unquote(parts[2]))
            elif (
                len(parts) == 4
                and parts[0] == "settings"
                and parts[1] == "users"
                and parts[3] == "role"
            ):
                self._settings_users_role(auth, unquote(parts[2]))
            elif (
                len(parts) == 4
                and parts[0] == "settings"
                and parts[1] == "users"
                and parts[3] == "permissions"
            ):
                self._settings_users_permissions(auth, unquote(parts[2]))
            elif (
                len(parts) == 4
                and parts[0] == "settings"
                and parts[1] == "users"
                and parts[3] == "deactivate"
            ):
                self._settings_users_deactivate(auth, unquote(parts[2]))
            elif (
                len(parts) == 4
                and parts[0] == "settings"
                and parts[1] == "users"
                and parts[3] == "reactivate"
            ):
                self._settings_users_reactivate(auth, unquote(parts[2]))
            elif (
                len(parts) == 4
                and parts[0] == "settings"
                and parts[1] == "users"
                and parts[3] == "reset-password"
            ):
                self._settings_users_reset_password(auth, unquote(parts[2]))
            else:
                self.send_error(404)

        def _create_chat_thread(self, auth: OfficePanelRequestAuth | None) -> None:
            session_token = self._chat_employee_session_or_forbidden(auth)
            if session_token is None:
                return
            assert remote is not None
            form = self._form()
            thread = remote.create_chat_thread(
                employee_session_token=session_token,
                thread_type=form.get("thread_type", ""),
                participant_employee_ids=self._form_list("participant_employee_id"),
                title=form.get("title") or None,
                command_id=form.get("_command_id") or None,
            )
            self._redirect(f"/chat/{quote(str(thread['thread_id']), safe='')}")

        def _send_chat_message(
            self, auth: OfficePanelRequestAuth | None, thread_id: str
        ) -> None:
            session_token = self._chat_employee_session_or_forbidden(auth)
            if session_token is None:
                return
            assert remote is not None
            form = self._form()
            references = []
            for raw in self._form_list("reference"):
                reference_type, separator, reference_id = raw.partition(":")
                if separator:
                    references.append(
                        {
                            "reference_type": reference_type,
                            "reference_id": reference_id,
                        }
                    )
            remote.send_chat_message(
                thread_id,
                employee_session_token=session_token,
                body=form.get("body", ""),
                reply_to_message_id=form.get("reply_to_message_id") or None,
                mention_employee_ids=self._form_list("mention_employee_id"),
                references=references,
                command_id=form.get("_command_id") or None,
            )
            self._redirect(f"/chat/{quote(thread_id, safe='')}")

        def _mark_chat_read(
            self, auth: OfficePanelRequestAuth | None, thread_id: str
        ) -> None:
            session_token = self._chat_employee_session_or_forbidden(auth)
            if session_token is None:
                return
            assert remote is not None
            form = self._form()
            remote.mark_chat_thread_read(
                thread_id,
                employee_session_token=session_token,
                last_read_message_id=form.get("last_read_message_id") or None,
                command_id=form.get("_command_id") or None,
            )
            self._redirect(f"/chat/{quote(thread_id, safe='')}")

        def _settings_users_create(self, auth: OfficePanelRequestAuth | None) -> None:
            actor = self._settings_users_actor_or_forbidden(auth)
            if actor is None:
                return
            assert auth_service is not None
            form = self._form()
            selected = self._form_list("permission")
            role = form.get("role", "USER")
            try:
                target_role = validate_role(role)
            except ValueError as exc:
                self._html(
                    render_user_new(
                        actor=actor,
                        form=form,
                        selected_permissions=selected,
                        error_message=settings_users_error_message(exc),
                        context=self._page_context(),
                    ),
                    400,
                )
                return
            selectable, _disabled = permission_matrix_state(
                actor,
                target_role=target_role,
                target_read_only=False,
                explicit_permissions=set(),
                effective_permissions=set(),
            )
            permissions = parse_selected_permissions(selected, selectable)
            try:
                account = auth_service.create_account(
                    actor,
                    username=form.get("username", ""),
                    display_name=form.get("display_name", ""),
                    password=form.get("temporary_password", ""),
                    role=target_role,
                    email=form.get("email") or None,
                    explicit_permissions=permissions if permissions else None,
                    must_change_password=True,
                )
            except (
                AccountConflictError,
                AuthorizationError,
                LastActiveSuperadminError,
                ValueError,
            ) as exc:
                self._html(
                    render_user_new(
                        actor=actor,
                        form=form,
                        selected_permissions=selected,
                        error_message=settings_users_error_message(exc),
                        context=self._page_context(),
                    ),
                    403
                    if isinstance(exc, AuthorizationError)
                    else 400
                    if isinstance(exc, ValueError)
                    else 409,
                )
                return
            self._redirect(f"/settings/users/{quote(account.id, safe='')}?msg=created")

        def _settings_users_profile(
            self, auth: OfficePanelRequestAuth | None, account_id: str
        ) -> None:
            actor = self._settings_users_actor_or_forbidden(auth)
            if actor is None:
                return
            assert auth_service is not None
            form = self._form()
            try:
                auth_service.update_account_profile(
                    actor,
                    account_id,
                    username=form.get("username"),
                    display_name=form.get("display_name"),
                    email=form.get("email", ""),
                )
            except (
                AccountConflictError,
                AuthorizationError,
                AccountNotFoundError,
                ValueError,
                sqlite3.Error,
            ) as exc:
                try:
                    detail = auth_service.get_account(actor, account_id)
                except (AuthorizationError, AccountNotFoundError):
                    self._settings_users_forbidden()
                    return
                self._html(
                    render_user_detail(
                        actor=actor,
                        detail=detail,
                        audit_events=self._settings_users_audit(actor, account_id),
                        error_message=settings_users_error_message(exc),
                        context=self._page_context(),
                    ),
                    500
                    if isinstance(exc, sqlite3.Error)
                    else (409 if isinstance(exc, AccountConflictError) else 400),
                )
                return
            self._redirect(f"/settings/users/{quote(account_id, safe='')}?msg=saved")

        def _settings_users_role(
            self, auth: OfficePanelRequestAuth | None, account_id: str
        ) -> None:
            actor = self._settings_users_actor_or_forbidden(auth)
            if actor is None:
                return
            assert auth_service is not None
            form = self._form()
            new_role = form.get("role", "")
            try:
                before = auth_service.get_account(actor, account_id)
                auth_service.change_account_role(actor, account_id, new_role)
                after = auth_service.get_account(actor, account_id)
            except (
                AuthorizationError,
                LastActiveSuperadminError,
                AccountNotFoundError,
                ValueError,
            ) as exc:
                try:
                    detail = auth_service.get_account(actor, account_id)
                except (AuthorizationError, AccountNotFoundError):
                    self._settings_users_forbidden()
                    return
                self._html(
                    render_user_detail(
                        actor=actor,
                        detail=detail,
                        audit_events=self._settings_users_audit(actor, account_id),
                        error_message=settings_users_error_message(exc),
                        context=self._page_context(),
                    ),
                    400,
                )
                return
            removed = sorted(
                set(before.explicit_permissions).difference(after.explicit_permissions)
            )
            removed_query = ""
            if removed:
                removed_query = "&removed=" + quote(",".join(removed), safe="")
            self._redirect(
                f"/settings/users/{quote(account_id, safe='')}?msg=role_changed{removed_query}"
            )

        def _settings_users_permissions(
            self, auth: OfficePanelRequestAuth | None, account_id: str
        ) -> None:
            actor = self._settings_users_actor_or_forbidden(auth)
            if actor is None:
                return
            assert auth_service is not None
            selected = self._form_list("permission")
            try:
                detail = auth_service.get_account(actor, account_id)
                selectable, _disabled = permission_matrix_state(
                    actor,
                    target_role=detail.role,
                    target_read_only=detail.read_only,
                    explicit_permissions=set(detail.explicit_permissions),
                    effective_permissions=set(detail.effective_permissions),
                )
                permissions = parse_selected_permissions(selected, selectable)
                auth_service.set_account_permissions(actor, account_id, permissions)
            except (
                AuthorizationError,
                AccountNotFoundError,
                ValueError,
            ) as exc:
                try:
                    detail = auth_service.get_account(actor, account_id)
                except (AuthorizationError, AccountNotFoundError):
                    self._settings_users_forbidden()
                    return
                self._html(
                    render_user_detail(
                        actor=actor,
                        detail=detail,
                        audit_events=self._settings_users_audit(actor, account_id),
                        error_message=settings_users_error_message(exc),
                        context=self._page_context(),
                    ),
                    400,
                )
                return
            self._redirect(
                f"/settings/users/{quote(account_id, safe='')}?msg=permissions_saved"
            )

        def _settings_users_deactivate(
            self, auth: OfficePanelRequestAuth | None, account_id: str
        ) -> None:
            actor = self._settings_users_actor_or_forbidden(auth)
            if actor is None:
                return
            assert auth_service is not None
            try:
                auth_service.deactivate_account(actor, account_id)
            except (
                AuthorizationError,
                LastActiveSuperadminError,
                AccountNotFoundError,
                sqlite3.Error,
            ) as exc:
                try:
                    detail = auth_service.get_account(actor, account_id)
                except (AuthorizationError, AccountNotFoundError):
                    self._settings_users_forbidden()
                    return
                self._html(
                    render_user_deactivate_confirm(
                        detail=detail,
                        error_message=settings_users_error_message(exc),
                        context=self._page_context(),
                    ),
                    500 if isinstance(exc, sqlite3.Error) else 400,
                )
                return
            self._redirect("/settings/users?msg=deactivated")

        def _settings_users_reactivate(
            self, auth: OfficePanelRequestAuth | None, account_id: str
        ) -> None:
            actor = self._settings_users_actor_or_forbidden(auth)
            if actor is None:
                return
            assert auth_service is not None
            try:
                auth_service.reactivate_account(actor, account_id)
            except (AuthorizationError, AccountNotFoundError) as exc:
                try:
                    detail = auth_service.get_account(actor, account_id)
                except (AuthorizationError, AccountNotFoundError):
                    self._settings_users_forbidden()
                    return
                self._html(
                    render_user_detail(
                        actor=actor,
                        detail=detail,
                        audit_events=self._settings_users_audit(actor, account_id),
                        error_message=settings_users_error_message(exc),
                        context=self._page_context(),
                    ),
                    400,
                )
                return
            self._redirect(
                f"/settings/users/{quote(account_id, safe='')}?msg=reactivated"
            )

        def _settings_users_reset_password(
            self, auth: OfficePanelRequestAuth | None, account_id: str
        ) -> None:
            actor = self._settings_users_actor_or_forbidden(auth)
            if actor is None:
                return
            assert auth_service is not None
            form = self._form()
            password = form.get("temporary_password", "")
            confirm = form.get("temporary_password_confirm", "")
            if password != confirm:
                try:
                    detail = auth_service.get_account(actor, account_id)
                except (AuthorizationError, AccountNotFoundError):
                    self._settings_users_forbidden()
                    return
                self._html(
                    render_user_detail(
                        actor=actor,
                        detail=detail,
                        audit_events=self._settings_users_audit(actor, account_id),
                        error_message="Die Passwortbestätigung stimmt nicht überein.",
                        context=self._page_context(),
                    ),
                    400,
                )
                return
            try:
                auth_service.reset_account_password(
                    actor,
                    account_id,
                    temporary_password=password,
                )
            except (
                AuthorizationError,
                AccountNotFoundError,
                ValueError,
                sqlite3.Error,
            ) as exc:
                try:
                    detail = auth_service.get_account(actor, account_id)
                except (AuthorizationError, AccountNotFoundError):
                    self._settings_users_forbidden()
                    return
                self._html(
                    render_user_detail(
                        actor=actor,
                        detail=detail,
                        audit_events=self._settings_users_audit(actor, account_id),
                        error_message=settings_users_error_message(exc),
                        context=self._page_context(),
                    ),
                    500 if isinstance(exc, sqlite3.Error) else 400,
                )
                return
            self._redirect(
                f"/settings/users/{quote(account_id, safe='')}?msg=password_reset"
            )

        def _create_catalog_dish(self) -> None:
            """CATALOG_ADMIN_PANEL_V1: a rejected create re-renders the form
            with the submitted values and the German reason, rather than the
            generic error page — the operator would otherwise lose everything
            they typed. Unavailability keeps the shared 503 path."""
            form = self._form()
            try:
                dish_id = panel.create_catalog_dish(form)
            except CatalogCommandError as exc:
                self._html(
                    panel.render_gericht_new(
                        context=self._page_context(),
                        form=form,
                        error_message=office_command_error_message(exc.code),
                    ),
                    exc.status,
                )
                return
            except RemoteCoreError as exc:
                self._remote_error_page(exc)
                return
            except (ValueError, KeyError) as exc:
                self._html(
                    panel.render_gericht_new(
                        context=self._page_context(),
                        form=form,
                        error_message=office_command_error_message(str(exc)),
                    ),
                    400,
                )
                return
            self._redirect(f"/gerichte/{quote(dish_id, safe='')}")

        def _inquiry_action(self, inquiry_id: str, action: str) -> None:
            if action == "update":
                panel.update_inquiry(inquiry_id, self._form())
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "contact-completion":
                panel.complete_inquiry_contacts(inquiry_id, self._form())
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "customer-addresses":
                form = self._form()
                panel.set_inquiry_customer_addresses(inquiry_id, form)
                return_order_id = form.get("return_order_id", "").strip()
                if return_order_id:
                    self._redirect(f"/order/{return_order_id}")
                else:
                    self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "fulfillment-mode":
                form = self._form()
                panel.set_inquiry_fulfillment_mode(inquiry_id, form)
                return_order_id = form.get("return_order_id", "").strip()
                if return_order_id:
                    self._redirect(f"/order/{return_order_id}")
                else:
                    self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "verify":
                panel.inquiry_service.verify_customer_by_call(inquiry_id)
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "convert":
                order, _initial_version = panel.convert_inquiry_to_order(inquiry_id)
                self._redirect(f"/order/{order.order_id}")
            elif action == "convert-accepted":
                order, _initial_version = panel.convert_accepted_offer_for_inquiry(
                    inquiry_id
                )
                self._redirect(f"/order/{order.order_id}")
            else:
                self.send_error(404)

        def _offer_action(self, offer_id: str, action: str) -> None:
            form = self._form()
            if action == "mark-sent":
                panel.mark_offer_sent(offer_id, form)
                self._redirect(f"/offer/{offer_id}")
            elif action == "record-acceptance":
                panel.record_offer_acceptance(offer_id, form)
                self._redirect(f"/offer/{offer_id}")
            elif action == "record-rejection":
                panel.record_offer_rejection(offer_id, form)
                self._redirect(f"/offer/{offer_id}")
            elif action == "record-withdrawal":
                panel.record_offer_withdrawal(offer_id, form)
                self._redirect(f"/offer/{offer_id}")
            elif action == "convert":
                order, _version = panel.convert_accepted_offer(offer_id, form)
                self._redirect(f"/order/{order.order_id}")
            else:
                self.send_error(404)

        def _delete_order(self, order_id: str) -> None:
            auth = self._request_auth
            if (
                auth is None
                or auth.kind != "employee"
                or auth.employee is None
                or auth.legacy_shared_access
                or auth.employee.account.role != "SUPERADMIN"
            ):
                self._business_forbidden(active_section="orders")
                return
            if remote is not None:
                raise ValueError("order_delete_unavailable")
            order = order_repo.get_order(order_id)
            if order is None:
                raise KeyError(order_id)
            versions = order_repo.list_order_versions(order_id)
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
            if target is None:
                raise ValueError("order_delete_name_unavailable")
            operational_data = panel._order_detail_operational_data(
                order_id, target.order_version_id
            )
            expected_name = (
                operational_data.company_name or operational_data.contact_name or ""
            ).strip()
            if not expected_name:
                raise ValueError("order_delete_name_unavailable")
            submitted_name = self._form().get("confirmation_name", "").strip()
            if not hmac.compare_digest(submitted_name, expected_name):
                raise ValueError("order_delete_confirmation_mismatch")

            def work() -> None:
                purge_order_with_dependencies(order_repo, order_id)

            if command_executor is not None:
                command_executor.run(work)
            else:
                work()
            self._redirect("/orders")

        def _order_action(self, order_id: str, action: str) -> None:
            if action == "version":
                panel.create_version(order_id, self._form())
            elif action == "delivery-address":
                panel.change_delivery_address(order_id, self._form())
            elif action == "print-confirm":
                form = self._form()
                _ = form["order_version_id"]
                panel.request_kitchen_print(order_id, form)
            elif action == "effective":
                panel.core.make_order_version_effective(
                    order_id, self._form()["order_version_id"]
                )
            elif action == "ready":
                panel.core.request_ready_to_send(order_id)
            elif action == "cancel":
                panel.core.cancel_order(order_id)
            elif action == "delete":
                self._delete_order(order_id)
                return
            elif action == "payment-reminder":
                panel.save_payment_reminder(order_id, self._form())
            elif action == "confirmation-document":
                panel.prepare_confirmation_document(order_id, self._form())
            elif action == "pause":
                panel.pause_order(order_id, self._form())
            elif action == "resume":
                panel.resume_order(order_id, self._form())
            else:
                self.send_error(404)
                return
            self._redirect(f"/order/{order_id}")

    return OfficePanelHandler


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
    auth_mode: OfficePanelAuthMode = "basic",
    auth_service: EmployeeAuthService | None = None,
    secure_cookie: bool = True,
) -> HTTPServer:
    """Create the intentionally single-threaded office HTTP server."""
    return HTTPServer(
        (host, port),
        make_office_panel_handler(
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
            offer_document_repo=offer_document_repo,
            offer_pdf_static_content=offer_pdf_static_content,
            kitchen_print_job_repo=kitchen_print_job_repo,
            ui_version=ui_version,
            auth_mode=auth_mode,
            auth_service=auth_service,
            secure_cookie=secure_cookie,
        ),
    )

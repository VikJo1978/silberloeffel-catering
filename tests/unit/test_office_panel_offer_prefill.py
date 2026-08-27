from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from catering_system.domain.configurator_handoff import ConfiguratorHandoffRecord
from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import (
    Inquiry,
    InquiryOfferProjection,
    InquiryOfficeState,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot,
)
from catering_system.repositories import (
    sqlite_configurator_handoff_repository as handoff_repo_module,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_configurator_handoff_repository import (
    SQLiteConfiguratorHandoffRepository,
    _apply_migrations_in_current_transaction,
    _validate_operation,
)
from catering_system.services.configurator_handoff_service import (
    ConfiguratorHandoffService,
)
from catering_system.ui.office_panel import OfficePanel
from catering_system.ui.office_panel_inquiry_detail import (
    InquiryDetailFormFields,
    render_inquiry_detail,
)
from catering_system.ui.office_panel_offer_prefill import (
    build_configurator_handoff_url,
    build_offer_prefill_url,
    normalize_configurator_url,
    offer_prefill_payload,
)
from catering_system.ui.office_panel_views import OfficePageContext
from tests.helpers.office_panel_context import legacy_office_context


def _employee_context(account_id: str = "employee-1"):
    return OfficePageContext(
        legacy_shared_access=False,
        employee_account_id=account_id,
        employee_effective_permissions=frozenset({"offers.prepare"}),
    )


def _handoff_service(db_path: Path) -> ConfiguratorHandoffService:
    return ConfiguratorHandoffService(SQLiteConfiguratorHandoffRepository(db_path))


def _handoff_record(
    *,
    token_hash: str = "hash-1",
    consumed_at: datetime | None = None,
    consumed_by_account_id: str | None = None,
) -> ConfiguratorHandoffRecord:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    return ConfiguratorHandoffRecord(
        id="handoff-1",
        token_hash=token_hash,
        operation="prepare_first_offer",
        inquiry_id="11111111-1111-1111-1111-111111111111",
        issued_for_account_id="employee-1",
        issued_at=now,
        expires_at=now,
        consumed_at=consumed_at,
        consumed_by_account_id=consumed_by_account_id,
    )


def _inquiry(*, guest_count: int | None = 42) -> Inquiry:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=date(2026, 10, 3),
        created_at=now,
        updated_at=now,
        inquiry_source="website_form",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:30–23:00",
        location_text="Große Bleichen 1, Hamburg",
        guest_count_estimate=guest_count,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_subject="Möbel & Mehr GmbH — Jubiläum",
        intake_message=(
            "Firma: Möbel & Mehr GmbH\n"
            "Name: Jörg Weiß\n"
            "Veranstaltungsart: Jubiläum\n"
            "Telefon: 040 12345\n"
            "E-Mail: joerg@example.test\n"
            "Wunsch: Vegetarisch & glutenfrei"
        ),
        intake_summary="Website-Anfrage — 42 Personen, 2026-10-03",
        intake_external_ref="web-test-42",
        customer_snapshot=InquiryCustomerSnapshot(
            email="joerg@example.test",
            phone="040 12345",
        ),
    )


def test_payload_maps_labelled_context_without_creating_core_records() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    inquiry = _inquiry()
    inquiry_repo.save(inquiry)

    panel = OfficePanel(
        inquiry_repo,
        order_repo,
        configurator_url="http://127.0.0.1:5173",
    )
    page = panel.render_inquiry(inquiry.inquiry_id, context=legacy_office_context())

    assert page is not None
    assert "Angebot mit Anfragedaten vorbereiten" in page
    assert 'href="http://127.0.0.1:5173/#core-inquiry=' in page
    assert "Authorization" not in page
    assert "CORE_OFFICE_API_TOKEN" not in page
    assert "offer_snapshot_v" not in page
    assert "snapshot_hash" not in page
    assert order_repo.list_orders() == []

    payload = offer_prefill_payload(inquiry)
    transfer = payload["transfer"]
    assert isinstance(transfer, dict)
    planning = transfer["planning"]
    context = transfer["orderContextPrefill"]
    assert planning["persons"] == 42
    assert planning["eventType"] == "Jubiläum"
    assert context["companyName"] == "Möbel & Mehr GmbH"
    assert context["contactPerson"] == "Jörg Weiß"
    assert context["email"] == "joerg@example.test"
    assert context["phone"] == "040 12345"
    assert context["eventDate"] == "2026-10-03"


def test_fragment_maps_structured_customer_snapshot_and_all_event_fields() -> None:
    inquiry = replace(
        _inquiry(),
        intake_message=(
            "Veranstaltungsart: Jubiläum\n"
            "Wunsch: Vegetarisch & glutenfrei\n"
            "Zusätzlicher Anfragekontext"
        ),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="Strukturierte Firma GmbH",
            contact_name="Strukturierter Kontakt",
            email="structured@example.test",
            phone="+49 40 98765",
        ),
    )

    url = build_offer_prefill_url("https://angebote.example.test", inquiry)
    request_url, fragment = url.split("#", 1)
    encoded = fragment.split("=", 1)[1]
    padded = encoded + "=" * (-len(encoded) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))

    assert request_url == "https://angebote.example.test/"
    assert decoded["transfer"]["orderContextPrefill"] == {
        "companyName": "Strukturierte Firma GmbH",
        "contactPerson": "Strukturierter Kontakt",
        "email": "structured@example.test",
        "phone": "+49 40 98765",
        "eventDate": "2026-10-03",
        "eventTime": "18:30–23:00",
        "location": "Große Bleichen 1, Hamburg",
        "billingAddress": "",
        "remarks": (
            "Betreff: Möbel & Mehr GmbH — Jubiläum\n\n"
            "Wunsch: Vegetarisch & glutenfrei\n\n"
            "Zusätzlicher Anfragekontext\n\n"
            "Zusammenfassung: Website-Anfrage — 42 Personen, 2026-10-03"
        ),
    }


def test_fulfillment_and_structured_addresses_are_carried_into_handoff() -> None:
    inquiry = replace(
        _inquiry(),
        fulfillment_mode="DELIVERY",
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="Muster GmbH",
            contact_name="Max Muster",
            email="max@example.test",
            phone="+49 40 12345",
            invoice_address=CustomerAddress(
                street="Rechnungsweg 7",
                postal_code="22549",
                city="Hamburg",
                country="DE",
            ),
            delivery_address=CustomerAddress(
                street="Festplatz 3",
                postal_code="22765",
                city="Hamburg",
                country="DE",
            ),
            delivery_address_mode="SEPARATE",
        ),
    )

    transfer = offer_prefill_payload(inquiry)["transfer"]

    assert transfer["orderContextPrefill"]["billingAddress"] == (
        "Rechnungsweg 7, 22549 Hamburg, DE"
    )
    assert transfer["fulfillmentPrefill"] == {
        "fulfillmentMode": "DELIVERY",
        "deliveryAddressMode": "SEPARATE",
        "invoiceAddress": {
            "street": "Rechnungsweg 7",
            "postalCode": "22549",
            "city": "Hamburg",
            "country": "DE",
        },
        "deliveryAddress": {
            "street": "Festplatz 3",
            "postalCode": "22765",
            "city": "Hamburg",
            "country": "DE",
        },
    }


def test_unknown_fulfillment_is_explicit_without_inventing_addresses() -> None:
    transfer = offer_prefill_payload(_inquiry())["transfer"]

    assert transfer["fulfillmentPrefill"] == {
        "fulfillmentMode": "UNKNOWN",
        "deliveryAddressMode": "UNKNOWN",
        "invoiceAddress": {
            "street": "",
            "postalCode": "",
            "city": "",
            "country": "",
        },
        "deliveryAddress": {
            "street": "",
            "postalCode": "",
            "city": "",
            "country": "",
        },
    }


def test_structured_customer_snapshot_precedes_legacy_labelled_contact() -> None:
    inquiry = replace(
        _inquiry(),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="Structured Company",
            contact_name="Structured Contact",
            email="structured@example.test",
            phone="+49 40 98765",
        ),
    )

    context = offer_prefill_payload(inquiry)["transfer"]["orderContextPrefill"]

    assert context["companyName"] == "Structured Company"
    assert context["contactPerson"] == "Structured Contact"
    assert context["email"] == "structured@example.test"
    assert context["phone"] == "+49 40 98765"


def test_fragment_round_trip_preserves_unicode_and_stays_out_of_request_url() -> None:
    url = build_offer_prefill_url("https://angebote.example.test/app/", _inquiry())
    request_url, fragment = url.split("#", 1)
    assert request_url == "https://angebote.example.test/app"
    assert "Jörg" not in request_url
    assert fragment.startswith("core-inquiry=")

    encoded = fragment.split("=", 1)[1]
    padded = encoded + "=" * (-len(encoded) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    assert decoded["schema_version"] == "core_inquiry_offer_prefill_v1"
    assert decoded["transfer"]["orderContextPrefill"]["contactPerson"] == "Jörg Weiß"


def test_employee_mode_first_offer_uses_core_handoff_only(tmp_path: Path) -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    inquiry = _inquiry()
    inquiry_repo.save(inquiry)
    panel = OfficePanel(
        inquiry_repo,
        order_repo,
        configurator_url="https://angebote.example.test/app",
        configurator_handoff_service=_handoff_service(tmp_path / "handoff.db"),
    )

    page = panel.render_inquiry(inquiry.inquiry_id, context=_employee_context())

    assert page is not None
    assert 'href="https://angebote.example.test/app#core-handoff=' in page
    assert "#core-inquiry=" not in page
    assert inquiry.inquiry_id not in page


def test_raw_handoff_code_is_not_stored_in_db(tmp_path: Path) -> None:
    service = _handoff_service(tmp_path / "handoff.db")
    minted = service.mint_first_offer(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        issued_for_account_id="employee-1",
    )

    row = (
        sqlite3.connect(tmp_path / "handoff.db")
        .execute(
            "SELECT token_hash FROM configurator_handoffs WHERE id = ?",
            (minted.record.id,),
        )
        .fetchone()
    )

    assert row is not None
    assert row[0] != minted.code
    assert minted.code not in row[0]


def test_build_configurator_handoff_url_uses_opaque_fragment_only() -> None:
    url = build_configurator_handoff_url(
        "https://angebote.example.test/app/",
        "opaque-code-123",
    )

    assert url == "https://angebote.example.test/app#core-handoff=opaque-code-123"


def test_blank_configurator_url_returns_empty_prefill_and_handoff_urls() -> None:
    assert build_offer_prefill_url("", _inquiry()) == ""
    assert build_configurator_handoff_url("", "opaque-code-123") == ""


def test_handoff_repository_commits_add_and_consume_from_shared_connection() -> None:
    connection = sqlite3.connect(":memory:")
    repository = SQLiteConfiguratorHandoffRepository.from_connection(connection)
    record = _handoff_record()
    consumed_at = datetime(2026, 7, 13, 13, tzinfo=UTC)

    repository.add(record)
    assert repository.get_by_token_hash(record.token_hash) == record

    assert repository.consume(
        handoff_id=record.id,
        consumed_at=consumed_at,
        consumed_by_account_id="employee-2",
    )

    consumed = repository.get_by_token_hash(record.token_hash)
    assert consumed is not None
    assert consumed.consumed_at == consumed_at
    assert consumed.consumed_by_account_id == "employee-2"
    connection.close()


def test_handoff_repository_file_backed_consume_commits_and_lookup_miss(
    tmp_path: Path,
) -> None:
    repository = SQLiteConfiguratorHandoffRepository(tmp_path / "handoff.db")
    record = _handoff_record(token_hash="hash-2")

    repository.add(record)
    assert repository.get_by_token_hash("missing-hash") is None
    assert repository.consume(
        handoff_id=record.id,
        consumed_at=datetime(2026, 7, 13, 14, tzinfo=UTC),
        consumed_by_account_id="employee-3",
    )

    repository.close()


def test_handoff_repository_rejects_unknown_operation_and_migration_name_mismatch() -> (
    None
):
    with pytest.raises(ValueError, match="unknown configurator handoff operation"):
        _validate_operation("unexpected")

    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (component, version)
        )
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations (component, version, name, applied_at) "
        "VALUES (?, ?, ?, ?)",
        ("configurator_handoff", 1, "wrong_name", "2026-07-13T12:00:00Z"),
    )

    with pytest.raises(RuntimeError, match="name mismatch"):
        _apply_migrations_in_current_transaction(connection)

    connection.close()


def test_handoff_repository_closes_connection_when_migration_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    fake_connection = FakeConnection()
    monkeypatch.setattr(
        handoff_repo_module.sqlite3,
        "connect",
        lambda _path: fake_connection,
    )
    monkeypatch.setattr(
        handoff_repo_module,
        "apply_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        SQLiteConfiguratorHandoffRepository("handoff.db")

    assert fake_connection.closed is True


def test_handoff_service_consume_updates_record_and_rejects_replay() -> None:
    class StubRepository:
        def __init__(self) -> None:
            self.calls: list[tuple[str, datetime, str]] = []
            self.result = True

        def consume(
            self,
            *,
            handoff_id: str,
            consumed_at: datetime,
            consumed_by_account_id: str,
        ) -> bool:
            self.calls.append((handoff_id, consumed_at, consumed_by_account_id))
            return self.result

    consumed_at = datetime(2026, 7, 13, 13, tzinfo=UTC)
    repository = StubRepository()
    service = ConfiguratorHandoffService(repository, now=lambda: consumed_at)
    record = _handoff_record()

    consumed = service.consume(record=record, consumed_by_account_id="employee-2")

    assert repository.calls == [(record.id, consumed_at, "employee-2")]
    assert consumed.consumed_at == consumed_at
    assert consumed.consumed_by_account_id == "employee-2"

    repository.result = False
    with pytest.raises(RuntimeError, match="already consumed"):
        service.consume(record=record, consumed_by_account_id="employee-2")


def test_handoff_service_lookup_round_trips_minted_code(tmp_path: Path) -> None:
    service = _handoff_service(tmp_path / "handoff.db")
    minted = service.mint_first_offer(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        issued_for_account_id="employee-1",
    )

    assert service.lookup(minted.code) == minted.record
    assert service.lookup("missing-code") is None


def test_unknown_guest_count_remains_null() -> None:
    payload = offer_prefill_payload(_inquiry(guest_count=None))
    assert payload["transfer"]["planning"]["persons"] is None


@pytest.mark.parametrize(
    "value",
    [
        "ftp://configurator.example.test",
        "http://user:secret@configurator.example.test",
        "http://configurator.example.test?token=secret",
        "http://configurator.example.test#existing",
        "relative/path",
    ],
)
def test_invalid_configurator_url_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_configurator_url(value)


def test_empty_configurator_url_keeps_handoff_dormant() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    inquiry_repo.save(_inquiry())
    page = OfficePanel(inquiry_repo, order_repo).render_inquiry(
        "11111111-1111-1111-1111-111111111111",
        context=legacy_office_context(),
    )
    assert page is not None
    assert "Angebot mit Anfragedaten vorbereiten" not in page
    assert "Der Angebotskonfigurator ist derzeit nicht verfügbar" in page


@pytest.mark.parametrize(
    ("configurator_url", "expected"),
    [
        ("https://angebote.example.test", "Angebot vorbereiten</a>"),
        ("", "Der Angebotskonfigurator ist derzeit nicht verfügbar"),
    ],
)
def test_v2_inquiry_detail_has_action_or_safe_unavailable_state(
    configurator_url: str,
    expected: str,
) -> None:
    inquiry_repo = InMemoryInquiryRepository()
    inquiry = _inquiry()
    inquiry_repo.save(inquiry)
    page = OfficePanel(
        inquiry_repo,
        InMemoryOrderRepository(),
        configurator_url=configurator_url,
        ui_version="v2",
    ).render_inquiry(inquiry.inquiry_id, context=legacy_office_context())

    assert page is not None
    assert expected in page


def test_blocked_inquiry_never_renders_configurator_link() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    inquiry = replace(
        _inquiry(),
        call_verification_required=True,
        call_verification_status="pending",
    )
    inquiry_repo.save(inquiry)
    page = OfficePanel(
        inquiry_repo,
        order_repo,
        configurator_url="https://angebote.example.test",
    ).render_inquiry(inquiry.inquiry_id, context=legacy_office_context())

    assert page is not None
    assert "https://angebote.example.test" not in page


def test_existing_offer_links_to_core_detail_instead_of_configurator() -> None:
    inquiry = _inquiry()
    offer_id = "22222222-2222-4222-8222-222222222222"
    state = InquiryOfficeState(
        is_open=True,
        next_action="offer-pending",
        offer=InquiryOfferProjection(
            offer_id=offer_id,
            offer_version_id="33333333-3333-4333-8333-333333333333",
            commercial_state="Prepared",
        ),
        offer_preparation_blockers=("offer_already_exists",),
    )
    detail = render_inquiry_detail(
        inquiry,
        [],
        state,
        state.offer_preparation_blockers,
        forms=InquiryDetailFormFields(
            csrf_input="",
            primary_command_fields="",
            update_command_fields="",
        ),
        offer_url="https://angebote.example.test#must-not-render",
    )

    assert f'href="/offer/{offer_id}"' in detail.body
    assert "Angebot öffnen" in detail.body
    assert "angebote.example.test" not in detail.body

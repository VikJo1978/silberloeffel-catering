"""Seed realistic pre-production workflow data for customer demos.

This is deliberately a maintenance/demo tool, not an application write path.
It refuses to run when Inquiry/Offer/Order data already exists and leaves
employee accounts, permissions, catalog, production configuration and chat
untouched.
"""

from __future__ import annotations

import argparse
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.offer import derive_offer_state
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.repositories.core_transaction import open_core_connection
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.offer_service import OfferService


@dataclass(frozen=True)
class WorkflowCase:
    company: str
    contact: str
    email_slug: str
    phone: str
    event_title: str
    event_date_offset: int
    event_start: time
    delivery_time: time | None
    location: str
    invoice_address: CustomerAddress
    delivery_address: CustomerAddress | None
    guests: int
    source: str
    crm_stage: str
    fulfillment_mode: str
    delivery_address_mode: str
    call_verification_required: bool = False
    call_verification_status: str = "not_required"
    payment_method: str = "RECHNUNG"
    payment_text: str = "Zahlung per Rechnung innerhalb von 14 Tagen."


@dataclass(frozen=True)
class SeedSummary:
    inquiries: int
    offers: int
    orders: int
    offer_states: tuple[str, ...]


def _address(street: str, postal_code: str) -> CustomerAddress:
    return CustomerAddress(
        street=street,
        postal_code=postal_code,
        city="Hamburg",
        country="Deutschland",
    )


def _cases() -> tuple[WorkflowCase, ...]:
    return (
        WorkflowCase(
            company="Alster Digital GmbH",
            contact="Lena Hoffmann",
            email_slug="alster-digital",
            phone="+49405550101",
            event_title="Team-Lunch",
            event_date_offset=8,
            event_start=time(12, 30),
            delivery_time=None,
            location="Hamburg-Winterhude",
            invoice_address=_address("Barmbeker Straße 18", "22303"),
            delivery_address=None,
            guests=35,
            source="phone_by_office",
            crm_stage="Neue Anfrage",
            fulfillment_mode="PICKUP",
            delivery_address_mode="SAME_AS_INVOICE",
            call_verification_required=True,
            call_verification_status="pending",
            payment_method="BAR_VOR_ORT",
            payment_text="Barzahlung bei Abholung.",
        ),
        WorkflowCase(
            company="HafenCity Labs GmbH",
            contact="Jonas Krüger",
            email_slug="hafencity-labs",
            phone="+49405550102",
            event_title="Projekt-Kick-off",
            event_date_offset=12,
            event_start=time(17, 0),
            delivery_time=time(15, 45),
            location="Hamburg-HafenCity",
            invoice_address=_address("Brooktorkai 16", "20457"),
            delivery_address=_address("Am Sandtorkai 32", "20457"),
            guests=60,
            source="website_form",
            crm_stage="In Prüfung",
            fulfillment_mode="DELIVERY",
            delivery_address_mode="SEPARATE",
            call_verification_required=True,
            call_verification_status="verified",
        ),
        WorkflowCase(
            company="Nordlicht Architektur GmbH",
            contact="Miriam Petersen",
            email_slug="nordlicht-architektur",
            phone="+49405550103",
            event_title="Büro-Jubiläum",
            event_date_offset=17,
            event_start=time(18, 30),
            delivery_time=time(17, 0),
            location="Hamburg-Eppendorf",
            invoice_address=_address("Eppendorfer Weg 88", "20259"),
            delivery_address=None,
            guests=25,
            source="email",
            crm_stage="Vorschlag vorbereiten",
            fulfillment_mode="DELIVERY",
            delivery_address_mode="SAME_AS_INVOICE",
        ),
        WorkflowCase(
            company="Elbkontor Logistik GmbH",
            contact="Patrick Neumann",
            email_slug="elbkontor-logistik",
            phone="+49405550104",
            event_title="Kundenevent",
            event_date_offset=22,
            event_start=time(19, 0),
            delivery_time=time(17, 15),
            location="Hamburg-Altona",
            invoice_address=_address("Große Bergstraße 154", "22767"),
            delivery_address=_address("Museumstraße 23", "22765"),
            guests=90,
            source="configurator",
            crm_stage="Angebot in Bearbeitung",
            fulfillment_mode="DELIVERY",
            delivery_address_mode="SEPARATE",
        ),
        WorkflowCase(
            company="Speicherstadt Medien GmbH",
            contact="Sophie Brandt",
            email_slug="speicherstadt-medien",
            phone="+49405550105",
            event_title="Herbstempfang",
            event_date_offset=28,
            event_start=time(18, 0),
            delivery_time=time(16, 30),
            location="Hamburg-Speicherstadt",
            invoice_address=_address("Willy-Brandt-Straße 45", "20457"),
            delivery_address=_address("Bei St. Annen 1", "20457"),
            guests=120,
            source="email",
            crm_stage="Angebot gesendet / Rückmeldung offen",
            fulfillment_mode="DELIVERY",
            delivery_address_mode="SEPARATE",
        ),
        WorkflowCase(
            company="HanseWerkstatt GmbH",
            contact="Daniel Köhler",
            email_slug="hansewerkstatt",
            phone="+49405550106",
            event_title="Mitarbeiterabend",
            event_date_offset=31,
            event_start=time(18, 30),
            delivery_time=time(17, 0),
            location="Hamburg-Barmbek",
            invoice_address=_address("Fuhlsbüttler Straße 112", "22305"),
            delivery_address=None,
            guests=55,
            source="website_form",
            crm_stage="Angebot gesendet / Rückmeldung offen",
            fulfillment_mode="DELIVERY",
            delivery_address_mode="SAME_AS_INVOICE",
        ),
        WorkflowCase(
            company="Fleetblick Consulting GmbH",
            contact="Nina Scholz",
            email_slug="fleetblick-consulting",
            phone="+49405550107",
            event_title="Strategie-Workshop",
            event_date_offset=36,
            event_start=time(16, 0),
            delivery_time=time(14, 30),
            location="Hamburg-Neustadt",
            invoice_address=_address("Große Bleichen 21", "20354"),
            delivery_address=None,
            guests=40,
            source="email",
            crm_stage="Angebot gesendet / Rückmeldung offen",
            fulfillment_mode="DELIVERY",
            delivery_address_mode="SAME_AS_INVOICE",
        ),
        WorkflowCase(
            company="Bergedorfer Technik GmbH",
            contact="Tobias Hartmann",
            email_slug="bergedorfer-technik",
            phone="+49405550108",
            event_title="Sommerfest Nachfeier",
            event_date_offset=43,
            event_start=time(17, 30),
            delivery_time=time(15, 45),
            location="Hamburg-Bergedorf",
            invoice_address=_address("Sachsentor 38", "21029"),
            delivery_address=_address("Weidenbaumsweg 21", "21029"),
            guests=80,
            source="configurator",
            crm_stage="Angebot gesendet / Rückmeldung offen",
            fulfillment_mode="DELIVERY",
            delivery_address_mode="SEPARATE",
            payment_method="RECHNUNG",
            payment_text="Zahlung per Rechnung innerhalb von 14 Tagen.",
        ),
        WorkflowCase(
            company="Elbbrücken Projekt GmbH",
            contact="Katharina Wolf",
            email_slug="elbbruecken-projekt",
            phone="+49405550109",
            event_title="Jahresauftakt",
            event_date_offset=51,
            event_start=time(18, 0),
            delivery_time=time(16, 0),
            location="Hamburg-Rothenburgsort",
            invoice_address=_address("Amsinckstraße 57", "20097"),
            delivery_address=_address("Billhorner Brückenstraße 40", "20539"),
            guests=150,
            source="website_form",
            crm_stage="Angebot gesendet / Rückmeldung offen",
            fulfillment_mode="DELIVERY",
            delivery_address_mode="SEPARATE",
            payment_method="VORKASSE",
            payment_text="Vorkasse, zahlbar bis 14 Tage vor Veranstaltungsbeginn.",
        ),
    )


def _position(
    *,
    name: str,
    description: str,
    guests: int,
    unit_net_cents: int,
) -> dict[str, object]:
    net = guests * unit_net_cents
    vat = round(net * 0.07)
    return {
        "position_id": str(uuid.uuid4()),
        "kind": "custom",
        "catalog_item_id": None,
        "name": name,
        "description": description,
        "composition": description,
        "quantity_mode": "total",
        "quantity": str(guests),
        "unit_label": "Personen",
        "unit_net_cents": unit_net_cents,
        "net_total_cents": net,
        "vat_rate_percent": 7,
        "vat_amount_cents": vat,
        "gross_total_cents": net + vat,
        "notes": None,
        "related_position_id": None,
    }


def _delivery_position() -> dict[str, object]:
    net = 6500
    vat = round(net * 0.19)
    return {
        "position_id": str(uuid.uuid4()),
        "kind": "delivery",
        "catalog_item_id": None,
        "name": "Anlieferung Hamburg",
        "description": "Anlieferung zum vereinbarten Zeitfenster.",
        "composition": None,
        "quantity_mode": "total",
        "quantity": "1",
        "unit_label": "Pauschale",
        "unit_net_cents": net,
        "net_total_cents": net,
        "vat_rate_percent": 19,
        "vat_amount_cents": vat,
        "gross_total_cents": net + vat,
        "notes": None,
        "related_position_id": None,
    }


def _variant(
    *,
    label: str,
    description: str,
    guests: int,
    unit_net_cents: int,
    delivery: bool,
) -> dict[str, object]:
    positions = [
        _position(
            name=f"Fingerfood Arrangement {label}",
            description=description,
            guests=guests,
            unit_net_cents=unit_net_cents,
        )
    ]
    if delivery:
        positions.append(_delivery_position())

    net = sum(int(item["net_total_cents"]) for item in positions)
    vat_7_base = sum(
        int(item["net_total_cents"])
        for item in positions
        if item["vat_rate_percent"] == 7
    )
    vat_7 = sum(
        int(item["vat_amount_cents"])
        for item in positions
        if item["vat_rate_percent"] == 7
    )
    vat_19_base = sum(
        int(item["net_total_cents"])
        for item in positions
        if item["vat_rate_percent"] == 19
    )
    vat_19 = sum(
        int(item["vat_amount_cents"])
        for item in positions
        if item["vat_rate_percent"] == 19
    )
    return {
        "variant_id": str(uuid.uuid4()),
        "label": label,
        "description": description,
        "positions": positions,
        "totals": {
            "net_cents": net,
            "vat_7_base_cents": vat_7_base,
            "vat_7_amount_cents": vat_7,
            "vat_19_base_cents": vat_19_base,
            "vat_19_amount_cents": vat_19,
            "gross_cents": net + vat_7 + vat_19,
        },
    }


def _snapshot(
    case: WorkflowCase,
    inquiry_id: str,
    *,
    now: datetime,
    today: date,
) -> dict[str, object]:
    invoice = case.invoice_address
    postal_address = (
        f"{invoice.street}, {invoice.postal_code} {invoice.city}, {invoice.country}"
    )
    payload: dict[str, object] = {
        "schema_version": "offer_snapshot_v1",
        "source": "fingerfood-configurator-backend",
        "source_draft_id": f"seed-{uuid.uuid4()}",
        "inquiry_id": inquiry_id,
        "snapshot_id": str(uuid.uuid4()),
        "snapshot_created_at": now.isoformat(),
        "valid_until": (today + timedelta(days=21)).isoformat(),
        "currency": "EUR",
        "recipient": {
            "company_name": case.company,
            "contact_name": case.contact,
            "email": f"{case.email_slug}@{case.email_domain}",
            "postal_address": postal_address,
        },
        "event": {
            "event_date": (today + timedelta(days=case.event_date_offset)).isoformat(),
            "time_window_text": (
                f"{case.event_start.strftime('%H:%M')}–"
                f"{(datetime.combine(today, case.event_start) + timedelta(hours=4)).time().strftime('%H:%M')}"
            ),
            "location_text": case.location,
            "guest_count": case.guests,
            "planning_mode": "caterer_suggestion",
            "event_start_local": case.event_start.strftime("%H:%M"),
            "delivery_time_local": (
                case.delivery_time.strftime("%H:%M")
                if case.delivery_time is not None
                else None
            ),
        },
        "customer_text": {
            "title": f"{case.event_title}",
            "introduction": (
                f"Vielen Dank für Ihre Anfrage für {case.guests} Personen. "
                "Nachfolgend finden Sie zwei mögliche Fingerfood-Varianten."
            ),
            "notes": (
                "DEMO-DATENSATZ für eine Softwarepräsentation. "
                "Keine echte Kundenanfrage und kein verbindliches Angebot."
            ),
        },
        "payment_terms": {
            "method": case.payment_method,
            "customer_visible_text": case.payment_text,
        },
        "calculator": {
            "name": "fingerfood-configurator-backend",
            "calculator_revision": "2026-09",
            "catalog_revision": "2026-09",
            "tax_revision": "de-2026",
        },
        "variants": [
            _variant(
                label="Klassik",
                description=(
                    "Mini-Quiches, Wraps, Bruschetta, Hähnchenspieße "
                    "und vegetarische Auswahl."
                ),
                guests=case.guests,
                unit_net_cents=2900,
                delivery=case.fulfillment_mode == "DELIVERY",
            ),
            _variant(
                label="Premium",
                description=(
                    "Roastbeef-Crostini, Lachs, Garnelenspieße, vegane Tartlets "
                    "und Dessertgläser."
                ),
                guests=case.guests,
                unit_net_cents=3900,
                delivery=case.fulfillment_mode == "DELIVERY",
            ),
        ],
    }
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def _create_inquiry(
    service: InquiryService,
    case: WorkflowCase,
    *,
    today: date,
) -> str:
    event_date = today + timedelta(days=case.event_date_offset)
    inquiry = service.create_inquiry(
        event_date=event_date,
        inquiry_source=case.source,
        crm_stage=case.crm_stage,
        customer_linkage={},
        time_window_text=f"ab {case.event_start.strftime('%H:%M')} Uhr",
        location_text=case.location,
        guest_count_estimate=case.guests,
        planning_mode="caterer_suggestion",
        call_verification_required=case.call_verification_required,
        call_verification_status=case.call_verification_status,
        intake_subject=f"{case.event_title} – {case.company}",
        intake_message=(
            "Gewünscht ist ein Fingerfood-Catering "
            f"für {case.guests} Personen in {case.location}."
        ),
        intake_summary=(
            f"{case.event_title}, {case.guests} Personen, "
            f"{event_date.isoformat()}, {case.location}"
        ),
        intake_external_ref=f"WEB-{uuid.uuid4()}",
        contact_email=f"{case.email_slug}@{case.email_domain}",
        contact_phone=case.phone,
        contact_name=case.contact,
        company_name=case.company,
        fulfillment_mode=case.fulfillment_mode,
        event_start_local=case.event_start,
        delivery_time_local=case.delivery_time,
    )
    service.set_inquiry_customer_addresses(
        inquiry.inquiry_id,
        invoice_address=case.invoice_address,
        delivery_address=case.delivery_address,
        delivery_address_mode=case.delivery_address_mode,
    )
    return inquiry.inquiry_id


def seed_demo_workflow(db_path: str | Path) -> SeedSummary:
    connection = open_core_connection(db_path)
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    offers = SQLiteOfferRepository.from_connection(connection)
    orders = SQLiteOrderRepository.from_connection(connection)
    commercial = SQLiteOrderCommercialSnapshotRepository.from_connection(connection)

    if inquiries.list_all() or offers.list_all() or orders.list_orders():
        connection.close()
        raise RuntimeError(
            "seed refused: inquiries/offers/orders already exist; "
            "clean workflow data first"
        )

    now = datetime.now(UTC)
    today = date.today()
    inquiry_service = InquiryService(inquiries)
    offer_service = OfferService(
        offers,
        inquiries,
        orders,
        commercial,
        now=lambda: now,
        today=lambda: today,
    )

    offer_states: list[str] = []
    created_orders = 0

    connection.execute("BEGIN IMMEDIATE")
    try:
        cases = _cases()
        inquiry_ids = [
            _create_inquiry(inquiry_service, case, today=today) for case in cases
        ]

        # 0-2: Inquiry-only stages.
        # 3: Prepared offer.
        prepared_case = cases[3]
        prepared = offer_service.prepare_offer_version(
            inquiry_ids[3],
            _snapshot(prepared_case, inquiry_ids[3], now=now, today=today),
        )
        offer_states.append(
            derive_offer_state(
                prepared,
                prepared.versions[-1].offer_version_id,
                today=today,
            )
        )

        # 4: Sent, waiting for response.
        sent_case = cases[4]
        sent = offer_service.prepare_offer_version(
            inquiry_ids[4],
            _snapshot(sent_case, inquiry_ids[4], now=now, today=today),
        )
        sent_version = sent.versions[-1]
        sent = offer_service.record_sent_evidence(
            sent.offer_id,
            sent_version.offer_version_id,
            sent_at=now - timedelta(hours=3),
            channel="email",
            recipient_reference=f"{sent_case.email_slug}@{sent_case.email_domain}",
            evidence_reference="E-Mail-Ausgang",
            recorded_by="viktor",
        )
        offer_states.append(
            derive_offer_state(sent, sent_version.offer_version_id, today=today)
        )

        # 5: Sent and rejected.
        rejected_case = cases[5]
        rejected = offer_service.prepare_offer_version(
            inquiry_ids[5],
            _snapshot(rejected_case, inquiry_ids[5], now=now, today=today),
        )
        rejected_version = rejected.versions[-1]
        rejected = offer_service.record_sent_evidence(
            rejected.offer_id,
            rejected_version.offer_version_id,
            sent_at=now - timedelta(days=1),
            channel="email",
            recipient_reference=f"{rejected_case.email_slug}@{rejected_case.email_domain}",
            evidence_reference="E-Mail-Ausgang",
            recorded_by="viktor",
        )
        rejected = offer_service.record_rejection_evidence(
            rejected.offer_id,
            rejected_version.offer_version_id,
            rejected_at=now - timedelta(hours=6),
            recorded_by="viktor",
            evidence_reference="Kundenabsage",
        )
        inquiry_service.update_inquiry(
            inquiry_ids[5],
            crm_stage="Abgelehnt / verloren",
        )
        offer_states.append(
            derive_offer_state(rejected, rejected_version.offer_version_id, today=today)
        )

        # 6: Accepted, waiting for conversion.
        accepted_case = cases[6]
        accepted = offer_service.prepare_offer_version(
            inquiry_ids[6],
            _snapshot(accepted_case, inquiry_ids[6], now=now, today=today),
        )
        accepted_version = accepted.versions[-1]
        accepted_variant = accepted_version.variants[0]
        accepted = offer_service.record_sent_evidence(
            accepted.offer_id,
            accepted_version.offer_version_id,
            sent_at=now - timedelta(hours=5),
            channel="email",
            recipient_reference=f"{accepted_case.email_slug}@{accepted_case.email_domain}",
            evidence_reference="E-Mail-Ausgang",
            recorded_by="viktor",
        )
        accepted = offer_service.record_acceptance_evidence(
            accepted.offer_id,
            accepted_version.offer_version_id,
            accepted_variant.variant_id,
            accepted_at=now - timedelta(hours=2),
            channel="email",
            evidence_reference="Kundenzusage",
            recorded_by="viktor",
            note="Kunde bestätigt Variante Klassik.",
        )
        offer_states.append(
            derive_offer_state(accepted, accepted_version.offer_version_id, today=today)
        )

        # 7-8: Accepted and converted to active Orders.
        for index in (7, 8):
            case = cases[index]
            converted = offer_service.prepare_offer_version(
                inquiry_ids[index],
                _snapshot(case, inquiry_ids[index], now=now, today=today),
            )
            version = converted.versions[-1]
            chosen_variant = version.variants[1 if index == 8 else 0]
            converted = offer_service.record_sent_evidence(
                converted.offer_id,
                version.offer_version_id,
                sent_at=now - timedelta(days=2),
                channel="email",
                recipient_reference=f"{case.email_slug}@{case.email_domain}",
                evidence_reference="E-Mail-Ausgang",
                recorded_by="viktor",
            )
            converted = offer_service.record_acceptance_evidence(
                converted.offer_id,
                version.offer_version_id,
                chosen_variant.variant_id,
                accepted_at=now - timedelta(days=1),
                channel="email",
                evidence_reference="Kundenzusage",
                recorded_by="viktor",
                note=f"Kunde bestätigt Variante {chosen_variant.label}.",
            )
            acceptance = converted.acceptance_evidence
            assert acceptance is not None
            converted, _order, _order_version = offer_service.convert_accepted_offer(
                converted.offer_id,
                version.offer_version_id,
                chosen_variant.variant_id,
                acceptance.acceptance_id,
            )
            inquiry_service.update_inquiry(
                inquiry_ids[index],
                crm_stage="Bestätigt / Auftrag",
            )
            created_orders += 1
            offer_states.append(
                derive_offer_state(
                    converted,
                    version.offer_version_id,
                    today=today,
                )
            )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return SeedSummary(
        inquiries=len(_cases()),
        offers=len(offer_states),
        orders=created_orders,
        offer_states=tuple(offer_states),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed realistic Hamburg workflow data into an empty Core DB."
    )
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    args = parser.parse_args()

    summary = seed_demo_workflow(args.db)
    print(
        "seed: ok "
        f"inquiries={summary.inquiries} "
        f"offers={summary.offers} "
        f"orders={summary.orders} "
        f"states={','.join(summary.offer_states)}"
    )


if __name__ == "__main__":
    main()

"""Phase 3B kitchen print document artifact lifecycle."""

from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pypdf import PdfReader

from catering_system.domain.kitchen_print_job import KitchenPrintJob, KitchenPrintPolicy
from catering_system.repositories.in_memory_kitchen_print_document_store import (
    InMemoryKitchenPrintDocumentStore,
)
from catering_system.repositories.in_memory_kitchen_print_job_repository import (
    InMemoryKitchenPrintJobRepository,
)
from catering_system.services.kitchen_print_document_factory import (
    KitchenPrintDocumentFactory,
)
from catering_system.services.kitchen_print_pdf_renderer import (
    KitchenPrintPdfUnsupportedCharacterError,
    render_kitchen_print_pdf,
)
from catering_system.services.kitchen_print_service import KitchenPrintService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
)
from catering_system.services.order_service import OrderService
from tests.unit.test_offer_service import _accepted_offer_state

_NOW = datetime(2026, 8, 8, 11, 0, tzinfo=UTC)
_JOB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_POLICY = KitchenPrintPolicy(
    acceptance_timeout=timedelta(seconds=30),
    acknowledgment_timeout=timedelta(minutes=5),
)


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return " ".join(
        text for page in reader.pages for text in (page.extract_text(),) if text
    )


def _document_factory_world(
    *, accepted: bool = True
) -> tuple[
    KitchenPrintDocumentFactory,
    InMemoryKitchenPrintDocumentStore,
    KitchenPrintJob,
    object,
    object,
    object,
]:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    jobs = InMemoryKitchenPrintJobRepository(orders)
    print_service = KitchenPrintService(
        orders,
        jobs,
        policy=_POLICY,
        clock=lambda: _NOW,
    )
    requested = print_service.request_print(
        order.order_id,
        order_version.order_version_id,
        print_job_id=_JOB_A,
    )
    job = print_service.accept_print_job(_JOB_A) if accepted else requested
    store = InMemoryKitchenPrintDocumentStore()
    factory = KitchenPrintDocumentFactory(
        OrderPrintProjectionService(orders, offer_service._commercial_snapshots),
        store,
    )
    return factory, store, job, offer, offers, orders


def test_create_for_print_job_returns_one_artifact_per_job() -> None:
    factory, _store, job, _offer, _offers, _orders = _document_factory_world()

    first = factory.create_for_print_job(job)
    second = factory.create_for_print_job(job)

    assert first.document_ref == second.document_ref
    assert first.projection_hash == second.projection_hash
    assert first.body == second.body
    assert first.print_job_id == _JOB_A


def test_pdf_render_is_byte_identical_for_same_stable_inputs() -> None:
    factory, _store, job, _offer, _offers, _orders = _document_factory_world()
    projection = factory._projection_service.resolve(
        job.order_id,
        job.order_version_id,
        intent="kitchen_job",
    )

    first = render_kitchen_print_pdf(projection, created_at=_NOW)
    second = render_kitchen_print_pdf(projection, created_at=_NOW)

    assert first == second
    assert first.startswith(b"%PDF-")
    assert projection.flags.intent == "kitchen_job"


def test_pdf_contains_kitchen_projection_content() -> None:
    factory, _store, job, _offer, _offers, _orders = _document_factory_world()
    projection = factory._projection_service.resolve(
        job.order_id,
        job.order_version_id,
        intent="kitchen_job",
    )
    pdf = render_kitchen_print_pdf(projection, created_at=_NOW)
    text = _pdf_text(pdf)
    event = projection.event
    first_position = projection.commercial.positions[0]
    detail = first_position.description or first_position.composition
    planning_label = {
        "caterer_suggestion": "Vorschlag durch Silberlöffel",
        "self_select": "Auswahl durch den Kunden",
    }[event.planning_mode]

    assert "SILBERLÖFFEL" in text
    assert "Küchenzettel" in text
    assert event.order_id not in text
    assert event.order_version_id not in text
    assert event.event_date.strftime("%d.%m.%Y") in text
    assert event.time_window_text in text
    assert event.location_text in text
    assert str(event.guest_count_estimate) in text
    assert planning_label in text
    assert event.planning_mode not in text
    assert "Stand" in text
    assert "KUNDE / LIEFERUNG" in text
    assert "MENÜ" in text
    assert first_position.name in text
    if detail is not None:
        assert detail in text
    if first_position.quantity_display is not None:
        assert first_position.quantity_display in text


def test_pdf_contains_exact_customer_delivery_context() -> None:
    factory, _store, job, _offer, _offers, _orders = _document_factory_world()
    projection = factory._projection_service.resolve(
        job.order_id,
        job.order_version_id,
        intent="kitchen_job",
    )
    projection = replace(
        projection,
        customer=replace(
            projection.customer,
            company_name="Grant Hotel",
            contact_name="Frau Grant",
            phone="040 123456",
            delivery_address_lines=("Brombeerenstr. 4", "22041 Hamburg"),
        ),
    )

    text = _pdf_text(render_kitchen_print_pdf(projection, created_at=_NOW))

    assert "Grant Hotel" in text
    assert "Frau Grant" in text
    assert "040 123456" in text
    assert "Brombeerenstr. 4" in text
    assert "22041 Hamburg" in text
    assert projection.event.order_id not in text
    assert projection.event.order_version_id not in text


def test_pdf_contains_cancelled_watermark_change_and_empty_menu_states() -> None:
    factory, _store, job, _offer, _offers, _orders = _document_factory_world()
    projection = factory._projection_service.resolve(
        job.order_id,
        job.order_version_id,
        intent="kitchen_job",
    )
    projection = replace(
        projection,
        event=replace(
            projection.event,
            guest_count_estimate=None,
            order_cancelled_at=_NOW,
            change_reason=None,
            changed_fields=("location_text", "guest_count_estimate"),
        ),
        commercial=replace(projection.commercial, positions=()),
        flags=replace(projection.flags, watermark="VERALTET"),
    )

    text = _pdf_text(render_kitchen_print_pdf(projection, created_at=_NOW))

    assert "STORNIERT" in text
    assert "VERALTET" in text
    assert "Gäste" in text
    assert "-" in text
    assert "ÄNDERUNG" in text
    assert "Geändert: Ort, Gästezahl" in text
    assert "location_text" not in text
    assert "guest_count_estimate" not in text
    assert "Keine Positionen." in text


def test_pdf_rejects_unsupported_projection_text() -> None:
    factory, _store, job, _offer, _offers, _orders = _document_factory_world()
    projection = factory._projection_service.resolve(
        job.order_id,
        job.order_version_id,
        intent="kitchen_job",
    )
    projection = replace(
        projection,
        event=replace(projection.event, changed_fields=("emoji 🚫",)),
    )

    with pytest.raises(KitchenPrintPdfUnsupportedCharacterError) as exc_info:
        render_kitchen_print_pdf(projection, created_at=_NOW)

    assert exc_info.value.field == "changed_fields[0]"


def test_document_is_immutable_after_live_data_changes() -> None:
    factory, store, job, offer, offers, orders = _document_factory_world()
    document = factory.create_for_print_job(job)
    original_hash = document.projection_hash
    original_ref = document.document_ref
    original_bytes = document.body

    stored_offer = offers.get(offer.offer_id)
    assert stored_offer is not None
    version = stored_offer.versions[0]
    variant = version.variants[0]
    mutated = replace(
        stored_offer,
        versions=(
            replace(
                version,
                variants=(
                    replace(
                        variant,
                        positions=(
                            replace(variant.positions[0], name="MUTATED LIVE OFFER"),
                        ),
                    ),
                ),
            ),
        ),
    )
    offers._offers[stored_offer.offer_id] = mutated

    order = orders.get_order(job.order_id)
    assert order is not None
    order_version = orders.get_order_version(job.order_version_id)
    assert order_version is not None
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    OrderService(orders).create_relevant_order_change_version(
        order,
        event_date=date(2026, 9, 1),
        time_window_text="abends",
        location_text="Lübeck",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
    )

    stored_document = store.get_by_print_job_id(_JOB_A)
    assert stored_document is not None
    assert stored_document.projection_hash == original_hash
    assert stored_document.document_ref == original_ref
    assert stored_document.body == original_bytes


def test_document_stores_snapshot_bytes_not_live_reference() -> None:
    factory, _store, job, _offer, _offers, _orders = _document_factory_world()

    document = factory.create_for_print_job(job)

    assert document.body
    assert document.body.startswith(b"%PDF-")
    assert document.projection_hash
    assert document.content_type == "application/pdf"
    assert document.print_job_id == job.print_job_id
    assert not hasattr(document, "order_version_id")


def test_unaccepted_job_cannot_produce_immutable_document() -> None:
    factory, _store, job, _offer, _offers, _orders = _document_factory_world(
        accepted=False
    )

    with pytest.raises(ValueError, match="accepted kitchen print job is required"):
        factory.create_for_print_job(job)


def test_kitchen_print_document_factory_boundary_stays_projection_only() -> None:
    root = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "catering_system"
        / "services"
        / "kitchen_print_document_factory.py"
    )
    text = root.read_text(encoding="utf-8")
    assert "sqlite" not in text.lower()
    assert "KitchenPrintService" not in text
    assert "OrderRepository" not in text


def test_document_ref_is_content_addressed_by_body_hash() -> None:
    factory, _store, job, _offer, _offers, _orders = _document_factory_world()
    document = factory.create_for_print_job(job)
    expected_ref = f"sha256:{hashlib.sha256(document.body).hexdigest()}"
    assert document.document_ref == expected_ref
    assert document.document_ref != (
        f"sha256:{hashlib.sha256(job.order_version_id.encode()).hexdigest()}"
    )


def test_store_is_append_only_and_rejects_conflicting_artifact() -> None:
    factory, store, job, _offer, _offers, _orders = _document_factory_world()
    document = factory.create_for_print_job(job)
    assert store.save(document) == document

    with pytest.raises(
        ValueError, match="print_job_id already has a different document"
    ):
        store.save(
            replace(
                document,
                document_ref="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            )
        )


def test_claim_then_document_creation_does_not_mutate_job_facts() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    jobs = InMemoryKitchenPrintJobRepository(orders)
    print_service = KitchenPrintService(
        orders,
        jobs,
        policy=_POLICY,
        clock=lambda: _NOW,
    )
    print_service.request_print(
        order.order_id,
        order_version.order_version_id,
        print_job_id=_JOB_A,
    )
    store = InMemoryKitchenPrintDocumentStore()
    factory = KitchenPrintDocumentFactory(
        OrderPrintProjectionService(orders, offer_service._commercial_snapshots),
        store,
    )
    before = jobs.get(_JOB_A)
    assert before is not None
    assert before.accepted_at is None

    claimed = print_service.claim_next_eligible()
    assert claimed is not None
    accepted_snapshot = jobs.get(_JOB_A)
    assert accepted_snapshot is not None
    assert accepted_snapshot.accepted_at == _NOW

    document = factory.create_for_print_job(claimed)
    assert document.document_ref
    after = jobs.get(_JOB_A)
    version = orders.get_order_version(order_version.order_version_id)
    assert after == accepted_snapshot
    assert version is not None
    assert version.kitchen_print_confirmed_at is None

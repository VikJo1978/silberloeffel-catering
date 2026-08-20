"""Unit tests — Slice B1/B2/B3/B5/B6 Order, OrderVersion, conversion, history, candidate reads."""

from __future__ import annotations

import sys
from dataclasses import fields, replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    PLANNING_MODES,
    Inquiry,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)
from catering_system.domain.offer import (
    AcceptanceEvidence,
    OfferPosition,
    OfferVariant,
    OfferVersion,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_operational_context import (
    OrderOperationalContextData,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.order_service import (
    OperationalContextMissingError,
    OrderService,
    _operational_context_for_new_version,
)
from tests.helpers.order_seed import seed_order

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    company_name="Müller GmbH",
    contact_name="Anna Müller",
    email="kunde@example.com",
    phone="+49301234567",
    invoice_address=CustomerAddress(
        street="Alter Wall 22",
        postal_code="20457",
        city="Hamburg",
        country="Deutschland",
    ),
    delivery_address_mode="SAME_AS_INVOICE",
)

_B3_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "is_active",
        "is_effective",
        "active_version_id",
        "effective_version_id",
        "selected_version_id",
        "release_ready",
        "ready_to_send",
    }
)


def _module_source_lower(module: object) -> str:
    return Path(module.__file__).read_text(encoding="utf-8").lower()


def _sample_inquiry() -> Inquiry:
    now = datetime.now(UTC)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
        customer_snapshot=_CONTACT_COMPLETE_SNAPSHOT,
    )


def _offer_version_from_inquiry(inquiry: Inquiry) -> OfferVersion:
    return OfferVersion(
        offer_version_id="offer-version-1",
        offer_id="offer-1",
        version_number=1,
        created_at=inquiry.created_at,
        valid_until=inquiry.event_date,
        snapshot_id="snapshot-1",
        snapshot_hash="sha256:" + ("0" * 64),
        event_date=inquiry.event_date,
        time_window_text=inquiry.time_window_text,
        location_text=inquiry.location_text,
        guest_count=inquiry.guest_count_estimate,
        planning_mode=inquiry.planning_mode,
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        variants=(
            OfferVariant(
                variant_id="variant-1",
                offer_version_id="offer-version-1",
                label="Standard",
                positions=(
                    OfferPosition(
                        position_id="position-1",
                        kind="catalog",
                        name="Menü",
                        unit_net_cents=100,
                        net_total_cents=100,
                        vat_rate_percent=7,
                        vat_amount_cents=7,
                        gross_total_cents=107,
                    ),
                ),
            ),
        ),
    )


def _acceptance_for_offer_version(offer_version: OfferVersion) -> AcceptanceEvidence:
    return AcceptanceEvidence(
        acceptance_id="acceptance-1",
        offer_id=offer_version.offer_id,
        accepted_offer_version_id=offer_version.offer_version_id,
        accepted_variant_id=offer_version.variants[0].variant_id,
        accepted_at=offer_version.created_at,
        recorded_at=offer_version.created_at,
        channel="phone",
        evidence_reference="unit-test",
        recorded_by="unit-test",
    )


def _create_initial_order(
    svc: OrderService, inquiry: Inquiry
) -> tuple[Order, OrderVersion]:
    offer_version = _offer_version_from_inquiry(inquiry)
    return svc.create_order_from_offer_version(
        inquiry.inquiry_id,
        offer_version,
        inquiry,
        acceptance_evidence=_acceptance_for_offer_version(offer_version),
    )


def test_create_order_from_offer_version_requires_acceptance_before_persistence() -> (
    None
):
    repo = InMemoryOrderRepository()
    inquiry = _sample_inquiry()
    offer_version = _offer_version_from_inquiry(inquiry)

    with pytest.raises(ValueError, match="AcceptanceEvidence required"):
        OrderService(repo).create_order_from_offer_version(
            inquiry.inquiry_id,
            offer_version,
            inquiry,
        )

    assert repo.list_orders() == []


@pytest.mark.parametrize(
    ("field_name", "field_value", "message"),
    (
        ("offer_id", "other-offer", "different Offer"),
        ("accepted_offer_version_id", "other-version", "does not match OfferVersion"),
        ("accepted_variant_id", "other-variant", "does not belong to OfferVersion"),
    ),
)
def test_create_order_from_offer_version_rejects_mismatched_acceptance_before_persistence(
    field_name: str,
    field_value: str,
    message: str,
) -> None:
    repo = InMemoryOrderRepository()
    inquiry = _sample_inquiry()
    offer_version = _offer_version_from_inquiry(inquiry)
    acceptance = replace(
        _acceptance_for_offer_version(offer_version),
        **{field_name: field_value},
    )

    with pytest.raises(ValueError, match=message):
        OrderService(repo).create_order_from_offer_version(
            inquiry.inquiry_id,
            offer_version,
            inquiry,
            acceptance_evidence=acceptance,
        )

    assert repo.list_orders() == []


def test_convert_inquiry_to_order_requires_accepted_offer_when_missing() -> None:
    svc = OrderService(InMemoryOrderRepository())
    with pytest.raises(ValueError, match="accepted offer required"):
        svc.convert_inquiry_to_order(_sample_inquiry())


def test_convert_inquiry_to_order_returns_existing_order() -> None:
    repo = InMemoryOrderRepository()
    inquiry = _sample_inquiry()
    seeded, ver = seed_order(repo, inquiry)
    order, got = OrderService(repo).convert_inquiry_to_order(inquiry)
    assert order.order_id == seeded.order_id
    assert got.order_version_id == ver.order_version_id


def test_create_relevant_order_change_version_second_preserves_first() -> None:
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    v2 = svc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 11, 2),
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[1],
    )
    assert v2.version_number == 2
    assert v2.order_id == order.order_id
    hist = repo.list_order_versions(order.order_id)
    assert len(hist) == 2
    assert hist[0].order_version_id == v1.order_version_id
    assert hist[0].version_number == 1
    assert hist[1].order_version_id == v2.order_version_id
    assert hist[1].time_window_text == "abends"
    reloaded = repo.get_order_version(v1.order_version_id)
    assert reloaded is not None
    assert reloaded.event_date == v1.event_date
    updated_order = repo.get_order(order.order_id)
    assert updated_order is not None
    assert updated_order.updated_at >= order.updated_at


def test_initial_version_stores_frozen_operational_context() -> None:
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, version = _create_initial_order(svc, _sample_inquiry())

    context = repo.get_operational_context(version.order_version_id)
    assert context is not None
    assert context.order_id == order.order_id
    assert context.recipient_company == "Müller GmbH"
    assert context.recipient_name == "Anna Müller"
    assert context.recipient_phone == "+49301234567"
    assert context.delivery_address is not None
    assert context.delivery_address.street == "Alter Wall 22"
    assert context.source == "initial_inquiry_snapshot"


def test_child_version_inherits_parent_operational_context_not_live_inquiry() -> None:
    inquiry = _sample_inquiry()
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = _create_initial_order(svc, inquiry)
    mutated = replace(
        inquiry,
        customer_snapshot=replace(
            inquiry.customer_snapshot,
            company_name="Live Mutation GmbH",
            contact_name="Live Mutation",
        ),
    )
    v2 = svc.propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text=v1.time_window_text,
        location_text=v1.location_text,
        guest_count_estimate=40,
        planning_mode=v1.planning_mode,
        actor_reference="office",
        change_reason="anzahl",
    )

    v1_context = repo.get_operational_context(v1.order_version_id)
    v2_context = repo.get_operational_context(v2.order_version_id)
    assert mutated.customer_snapshot is not None
    assert mutated.customer_snapshot.company_name == "Live Mutation GmbH"
    assert v1_context is not None
    assert v2_context is not None
    assert v2_context.order_version_id == v2.order_version_id
    assert v2_context.recipient_company == v1_context.recipient_company
    assert v2_context.recipient_company == "Müller GmbH"
    assert v2_context.source == "inherited_parent"
    assert v1_context is not v2_context


def test_explicit_operational_context_change_and_grandchild_inheritance() -> None:
    inquiry = _sample_inquiry()
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = _create_initial_order(svc, inquiry)
    new_address = CustomerAddress(
        street="Neuer Weg 5",
        postal_code="20095",
        city="Hamburg",
        country="Deutschland",
    )
    explicit = OrderOperationalContextData(
        recipient_company="Neue Firma GmbH",
        recipient_name="Nina Neu",
        recipient_phone="+494012345",
        delivery_address=new_address,
    )
    v2 = svc.propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text=v1.time_window_text,
        location_text=v1.location_text,
        guest_count_estimate=40,
        planning_mode=v1.planning_mode,
        actor_reference="office",
        change_reason="adresse",
        operational_context=explicit,
    )
    v1_context = repo.get_operational_context(v1.order_version_id)
    v2_context = repo.get_operational_context(v2.order_version_id)
    assert v1_context is not None
    assert v2_context is not None
    assert v1_context.recipient_company == "Müller GmbH"
    assert v2_context.recipient_company == "Neue Firma GmbH"
    assert v2_context.delivery_address == new_address
    assert v2_context.source == "explicit_change"

    v3 = svc.propose_order_version_change(
        order.order_id,
        event_date=v2.event_date,
        time_window_text=v2.time_window_text,
        location_text=v2.location_text,
        guest_count_estimate=45,
        planning_mode=v2.planning_mode,
        actor_reference="office",
        change_reason="anzahl",
    )
    v3_context = repo.get_operational_context(v3.order_version_id)
    assert v3_context is not None
    assert v3_context.recipient_company == "Neue Firma GmbH"
    assert v3_context.delivery_address == new_address
    assert v3_context.source == "inherited_parent"


def test_operational_context_inherits_from_exact_parent_not_latest_branch() -> None:
    inquiry = _sample_inquiry()
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = _create_initial_order(svc, inquiry)
    explicit_b = OrderOperationalContextData(
        recipient_company="Branch B GmbH",
        recipient_name="Berta Branch",
        recipient_phone="+4940555",
        delivery_address=CustomerAddress(
            street="Branch Weg 2",
            postal_code="20095",
            city="Hamburg",
            country="Deutschland",
        ),
    )
    v2 = svc.propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text=v1.time_window_text,
        location_text=v1.location_text,
        guest_count_estimate=40,
        planning_mode=v1.planning_mode,
        actor_reference="office",
        change_reason="adresse",
        operational_context=explicit_b,
    )
    v3 = replace(
        v2,
        order_version_id="branch-v3",
        version_number=3,
        parent_order_version_id=v1.order_version_id,
    )

    inherited = _operational_context_for_new_version(
        order_repository=repo,
        order=order,
        version=v3,
        data=None,
        created_at=v3.created_at,
    )

    assert inherited is not None
    assert inherited.order_version_id == v3.order_version_id
    assert inherited.source == "inherited_parent"
    assert inherited.recipient_company == "Müller GmbH"
    assert inherited.recipient_company != "Branch B GmbH"
    assert repo.get_operational_context(v2.order_version_id).recipient_company == (
        "Branch B GmbH"
    )


def test_delivery_address_change_creates_explicit_context_without_inquiry_mutation() -> (
    None
):
    inquiry = _sample_inquiry()
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = _create_initial_order(svc, inquiry)
    before_context = repo.get_operational_context(v1.order_version_id)
    assert before_context is not None
    new_address = CustomerAddress(
        street="Neuer Weg 5",
        postal_code="20095",
        city="Hamburg",
        country="Deutschland",
    )

    v2 = svc.propose_delivery_address_change(
        order.order_id,
        parent_order_version_id=v1.order_version_id,
        delivery_address=new_address,
        actor_reference="office-panel",
        change_reason="Lieferadresse geändert",
    )

    after_context = repo.get_operational_context(v1.order_version_id)
    v2_context = repo.get_operational_context(v2.order_version_id)
    assert v2.version_number == 2
    assert v2.parent_order_version_id == v1.order_version_id
    assert v2.changed_fields == ("delivery_address",)
    assert after_context == before_context
    assert inquiry.customer_snapshot == _CONTACT_COMPLETE_SNAPSHOT
    assert v2_context is not None
    assert v2_context.source == "explicit_change"
    assert v2_context.recipient_company == before_context.recipient_company
    assert v2_context.recipient_name == before_context.recipient_name
    assert v2_context.recipient_phone == before_context.recipient_phone
    assert v2_context.delivery_address == new_address


def test_delivery_address_change_uses_explicit_parent_not_latest_branch() -> None:
    inquiry = _sample_inquiry()
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = _create_initial_order(svc, inquiry)
    branch_b = OrderOperationalContextData(
        recipient_company="Branch B GmbH",
        recipient_name="Berta Branch",
        recipient_phone="+4940555",
        delivery_address=CustomerAddress(
            street="Branch Weg 2",
            postal_code="20095",
            city="Hamburg",
            country="Deutschland",
        ),
    )
    v2 = svc.propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text=v1.time_window_text,
        location_text=v1.location_text,
        guest_count_estimate=40,
        planning_mode=v1.planning_mode,
        actor_reference="office",
        change_reason="branch",
        operational_context=branch_b,
    )
    new_address = CustomerAddress(
        street="Zurück zu V1 9",
        postal_code="20457",
        city="Hamburg",
        country="Deutschland",
    )

    v3 = svc.propose_delivery_address_change(
        order.order_id,
        parent_order_version_id=v1.order_version_id,
        delivery_address=new_address,
        actor_reference="office-panel",
        change_reason="Lieferadresse geändert",
    )

    v3_context = repo.get_operational_context(v3.order_version_id)
    assert v2.version_number == 2
    assert v3.version_number == 3
    assert v3.parent_order_version_id == v1.order_version_id
    assert v3_context is not None
    assert v3_context.recipient_company == "Müller GmbH"
    assert v3_context.recipient_company != "Branch B GmbH"
    assert v3_context.delivery_address == new_address


def test_delivery_address_change_rejects_missing_parent_context_without_partial_version() -> (
    None
):
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    before_versions = repo.list_order_versions(order.order_id)

    with pytest.raises(OperationalContextMissingError):
        svc.propose_delivery_address_change(
            order.order_id,
            parent_order_version_id=v1.order_version_id,
            delivery_address=CustomerAddress(street="Neuer Weg 5"),
            actor_reference="office-panel",
            change_reason="Lieferadresse geändert",
        )

    assert repo.list_order_versions(order.order_id) == before_versions
    assert repo.get_order(order.order_id).candidate_order_version_id is None


def test_delivery_address_change_rejects_parent_not_owned_without_partial_version() -> (
    None
):
    inquiry = _sample_inquiry()
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order_a, v1a = _create_initial_order(svc, inquiry)
    other_inquiry = replace(inquiry, inquiry_id="22222222-2222-2222-2222-222222222222")
    order_b, v1b = _create_initial_order(svc, other_inquiry)
    before_versions = repo.list_order_versions(order_a.order_id)

    with pytest.raises(ValueError, match="not a version of order"):
        svc.propose_delivery_address_change(
            order_a.order_id,
            parent_order_version_id=v1b.order_version_id,
            delivery_address=CustomerAddress(street="Neuer Weg 5"),
            actor_reference="office-panel",
            change_reason="Lieferadresse geändert",
        )

    assert v1a.order_id == order_a.order_id
    assert v1b.order_id == order_b.order_id
    assert repo.list_order_versions(order_a.order_id) == before_versions


def test_legacy_parent_without_operational_context_does_not_invent_child_context() -> (
    None
):
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())

    v2 = svc.propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text=v1.time_window_text,
        location_text=v1.location_text,
        guest_count_estimate=40,
        planning_mode=v1.planning_mode,
        actor_reference="office",
        change_reason="anzahl",
    )

    assert repo.get_operational_context(v1.order_version_id) is None
    assert repo.get_operational_context(v2.order_version_id) is None


def test_in_memory_repository_rejects_operational_version_update() -> None:
    repo = InMemoryOrderRepository()
    order, v1 = seed_order(repo, _sample_inquiry())
    with pytest.raises(ValueError, match="snapshot is immutable"):
        repo.update_order_version(replace(v1, location_text="Andere Adresse"))
    assert repo.get_order(order.order_id) is not None
    assert repo.get_order_version(v1.order_version_id) == v1


def test_list_order_versions_and_get_latest_match_history_not_activation() -> None:
    """Full history via service; latest is max(version_number); history not collapsed to one active row."""
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    v2 = svc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 12, 3),
        time_window_text="spät",
        location_text="München",
        guest_count_estimate=50,
        planning_mode=PLANNING_MODES[0],
    )
    from_repo = repo.list_order_versions(order.order_id)
    full = svc.list_order_versions(order.order_id)
    assert full == from_repo
    assert len(full) == 2
    assert full[0].version_number == 1
    assert full[1].version_number == 2
    nums = [v.version_number for v in full]
    assert nums == sorted(nums)
    latest = svc.get_latest_order_version(order.order_id)
    assert latest is not None
    assert latest.order_version_id == v2.order_version_id
    assert latest.version_number == max(nums)
    assert latest.version_number == max(v1.version_number, v2.version_number)


def test_get_latest_order_version_returns_none_when_no_versions() -> None:
    """Explicit None when no versions; no synthetic active/effective version."""
    svc = OrderService(InMemoryOrderRepository())
    missing_id = "00000000-0000-0000-0000-000000000000"
    assert svc.get_latest_order_version(missing_id) is None
    assert svc.list_order_versions(missing_id) == []


def test_set_and_get_candidate_order_version_office_side_only() -> None:
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    assert repo.get_order(order.order_id) is not None
    assert repo.get_order(order.order_id).candidate_order_version_id is None
    assert svc.get_candidate_order_version(order.order_id) is None
    updated = svc.set_candidate_order_version(order.order_id, v1.order_version_id)
    assert updated.candidate_order_version_id == v1.order_version_id
    cand = svc.get_candidate_order_version(order.order_id)
    assert cand is not None
    assert cand.order_version_id == v1.order_version_id


def test_changing_candidate_preserves_full_version_history() -> None:
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    v2 = svc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 11, 2),
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[1],
    )
    svc.set_candidate_order_version(order.order_id, v1.order_version_id)
    svc.set_candidate_order_version(order.order_id, v2.order_version_id)
    hist = svc.list_order_versions(order.order_id)
    assert len(hist) == 2
    assert {hist[0].order_version_id, hist[1].order_version_id} == {
        v1.order_version_id,
        v2.order_version_id,
    }
    assert (
        svc.get_candidate_order_version(order.order_id).order_version_id
        == v2.order_version_id
    )


def test_candidate_can_differ_from_latest_historical_version() -> None:
    """B6: candidate is not latest-in-history; not effective operational selection."""
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    v2 = svc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 11, 2),
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[1],
    )
    svc.set_candidate_order_version(order.order_id, v1.order_version_id)
    latest = svc.get_latest_order_version(order.order_id)
    cand = svc.get_candidate_order_version(order.order_id)
    assert latest is not None and cand is not None
    assert latest.order_version_id == v2.order_version_id
    assert cand.order_version_id == v1.order_version_id
    assert latest.version_number > cand.version_number


def test_set_candidate_rejects_foreign_version_id() -> None:
    repo = InMemoryOrderRepository()
    svc = OrderService(repo)
    order, _ = seed_order(repo, _sample_inquiry())
    with pytest.raises(ValueError, match="not a version of order"):
        svc.set_candidate_order_version(
            order.order_id, "00000000-0000-0000-0000-000000000001"
        )


def _assert_dataclasses_have_no_b3_forbidden_fields() -> None:
    for cls in (Order, OrderVersion):
        names = {f.name for f in fields(cls)}
        assert names.isdisjoint(_B3_FORBIDDEN_FIELD_NAMES)


def test_order_domain_has_no_kitchen_or_release_surface() -> None:
    """B1/B2/B3/B6 guard, amended by OPERATIONAL_CORE_EXECUTION_PACK_V1 §7:
    exactly kitchen_print_confirmed_at (OrderVersion) and effective_order_version_id
    (Order) are allowed; no other activation/release/kiosk surface on Order types."""
    import catering_system.domain.order as order_mod

    lowered = _module_source_lower(order_mod)
    assert "ready_to_send" not in lowered
    assert "wochen" not in lowered
    assert "kiosk" not in lowered
    _assert_dataclasses_have_no_b3_forbidden_fields()
    assert {f.name for f in fields(Order)} == {
        "order_id",
        "source_inquiry_id",
        "created_at",
        "updated_at",
        "candidate_order_version_id",
        "effective_order_version_id",
        "cancelled_at",
    }
    assert {f.name for f in fields(OrderVersion)} == {
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
    }


def test_order_service_has_no_kitchen_or_release_surface() -> None:
    import catering_system.services.order_service as os_mod

    lowered = _module_source_lower(os_mod)
    assert "ready_to_send" not in lowered
    assert "kitchen" not in lowered
    assert "print" not in lowered
    for name in _B3_FORBIDDEN_FIELD_NAMES:
        assert not hasattr(OrderService, name)
    _assert_dataclasses_have_no_b3_forbidden_fields()

"""Narrow compatibility setup for legacy Office API order fixtures."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from catering_system.domain.offer import AcceptanceEvidence


@pytest.fixture(autouse=True)
def _office_api_order_fixture_uses_explicit_acceptance(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the legacy Office API setup aligned with the M1 acceptance gate."""
    module = request.module
    if module is None or Path(module.__file__).name != "test_office_api.py":
        return

    def create_order_with_operational_context(db_path: Path) -> tuple[str, str]:
        mod: Any = module
        inquiries = mod.SQLiteInquiryRepository(db_path)
        orders = mod.SQLiteOrderRepository(db_path)
        inquiry = mod.InquiryService(inquiries).create_inquiry(
            event_date=mod.date(2026, 10, 1),
            inquiry_source="manual",
            crm_stage="Neue Anfrage",
            customer_linkage={},
            time_window_text="mittags",
            location_text="Hamburg",
            guest_count_estimate=25,
            planning_mode="caterer_suggestion",
            call_verification_required=False,
            call_verification_status="not_required",
            contact_email="kunde@example.com",
            contact_phone="+4940235649",
            company_name="A GmbH",
            contact_name="B Person",
        )
        offer_version = mod._offer_version_for_order_creation()
        acceptance = AcceptanceEvidence(
            acceptance_id=str(uuid.uuid4()),
            offer_id=offer_version.offer_id,
            accepted_offer_version_id=offer_version.offer_version_id,
            accepted_variant_id=offer_version.variants[0].variant_id,
            accepted_at=offer_version.created_at,
            recorded_at=offer_version.created_at,
            channel="phone",
            evidence_reference="office-api-test-helper",
            recorded_by="unit-test",
        )
        order, version = mod.OrderService(orders).create_order_from_offer_version(
            inquiry.inquiry_id,
            offer_version,
            inquiry,
            acceptance_evidence=acceptance,
        )
        inquiries.close()
        orders.close()
        return order.order_id, version.order_version_id

    monkeypatch.setattr(
        module,
        "_create_order_with_operational_context",
        create_order_with_operational_context,
    )

"""Unit tests — Slice B4 customer verification (Core/office-side)."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from catering_system.domain.customer_verification import (
    ClientClassification,
    classify_from_linkage_and_contact_matches,
)
from catering_system.domain.inquiry import CRM_PIPELINE, Inquiry, PLANNING_MODES
from catering_system.services.customer_verification_service import (
    CustomerVerificationService,
    merge_verification_decision_into_inquiry,
)


def _module_source_lower(module: object) -> str:
    return Path(module.__file__).read_text(encoding="utf-8").lower()


def _base_inquiry(**kwargs: object) -> Inquiry:
    now = datetime.now(timezone.utc)
    defaults = dict(
        inquiry_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        event_date=date(2026, 5, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittag",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=True,
        call_verification_status="pending",
    )
    defaults.update(kwargs)
    return Inquiry(**defaults)  # type: ignore[arg-type]


def test_known_when_existing_customer_or_contact_linkage() -> None:
    svc = CustomerVerificationService()
    d = svc.evaluate(
        customer_linkage={"customer_id": "c-1"},
        email_matched=False,
        phone_matched=False,
    )
    assert d.classification == ClientClassification.KNOWN
    assert d.call_verification_required is False
    assert d.call_verification_status == "not_required"

    d2 = svc.evaluate(
        customer_linkage={"contact_id": "ct-9"},
        email_matched=True,
        phone_matched=False,
    )
    assert d2.classification == ClientClassification.KNOWN


def test_new_when_no_linkage_and_no_contact_match() -> None:
    svc = CustomerVerificationService()
    d = svc.evaluate(
        customer_linkage={},
        email_matched=False,
        phone_matched=False,
    )
    assert d.classification == ClientClassification.NEW
    assert d.call_verification_required is True
    assert d.call_verification_status == "pending"


def test_suspicious_when_partial_or_ambiguous_contact_match_without_linkage() -> None:
    svc = CustomerVerificationService()
    one = svc.evaluate(
        customer_linkage={},
        email_matched=True,
        phone_matched=False,
    )
    assert one.classification == ClientClassification.SUSPICIOUS
    assert one.call_verification_required is True
    assert one.call_verification_status == "pending"

    other = svc.evaluate(
        customer_linkage={},
        email_matched=False,
        phone_matched=True,
    )
    assert other.classification == ClientClassification.SUSPICIOUS

    both = svc.evaluate(
        customer_linkage={},
        email_matched=True,
        phone_matched=True,
    )
    assert both.classification == ClientClassification.SUSPICIOUS


def test_classify_domain_matches_service() -> None:
    dec = classify_from_linkage_and_contact_matches(
        customer_linkage={"customer_id": "x"},
        email_matched=False,
        phone_matched=False,
    )
    assert dec.classification == ClientClassification.KNOWN


def test_apply_updates_inquiry_verification_fields() -> None:
    svc = CustomerVerificationService()
    inquiry = _base_inquiry()
    dec = svc.evaluate(customer_linkage={}, email_matched=False, phone_matched=False)
    out = svc.apply_decision_to_inquiry(inquiry, dec)
    assert out.call_verification_required is True
    assert out.call_verification_status == "pending"


def test_apply_preserves_verified_inquiry() -> None:
    svc = CustomerVerificationService()
    inquiry = _base_inquiry(call_verification_status="verified")
    dec = svc.evaluate(customer_linkage={}, email_matched=False, phone_matched=False)
    out = merge_verification_decision_into_inquiry(inquiry, dec)
    assert out.call_verification_status == "verified"
    assert out is inquiry


def test_customer_verification_modules_have_no_kitchen_or_release_surface() -> None:
    import catering_system.domain.customer_verification as cv_mod
    import catering_system.services.customer_verification_service as cvs_mod

    for mod in (cv_mod, cvs_mod):
        lowered = _module_source_lower(mod)
        assert "kitchen" not in lowered
        assert "ready_to_send" not in lowered
        assert "wochen" not in lowered
        assert "kiosk" not in lowered

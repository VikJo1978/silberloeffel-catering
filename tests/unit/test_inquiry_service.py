"""Unit tests for InquiryService — A1 scaffold only."""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from datetime import date, timedelta, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService


def _base_create_kwargs() -> dict:
    return {
        "event_date": date(2026, 6, 1),
        "crm_stage": CRM_PIPELINE[0],
        "customer_linkage": {},
        "time_window_text": "abends",
        "location_text": "Berlin",
        "guest_count_estimate": 40,
        "planning_mode": PLANNING_MODES[0],
        "call_verification_required": True,
        "call_verification_status": CALL_VERIFICATION_STATUSES[1],
    }


def test_create_works_for_each_allowed_inquiry_source() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    for src in ("wix_form", "email", "phone", "manual"):
        q = svc.create_inquiry(inquiry_source=src, **_base_create_kwargs())
        assert q.inquiry_source == src


def test_invalid_inquiry_source_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="inquiry_source"):
        svc.create_inquiry(inquiry_source="other", **_base_create_kwargs())


def test_invalid_crm_stage_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    kw = _base_create_kwargs()
    kw["crm_stage"] = "not a stage"
    with pytest.raises(ValueError, match="crm_stage"):
        svc.create_inquiry(inquiry_source="manual", **kw)


def test_invalid_planning_mode_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    kw = _base_create_kwargs()
    kw["planning_mode"] = "buffet"
    with pytest.raises(ValueError, match="planning_mode"):
        svc.create_inquiry(inquiry_source="manual", **kw)


def test_invalid_call_verification_status_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    kw = _base_create_kwargs()
    kw["call_verification_status"] = "unknown"
    with pytest.raises(ValueError, match="call_verification_status"):
        svc.create_inquiry(inquiry_source="manual", **kw)


def test_invalid_customer_linkage_keys_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    kw = _base_create_kwargs()
    kw["customer_linkage"] = {"crm_id": "x"}
    with pytest.raises(ValueError, match="customer_linkage"):
        svc.create_inquiry(inquiry_source="manual", **kw)


def test_invalid_customer_linkage_value_types_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    kw = _base_create_kwargs()
    kw["customer_linkage"] = {"customer_id": 99}
    with pytest.raises(ValueError, match="customer_linkage"):
        svc.create_inquiry(inquiry_source="manual", **kw)


def test_customer_linkage_not_dict_rejected() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    kw = _base_create_kwargs()
    kw["customer_linkage"] = []  # type: ignore[assignment]
    with pytest.raises(TypeError, match="customer_linkage"):
        svc.create_inquiry(inquiry_source="manual", **kw)


def test_customer_linkage_placeholder_only_literal_true() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    kw = _base_create_kwargs()
    kw["customer_linkage"] = {"placeholder": False}
    with pytest.raises(ValueError, match="placeholder"):
        svc.create_inquiry(inquiry_source="manual", **kw)


def test_update_changes_fields_and_updated_at() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q0 = svc.create_inquiry(inquiry_source="email", **_base_create_kwargs())
    before = q0.updated_at
    q1 = svc.update_inquiry(
        q0.inquiry_id,
        crm_stage=CRM_PIPELINE[1],
        planning_mode=PLANNING_MODES[1],
        call_verification_status=CALL_VERIFICATION_STATUSES[2],
    )
    assert q1.crm_stage == CRM_PIPELINE[1]
    assert q1.planning_mode == PLANNING_MODES[1]
    assert q1.call_verification_status == CALL_VERIFICATION_STATUSES[2]
    assert q1.updated_at > before
    assert q1.created_at == q0.created_at


def test_update_inquiry_preserves_inquiry_id() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q0 = svc.create_inquiry(inquiry_source="manual", **_base_create_kwargs())
    q1 = svc.update_inquiry(q0.inquiry_id, location_text="Leipzig")
    assert q1.inquiry_id == q0.inquiry_id


def test_update_inquiry_preserves_created_at() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q0 = svc.create_inquiry(inquiry_source="manual", **_base_create_kwargs())
    q1 = svc.update_inquiry(q0.inquiry_id, time_window_text="mittags")
    assert q1.created_at == q0.created_at


def test_update_missing_inquiry_fails() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError, match="no inquiry"):
        svc.update_inquiry("00000000-0000-0000-0000-000000000000", crm_stage="x")


def test_required_fields_and_timestamps_on_create() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = svc.create_inquiry(inquiry_source="manual", **_base_create_kwargs())
    assert q.inquiry_id
    assert isinstance(q.inquiry_id, str)
    assert q.created_at
    assert q.updated_at
    assert q.created_at.tzinfo == timezone.utc
    assert q.updated_at.tzinfo == timezone.utc
    assert q.event_date == date(2026, 6, 1)
    assert q.inquiry_source == "manual"
    assert q.crm_stage == CRM_PIPELINE[0]
    assert isinstance(q.customer_linkage, dict)
    assert q.time_window_text == "abends"
    assert q.location_text == "Berlin"
    assert q.guest_count_estimate == 40
    assert q.planning_mode == PLANNING_MODES[0]
    assert q.call_verification_required is True
    assert q.call_verification_status == CALL_VERIFICATION_STATUSES[1]


def test_updated_at_changes_on_update() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q0 = svc.create_inquiry(inquiry_source="phone", **_base_create_kwargs())
    t0 = q0.updated_at
    q1 = svc.update_inquiry(q0.inquiry_id, location_text="Hamburg")
    assert q1.updated_at >= t0
    assert (q1.updated_at - t0) >= timedelta(seconds=0)


def test_no_inquiry_status_on_model() -> None:
    assert "InquiryStatus" not in Inquiry.__annotations__


def test_no_order_side_behavior_in_service_surface() -> None:
    assert not hasattr(InquiryService, "create_order")
    assert not hasattr(InquiryService, "to_order")


def test_repository_save_get_update_basic() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = svc.create_inquiry(inquiry_source="email", **_base_create_kwargs())
    got = repo.get_by_id(q.inquiry_id)
    assert got is not None
    assert got.inquiry_id == q.inquiry_id
    q2 = svc.update_inquiry(q.inquiry_id, guest_count_estimate=50)
    again = repo.get_by_id(q.inquiry_id)
    assert again is not None
    assert again.guest_count_estimate == 50
    assert q2.guest_count_estimate == 50


def test_repository_update_fails_on_missing_inquiry_id() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = svc.create_inquiry(inquiry_source="wix_form", **_base_create_kwargs())
    orphan = replace(q, inquiry_id="00000000-0000-0000-0000-000000000099")
    with pytest.raises(KeyError):
        repo.update(orphan)


def test_create_inquiry_logs_info_path(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    svc.create_inquiry(inquiry_source="manual", **_base_create_kwargs())
    texts = caplog.text
    assert "create_inquiry called" in texts
    assert "inquiry created" in texts


def test_update_inquiry_logs_warning_when_not_found(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    with pytest.raises(ValueError):
        svc.update_inquiry("missing-id", location_text="x")
    assert "update_inquiry failed: inquiry not found" in caplog.text


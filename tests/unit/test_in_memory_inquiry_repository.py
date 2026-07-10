"""Unit tests — InMemoryInquiryRepository.find_by_source_and_external_ref
(WEBSITE_FORM_INTAKE_IDEMPOTENCY_PACK_V1).

Proves the in-memory implementation matches SQLiteInquiryRepository's own
behavior for the same method (test_sqlite_repositories.py) — same shape of
tests, same four cases, so both Protocol implementations are provably in
parity, not just individually plausible.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)


def _sample_inquiry() -> Inquiry:
    now = datetime.now(timezone.utc)
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
    )


def test_find_by_source_and_external_ref_matches() -> None:
    repo = InMemoryInquiryRepository()
    inquiry = replace(
        _sample_inquiry(), inquiry_source="website_form", intake_external_ref="web-42"
    )
    repo.save(inquiry)
    found = repo.find_by_source_and_external_ref("website_form", "web-42")
    assert found is not None
    assert found.inquiry_id == inquiry.inquiry_id


def test_find_by_source_and_external_ref_returns_none_when_source_differs() -> None:
    repo = InMemoryInquiryRepository()
    inquiry = replace(
        _sample_inquiry(), inquiry_source="configurator", intake_external_ref="42"
    )
    repo.save(inquiry)
    assert repo.find_by_source_and_external_ref("website_form", "42") is None


def test_find_by_source_and_external_ref_returns_none_when_ref_differs() -> None:
    repo = InMemoryInquiryRepository()
    inquiry = replace(
        _sample_inquiry(), inquiry_source="website_form", intake_external_ref="web-42"
    )
    repo.save(inquiry)
    assert repo.find_by_source_and_external_ref("website_form", "does-not-exist") is None


def test_find_by_source_and_external_ref_returns_none_when_ref_missing() -> None:
    repo = InMemoryInquiryRepository()
    inquiry = replace(
        _sample_inquiry(), inquiry_source="website_form", intake_external_ref=None
    )
    repo.save(inquiry)
    assert repo.find_by_source_and_external_ref("website_form", "web-42") is None


def test_find_by_source_and_external_ref_returns_none_when_repo_empty() -> None:
    repo = InMemoryInquiryRepository()
    assert repo.find_by_source_and_external_ref("website_form", "anything") is None

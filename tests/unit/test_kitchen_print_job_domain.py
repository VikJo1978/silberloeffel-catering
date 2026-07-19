"""KitchenPrintJob domain validation and pure derivation coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from catering_system.domain.kitchen_print_job import (
    KitchenPrintJob,
    KitchenPrintPolicy,
    derive_kitchen_print_job_state,
    validate_kitchen_print_job_transition,
)

JOB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ORDER = "11111111-1111-4111-8111-111111111111"
VERSION = "22222222-2222-4222-8222-222222222222"
_NOW = datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc)


def _job(**overrides: object) -> KitchenPrintJob:
    base = dict(
        print_job_id=JOB,
        order_id=ORDER,
        order_version_id=VERSION,
        attempt_number=1,
        requested_at=_NOW,
        accept_deadline_at=_NOW + timedelta(seconds=30),
    )
    base.update(overrides)
    return KitchenPrintJob(**base)  # type: ignore[arg-type]


def test_policy_rejects_non_positive_ack_timeout() -> None:
    with pytest.raises(ValueError, match="acknowledgment_timeout must be positive"):
        KitchenPrintPolicy(acknowledgment_timeout=timedelta(0))


def test_job_rejects_non_uuid4_print_job_id() -> None:
    with pytest.raises(ValueError, match="print_job_id must be UUID4"):
        _job(print_job_id="not-a-uuid")


def test_job_rejects_accept_deadline_before_request() -> None:
    with pytest.raises(
        ValueError, match="accept_deadline_at must be after requested_at"
    ):
        _job(accept_deadline_at=_NOW - timedelta(seconds=1))


def test_job_rejects_accepted_without_ack_deadline() -> None:
    with pytest.raises(
        ValueError, match="accepted_at and ack_deadline_at must be set together"
    ):
        _job(accepted_at=_NOW + timedelta(seconds=5))


def test_job_rejects_rejection_without_code() -> None:
    with pytest.raises(
        ValueError, match="rejected_at and rejection_code must be set together"
    ):
        _job(rejected_at=_NOW + timedelta(seconds=5))


def test_job_rejects_acknowledgement_without_acceptance() -> None:
    with pytest.raises(
        ValueError, match="acknowledgement requires technical acceptance"
    ):
        _job(acknowledged_at=_NOW + timedelta(seconds=10))


def test_job_rejects_acknowledgement_with_conflicting_terminal_facts() -> None:
    with pytest.raises(
        ValueError, match="acknowledgement conflicts with terminal job facts"
    ):
        _job(
            accepted_at=_NOW + timedelta(seconds=5),
            ack_deadline_at=_NOW + timedelta(minutes=1),
            rejected_at=_NOW + timedelta(seconds=6),
            rejection_code="render_failed",
            acknowledged_at=_NOW + timedelta(seconds=7),
        )


def test_transition_rejects_immutable_field_rewrite() -> None:
    previous = _job()
    updated = replace(previous, order_id="33333333-3333-4333-8333-333333333333")
    with pytest.raises(ValueError, match="print job field order_id is immutable"):
        validate_kitchen_print_job_transition(previous, updated)


def test_transition_rejects_revoking_recorded_fact() -> None:
    previous = replace(
        _job(),
        accepted_at=_NOW + timedelta(seconds=5),
        ack_deadline_at=_NOW + timedelta(minutes=1),
    )
    updated = replace(previous, accepted_at=None, ack_deadline_at=None)
    with pytest.raises(ValueError, match="print job fact accepted_at is not revocable"):
        validate_kitchen_print_job_transition(previous, updated)


def test_derive_state_cancelled_when_order_cancelled_before_ack() -> None:
    job = _job()
    assert (
        derive_kitchen_print_job_state(job, now=_NOW, order_cancelled=True)
        == "cancelled"
    )


def test_derive_state_ack_overdue_after_deadline() -> None:
    accepted = _NOW + timedelta(seconds=5)
    job = replace(
        _job(),
        accepted_at=accepted,
        ack_deadline_at=accepted + timedelta(minutes=1),
    )
    assert (
        derive_kitchen_print_job_state(job, now=accepted + timedelta(minutes=2))
        == "ack_overdue"
    )


def test_derive_state_acceptance_overdue_before_accept() -> None:
    job = _job(accept_deadline_at=_NOW + timedelta(seconds=10))
    assert (
        derive_kitchen_print_job_state(job, now=_NOW + timedelta(seconds=11))
        == "acceptance_overdue"
    )

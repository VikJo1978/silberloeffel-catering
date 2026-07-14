"""Pure office inquiry-state derivation for truthful queues and actions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from catering_system.domain.inquiry import (
    Inquiry,
    derive_inquiry_office_state,
)


def _inquiry(**overrides: object) -> Inquiry:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
    values: dict[str, object] = {
        "inquiry_id": "11111111-1111-4111-8111-111111111111",
        "event_date": date(2026, 10, 1),
        "created_at": now,
        "updated_at": now,
        "inquiry_source": "manual",
        "crm_stage": "Neue Anfrage",
        "customer_linkage": {},
        "time_window_text": "mittags",
        "location_text": "Hamburg",
        "guest_count_estimate": 25,
        "planning_mode": "caterer_suggestion",
        "call_verification_required": False,
        "call_verification_status": "not_required",
    }
    values.update(overrides)
    return Inquiry(**values)  # type: ignore[arg-type]


def test_open_inquiry_derives_convert_action() -> None:
    state = derive_inquiry_office_state(
        _inquiry(),
        has_order=False,
        has_active_order=False,
    )
    assert state.is_open is True
    assert state.next_action == "convert"


def test_required_unverified_call_derives_verify_only() -> None:
    state = derive_inquiry_office_state(
        _inquiry(
            call_verification_required=True,
            call_verification_status="pending",
        ),
        has_order=False,
        has_active_order=False,
    )
    assert state.is_open is True
    assert state.next_action == "verify"


def test_rejected_inquiry_is_closed_without_action() -> None:
    state = derive_inquiry_office_state(
        _inquiry(crm_stage="Abgelehnt / verloren"),
        has_order=False,
        has_active_order=False,
    )
    assert state.is_open is False
    assert state.next_action is None


def test_converted_inquiry_is_closed_and_active_order_blocks_action() -> None:
    state = derive_inquiry_office_state(
        _inquiry(crm_stage="Bestätigt / Auftrag"),
        has_order=True,
        has_active_order=True,
    )
    assert state.is_open is False
    assert state.next_action is None


def test_cancelled_order_stays_out_of_queue_but_allows_existing_reconversion() -> None:
    state = derive_inquiry_office_state(
        _inquiry(crm_stage="Bestätigt / Auftrag"),
        has_order=True,
        has_active_order=False,
    )
    assert state.is_open is False
    assert state.next_action == "convert"


def test_active_order_requires_existing_order_fact() -> None:
    with pytest.raises(ValueError, match="active order"):
        derive_inquiry_office_state(
            replace(_inquiry(), crm_stage="In Prüfung"),
            has_order=False,
            has_active_order=True,
        )

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from tests.helpers.courier_cash_handoff_contract import (
    ACTOR_ROLES,
    COMMAND_KEYS,
    CONTRACT_VERSION,
    EVENT_TYPES,
    NOT_RECEIVED_REASONS,
    PROJECTION_KEYS,
    SUCCESS_KEYS,
    assert_no_financial_fields,
    validate_command,
    validate_projection,
    validate_response,
)

_ROOT = Path(__file__).parents[2]
_CONTRACT = _ROOT / "docs/contracts/courier-cash-handoff-v1"


def _json(name: str) -> object:
    return json.loads((_CONTRACT / name).read_text(encoding="utf-8"))


def _fixtures() -> dict[str, object]:
    value = _json("fixtures.json")
    assert isinstance(value, dict)
    return value


def test_contract_pack_is_frozen_and_chooses_direct_write_topology() -> None:
    text = (_CONTRACT / "README.md").read_text(encoding="utf-8")
    assert "Status: **FROZEN**" in text
    assert "POST /machine/v1/courier/cash-events" in text
    assert "Kiosk remains strictly read-only" in text
    assert "cash_execution_context_id" in text
    assert "same persisted success response" in text


def test_projection_schema_exact_and_shared_fixtures_valid() -> None:
    schema = _json("order-feed-cash-handoff.schema.json")
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == PROJECTION_KEYS
    assert schema["properties"]["contract_version"]["const"] == CONTRACT_VERSION
    projections = _fixtures()["projection"]
    for projection in projections.values():
        validate_projection(projection)


def test_command_schema_freezes_exact_event_role_reason_sets() -> None:
    schema = _json("cash-event-command.schema.json")
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == COMMAND_KEYS
    assert set(schema["properties"]["event_type"]["enum"]) == EVENT_TYPES
    assert set(schema["properties"]["actor_role"]["enum"]) == ACTOR_ROLES
    assert set(schema["properties"]["not_received_reason"]["enum"]) == (
        NOT_RECEIVED_REASONS | {None}
    )


def test_all_command_fixtures_validate() -> None:
    commands = _fixtures()["commands"]
    assert {command["event_type"] for command in commands.values()} == EVENT_TYPES
    for command in commands.values():
        validate_command(command)


def test_all_not_received_reasons_follow_note_rule() -> None:
    base = _fixtures()["commands"]["not_received_other"]
    for reason in NOT_RECEIVED_REASONS:
        command = deepcopy(base)
        command["not_received_reason"] = reason
        command["note"] = "Manueller Hinweis" if reason == "OTHER" else None
        validate_command(command)

    missing_note = deepcopy(base)
    missing_note["note"] = None
    with pytest.raises(ValueError, match="note"):
        validate_command(missing_note)

    unwanted_note = deepcopy(base)
    unwanted_note["not_received_reason"] = "CUSTOMER_NOT_FOUND"
    with pytest.raises(ValueError, match="only allowed"):
        validate_command(unwanted_note)


def test_driver_never_produces_final_paid_and_chef_confirmation_is_distinct() -> None:
    rows = _json("transition-table.json")["transitions"]
    final_rows = [row for row in rows if row["final_payment"]]
    assert final_rows
    assert all("DRIVER" not in row["actor_roles"] for row in final_rows)
    assert {row["event_type"] for row in final_rows} == {
        "BAR_RECEIVED_FROM_DRIVER_BY_CHEF",
        "BAR_RECEIVED_DIRECT_BY_CHEF_AND_QUITTUNG_HANDED_TO_CUSTOMER",
    }
    handoff = next(row for row in rows if row["event_type"] == "BAR_HANDED_TO_CHEF")
    confirm = next(
        row
        for row in rows
        if row["event_type"] == "BAR_RECEIVED_FROM_DRIVER_BY_CHEF"
    )
    assert handoff["to_state"] == "AWAITING_CHEF_CONFIRMATION"
    assert handoff["actor_roles"] == ["DRIVER"]
    assert confirm["from_states"] == ["AWAITING_CHEF_CONFIRMATION"]
    assert confirm["actor_roles"] == ["CHEF"]
    assert confirm["to_state"] == "FINAL_PAID"


def test_not_received_and_privileged_correction_map_to_manual_office_truth() -> None:
    rows = _json("transition-table.json")["transitions"]
    not_received = next(row for row in rows if row["event_type"] == "BAR_NOT_RECEIVED")
    assert not_received["to_state"] == "NOT_RECEIVED"
    assert not_received["final_payment"] is False
    assert not_received["office_task"] == "Barzahlung klären"

    correction = next(
        row for row in rows if row["event_type"] == "BAR_HANDOFF_CORRECTION"
    )
    assert set(correction["actor_roles"]) == {"CHEF", "OFFICE"}
    assert correction["to_state"] == "MANUAL_REVIEW_REQUIRED"
    command = deepcopy(_fixtures()["commands"]["correction"])
    command["actor_role"] = "DRIVER"
    with pytest.raises(ValueError, match="not allowed"):
        validate_command(command)


def test_success_stale_unauthorized_and_outage_fixtures_are_explicit() -> None:
    responses = _fixtures()["responses"]
    success = responses["driver_custody"]
    validate_response(success)
    assert set(success) == SUCCESS_KEYS
    assert success["cash_state"] == "DRIVER_CUSTODY"
    assert validate_response(responses["stale_context"]) == {
        "error": "stale_cash_context"
    }
    assert validate_response(responses["unauthorized"]) == {"error": "unauthorized"}
    assert validate_response(responses["unavailable"]) == {
        "error": "core_unavailable"
    }


def test_replay_stale_and_outage_behaviour_is_frozen() -> None:
    text = (_CONTRACT / "README.md").read_text(encoding="utf-8")
    assert '409 `{"error":"idempotency_conflict"}`' in text
    assert '409 `{"error":"stale_order_revision"}`' in text
    assert '409 `{"error":"stale_cash_context"}`' in text
    assert "conflicts before mutation" in text
    assert "must **not** display the event as saved" in text

    command = _fixtures()["commands"]["driver_received"]
    replay = deepcopy(command)
    assert replay == command
    conflict = deepcopy(command)
    conflict["actor_id"] = "driver-99"
    assert conflict["idempotency_key"] == command["idempotency_key"]
    assert conflict != command


def test_contract_json_assets_never_contain_financial_fields() -> None:
    for path in sorted(_CONTRACT.glob("*.json")):
        assert_no_financial_fields(
            json.loads(path.read_text(encoding="utf-8"))
        )

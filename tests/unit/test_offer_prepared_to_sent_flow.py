"""Integration test: prepare-offer → mark-sent → Sent with immutable snapshot."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pytest

from catering_system.domain.offer import derive_offer_state
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
)
from tests.unit.test_office_api import (
    _MARK_SENT_ARGS,
    _mark_sent_url,
    _post,
    _prepare_offer_url,
    _record_acceptance_url,
    _seed,
    _seed_employee_auth,
    _start_api_server,
    _valid_offer_snapshot,
)

_RECORD_ACCEPTANCE_ARGS = {
    "accepted_variant_id": "44444444-4444-4444-8444-444444444441",
    "accepted_at": "2026-07-15T11:00:00+00:00",
    "channel": "email",
    "evidence_reference": "reply-1",
    "note": None,
}


@pytest.fixture()
def office_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from catering_system.ui import office_api_views

    monkeypatch.setattr(
        office_api_views,
        "berlin_today",
        lambda: date(2026, 7, 15),
    )
    db = tmp_path / "core.db"
    ids = _seed(db)
    _seed_employee_auth(db)
    server, thread, base = _start_api_server(db)
    yield base, ids, db
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert thread.is_alive() is False


def test_prepare_offer_mark_sent_preserves_snapshot_and_blocks_replay(
    office_api: tuple[str, dict[str, str], Path],
) -> None:
    base, ids, db = office_api
    inquiry_id = ids["inquiry_offer_ready"]
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry_id)

    prepare_status, prepare_body, _headers = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": snapshot},
    )
    assert prepare_status == 201
    offer_id = prepare_body["offer_id"]
    version_id = prepare_body["offer_version_id"]

    offers = SQLiteOfferRepository(db)
    prepared = offers.get(offer_id)
    assert prepared is not None
    before_hash = prepared.versions[0].snapshot_hash
    offers.close()

    mark_url = _mark_sent_url(base, offer_id, version_id)
    mark_status, mark_body, _headers = _post(mark_url, args=_MARK_SENT_ARGS)
    assert mark_status == 200
    assert mark_body["offer_version_id"] == version_id

    offers = SQLiteOfferRepository(db)
    after = offers.get(offer_id)
    assert after is not None
    version = after.versions[0]
    assert version.snapshot_hash == before_hash
    assert len(after.sent_evidence) == 1
    assert derive_offer_state(after, version_id, today=date(2026, 7, 15)) == "Sent"
    offers.close()

    replay_status, replay_body, _headers = _post(
        mark_url,
        args=_MARK_SENT_ARGS,
        command_id=str(uuid.uuid4()),
    )
    assert replay_status == 409
    assert replay_body["error"] == "sent_evidence_exists"

    offers = SQLiteOfferRepository(db)
    reloaded = offers.get(offer_id)
    assert reloaded is not None
    assert len(reloaded.sent_evidence) == 1
    assert reloaded.versions[0].snapshot_hash == before_hash
    offers.close()


def test_record_acceptance_rejects_prepared_offer(
    office_api: tuple[str, dict[str, str], Path],
) -> None:
    base, ids, _db = office_api
    inquiry_id = ids["inquiry_offer_ready"]

    prepare_status, prepare_body, _headers = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert prepare_status == 201

    accept_status, accept_body, _headers = _post(
        _record_acceptance_url(base, prepare_body["offer_id"], prepare_body["offer_version_id"]),
        args=_RECORD_ACCEPTANCE_ARGS,
    )
    assert accept_status == 422
    assert accept_body["error"] == "acceptance_blocked"

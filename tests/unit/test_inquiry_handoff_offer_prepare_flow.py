"""Integration test: Inquiry → trusted handoff → prepare-offer → OfferVersion.

Documents the committed commercial path without UI or Configurator runtime.
Configurator draft state lives outside Core; this test proves the Core contract
that follows a successful handoff exchange.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
)
from catering_system.domain.offer import derive_offer_state
from tests.unit.test_office_api import (
    _employee_auth,
    _exchange_handoff,
    _mint_first_offer_handoff,
    _post,
    _prepare_offer_url,
    _seed,
    _seed_employee_auth,
    _start_api_server,
    _valid_offer_snapshot,
)


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


def _inquiry_snapshot(db: Path, inquiry_id: str) -> dict[str, object]:
    repo = SQLiteInquiryRepository(db)
    inquiry = repo.get_by_id(inquiry_id)
    repo.close()
    assert inquiry is not None
    return asdict(inquiry)


def test_trusted_handoff_then_prepare_offer_commits_single_offer_version(
    office_api: tuple[str, dict[str, str], Path],
) -> None:
    base, ids, db = office_api
    inquiry_id = ids["inquiry_offer_ready"]
    inquiry_before = _inquiry_snapshot(db, inquiry_id)

    auth = _employee_auth(db)
    code, handoff_id = _mint_first_offer_handoff(
        db,
        inquiry_id=inquiry_id,
        account_id=auth["account_id"],
    )

    exchange_status, exchange_body, _headers = _exchange_handoff(
        base,
        code=code,
        session_token=auth["session_token"],
    )
    assert exchange_status == 200
    assert exchange_body["handoff_id"] == handoff_id
    assert exchange_body["operation"] == "prepare_first_offer"
    assert exchange_body["inquiry"]["inquiry_id"] == inquiry_id

    snapshot = _valid_offer_snapshot(inquiry_id=inquiry_id)
    prepare_url = _prepare_offer_url(base, inquiry_id)
    command_id = str(uuid.uuid4())

    prepare_status, prepare_body, _headers = _post(
        prepare_url,
        args={"snapshot": snapshot},
        command_id=command_id,
    )
    assert prepare_status == 201
    offer_id = prepare_body["offer_id"]
    version_id = prepare_body["offer_version_id"]
    assert prepare_body["snapshot_id"] == snapshot["snapshot_id"]

    inquiry_after = _inquiry_snapshot(db, inquiry_id)
    assert inquiry_after == inquiry_before

    offers = SQLiteOfferRepository(db)
    stored = offers.get_by_source_inquiry_id(inquiry_id)
    assert stored is not None
    assert stored.offer_id == offer_id
    assert stored.source_inquiry_id == inquiry_id
    assert len(stored.versions) == 1
    version = stored.versions[0]
    assert version.offer_version_id == version_id
    assert version.version_number == 1
    assert version.snapshot_hash == snapshot["snapshot_hash"]
    assert version.snapshot_id == snapshot["snapshot_id"]
    assert derive_offer_state(stored, version_id, today=date(2026, 7, 15)) == "Prepared"
    offers.close()

    duplicate_status, duplicate_body, _headers = _post(
        prepare_url,
        args={"snapshot": snapshot},
        command_id=str(uuid.uuid4()),
    )
    assert duplicate_status == 409
    assert duplicate_body["error"] == "offer_already_exists"
    assert duplicate_body["offer_id"] == offer_id

    offers = SQLiteOfferRepository(db)
    assert len(offers.get(offer_id).versions) == 1  # type: ignore[union-attr]
    offers.close()

    conn = sqlite3.connect(db)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM orders WHERE source_inquiry_id = ?",
            (inquiry_id,),
        ).fetchone()[0]
        == 0
    )
    conn.close()

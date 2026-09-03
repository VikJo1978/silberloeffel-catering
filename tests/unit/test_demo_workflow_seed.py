from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from catering_system.demo_workflow_seed import seed_demo_workflow


def _counts(db_path: Path) -> tuple[int, int, int, int]:
    connection = sqlite3.connect(db_path)
    try:
        return tuple(
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("inquiries", "offers", "orders", "employee_accounts")
        )
    finally:
        connection.close()


def test_demo_seed_creates_multiple_workflow_stages(tmp_path: Path) -> None:
    db_path = tmp_path / "core.db"

    summary = seed_demo_workflow(db_path)

    assert summary.inquiries == 9
    assert summary.offers == 6
    assert summary.orders == 2
    assert set(summary.offer_states) == {
        "Prepared",
        "Sent",
        "Rejected",
        "Accepted",
        "Converted",
    }
    assert summary.offer_states.count("Converted") == 2
    assert _counts(db_path)[:3] == (9, 6, 2)


def test_demo_seed_refuses_to_mix_with_existing_workflow_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "core.db"
    first = seed_demo_workflow(db_path)

    with pytest.raises(RuntimeError, match="already exist"):
        seed_demo_workflow(db_path)

    assert _counts(db_path)[:3] == (
        first.inquiries,
        first.offers,
        first.orders,
    )

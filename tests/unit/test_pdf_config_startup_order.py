"""PDF_STARTUP_ORDER_AND_DOCS_V1 (issue #41) — Office Panel direct-mode
startup must validate PDF configuration before opening core.db: an invalid
OFFICE_PDF_* configuration must never create a database file, run a
migration, or construct a repository. Office API already gets this right;
its tests here are a regression guard, not new behavior."""

from __future__ import annotations

import hashlib
import os
import select
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.offer_pdf_static_content import TEST_ACCEPTANCE_STATEMENT

_VALID_PDF_ENV = {
    "OFFICE_PDF_COMPANY_LEGAL_NAME": "TEST GmbH [PLATZHALTER]",
    "OFFICE_PDF_COMPANY_ADDRESS_LINES": "Teststraße 1|20095 Hamburg",
    "OFFICE_PDF_ACCEPTANCE_STATEMENT": TEST_ACCEPTANCE_STATEMENT,
}

_ALL_OFFICE_PDF_VARS = (
    "OFFICE_PDF_COMPANY_LEGAL_NAME",
    "OFFICE_PDF_COMPANY_ADDRESS_LINES",
    "OFFICE_PDF_ACCEPTANCE_STATEMENT",
    "OFFICE_PDF_LOGO_PATH",
    "OFFICE_PDF_COMPANY_PHONE",
    "OFFICE_PDF_COMPANY_EMAIL",
    "OFFICE_PDF_COMPANY_WEB",
    "OFFICE_PDF_COMPANY_REGISTER_TEXT",
    "OFFICE_PDF_COMPANY_VAT_ID_TEXT",
    "OFFICE_PDF_FOOTER_NOTE",
    "OFFICE_PDF_BANK_DETAILS_TEXT",
)


def _base_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    for name in (*_ALL_OFFICE_PDF_VARS, "CORE_OFFICE_API_URL", "CORE_OFFICE_API_TOKEN"):
        env.pop(name, None)
    return env


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# --- Office Panel direct mode: invalid PDF config has no DB side effect -----


def test_direct_mode_invalid_pdf_config_creates_no_db_file(tmp_path: Path) -> None:
    db = tmp_path / "does-not-exist-yet.db"
    env = _base_env()
    env["OFFICE_PANEL_PASSWORD"] = "test-password-local-only"
    env["OFFICE_PDF_COMPANY_LEGAL_NAME"] = _VALID_PDF_ENV[
        "OFFICE_PDF_COMPANY_LEGAL_NAME"
    ]
    env["OFFICE_PDF_COMPANY_ADDRESS_LINES"] = _VALID_PDF_ENV[
        "OFFICE_PDF_COMPANY_ADDRESS_LINES"
    ]
    # OFFICE_PDF_ACCEPTANCE_STATEMENT deliberately left unset.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "catering_system.ui.office_panel",
            "--db",
            str(db),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "OFFICE_PDF_ACCEPTANCE_STATEMENT" in result.stderr
    assert not db.exists(), "invalid PDF config must not create the database file"
    assert "Office panel on http" not in result.stdout


def test_direct_mode_invalid_pdf_config_leaves_existing_db_byte_identical(
    tmp_path: Path,
) -> None:
    """A pre-existing, already-migrated database must be untouched when
    startup later fails on PDF configuration."""
    from catering_system.repositories.bootstrap_customer_identity_schema import (
        bootstrap_customer_identity_schema,
    )
    from catering_system.repositories.core_transaction import open_core_connection
    from catering_system.repositories.sqlite_inquiry_repository import (
        SQLiteInquiryRepository,
    )

    db = tmp_path / "pre-existing.db"
    connection = open_core_connection(str(db))
    SQLiteInquiryRepository.from_connection(connection)
    bootstrap_customer_identity_schema(connection)
    connection.close()
    before_hash = hashlib.sha256(db.read_bytes()).hexdigest()

    env = _base_env()
    env["OFFICE_PANEL_PASSWORD"] = "test-password-local-only"
    env["OFFICE_PDF_COMPANY_LEGAL_NAME"] = _VALID_PDF_ENV[
        "OFFICE_PDF_COMPANY_LEGAL_NAME"
    ]
    env["OFFICE_PDF_COMPANY_ADDRESS_LINES"] = _VALID_PDF_ENV[
        "OFFICE_PDF_COMPANY_ADDRESS_LINES"
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "catering_system.ui.office_panel",
            "--db",
            str(db),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    after_hash = hashlib.sha256(db.read_bytes()).hexdigest()
    assert after_hash == before_hash


def test_direct_mode_invalid_pdf_config_never_opens_connection_or_builds_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """White-box companion to the black-box DB-file tests above: every
    repository construction in direct mode requires the connection object
    that only ``open_core_connection`` produces, so a tripwire on that one
    call proves no migration and no repository construction was even
    attempted — not merely that they left no observable trace."""
    import catering_system.ui.office_panel as office_panel_module
    from catering_system.repositories import core_transaction

    calls: list[str] = []

    def _tripwire(db_path: object) -> None:
        calls.append("open_core_connection")
        raise AssertionError("open_core_connection must not be called")

    monkeypatch.setattr(core_transaction, "open_core_connection", _tripwire)
    monkeypatch.setenv("OFFICE_PANEL_PASSWORD", "test-password-local-only")
    monkeypatch.setenv(
        "OFFICE_PDF_COMPANY_LEGAL_NAME", _VALID_PDF_ENV["OFFICE_PDF_COMPANY_LEGAL_NAME"]
    )
    monkeypatch.setenv(
        "OFFICE_PDF_COMPANY_ADDRESS_LINES",
        _VALID_PDF_ENV["OFFICE_PDF_COMPANY_ADDRESS_LINES"],
    )
    monkeypatch.delenv("OFFICE_PDF_ACCEPTANCE_STATEMENT", raising=False)
    monkeypatch.delenv("CORE_OFFICE_API_URL", raising=False)
    monkeypatch.delenv("CORE_OFFICE_API_TOKEN", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["office_panel", "--db", str(tmp_path / "tripwire.db"), "--port", "0"],
    )
    with pytest.raises(SystemExit) as exc_info:
        office_panel_module.main()
    assert "OFFICE_PDF_ACCEPTANCE_STATEMENT" in str(exc_info.value)
    assert calls == []


def test_direct_mode_valid_pdf_config_still_starts_normally(tmp_path: Path) -> None:
    """Regression guard: moving the preflight earlier must not change the
    valid-configuration startup path."""
    db = tmp_path / "valid-startup.db"
    env = _base_env()
    env["OFFICE_PANEL_PASSWORD"] = "test-password-local-only"
    env.update(_VALID_PDF_ENV)
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",  # unbuffered stdout, so readline() below sees it promptly
            "-m",
            "catering_system.ui.office_panel",
            "--db",
            str(db),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready, _, _ = select.select([proc.stdout], [], [], 10)
        assert ready, "office panel printed no startup banner within 10s"
        line = proc.stdout.readline()
        assert "Office panel on http" in line
        assert proc.poll() is None  # still running, didn't crash on startup
        assert db.exists()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# --- Office API: regression guard (already correct before this slice) -------


def test_office_api_invalid_pdf_config_creates_no_db_file(tmp_path: Path) -> None:
    db = tmp_path / "api-does-not-exist-yet.db"
    env = _base_env()
    env["OFFICE_API_TOKEN"] = "test-token-local-only"
    env["OFFICE_PDF_COMPANY_LEGAL_NAME"] = _VALID_PDF_ENV[
        "OFFICE_PDF_COMPANY_LEGAL_NAME"
    ]
    env["OFFICE_PDF_COMPANY_ADDRESS_LINES"] = _VALID_PDF_ENV[
        "OFFICE_PDF_COMPANY_ADDRESS_LINES"
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "catering_system.ui.office_api",
            "--db",
            str(db),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "OFFICE_PDF_ACCEPTANCE_STATEMENT" in result.stderr
    assert not db.exists()
    assert "Core Office API on http" not in result.stdout


def test_office_api_valid_pdf_config_still_starts_normally(tmp_path: Path) -> None:
    db = tmp_path / "api-valid-startup.db"
    env = _base_env()
    env["OFFICE_API_TOKEN"] = "test-token-local-only"
    env.update(_VALID_PDF_ENV)
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "catering_system.ui.office_api",
            "--db",
            str(db),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready, _, _ = select.select([proc.stdout], [], [], 10)
        assert ready, "office api printed no startup banner within 10s"
        line = proc.stdout.readline()
        assert "Core Office API on http" in line
        assert proc.poll() is None
        assert db.exists()
    finally:
        proc.terminate()
        proc.wait(timeout=10)

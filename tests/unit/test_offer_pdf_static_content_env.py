"""Shared OFFICE_PDF_* environment contract (used by Office API and Office
Panel direct-mode startup) — fail-closed: no invented/placeholder company
text may silently reach production composition."""

from __future__ import annotations

import pytest

from catering_system.ui.offer_pdf_static_content_env import (
    offer_pdf_static_content_from_env,
)
from tests.helpers.offer_pdf_static_content import TEST_ACCEPTANCE_STATEMENT

_REQUIRED_VARS = (
    "OFFICE_PDF_COMPANY_LEGAL_NAME",
    "OFFICE_PDF_COMPANY_ADDRESS_LINES",
    "OFFICE_PDF_ACCEPTANCE_STATEMENT",
)
_OPTIONAL_VARS = (
    "OFFICE_PDF_COMPANY_PHONE",
    "OFFICE_PDF_COMPANY_EMAIL",
    "OFFICE_PDF_COMPANY_WEB",
    "OFFICE_PDF_COMPANY_REGISTER_TEXT",
    "OFFICE_PDF_COMPANY_VAT_ID_TEXT",
    "OFFICE_PDF_FOOTER_NOTE",
    "OFFICE_PDF_BANK_DETAILS_TEXT",
    "OFFICE_PDF_LOGO_PATH",
)


def _clear_all(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _REQUIRED_VARS + _OPTIONAL_VARS:
        monkeypatch.delenv(name, raising=False)


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_PDF_COMPANY_LEGAL_NAME", "Silberlöffel GmbH")
    monkeypatch.setenv(
        "OFFICE_PDF_COMPANY_ADDRESS_LINES", "Musterstraße 1|20095 Hamburg"
    )
    monkeypatch.setenv(
        "OFFICE_PDF_ACCEPTANCE_STATEMENT", "Approved production wording."
    )


def test_missing_all_required_vars_fails_startup_with_clear_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all(monkeypatch)
    with pytest.raises(SystemExit) as exc_info:
        offer_pdf_static_content_from_env()
    message = str(exc_info.value)
    for name in _REQUIRED_VARS:
        assert name in message


def test_missing_one_required_var_fails_startup_naming_only_that_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    monkeypatch.delenv("OFFICE_PDF_ACCEPTANCE_STATEMENT", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        offer_pdf_static_content_from_env()
    message = str(exc_info.value)
    assert "OFFICE_PDF_ACCEPTANCE_STATEMENT" in message
    assert "OFFICE_PDF_COMPANY_LEGAL_NAME" not in message
    assert "OFFICE_PDF_COMPANY_ADDRESS_LINES" not in message


def test_blank_required_var_is_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    monkeypatch.setenv("OFFICE_PDF_COMPANY_LEGAL_NAME", "   ")
    with pytest.raises(SystemExit) as exc_info:
        offer_pdf_static_content_from_env()
    assert "OFFICE_PDF_COMPANY_LEGAL_NAME" in str(exc_info.value)


def test_valid_required_vars_produce_populated_static_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    content = offer_pdf_static_content_from_env()
    assert content.company_legal_name == "Silberlöffel GmbH"
    assert content.company_address_lines == ("Musterstraße 1", "20095 Hamburg")
    assert content.acceptance_statement == "Approved production wording."
    assert content.company_phone is None
    assert content.logo_png_bytes is None


def test_env_loaded_content_never_carries_the_test_placeholder_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production composition (Office API and Office Panel direct-mode
    startup) reads real approved text through this loader only — it must
    never produce the obviously-fake test placeholder used by tests/
    helpers/offer_pdf_static_content.py."""
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    content = offer_pdf_static_content_from_env()
    assert content.acceptance_statement != TEST_ACCEPTANCE_STATEMENT
    assert "PLATZHALTER" not in content.company_legal_name
    assert "TEST" not in content.company_legal_name.upper()


def test_optional_vars_populate_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    monkeypatch.setenv("OFFICE_PDF_COMPANY_PHONE", "+49 40 1234567")
    monkeypatch.setenv("OFFICE_PDF_FOOTER_NOTE", "Vielen Dank für Ihr Vertrauen.")
    content = offer_pdf_static_content_from_env()
    assert content.company_phone == "+49 40 1234567"
    assert content.footer_note == "Vielen Dank für Ihr Vertrauen."


# --- OFFICE_PDF_LOGO_PATH: fail closed, never a raw traceback (issue #41) ---


def test_logo_path_pointing_at_missing_file_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    missing = tmp_path / "does-not-exist.png"
    monkeypatch.setenv("OFFICE_PDF_LOGO_PATH", str(missing))
    with pytest.raises(SystemExit) as exc_info:
        offer_pdf_static_content_from_env()
    message = str(exc_info.value)
    assert "OFFICE_PDF_LOGO_PATH" in message
    assert str(missing) in message


def test_logo_path_pointing_at_unreadable_file_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    unreadable = tmp_path / "no-permission.png"
    unreadable.write_bytes(b"\x89PNG\r\n")
    unreadable.chmod(0o000)
    monkeypatch.setenv("OFFICE_PDF_LOGO_PATH", str(unreadable))
    try:
        with pytest.raises(SystemExit) as exc_info:
            offer_pdf_static_content_from_env()
        message = str(exc_info.value)
        assert "OFFICE_PDF_LOGO_PATH" in message
        assert str(unreadable) in message
    finally:
        unreadable.chmod(0o644)


def test_logo_path_pointing_at_a_directory_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    monkeypatch.setenv("OFFICE_PDF_LOGO_PATH", str(tmp_path))
    with pytest.raises(SystemExit) as exc_info:
        offer_pdf_static_content_from_env()
    message = str(exc_info.value)
    assert "OFFICE_PDF_LOGO_PATH" in message
    assert str(tmp_path) in message


def test_logo_path_error_never_carries_a_raw_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The failure must be a clean SystemExit, not an unhandled OSError —
    proven by asserting the raised type directly rather than only its
    message."""
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    monkeypatch.setenv("OFFICE_PDF_LOGO_PATH", str(tmp_path / "missing.png"))
    with pytest.raises(SystemExit):
        offer_pdf_static_content_from_env()
    # If this were still the unhandled-OSError bug, pytest.raises(SystemExit)
    # above would itself fail with an unexpected exception type.


def test_valid_logo_path_still_loads_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_all(monkeypatch)
    _set_required(monkeypatch)
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setenv("OFFICE_PDF_LOGO_PATH", str(logo))
    content = offer_pdf_static_content_from_env()
    assert content.logo_png_bytes == b"\x89PNG\r\n\x1a\n"

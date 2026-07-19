"""Unit tests for canonical Core phone normalization."""

from __future__ import annotations

import pytest

from catering_system.domain.phone_normalization import (
    is_private_or_anonymous_caller,
    normalize_phone,
    normalize_phone_for_contact_point,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0170 123 4567", "+491701234567"),
        ("004917001234567", "+4917001234567"),
        ("+49 170 1234567", "+491701234567"),
        ("(0170) 123-4567", "+491701234567"),
    ],
)
def test_normalize_phone_formats(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


def test_normalize_phone_empty_and_invalid() -> None:
    assert normalize_phone("") == ""
    assert normalize_phone("   ") == ""
    assert normalize_phone("abc") == ""


@pytest.mark.parametrize(
    "raw",
    ["anonymous", "Anonym", "Unbekannt", "-", ""],
)
def test_private_or_anonymous_caller(raw: str) -> None:
    assert is_private_or_anonymous_caller(raw)


def test_normalize_phone_for_contact_point_rejects_private() -> None:
    with pytest.raises(ValueError, match="private or anonymous"):
        normalize_phone_for_contact_point("anonymous")


def test_normalize_phone_for_contact_point_accepts_valid() -> None:
    assert normalize_phone_for_contact_point("01700000099") == "+491700000099"


def test_normalize_phone_non_german_digits_without_plus() -> None:
    assert normalize_phone("1701234567") == "1701234567"


def test_normalize_phone_for_contact_point_rejects_empty() -> None:
    with pytest.raises(ValueError, match="private or anonymous caller"):
        normalize_phone_for_contact_point("   ")

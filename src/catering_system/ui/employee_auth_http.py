"""Shared HTTP helpers for AUTH_RBAC_V1 employee session handling."""

from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any

SESSION_COOKIE_NAME = "sl_employee_session"
CSRF_COOKIE_NAME = "sl_employee_csrf"


def cookie_value(headers: Any, name: str) -> str | None:
    raw = headers.get("Cookie", "")
    if not raw:
        return None
    cookie = SimpleCookie()
    cookie.load(raw)
    morsel = cookie.get(name)
    if morsel is None:
        return None
    value = morsel.value.strip()
    return value or None


def session_token_from_headers(headers: Any) -> str | None:
    return cookie_value(headers, SESSION_COOKIE_NAME)


def csrf_token_from_headers(headers: Any) -> str | None:
    return cookie_value(headers, CSRF_COOKIE_NAME)


def bearer_token_from_headers(headers: Any) -> str | None:
    raw = headers.get("Authorization", "")
    if not raw.startswith("Bearer "):
        return None
    token = raw.removeprefix("Bearer ").strip()
    return token or None


def _cookie_header(
    name: str,
    value: str,
    *,
    secure: bool,
    http_only: bool,
    max_age: int | None = None,
) -> str:
    cookie = SimpleCookie()
    cookie[name] = value
    morsel = cookie[name]
    morsel["path"] = "/"
    morsel["samesite"] = "Lax"
    if http_only:
        morsel["httponly"] = True
    if secure:
        morsel["secure"] = True
    if max_age is not None:
        morsel["max-age"] = str(max_age)
    return morsel.OutputString()


def session_cookie_header(
    token: str,
    *,
    secure: bool,
    max_age: int | None = None,
) -> str:
    return _cookie_header(
        SESSION_COOKIE_NAME,
        token,
        secure=secure,
        http_only=True,
        max_age=max_age,
    )


def csrf_cookie_header(
    token: str,
    *,
    secure: bool,
    max_age: int | None = None,
) -> str:
    return _cookie_header(
        CSRF_COOKIE_NAME,
        token,
        secure=secure,
        http_only=True,
        max_age=max_age,
    )


def clear_cookie_header(name: str, *, secure: bool, http_only: bool) -> str:
    return _cookie_header(
        name,
        "",
        secure=secure,
        http_only=http_only,
        max_age=0,
    )

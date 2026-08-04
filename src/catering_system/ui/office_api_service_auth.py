"""Service bearer authentication for Core Office API privileged routes."""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from typing import Literal

ServiceAuthOutcome = Literal["allowed", "forbidden", "missing", "invalid", "ambiguous"]


@dataclass(frozen=True)
class ServiceAuthResult:
    outcome: ServiceAuthOutcome
    client_id: str | None = None


class IntrospectionServiceTokenConfigError(Exception):
    """Invalid EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON configuration."""


class OfficeApiServiceAuth:
    """Distinguishes the office-panel bearer from introspection-capable clients."""

    def __init__(
        self,
        *,
        office_panel_token: str,
        introspection_clients: dict[str, str],
    ) -> None:
        self._office_panel_token = office_panel_token
        self._introspection_clients = dict(introspection_clients)

    def authenticate_introspection(
        self, authorization: str | None
    ) -> ServiceAuthResult:
        if authorization is None or not authorization.startswith("Bearer "):
            return ServiceAuthResult(outcome="missing")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            return ServiceAuthResult(outcome="missing")
        office_match = hmac.compare_digest(token, self._office_panel_token)
        matched_clients = [
            client_id
            for client_id, expected in self._introspection_clients.items()
            if hmac.compare_digest(token, expected)
        ]
        if office_match and matched_clients:
            return ServiceAuthResult(outcome="ambiguous")
        if office_match:
            return ServiceAuthResult(outcome="forbidden", client_id="office-panel")
        if len(matched_clients) > 1:
            return ServiceAuthResult(outcome="ambiguous")
        if len(matched_clients) == 1:
            return ServiceAuthResult(
                outcome="allowed",
                client_id=matched_clients[0],
            )
        return ServiceAuthResult(outcome="invalid")


def parse_introspection_service_tokens(
    raw: str,
    *,
    office_panel_token: str,
) -> dict[str, str]:
    """Parse introspection client tokens; empty raw keeps the route fail-closed."""
    value = raw.strip()
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise IntrospectionServiceTokenConfigError(
            "EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON must be valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise IntrospectionServiceTokenConfigError(
            "EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON must be a JSON object"
        )
    tokens: dict[str, str] = {}
    seen_values: dict[str, str] = {}
    for key, token_value in parsed.items():
        if not isinstance(key, str) or not key.strip():
            raise IntrospectionServiceTokenConfigError(
                "EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON client id must be a "
                "non-empty string"
            )
        if not isinstance(token_value, str) or not token_value.strip():
            raise IntrospectionServiceTokenConfigError(
                "EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON token must be a "
                "non-empty string"
            )
        client_id = key.strip()
        token = token_value.strip()
        if hmac.compare_digest(token, office_panel_token):
            raise IntrospectionServiceTokenConfigError(
                "EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON must not reuse "
                "OFFICE_API_TOKEN"
            )
        previous_client = seen_values.get(token)
        if previous_client is not None:
            raise IntrospectionServiceTokenConfigError(
                "EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON contains duplicate "
                "service tokens"
            )
        tokens[client_id] = token
        seen_values[token] = client_id
    return tokens


def read_introspection_service_tokens_from_env(
    *,
    office_panel_token: str,
) -> dict[str, str]:
    raw = os.environ.get("EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON", "")
    try:
        return parse_introspection_service_tokens(
            raw,
            office_panel_token=office_panel_token,
        )
    except IntrospectionServiceTokenConfigError as exc:
        raise SystemExit(str(exc)) from exc

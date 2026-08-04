"""Private employee-session introspection route for trusted backends (AUTH-2E1)."""

from __future__ import annotations

import logging
import re
from typing import Literal

from catering_system.domain.employee_introspection import (
    EmployeeIntrospectionResponse,
    employee_introspection_from_session,
)
from catering_system.services.employee_auth_service import EmployeeAuthService
from catering_system.ui.office_api_service_auth import (
    OfficeApiServiceAuth,
    ServiceAuthResult,
)

_log = logging.getLogger(__name__)

EMPLOYEE_INTROSPECT_PATH = "/office/v1/auth/employee/introspect"
EMPLOYEE_SESSION_HEADER = "X-Employee-Session"
_MAX_EMPLOYEE_SESSION_LEN = 256
_SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")

ParseSessionHeader = str | None | Literal["malformed"]


def parse_employee_session_header(raw: str | None) -> ParseSessionHeader:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if (
        len(value) > _MAX_EMPLOYEE_SESSION_LEN
        or _SESSION_TOKEN_RE.fullmatch(value) is None
    ):
        return "malformed"
    return value


def parse_employee_session_header_values(
    values: list[str] | None,
) -> ParseSessionHeader:
    if not values:
        return None
    if len(values) != 1:
        return "malformed"
    return parse_employee_session_header(values[0])


def validate_introspection_request_body(
    *,
    content_length: str | None,
    transfer_encoding: str | None,
) -> bool:
    """Return True when the request body must be rejected with 400."""
    if transfer_encoding is not None:
        encodings = [
            part.strip().lower()
            for part in transfer_encoding.split(",")
            if part.strip()
        ]
        if "chunked" in encodings:
            return True
    if content_length is None or content_length in ("", "0"):
        return False
    try:
        length = int(content_length)
    except ValueError:
        return True
    if length < 0:
        return True
    return length > 0


def perform_employee_introspection(
    *,
    service_auth: OfficeApiServiceAuth,
    authorization: str | None,
    content_length: str | None,
    transfer_encoding: str | None,
    session_header_values: list[str] | None,
    employee_auth: EmployeeAuthService,
) -> tuple[int, EmployeeIntrospectionResponse | None, str | None]:
    """Return HTTP status, response body, or error code for service-auth failures."""
    auth_result = service_auth.authenticate_introspection(authorization)
    status, error_code = _service_auth_status(auth_result)
    if status != 200:
        return status, None, error_code

    if validate_introspection_request_body(
        content_length=content_length,
        transfer_encoding=transfer_encoding,
    ):
        return 400, None, "invalid_request"

    parsed = parse_employee_session_header_values(session_header_values)
    if parsed == "malformed":
        return 400, None, "invalid_request"

    employee = (
        None
        if parsed is None
        else employee_auth.resolve_session_for_introspection(parsed)
    )
    response = employee_introspection_from_session(employee)
    _log.info(
        "employee_introspect client=%s authenticated=%s application_access_allowed=%s account_id=%s",
        auth_result.client_id,
        response.authenticated,
        response.application_access_allowed,
        response.principal.account_id if response.principal is not None else "-",
    )
    return 200, response, None


def _service_auth_status(result: ServiceAuthResult) -> tuple[int, str | None]:
    if result.outcome == "allowed":
        return 200, None
    if result.outcome == "forbidden":
        return 403, "forbidden"
    if result.outcome == "ambiguous":
        return 403, "forbidden"
    return 401, "unauthorized"

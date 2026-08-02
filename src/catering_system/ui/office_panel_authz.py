"""Office Panel business authorization helpers (AUTH-2D1).

Centralizes permission checks for employee sessions while preserving the
migration/basic legacy rollback path. Settings/users routes keep their
separate employee-only actor rules from AUTH-2C.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from catering_system.domain.catalog import ALLERGEN_CODES, AllergenCode
from catering_system.domain.employee_auth import PERMISSION_SET, AuthenticatedEmployee
from catering_system.ui.office_panel import OfficePanel, parse_catalog_price_input

if TYPE_CHECKING:
    from catering_system.ui.office_panel_http import OfficePanelRequestAuth


class BusinessAccessDenied(Exception):
    """Raised when an employee session lacks a required business permission."""


class DynamicCatalogUpdateAuth:
    """Marker: POST /gerichte/{id}/update uses field-level authorization after CSRF."""


DYNAMIC_CATALOG_UPDATE_AUTH = DynamicCatalogUpdateAuth()


class BusinessAuthRequest(Protocol):
    kind: Literal["basic", "employee"]
    legacy_shared_access: bool
    employee: AuthenticatedEmployee | None


def can_access(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_code: str,
) -> bool:
    """Return whether ``permission_code`` is allowed for this request principal."""
    if permission_code not in PERMISSION_SET:
        return False
    if auth is None:
        return False
    if auth.legacy_shared_access:
        return True
    if auth.kind != "employee" or auth.employee is None:
        return False
    if not auth.employee.application_access_allowed:
        return False
    return permission_code in auth.employee.effective_permissions


def can_access_all(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_codes: tuple[str, ...],
) -> bool:
    return all(can_access(auth, code) for code in permission_codes)


def can_access_any(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_codes: tuple[str, ...],
) -> bool:
    return any(can_access(auth, code) for code in permission_codes)


def require_business_permission(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_code: str,
) -> None:
    if not can_access(auth, permission_code):
        raise BusinessAccessDenied()


def require_all_business_permissions(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_codes: tuple[str, ...],
) -> None:
    for permission_code in permission_codes:
        require_business_permission(auth, permission_code)


def require_any_business_permissions(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_codes: tuple[str, ...],
) -> None:
    if not can_access_any(auth, permission_codes):
        raise BusinessAccessDenied()


def require_business_permission_post(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_code: str,
) -> None:
    """POST alias — same employee/Basic semantics as GET (AUTH-2D2)."""
    require_business_permission(auth, permission_code)


def require_all_business_permissions_post(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_codes: tuple[str, ...],
) -> None:
    require_all_business_permissions(auth, permission_codes)


def require_any_business_permissions_post(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_codes: tuple[str, ...],
) -> None:
    require_any_business_permissions(auth, permission_codes)


@dataclass(frozen=True)
class CatalogUpdateValues:
    name: str
    description: str | None
    composition: str | None
    notes: str | None
    allergens: tuple[AllergenCode, ...]
    price_cents: int


def _optional_form_text(raw: str) -> str | None:
    stripped = raw.strip()
    return stripped or None


def _optional_detail_text(value: object | None) -> str | None:
    if value is None:
        return None
    return _optional_form_text(str(value))


def _allergens_from_detail(detail: dict[str, object]) -> tuple[AllergenCode, ...]:
    raw = detail.get("allergens")
    if not isinstance(raw, list):
        return ()
    codes: list[AllergenCode] = []
    for item in raw:
        code = str(item).upper()
        if code in ALLERGEN_CODES:
            codes.append(code)  # type: ignore[arg-type]
    return tuple(code for code in ALLERGEN_CODES if code in codes)


def normalize_catalog_update_form(form: dict[str, str]) -> CatalogUpdateValues:
    return CatalogUpdateValues(
        name=form.get("name", "").strip(),
        description=_optional_form_text(form.get("description", "")),
        composition=_optional_form_text(form.get("composition", "")),
        notes=_optional_form_text(form.get("notes", "")),
        allergens=OfficePanel._catalog_allergens_from_form(form),
        price_cents=parse_catalog_price_input(form.get("price_net", "")),
    )


def normalize_catalog_update_detail(detail: dict[str, object]) -> CatalogUpdateValues:
    return CatalogUpdateValues(
        name=str(detail.get("name", "")).strip(),
        description=_optional_detail_text(detail.get("description")),
        composition=_optional_detail_text(detail.get("composition")),
        notes=_optional_detail_text(detail.get("notes")),
        allergens=_allergens_from_detail(detail),
        price_cents=int(str(detail.get("current_unit_net_cents", 0))),
    )


def catalog_update_change_flags(
    current: CatalogUpdateValues,
    submitted: CatalogUpdateValues,
) -> tuple[bool, bool]:
    metadata_changed = (
        submitted.name != current.name
        or submitted.description != current.description
        or submitted.composition != current.composition
        or submitted.notes != current.notes
        or submitted.allergens != current.allergens
    )
    price_changed = submitted.price_cents != current.price_cents
    return metadata_changed, price_changed


def authorize_catalog_update(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    *,
    current: dict[str, object],
    form: dict[str, str],
) -> None:
    if auth is not None and auth.legacy_shared_access:
        return
    baseline = normalize_catalog_update_detail(current)
    submitted = normalize_catalog_update_form(form)
    metadata_changed, price_changed = catalog_update_change_flags(baseline, submitted)
    if metadata_changed and price_changed:
        require_all_business_permissions(auth, ("catalog.edit", "prices.edit"))
    elif metadata_changed:
        require_business_permission(auth, "catalog.edit")
    elif price_changed:
        require_business_permission(auth, "prices.edit")
    else:
        require_any_business_permissions(auth, ("catalog.edit", "prices.edit"))

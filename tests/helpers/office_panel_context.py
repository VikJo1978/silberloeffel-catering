"""Shared Office Panel page contexts for non-auth unit tests."""

from __future__ import annotations

from catering_system.ui.office_panel_views import OfficePageContext


def legacy_office_context(**kwargs: object) -> OfficePageContext:
    """Preserve pre-AUTH-2D1 presentation expectations in focused UI tests."""
    return OfficePageContext(legacy_shared_access=True, **kwargs)  # type: ignore[arg-type]

"""Office Panel entrypoint with the local KI Telefonassistent inbox enabled."""

from __future__ import annotations

from catering_system.ui import office_panel
from catering_system.ui.office_panel_ai_runtime import (
    create_ai_enabled_office_panel_server,
)


def main() -> None:
    # Reuse the established CLI/bootstrap verbatim. Only server construction is
    # swapped so the large Office Panel runtime keeps one source of truth.
    office_panel.create_office_panel_server = create_ai_enabled_office_panel_server
    office_panel.main()


if __name__ == "__main__":
    main()

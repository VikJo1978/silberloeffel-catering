from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


path = Path("src/catering_system/ui/kiosk_server.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import date\n",
    "from collections.abc import Mapping\nfrom datetime import date, timedelta\n",
    "datetime import",
)
text = replace_once(
    text,
    "from catering_system.domain.wochenuebersicht import (\n",
    "from catering_system.domain.offer_charges import ReturnLogisticsDefinition\n"
    "from catering_system.domain.wochenuebersicht import (\n",
    "return logistics import",
)
text = replace_once(
    text,
    "from catering_system.repositories.order_repository import OrderRepository\n",
    "from catering_system.repositories.order_commercial_snapshot_repository import (\n"
    "    OrderCommercialSnapshotRepository,\n"
    ")\n"
    "from catering_system.repositories.order_repository import OrderRepository\n",
    "commercial snapshot repository import",
)
start = text.index("def render_order_feed_json(")
end = text.index("\n\ndef _requested_week", start)
replacement = '''def next_return_working_day(event_date: date) -> date:
    """Return the next Monday-Friday date after ``event_date``.

    Issue #171 deliberately does not invent public-holiday knowledge: Core has
    no business-calendar source yet. Weekend skipping is deterministic and the
    only working-day rule this projection may truthfully derive today.
    """
    candidate = event_date + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _return_logistics_projection(
    event_date: date, definition: ReturnLogisticsDefinition | None
) -> dict[str, str | None] | None:
    if definition is None:
        return None
    return_date = (
        event_date
        if definition.mode == "SAME_DAY"
        else next_return_working_day(event_date)
    )
    return {
        "mode": definition.mode,
        "return_date": return_date.isoformat(),
        "pickup_window_text": definition.pickup_window_text,
    }


def render_order_feed_json(
    feed_date: date,
    entries: tuple[WochenuebersichtEntry, ...],
    return_logistics_by_order_id: Mapping[
        str, ReturnLogisticsDefinition | None
    ] | None = None,
) -> bytes:
    """Pure renderer: per-date entries → courier order feed document (v2).

    Selection still comes exclusively from ``WochenuebersichtService``. The
    additive ``return_logistics`` planning fact is joined from the immutable
    accepted OrderCommercialSnapshot. Prices and courier execution state stay
    out of this payload.
    """
    return_logistics = return_logistics_by_order_id or {}
    document = {
        "date": feed_date.isoformat(),
        "orders": [
            {
                "order_id": e.order_id,
                "event_date": e.event_date.isoformat(),
                "time_window_text": e.time_window_text,
                "location_text": e.location_text,
                "guest_count_estimate": e.guest_count_estimate,
                "return_logistics": _return_logistics_projection(
                    e.event_date, return_logistics.get(e.order_id)
                ),
            }
            for e in entries
        ],
    }
    return json.dumps(document, ensure_ascii=False).encode("utf-8")
'''
text = text[:start] + replacement + text[end:]
text = replace_once(
    text,
    '''def make_kiosk_handler(
    order_repository: OrderRepository,
    pickup_signal: PickupSignalRefresher | None = None,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
) -> type[BaseHTTPRequestHandler]:
''',
    '''def make_kiosk_handler(
    order_repository: OrderRepository,
    pickup_signal: PickupSignalRefresher | None = None,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository | None = None,
) -> type[BaseHTTPRequestHandler]:
''',
    "handler signature",
)
text = replace_once(
    text,
    '''                payload = render_order_feed_json(
                    feed_date, service.get_day_overview(feed_date)
                )
''',
    '''                entries = service.get_day_overview(feed_date)
                return_logistics_by_order_id: dict[
                    str, ReturnLogisticsDefinition | None
                ] = {}
                if commercial_snapshot_repository is not None:
                    for entry in entries:
                        snapshot = commercial_snapshot_repository.get_by_order_id(
                            entry.order_id
                        )
                        return_logistics_by_order_id[entry.order_id] = (
                            snapshot.return_logistics if snapshot is not None else None
                        )
                payload = render_order_feed_json(
                    feed_date, entries, return_logistics_by_order_id
                )
''',
    "handler feed payload",
)
text = replace_once(
    text,
    '''def create_kiosk_server(
    order_repository: OrderRepository,
    host: str = "0.0.0.0",
    port: int = 8080,
    pickup_signal: PickupSignalRefresher | None = None,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
) -> HTTPServer:
''',
    '''def create_kiosk_server(
    order_repository: OrderRepository,
    host: str = "0.0.0.0",
    port: int = 8080,
    pickup_signal: PickupSignalRefresher | None = None,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository | None = None,
) -> HTTPServer:
''',
    "server signature",
)
text = replace_once(
    text,
    '''        make_kiosk_handler(
            order_repository, pickup_signal, pause_repository=pause_repository
        ),
''',
    '''        make_kiosk_handler(
            order_repository,
            pickup_signal,
            pause_repository=pause_repository,
            commercial_snapshot_repository=commercial_snapshot_repository,
        ),
''',
    "handler wiring",
)
text = replace_once(
    text,
    '''    from catering_system.repositories.sqlite_order_repository import (
        SQLiteOrderRepository,
    )

    order_repo = SQLiteOrderRepository(args.db)
    pause_repo = SQLiteOrderOperationalPauseRepository(args.db)
''',
    '''    from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
        SQLiteOrderCommercialSnapshotRepository,
    )
    from catering_system.repositories.sqlite_order_repository import (
        SQLiteOrderRepository,
    )

    order_repo = SQLiteOrderRepository(args.db)
    pause_repo = SQLiteOrderOperationalPauseRepository(args.db)
    commercial_snapshot_repo = SQLiteOrderCommercialSnapshotRepository(args.db)
''',
    "sqlite repository wiring",
)
text = replace_once(
    text,
    '''        pickup_signal,
        pause_repository=pause_repo,
    )
''',
    '''        pickup_signal,
        pause_repository=pause_repo,
        commercial_snapshot_repository=commercial_snapshot_repo,
    )
''',
    "server production wiring",
)
path.write_text(text, encoding="utf-8")

# Existing v1 handler test evolves explicitly to the v2 additive field.
path = Path("tests/unit/test_kiosk_server.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''        "guest_count_estimate",
    }
''',
    '''        "guest_count_estimate",
        "return_logistics",
    }
''',
    "kiosk exact field set",
)
text = replace_once(
    text,
    '''    assert order["guest_count_estimate"] == 25
''',
    '''    assert order["guest_count_estimate"] == 25
    assert order["return_logistics"] is None
''',
    "legacy return assertion",
)
path.write_text(text, encoding="utf-8")

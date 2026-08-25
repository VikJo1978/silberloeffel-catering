from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one match in {path}, got {text.count(old)}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/catering_system/ui/kiosk_server.py",
    '''    return {
        "mode": definition.mode,
        "return_date": return_date.isoformat(),
        "pickup_window_text": definition.pickup_window_text,
        "pickup_window_start_local": _format_local_time(
            definition.pickup_window_start_local
        ),
        "pickup_window_end_local": _format_local_time(
            definition.pickup_window_end_local
        ),
    }
''',
    '''    projection: dict[str, str | None] = {
        "mode": definition.mode,
        "return_date": return_date.isoformat(),
        "pickup_window_text": definition.pickup_window_text,
    }
    if definition.pickup_window_start_local is not None:
        projection["pickup_window_start_local"] = _format_local_time(
            definition.pickup_window_start_local
        )
        projection["pickup_window_end_local"] = _format_local_time(
            definition.pickup_window_end_local
        )
    return projection
''',
)

replace_once(
    "src/catering_system/ui/kiosk_server.py",
    '''def render_order_feed_json(
    feed_date: date,
    entries: tuple[WochenuebersichtEntry, ...],
    return_logistics_by_order_id: Mapping[str, ReturnLogisticsDefinition | None]
    | None = None,
) -> bytes:
''',
    '''def _order_feed_entry_projection(
    entry: WochenuebersichtEntry,
    return_logistics: ReturnLogisticsDefinition | None,
) -> dict[str, object]:
    projection: dict[str, object] = {
        "order_id": entry.order_id,
        "event_date": entry.event_date.isoformat(),
        "time_window_text": entry.time_window_text,
        "location_text": entry.location_text,
        "guest_count_estimate": entry.guest_count_estimate,
        "return_logistics": _return_logistics_projection(
            entry.event_date, return_logistics
        ),
    }
    delivery_window = _delivery_window_projection(entry)
    if delivery_window is not None:
        projection["delivery_window"] = delivery_window
    return projection


def render_order_feed_json(
    feed_date: date,
    entries: tuple[WochenuebersichtEntry, ...],
    return_logistics_by_order_id: Mapping[str, ReturnLogisticsDefinition | None]
    | None = None,
) -> bytes:
''',
)

replace_once(
    "src/catering_system/ui/kiosk_server.py",
    '''        "orders": [
            {
                "order_id": e.order_id,
                "event_date": e.event_date.isoformat(),
                "time_window_text": e.time_window_text,
                "location_text": e.location_text,
                "guest_count_estimate": e.guest_count_estimate,
                "delivery_window": _delivery_window_projection(e),
                "return_logistics": _return_logistics_projection(
                    e.event_date, return_logistics.get(e.order_id)
                ),
            }
            for e in entries
        ],
''',
    '''        "orders": [
            _order_feed_entry_projection(e, return_logistics.get(e.order_id))
            for e in entries
        ],
''',
)

replace_once(
    "tests/unit/test_issue175_kiosk_timing_projection.py",
    '''    assert order["time_window_text"] == "18:00-19:00"
    assert order["delivery_window"] is None
''',
    '''    assert order["time_window_text"] == "18:00-19:00"
    assert "delivery_window" not in order
''',
)

replace_once(
    "tests/unit/test_issue175_kiosk_timing_projection.py",
    '''    assert order["return_logistics"] == {
        "mode": "SAME_DAY",
        "return_date": "2026-10-01",
        "pickup_window_text": "22:00-23:00",
        "pickup_window_start_local": None,
        "pickup_window_end_local": None,
    }
''',
    '''    assert order["return_logistics"] == {
        "mode": "SAME_DAY",
        "return_date": "2026-10-01",
        "pickup_window_text": "22:00-23:00",
    }
''',
)

replace_once(
    "docs/proposals/KIOSK_ORDER_FEED_LOGISTICS_TIMING_V3.md",
    '''Each order gains an additive `delivery_window` field:
''',
    '''An order with a complete canonical outbound window gains an additive
`delivery_window` field:
''',
)

replace_once(
    "docs/proposals/KIOSK_ORDER_FEED_LOGISTICS_TIMING_V3.md",
    '''If the effective `OrderVersion` has no complete canonical delivery date/start/end,
`delivery_window` is `null`. `time_window_text` remains unchanged and is never
parsed or used to manufacture this object.
''',
    '''If the effective `OrderVersion` has no complete canonical delivery date/start/end,
the `delivery_window` key is absent. `time_window_text` remains unchanged and is
never parsed or used to manufacture this object. This preserves the exact V2
shape for legacy/non-canonical rows.
''',
)

replace_once(
    "docs/proposals/KIOSK_ORDER_FEED_LOGISTICS_TIMING_V3.md",
    '''Both values are `null` when no accepted canonical SAME_DAY pickup window exists.
`pickup_window_text` remains display text and is never parsed.
''',
    '''The two canonical pickup keys are present only when an accepted canonical
SAME_DAY pickup window exists. Otherwise both keys are absent, preserving the
existing V2 `return_logistics` shape. `pickup_window_text` remains display text
and is never parsed.
''',
)

replace_once(
    "docs/proposals/KIOSK_ORDER_FEED_LOGISTICS_TIMING_V3.md",
    '''accepted rows remain readable: canonical timing is explicitly absent/null rather
than inferred from `time_window_text` or `pickup_window_text`.
''',
    '''accepted rows remain readable: canonical timing keys are simply absent rather
than inferred from `time_window_text` or `pickup_window_text`.
''',
)

"""Deterministic JSON text from B16 debug dict — Slice B17 (read-only derived; not persisted)."""

from __future__ import annotations

import json


def order_progression_debug_dict_to_json(d: dict[str, object]) -> str:
    """Serializes a B16 debug dict to a stable JSON string (sorted keys, compact separators)."""
    return json.dumps(
        d,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

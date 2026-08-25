"""Explainable soft recommendation hints derived from factual customer history.

Hints are projections, not customer facts. They must never be persisted as explicit
preferences or treated as hard constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

CustomerRecommendationHintKind = Literal[
    "frequently_ordered",
    "recently_ordered",
]


@dataclass(frozen=True)
class CustomerRecommendationHint:
    kind: CustomerRecommendationHintKind
    catalog_item_id: str
    display_name: str
    order_count: int
    last_ordered_on: date
    source_order_ids: tuple[str, ...]
    explanation: str
    score_delta: int

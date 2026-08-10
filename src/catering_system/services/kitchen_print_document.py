"""Immutable kitchen print artifact DTO and builders (Phase 3B)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from catering_system.domain.kitchen_print_job import KitchenPrintJob
from catering_system.services.kitchen_print_pdf_renderer import render_kitchen_print_pdf
from catering_system.services.order_print_projection_service import OrderPrintProjection


@dataclass(frozen=True)
class KitchenPrintDocument:
    """Application DTO — frozen print artifact at claim time (ADR §2.1)."""

    document_ref: str
    print_job_id: str
    projection_hash: str
    content_type: str
    body: bytes
    created_at: datetime


def canonical_kitchen_projection_json(projection: OrderPrintProjection) -> str:
    event = projection.event
    commercial = projection.commercial
    flags = projection.flags
    payload = {
        "event": {
            "order_id": event.order_id,
            "order_version_id": event.order_version_id,
            "version_number": event.version_number,
            "event_date": event.event_date.isoformat(),
            "time_window_text": event.time_window_text,
            "location_text": event.location_text,
            "guest_count_estimate": event.guest_count_estimate,
            "planning_mode": event.planning_mode,
        },
        "commercial": {
            "source": commercial.source,
            "variant_label": commercial.variant_label,
            "positions": [
                {
                    "position_id": line.position_id,
                    "name": line.name,
                    "quantity_display": line.quantity_display,
                }
                for line in commercial.positions
            ],
        },
        "flags": {
            "intent": flags.intent,
            "watermark": flags.watermark,
            "is_preview": flags.is_preview,
            "is_stale": flags.is_stale,
        },
    }
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def build_kitchen_print_document(
    projection: OrderPrintProjection,
    job: KitchenPrintJob,
    *,
    now: datetime,
) -> KitchenPrintDocument:
    projection_hash = hashlib.sha256(
        canonical_kitchen_projection_json(projection).encode("utf-8")
    ).hexdigest()
    body = render_kitchen_print_pdf(projection, created_at=now)
    document_ref = f"sha256:{hashlib.sha256(body).hexdigest()}"
    return KitchenPrintDocument(
        document_ref=document_ref,
        print_job_id=job.print_job_id,
        projection_hash=projection_hash,
        content_type="application/pdf",
        body=body,
        created_at=now,
    )

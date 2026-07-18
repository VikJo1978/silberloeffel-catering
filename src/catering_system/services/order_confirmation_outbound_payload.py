"""Build frozen email payload from an immutable confirmation document snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentSnapshot,
)
from catering_system.domain.order_confirmation_outbound import TRANSPORT_KIND
from catering_system.services.order_confirmation_document_preview import (
    build_preview,
    render_preview_html,
)
from catering_system.services.order_confirmation_document_service import (
    payment_method_label,
)
from catering_system.services.order_confirmation_outbound_payload_hash import (
    compute_payload_hash,
    payload_hash_body,
)


@dataclass(frozen=True)
class OutboundEmailPayload:
    recipient_name: str | None
    recipient_email: str
    subject: str
    text_body: str
    html_body: str
    payload_hash: str


def _eur(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


def build_outbound_payload(
    snapshot: OrderConfirmationDocumentSnapshot,
) -> OutboundEmailPayload:
    if snapshot.recipient_email is None:
        raise ValueError("recipient email is required for outbound payload")
    preview = build_preview(snapshot)
    html_body = render_preview_html(preview)
    greeting_name = snapshot.recipient_name or snapshot.recipient_company or "Gast"
    subject = f"Auftragsbestätigung {snapshot.document_reference}"
    guest_text = (
        f"ca. {snapshot.guest_count_estimate} Gäste"
        if snapshot.guest_count_estimate is not None
        else "Gästezahl nach Vereinbarung"
    )
    text_body = "\n".join(
        [
            f"Guten Tag {greeting_name},",
            "",
            "anbei erhalten Sie unsere Auftragsbestätigung.",
            "",
            f"Referenz: {snapshot.document_reference}",
            f"Datum: {snapshot.event_date.strftime('%d.%m.%Y')}",
            f"Zeitfenster: {snapshot.time_window_text}",
            f"Ort: {snapshot.location_text}",
            f"Gäste: {guest_text}",
            f"Summe brutto: {_eur(snapshot.gross_total_cents)}",
            f"Zahlungsart: {payment_method_label(snapshot.payment_method)}",
            "",
            "Mit freundlichen Grüßen",
            "Silberlöffel Event Catering Service",
        ]
    )
    body = payload_hash_body(
        schema_version=1,
        transport_kind=TRANSPORT_KIND,
        document_snapshot_id=snapshot.document_snapshot_id,
        document_hash=snapshot.document_hash,
        recipient_email=snapshot.recipient_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
    return OutboundEmailPayload(
        recipient_name=snapshot.recipient_name,
        recipient_email=snapshot.recipient_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        payload_hash=compute_payload_hash(body),
    )

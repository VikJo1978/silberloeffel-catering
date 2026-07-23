"""Customer-facing Auftragsbestätigung preview projection and HTML renderer.

Persisted preview reads only from OrderConfirmationDocumentSnapshot.
No Inquiry repository and no CustomerDocumentProjection live rebuild.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from catering_system.domain.inquiry_customer_snapshot import customer_address_to_mapping
from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentSnapshot,
)
from catering_system.services.order_confirmation_document_service import (
    payment_method_label,
)

_SENDER_NAME = "Silberlöffel Event Catering Service"
_SENDER_LOCATION = "Hamburg"
_FOOTER_NOTE = "Bei Rückfragen wenden Sie sich bitte an unser Büro."


@dataclass(frozen=True)
class OrderConfirmationDocumentPreview:
    sender_name: str
    sender_location: str
    title: str
    document_reference: str
    created_at_text: str
    recipient_name: str | None
    recipient_company: str | None
    recipient_email_masked: str | None
    recipient_phone: str | None
    recipient_status: str
    event_date_text: str
    time_window_text: str
    location_text: str
    guest_count_text: str
    positions: tuple[dict[str, object], ...]
    vat_buckets: tuple[dict[str, object], ...]
    net_total_eur: str
    vat_total_eur: str
    gross_total_eur: str
    payment_method_label: str
    payment_customer_visible_text: str
    footer_note: str
    schema_version: int
    address_facts_stored: bool
    invoice_address: dict[str, str | None] | None
    delivery_address: dict[str, str | None] | None
    delivery_address_differs: bool | None
    document_warnings: tuple[str, ...]
    watermark: str | None = None


def build_preview(
    snapshot: OrderConfirmationDocumentSnapshot,
    *,
    watermark: str | None = None,
) -> OrderConfirmationDocumentPreview:
    from catering_system.domain.order_confirmation_document import mask_recipient_email

    guests = (
        f"ca. {snapshot.guest_count_estimate} Gäste"
        if snapshot.guest_count_estimate is not None
        else "–"
    )
    stored = snapshot.address_facts_stored
    return OrderConfirmationDocumentPreview(
        sender_name=_SENDER_NAME,
        sender_location=_SENDER_LOCATION,
        title="Auftragsbestätigung",
        document_reference=snapshot.document_reference,
        created_at_text=snapshot.created_at.strftime("%d.%m.%Y"),
        recipient_name=snapshot.recipient_name,
        recipient_company=snapshot.recipient_company,
        recipient_email_masked=mask_recipient_email(snapshot.recipient_email),
        recipient_phone=snapshot.recipient_phone,
        recipient_status=snapshot.recipient_status,
        event_date_text=snapshot.event_date.strftime("%d.%m.%Y"),
        time_window_text=snapshot.time_window_text,
        location_text=snapshot.location_text,
        guest_count_text=guests,
        positions=tuple(_position_shape(position) for position in snapshot.positions),
        vat_buckets=tuple(
            {
                "rate_percent": bucket.rate_percent,
                "base_net_eur": _eur(bucket.base_net_cents),
                "vat_eur": _eur(bucket.vat_cents),
            }
            for bucket in snapshot.vat_buckets
        ),
        net_total_eur=_eur(snapshot.net_total_cents),
        vat_total_eur=_eur(snapshot.vat_total_cents),
        gross_total_eur=_eur(snapshot.gross_total_cents),
        payment_method_label=payment_method_label(snapshot.payment_method),
        payment_customer_visible_text=snapshot.payment_customer_visible_text,
        footer_note=_FOOTER_NOTE,
        schema_version=snapshot.schema_version,
        address_facts_stored=stored,
        invoice_address=(
            customer_address_to_mapping(snapshot.invoice_address) if stored else None
        ),
        delivery_address=(
            customer_address_to_mapping(snapshot.delivery_address) if stored else None
        ),
        delivery_address_differs=(
            snapshot.delivery_address_differs if stored else None
        ),
        document_warnings=snapshot.document_warnings,
        watermark=watermark,
    )


def preview_to_json(preview: OrderConfirmationDocumentPreview) -> dict[str, object]:
    return {
        "sender_name": preview.sender_name,
        "sender_location": preview.sender_location,
        "title": preview.title,
        "document_reference": preview.document_reference,
        "created_at_text": preview.created_at_text,
        "recipient_name": preview.recipient_name,
        "recipient_company": preview.recipient_company,
        "recipient_email_masked": preview.recipient_email_masked,
        "recipient_phone": preview.recipient_phone,
        "recipient_status": preview.recipient_status,
        "event_date_text": preview.event_date_text,
        "time_window_text": preview.time_window_text,
        "location_text": preview.location_text,
        "guest_count_text": preview.guest_count_text,
        "positions": list(preview.positions),
        "vat_buckets": list(preview.vat_buckets),
        "net_total_eur": preview.net_total_eur,
        "vat_total_eur": preview.vat_total_eur,
        "gross_total_eur": preview.gross_total_eur,
        "payment_method_label": preview.payment_method_label,
        "payment_customer_visible_text": preview.payment_customer_visible_text,
        "footer_note": preview.footer_note,
        "schema_version": preview.schema_version,
        "address_facts_stored": preview.address_facts_stored,
        "invoice_address": preview.invoice_address,
        "delivery_address": preview.delivery_address,
        "delivery_address_differs": preview.delivery_address_differs,
        "document_warnings": list(preview.document_warnings),
        "watermark": preview.watermark,
    }


def render_preview_html(preview: OrderConfirmationDocumentPreview) -> str:
    watermark_html = (
        f'<p class="watermark">{_e(preview.watermark)}</p>'
        if preview.watermark is not None
        else ""
    )
    recipient_lines = []
    if preview.recipient_company:
        recipient_lines.append(f"<p>{_e(preview.recipient_company)}</p>")
    if preview.recipient_name:
        recipient_lines.append(f"<p>{_e(preview.recipient_name)}</p>")
    if preview.recipient_email_masked:
        recipient_lines.append(f"<p>{_e(preview.recipient_email_masked)}</p>")
    elif preview.recipient_status == "missing":
        recipient_lines.append('<p class="missing">Empfänger-E-Mail fehlt</p>')
    if preview.recipient_phone:
        recipient_lines.append(f"<p>{_e(preview.recipient_phone)}</p>")
    address_section = _address_section_html(preview)
    warnings_html = ""
    if preview.document_warnings:
        items = "".join(f"<li>{_e(code)}</li>" for code in preview.document_warnings)
        warnings_html = (
            f'<section class="section"><h2>Hinweise</h2><ul>{items}</ul></section>'
        )
    position_rows = []
    for position in preview.positions:
        details = []
        if position.get("description"):
            details.append(str(position["description"]))
        if position.get("composition"):
            details.append(str(position["composition"]))
        detail_html = (
            "".join(f"<p class='detail'>{_e(line)}</p>" for line in details)
            if details
            else ""
        )
        qty = position.get("quantity")
        qty_html = f"<p class='qty'>Menge: {_e(qty)}</p>" if qty else ""
        position_rows.append(
            "<tr>"
            f"<td><strong>{_e(position['name'])}</strong>{detail_html}{qty_html}</td>"
            f"<td class='money'>{_e(position['net_total_eur'])}</td>"
            f"<td class='money'>{_e(position['vat_eur'])}</td>"
            f"<td class='money'>{_e(position['gross_eur'])}</td>"
            "</tr>"
        )
    bucket_rows = "".join(
        "<tr>"
        f"<td>MwSt. {_e(bucket['rate_percent'])} %</td>"
        f"<td class='money'>{_e(bucket['base_net_eur'])}</td>"
        f"<td class='money'>{_e(bucket['vat_eur'])}</td>"
        "</tr>"
        for bucket in preview.vat_buckets
    )
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Auftragsbestätigung</title>
<style>
body{{font-family:Georgia,serif;margin:2rem auto;max-width:48rem;line-height:1.5;color:#111}}
header{{border-bottom:2px solid #111;padding-bottom:1rem;margin-bottom:1.5rem}}
.brand{{font-size:1.1rem;letter-spacing:0.08em;text-transform:uppercase}}
.title{{font-size:1.8rem;margin:1rem 0 0.25rem}}
.meta,.section{{margin:1.25rem 0}}
table{{width:100%;border-collapse:collapse;margin-top:0.75rem}}
th,td{{border-bottom:1px solid #ddd;padding:0.5rem 0.25rem;vertical-align:top}}
th{{text-align:left;font-size:0.85rem;text-transform:uppercase;letter-spacing:0.04em}}
.money{{text-align:right;white-space:nowrap}}
.detail,.qty{{margin:0.15rem 0 0;font-size:0.95rem;color:#444}}
.missing{{color:#a00;font-weight:bold}}
.watermark{{color:#666;font-size:1.4rem;border:3px dashed #666;padding:0.5rem;text-align:center;margin-bottom:1rem}}
footer{{margin-top:2rem;padding-top:1rem;border-top:1px solid #ddd;font-size:0.9rem;color:#555}}
</style></head><body>
{watermark_html}
<header>
<p class="brand">{_e(preview.sender_name)} · {_e(preview.sender_location)}</p>
<h1 class="title">{_e(preview.title)}</h1>
<p>Referenz: {_e(preview.document_reference)} · Erstellt am {_e(preview.created_at_text)}</p>
</header>
<section class="section"><h2>Kunde</h2>{"".join(recipient_lines) or "<p>–</p>"}</section>
{address_section}
{warnings_html}
<section class="section"><h2>Veranstaltung</h2>
<p>Datum: {_e(preview.event_date_text)}</p>
<p>Zeit: {_e(preview.time_window_text)}</p>
<p>Ort: {_e(preview.location_text)}</p>
<p>Gäste: {_e(preview.guest_count_text)}</p>
</section>
<section class="section"><h2>Leistungen</h2>
<table><thead><tr><th>Position</th><th class="money">Netto</th><th class="money">MwSt.</th><th class="money">Brutto</th></tr></thead>
<tbody>{"".join(position_rows)}</tbody></table></section>
<section class="section"><h2>MwSt.-Übersicht</h2>
<table><thead><tr><th>Satz</th><th class="money">Netto</th><th class="money">MwSt.</th></tr></thead>
<tbody>{bucket_rows}</tbody></table>
<p><strong>Summe netto:</strong> {_e(preview.net_total_eur)}</p>
<p><strong>Summe MwSt.:</strong> {_e(preview.vat_total_eur)}</p>
<p><strong>Summe brutto:</strong> {_e(preview.gross_total_eur)}</p>
</section>
<section class="section"><h2>Zahlung</h2>
<p>{_e(preview.payment_method_label)}</p>
<p>{_e(preview.payment_customer_visible_text)}</p>
</section>
<footer><p>{_e(preview.footer_note)}</p></footer>
</body></html>"""


def _address_section_html(preview: OrderConfirmationDocumentPreview) -> str:
    if not preview.address_facts_stored:
        return (
            '<section class="section"><h2>Adressen</h2>'
            "<p>Adressdaten sind in diesem Dokumentstand nicht gespeichert.</p>"
            "</section>"
        )
    invoice_html = (
        f"<p><strong>Rechnungsadresse</strong><br>"
        f"{_format_address_html(preview.invoice_address)}</p>"
    )
    # UNKNOWN / unset delivery: do not map differs=false to proven equality.
    if preview.delivery_address is None:
        return (
            '<section class="section"><h2>Adressen</h2>'
            f"{invoice_html}"
            "<p><strong>Lieferadresse</strong><br>Lieferadresse nicht festgelegt</p>"
            "</section>"
        )
    differs_text = "ja" if preview.delivery_address_differs is True else "nein"
    return (
        '<section class="section"><h2>Adressen</h2>'
        f"{invoice_html}"
        f"<p><strong>Lieferadresse</strong><br>"
        f"{_format_address_html(preview.delivery_address)}</p>"
        f"<p>Lieferadresse weicht ab: {_e(differs_text)}</p>"
        "</section>"
    )


def _format_address_html(address: dict[str, str | None] | None) -> str:
    if address is None:
        return "–"
    lines = [
        address.get("street"),
        " ".join(
            part for part in (address.get("postal_code"), address.get("city")) if part
        ).strip()
        or None,
        address.get("country"),
    ]
    rendered = "<br>".join(_e(line) for line in lines if line)
    return rendered or "–"


def _position_shape(position: object) -> dict[str, object]:
    from catering_system.domain.order_confirmation_document import (
        OrderConfirmationDocumentPosition,
    )

    assert isinstance(position, OrderConfirmationDocumentPosition)
    return {
        "position_id": position.position_id,
        "kind": position.kind,
        "name": position.name,
        "description": position.description,
        "composition": position.composition,
        "quantity": position.quantity,
        "unit_label": position.unit_label,
        "net_total_eur": _eur(position.net_total_cents),
        "vat_eur": _eur(position.vat_cents),
        "gross_eur": _eur(position.gross_cents),
        "related_position_id": position.related_position_id,
    }


def _eur(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


def _e(value: object) -> str:
    return html.escape(str(value))

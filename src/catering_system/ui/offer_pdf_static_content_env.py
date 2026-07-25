"""Shared OFFER_PDF_* environment contract for OfferPdfStaticContent.

Used by both the Core Office API and the Office Panel's direct-mode startup
so the two processes agree on exactly the same required/optional variables
and the same fail-closed behavior: no approved production company/legal
text is invented, and no test placeholder is allowed to silently reach
production composition (OFFER_PDF_DOWNLOAD_V1 / OFFER_PDF_PANEL_DOWNLOAD_V1).
"""

from __future__ import annotations

import os

from catering_system.domain.offer_pdf import OfferPdfStaticContent


def offer_pdf_static_content_from_env() -> OfferPdfStaticContent:
    legal_name = os.environ.get("OFFICE_PDF_COMPANY_LEGAL_NAME", "").strip()
    address_raw = os.environ.get("OFFICE_PDF_COMPANY_ADDRESS_LINES", "").strip()
    acceptance = os.environ.get("OFFICE_PDF_ACCEPTANCE_STATEMENT", "").strip()
    missing = [
        name
        for name, value in (
            ("OFFICE_PDF_COMPANY_LEGAL_NAME", legal_name),
            ("OFFICE_PDF_COMPANY_ADDRESS_LINES", address_raw),
            ("OFFICE_PDF_ACCEPTANCE_STATEMENT", acceptance),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing required offer-PDF static content environment "
            "variable(s): " + ", ".join(missing) + " — refusing to start "
            "with invented or placeholder company/legal text."
        )
    address_lines = tuple(
        line.strip() for line in address_raw.split("|") if line.strip()
    )
    logo_path = os.environ.get("OFFICE_PDF_LOGO_PATH", "").strip()
    logo_bytes = None
    if logo_path:
        with open(logo_path, "rb") as logo_file:
            logo_bytes = logo_file.read()
    return OfferPdfStaticContent(
        company_legal_name=legal_name,
        company_address_lines=address_lines,
        acceptance_statement=acceptance,
        company_phone=os.environ.get("OFFICE_PDF_COMPANY_PHONE", "").strip() or None,
        company_email=os.environ.get("OFFICE_PDF_COMPANY_EMAIL", "").strip() or None,
        company_web=os.environ.get("OFFICE_PDF_COMPANY_WEB", "").strip() or None,
        company_register_text=(
            os.environ.get("OFFICE_PDF_COMPANY_REGISTER_TEXT", "").strip() or None
        ),
        company_vat_id_text=(
            os.environ.get("OFFICE_PDF_COMPANY_VAT_ID_TEXT", "").strip() or None
        ),
        footer_note=os.environ.get("OFFICE_PDF_FOOTER_NOTE", "").strip() or None,
        bank_details_text=(
            os.environ.get("OFFICE_PDF_BANK_DETAILS_TEXT", "").strip() or None
        ),
        logo_png_bytes=logo_bytes,
    )

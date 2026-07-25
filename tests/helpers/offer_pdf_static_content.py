"""Obviously-fake OfferPdfStaticContent for tests.

OFFER_PDF_DOWNLOAD_V1 makes the static company/legal content an explicit
required dependency of OfficeApi, so every test that builds an API server
must supply one. These values are deliberately marked as placeholders so
they can never be mistaken for approved customer-facing wording.
"""

from __future__ import annotations

from catering_system.domain.offer_pdf import OfferPdfStaticContent

TEST_ACCEPTANCE_STATEMENT = "[TEST PLACEHOLDER — NOT APPROVED CUSTOMER WORDING]"


def fake_offer_pdf_static_content() -> OfferPdfStaticContent:
    return OfferPdfStaticContent(
        company_legal_name="TEST GmbH [PLATZHALTER]",
        company_address_lines=("Teststraße 1", "20095 Hamburg"),
        acceptance_statement=TEST_ACCEPTANCE_STATEMENT,
    )

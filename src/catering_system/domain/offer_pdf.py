"""Static, non-snapshot inputs for the OFFER_PDF_RENDERER_V1 renderer.

``OfferPdfStaticContent`` carries every company/legal fact the renderer
needs that is deliberately absent from ``OfferDocumentSnapshot`` (logo,
legal address, acceptance wording, ...). It is composed and injected by the
caller — the renderer must never read environment variables, files, the
database or the network to obtain any of this.
"""

from __future__ import annotations

from dataclasses import dataclass


class OfferDocumentUnsupportedSchemaError(Exception):
    """The snapshot's schema_version is not one this renderer understands."""


class OfferPdfMissingStaticContentError(Exception):
    """A required OfferPdfStaticContent fact is missing or blank."""


class OfferPdfMalformedSnapshotError(Exception):
    """Defense in depth: the snapshot violates a rendering precondition that
    OfferDocumentSnapshot's own invariants should already have prevented."""


class OfferPdfUnsupportedCharacterError(Exception):
    """A text field contains a glyph the deterministic font setup cannot
    render. Fails closed — never silently dropped, replaced or
    transliterated."""

    def __init__(self, *, field: str, text: str) -> None:
        self.field = field
        self.text = text
        super().__init__(f"unsupported character(s) in {field}")


class OfferPdfRenderError(Exception):
    """Wraps an unexpected failure from the underlying PDF library so no
    internal stack trace or path is exposed through a future API error."""


@dataclass(frozen=True)
class OfferPdfStaticContent:
    """Immutable, explicitly-injected company/legal facts for one render call.

    Required facts have no default so a missing value is a constructor-time
    TypeError before __post_init__ even runs; blank-but-present values are
    caught here.
    """

    company_legal_name: str
    company_address_lines: tuple[str, ...]
    acceptance_statement: str
    company_phone: str | None = None
    company_email: str | None = None
    company_web: str | None = None
    company_register_text: str | None = None
    company_vat_id_text: str | None = None
    footer_note: str | None = None
    logo_png_bytes: bytes | None = None
    bank_details_text: str | None = None

    def __post_init__(self) -> None:
        if not self.company_legal_name.strip():
            raise OfferPdfMissingStaticContentError("company_legal_name is required")
        if not self.company_address_lines or not any(
            line.strip() for line in self.company_address_lines
        ):
            raise OfferPdfMissingStaticContentError("company_address_lines is required")
        if not self.acceptance_statement.strip():
            raise OfferPdfMissingStaticContentError("acceptance_statement is required")


__all__ = [
    "OfferDocumentUnsupportedSchemaError",
    "OfferPdfMalformedSnapshotError",
    "OfferPdfMissingStaticContentError",
    "OfferPdfRenderError",
    "OfferPdfStaticContent",
    "OfferPdfUnsupportedCharacterError",
]

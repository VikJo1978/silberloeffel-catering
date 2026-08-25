# Issue #152 — Customer Order History Projection v1

## Purpose

Expose factual repeat-customer order history without creating a second source of truth.

## Source facts

The projection reads existing Core data only:

- `Inquiry.customer_id` is the explicit customer link.
- `Order` provides order identity, cancellation and the effective/candidate version references.
- `OrderVersion` provides event date and guest count.
- the immutable operational-context snapshot provides fulfillment mode where available.
- the linked accepted `OfferVersion` / `OfferVariant` provides customer-selected commercial positions and totals.

## Rules

- No customer matching by name, e-mail or phone.
- No persisted CRM-history table.
- No inferred preference is written from history.
- A legacy order remains visible when accepted-offer details are unavailable; unknown commercial fields stay `null`/empty.
- Fee/surcharge positions contribute to the commercial total but are not presented as dishes.
- Ordering is newest event first, then order id for deterministic output.
- This projection is read-only and editing explicit gastronomic preferences does not rewrite historical facts.

## Office API

`GET /office/v1/customers/{customer_id}/order-history`

Unknown customers return `404 customer_not_found`.

## Follow-up

History-derived recommendation hints are a separate layer. They must remain soft, explainable signals and must never be persisted as explicit customer preferences automatically.

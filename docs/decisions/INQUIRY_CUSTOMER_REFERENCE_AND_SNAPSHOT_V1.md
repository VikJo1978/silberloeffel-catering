# INQUIRY_CUSTOMER_REFERENCE_AND_SNAPSHOT_V1

Status: **implemented locally** — **not deployed** to production (2026-07-20).

## Semantics

### `customer_id`

- Optional stable reference to `customer_identities.customer_id` (TEXT UUID string).
- Set only via explicit `InquiryService.assign_customer_reference`.
- Never auto-matched, never auto-created.
- Absence is normal for legacy and new inquiries until explicitly assigned.

### `customer_snapshot` (`InquiryCustomerSnapshot`)

Immutable value object with explicit columns:

- `company_name` (from intake label `Firma`)
- `contact_name` (from intake label `Name`)
- `email`
- `phone`

Rules:

- May exist without `customer_id` (captured at intake from labelled contact fields).
- When `customer_id` is assigned, a non-empty snapshot is required.
- Stored snapshot is historical fact on the Inquiry; changes to `CustomerIdentity` do not mutate it.
- Identical re-assignment is idempotent; changing a stored snapshot raises a domain error.

### `customer_linkage`

Unchanged operational opaque dict — not derived from `customer_id`, not a stable FK.

## Intake (four frozen channels)

`website_form`, `email`, `phone`, `manual` continue through `InquiryService.create_inquiry`.

- Default `customer_id = None`.
- Snapshot built only from provided labelled intake contact fields.
- No CustomerIdentity lookup or creation.
- Website idempotency by `submission_id` unchanged.

## Persistence

SQLite component `inquiries` migration **v4** `add_customer_reference` adds nullable columns:

- `customer_id`
- `snapshot_company_name`, `snapshot_contact_name`, `snapshot_email`, `snapshot_phone`

No production migration in this slice.

## Out of scope (V1)

- Automatic matching / fuzzy phone match
- Auerswald / HubSpot linkage
- Order / OrderVersion schema changes
- Office UI workflow for customer confirmation
- Production deploy

## Next slice

`INQUIRY_CUSTOMER_REFERENCE_AND_SNAPSHOT_DEPLOY_V1` — controlled production migration + service restart when approved.

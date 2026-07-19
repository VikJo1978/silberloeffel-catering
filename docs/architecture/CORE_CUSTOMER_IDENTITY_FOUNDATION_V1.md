# CORE_CUSTOMER_IDENTITY_FOUNDATION_V1

## Scope

This slice introduces Core-owned customer identity foundation only. It is **not**
a CRM, not call ingestion, and not confirmed customer linkage.

## Entities

### CustomerIdentity

Minimal persisted identity:

- `customer_id`
- `display_name`
- optional `company_name`
- `status`: `active | inactive | merged`
- `created_at`, `updated_at`

CustomerIdentity is not a CRM aggregate. It does not store HubSpot IDs,
pipeline stages, marketing data, scoring, or Order-specific fields.

### PhoneContactPoint

Minimal phone candidate attached to one CustomerIdentity:

- `phone_contact_point_id`
- `customer_id`
- `normalized_phone`
- optional `display_phone` (display-only, never used for matching)
- `status`: `active | inactive`
- optional `valid_from`, `valid_to`
- `created_at`, `updated_at`

There is **no global uniqueness** on `normalized_phone`. One shared number may
belong to multiple CustomerIdentity records.

## Normalization

Core-owned canonical normalization lives in
`catering_system.domain.phone_normalization.normalize_phone`.

Repository lookups use exact canonical values only. Fuzzy matching is forbidden.
Private or anonymous caller values are rejected for PhoneContactPoint creation.

## Lookup semantics

`find_active_by_normalized_phone()` returns **all exact active candidates**:

- phone point status must be `active`
- linked CustomerIdentity status must be `active`
- `inactive` phone points and `merged` / `inactive` identities are excluded
- zero, one, or many matches are all valid outcomes

A match is a candidate only. It does **not** mean confirmed customer linkage.

## Explicit non-goals in this slice

- no Auerswald ingestion
- no new call key implementation
- no Rückruf UI changes
- no automatic customer creation from calls
- no Inquiry or Order schema changes
- no HubSpot outbound or HubSpot IDs as truth
- no production migration execution

## Follow-on slices

- Inquiry integration: separate slice
- Auerswald ingestion / call linkage: separate slice
- call-key decision remains unchanged (`OFFICE_CUSTOMER_IDENTITY_AND_CALL_KEY_DECISION_V1.md`)

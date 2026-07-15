# Offer contract V1

Status: revised draft after architectural review on 2026-07-15. This document
defines a future data boundary only. It authorizes no schema, API, UI, migration,
customer send, or configurator-to-Core write path.

## Purpose

Define the immutable commercial snapshot transferred through the future flow:

```text
Configurator UI
    → configurator backend calculation
    → OfferSnapshot V1
    → office review and authenticated Core command
    → Core Offer aggregate
```

The contract preserves exactly what was prepared and presented without making
the configurator operational truth. It is separate from the existing
`core_inquiry_offer_prefill_v1` and `proposal_payload_v1` preview contracts.

## Vocabulary

- **Offer**: Core-owned commercial aggregate linked to one Inquiry.
- **OfferVersion**: immutable snapshot of one prepared or sent commercial
  revision.
- **OfferVariant**: one customer-selectable alternative embedded in an
  OfferVersion. It is not independently mutable.
- **OfferPosition**: frozen customer-visible line within one variant.
- **Acceptance**: Core-owned evidence that the customer accepted one exact
  variant of one exact persisted OfferVersion.
- **Order**: operational aggregate created only after acceptance.

Configurator drafts, browser state, JSON Draft Storage, previews, and downloads
are not any of the Core records above.

## Ownership and authority

- Core owns Offer identity, immutable versions, lifecycle transitions,
  acceptance evidence, and conversion to Order.
- The configurator owns catalog editing, draft composition, preview, and
  calculation.
- The configurator backend is the only authority allowed to calculate monetary
  values for an OfferSnapshot. Client-side calculations are display-only.
- The Office Panel remains the human write surface and submits snapshots and
  decisions through named, authenticated, CSRF-protected, idempotent Core
  commands.
- Core validates contract shape, lifecycle, references, arithmetic consistency,
  and command preconditions. It does not recalculate old snapshots from the live
  catalog.
- The future Office Panel obtains the authoritative snapshot response from the
  configured configurator backend calculation endpoint and submits that exact
  response through an authenticated Core command. Manual pasted JSON and
  frontend-generated totals are not accepted as OfferSnapshot V1.
- The contract is transport-neutral. It does not select an API route, file
  upload, or deployment topology beyond that trust direction.

## OfferSnapshot V1

The logical envelope is:

```json
{
  "schema_version": "offer_snapshot_v1",
  "source": "fingerfood-configurator-backend",
  "source_draft_id": "optional-configurator-reference",
  "inquiry_id": "Core Inquiry UUID",
  "snapshot_id": "UUID",
  "snapshot_hash": "sha256:64-lowercase-hex-characters",
  "snapshot_created_at": "2026-07-15T08:30:00Z",
  "valid_until": "2026-07-29",
  "currency": "EUR",
  "recipient": {
    "company_name": "Example company",
    "contact_name": "Example contact",
    "email": "customer@example.invalid",
    "postal_address": "Customer-visible recipient address"
  },
  "event": {
    "event_date": "2026-08-20",
    "time_window_text": "18:00–22:00",
    "location_text": "Hamburg",
    "guest_count": 80,
    "planning_mode": "caterer_suggestion"
  },
  "customer_text": {
    "title": "Sommerfest",
    "introduction": "Customer-visible introduction",
    "notes": "Customer-visible conditions and notes"
  },
  "payment_terms": {
    "method": "RECHNUNG",
    "customer_visible_text": "Zahlung per Rechnung"
  },
  "calculator": {
    "name": "fingerfood-backend",
    "calculator_revision": "future-revision",
    "catalog_revision": "future-revision",
    "tax_revision": "future-revision"
  },
  "variants": [
    {
      "variant_id": "UUID",
      "label": "Variante A",
      "description": "Customer-visible alternative",
      "positions": [
        {
          "position_id": "UUID",
          "kind": "catalog",
          "catalog_item_id": "traceability-only-id",
          "name": "Frozen customer-visible name",
          "description": "Frozen description",
          "composition": "Frozen package composition",
          "quantity_mode": "total",
          "quantity": "80",
          "unit_label": "Stück",
          "unit_net_cents": 290,
          "net_total_cents": 23200,
          "vat_rate_percent": 7,
          "vat_amount_cents": 1624,
          "gross_total_cents": 24824,
          "notes": "Frozen customization",
          "related_position_id": null
        }
      ],
      "totals": {
        "net_cents": 23200,
        "vat_7_base_cents": 23200,
        "vat_7_amount_cents": 1624,
        "vat_19_base_cents": 0,
        "vat_19_amount_cents": 0,
        "gross_cents": 24824
      }
    }
  ]
}
```

Example values illustrate shape only and are not catalog, tax, pricing, or
business defaults.

## Field rules

### Envelope

- `schema_version` is exactly `offer_snapshot_v1`. Meaning is never changed in
  place; incompatible changes require a new schema version.
- Unknown object members are rejected in V1 rather than ignored.
- `source` is exactly `fingerfood-configurator-backend`. A frontend-generated
  payload must not claim this source.
- `source_draft_id` is optional configurator traceability and never a Core
  identifier or idempotency key.
- `inquiry_id` identifies the existing Core Inquiry. Import must fail if the
  Inquiry does not exist.
- V1 permits exactly one Core Offer aggregate per Inquiry. Further attempts,
  negotiations, and revisions create further OfferVersions on that aggregate;
  alternatives presented together are variants in one version.
- `snapshot_id` identifies this immutable snapshot. Reuse with different content
  must fail.
- `snapshot_hash` is SHA-256 over the UTF-8 RFC 8785 canonical JSON form of the
  complete snapshot with the `snapshot_hash` member omitted. The configurator
  backend produces it; Core recomputes and stores it. The hash detects content
  mismatch but is not authentication by itself.
- The configurator backend mints `snapshot_id`. Core mints its own `offer_id` and
  `offer_version_id` when the reviewed snapshot is persisted and retains
  `snapshot_id` as immutable source traceability.
- timestamps are UTC ISO-8601 values; dates are ISO `YYYY-MM-DD`.
- `currency` is exactly `EUR` in V1.
- `valid_until` is required and includes that full `Europe/Berlin` calendar
  date. Expiry never rejects or converts an Offer; it only makes that sent
  version ineligible for acceptance.

### V1 limits

- The UTF-8 snapshot envelope is at most 1 MiB in the full contract design.
- A snapshot contains 1–10 variants and each variant contains 1–500 positions in
  the full contract design.
- **Core runtime limits (implementation V1):** the first Offer validation and
  prepare commands enforce a stricter catering-oriented subset until a later
  slice explicitly widens them:
  - UTF-8 envelope at most **256 KiB**;
  - **1–5** variants per snapshot;
  - **1–100** positions per variant;
  - the future `prepare-offer` Office API route may raise its own body cap; the
    global Core Office API limit remains 64 KiB until that route ships.
- Snapshot, Offer, OfferVersion, variant, position, acceptance, Order, and
  Inquiry identifiers are canonical UUID strings. Evidence references are at
  most 1,000 characters; email is at most 320 characters.
- Titles, labels, names, and recipient fields are at most 500 characters.
- Descriptions, composition, customer-visible text, payment text, and notes are
  at most 20,000 characters each.
- Core rejects values beyond a limit; it never truncates authoritative
  commercial evidence.

### Recipient

- Recipient fields are frozen as presented so the sent evidence can identify
  who received the OfferVersion.
- At least one of `company_name` or `contact_name` is required. Email and postal
  address may be empty when another recorded delivery channel was used.
- Recipient data is commercial evidence. It does not create a customer master
  record and is not copied automatically back into Inquiry or Order.

### Event facts

- `event_date`, `time_window_text`, `location_text`, `guest_count`, and
  `planning_mode` are commercial snapshot facts, not an automatic mutation of
  Inquiry or Order.
- `guest_count` is either a positive integer or `null` when still unknown.
- Conversion maps reviewed accepted facts into OrderVersion 1 only through the
  future explicit conversion command.

### Customer-visible text

- `title`, `introduction`, descriptions, composition, notes, and conditions are
  frozen exactly as presented.
- All strings require explicit length limits and normal escaping at every
  renderer. HTML is not accepted as semantic content.
- Internal warnings, raw enums, catalog diagnostics, and Core blocker codes are
  not customer-visible text.

### Variants and positions

- An OfferVersion contains at least one variant.
- `variant_id` is unique within the snapshot and identifies a selectable
  alternative. It has no lifecycle outside its OfferVersion.
- Acceptance references exactly one `variant_id`; it never copies a mutable
  draft or resolves against the current catalog.
- A position snapshots its name, description, composition, quantity semantics,
  price, tax treatment, totals, and notes.
- `catalog_item_id` is optional traceability. It must never be dereferenced to
  reconstruct historical customer-visible or monetary facts.
- `kind` is `catalog`, `surcharge`, `fee`, or `custom`. Büffetpauschale,
  Geschirrpauschale, delivery, and other charged elements must appear as priced
  positions so totals are reproducible.
- A selected surcharge is always a separate `kind=surcharge` position with its
  own frozen unit price, VAT, and totals. Its `related_position_id` points to the
  base position and it uses the same VAT rate as that base position.
  `related_position_id` is null for every non-surcharge position.
  `unit_net_cents` on the base position never includes a surcharge, preventing
  hidden or double charging.
- `quantity` is a canonical positive decimal string with at most three
  fractional digits. `quantity_mode=total` uses that quantity directly;
  `quantity_mode=per_person` multiplies it by the snapshot's non-null
  `event.guest_count`.
- `quantity_mode=per_person` is invalid unless `event.guest_count` is a positive
  integer. Core rejects the complete snapshot rather than guessing a count.
- Discounts are not supported in V1. They require an explicit later contract
  rather than negative or hidden positions.
- Production groups, kitchen routing, allergens approval, and preparation
  instructions are outside this commercial contract.

### Money and VAT

- Every monetary value is an integer number of euro cents. Binary floating-point
  values are forbidden at this boundary.
- Unit and total values are non-negative. Negative positions are forbidden in
  V1; discounts require a later explicit contract.
- The configurator backend performs intermediate arithmetic with decimal
  numbers and rounds to integer cents using `ROUND_HALF_UP`. The frontend may
  display these results but must not independently mint authoritative totals.
- For each position, effective quantity is determined from `quantity_mode`.
  `net_total_cents` is the exact decimal product of `unit_net_cents` and
  effective quantity, rounded once to cents with `ROUND_HALF_UP`.
- `vat_amount_cents` is calculated per position as
  `net_total_cents × vat_rate_percent / 100`, rounded once with
  `ROUND_HALF_UP`. `gross_total_cents` equals
  `net_total_cents + vat_amount_cents`.
- `vat_rate_percent` is exactly `7` or `19` in V1; every other value is
  rejected.
- Position net, VAT, and gross values are frozen outputs of the configurator
  backend calculation.
- Each variant carries complete 7% and 19% bases and amounts plus final net and
  gross totals. Each rate bucket is the sum of its position net and
  position-VAT values; variant net, VAT, and gross totals are the sums of all
  positions. No second bucket-level rounding is performed.
- V1 supports mixed 7% and 19% positions. Additional services, delivery, and
  Pauschalen are explicit `fee` or `custom` positions with their own frozen VAT
  rate; they are never hidden additions to a variant total.
- Core checks internal arithmetic consistency but does not classify VAT or
  recalculate prices from catalog data.
- `calculator_revision`, `catalog_revision`, and `tax_revision` are
  required provenance. Their concrete revision formats must be fixed by the
  configurator implementation pack.
- The current VAT logic remains best-effort and must be approved for commercial
  use before this contract can become authoritative.

### Payment terms and validity

- `payment_terms.method` is required before a version can be sent.
- V1 values use the existing Core vocabulary exactly: `VORKASSE`, `RECHNUNG`,
  or `BAR_VOR_ORT`.
- `payment_terms.customer_visible_text` freezes how the agreed method was
  presented. It cannot contradict `method`.
- Payment terms belong to the OfferVersion, apply to all its variants, and
  cannot be overridden by the acceptance command.
- Changing payment method or validity after sending creates a new OfferVersion.
- On conversion the accepted payment method is transferred into the separate
  Order payment-reminder context; it never affects kitchen readiness.

## Sent evidence

`Sent` is a Core-owned append-only fact recorded against one persisted
OfferVersion:

```json
{
  "schema_version": "offer_sent_evidence_v1",
  "offer_id": "Core Offer UUID",
  "offer_version_id": "Core OfferVersion UUID",
  "sent_at": "2026-07-15T10:00:00Z",
  "recorded_at": "2026-07-15T10:00:05Z",
  "channel": "email",
  "recipient_reference": "customer@example.invalid",
  "evidence_reference": "external-message-or-document-reference",
  "recorded_by": "authenticated-office-principal"
}
```

- Sending is an explicit office command; preparing a snapshot does not imply
  that a customer received it.
- The office supplies factual `sent_at`. Core generates `recorded_at` at command
  execution and derives `recorded_by` from the authenticated office principal;
  neither Core-owned field is accepted from form or API arguments.
- `channel` is `email`, `postal`, `in_person`, or `other`.
- Evidence binds delivery metadata to the exact persisted OfferVersion and
  frozen recipient. It does not place message bodies or documents in Order.
- Sending a newer version makes every earlier sent, undecided version
  `Superseded`. A merely prepared newer version does not supersede the currently
  sent version.

## Acceptance evidence

Acceptance is not generated inside `OfferSnapshot`. It is recorded later by a
Core command against a persisted snapshot:

```json
{
  "schema_version": "offer_acceptance_v1",
  "acceptance_id": "Core UUID",
  "offer_id": "Core Offer UUID",
  "accepted_offer_version_id": "Core OfferVersion UUID",
  "accepted_variant_id": "Variant UUID from that snapshot",
  "accepted_at": "2026-07-16T09:15:00Z",
  "recorded_at": "2026-07-16T09:20:00Z",
  "channel": "email",
  "recorded_by": "authenticated-office-principal",
  "evidence_reference": "external-message-document-or-call-reference",
  "note": "optional factual note"
}
```

- `channel` is `email`, `phone`, `signed_document`, `in_person`, or `other`.
- Evidence records who entered the decision and how it was received; it does not
  claim to be a digital signature or an accounting document.
- `accepted_at` is when the customer accepted; `recorded_at` is when the office
  entered that fact in Core.
- The office supplies factual `accepted_at`. Core generates `recorded_at` at
  command execution and derives `recorded_by` from the authenticated office
  principal; neither Core-owned field is accepted from form or API arguments.
- `evidence_reference` identifies the supporting external email, document, CRM
  record, or call note. It is metadata, not an imported attachment.
- The referenced version and variant must exist, belong to the same Offer, and
  be the currently eligible sent version: not rejected, withdrawn, superseded,
  or expired.
- An Offer aggregate may have at most one accepted variant. Repeated recording
  with the same command ID and content is an idempotent replay; conflicting
  acceptance is rejected.
- Acceptance is append-only. A correction or later commercial change requires
  an explicit reviewed command and must not rewrite the original evidence.

## Rejection and withdrawal facts

- RejectionEvidence belongs to one sent OfferVersion and records the factual
  customer `rejected_at`, optional evidence reference, Core-generated
  `recorded_at`, and authenticated `recorded_by`.
- WithdrawalEvidence belongs to one prepared or sent OfferVersion and records
  Core-generated `withdrawn_at`, authenticated `recorded_by`, and an optional
  factual reason.
- A version with AcceptanceEvidence cannot be rejected or withdrawn. Rejection
  and withdrawal are append-only and idempotent under the normal Core command
  rules.
- Superseded has no independent mutable flag or command: it is derived when a
  newer version on the same Offer receives SentEvidence.

## Conversion command and link

Only the following conceptual command creates an Order from an Offer:

```text
ConvertAcceptedOffer(
    offer_version_id,
    variant_id,
    acceptance_id
)
```

- All three references must identify the same accepted commercial decision.
- The command atomically creates Order plus OrderVersion 1, stores an immutable
  conversion link `(offer_id, offer_version_id, variant_id, acceptance_id,
  order_id)`, transfers the agreed payment method into the separate reminder
  context, and updates the Inquiry CRM stage.
- Event facts map into OrderVersion 1. Prices, VAT, validity, recipient,
  customer-visible text, sent evidence, and acceptance evidence remain on the
  Offer side and are never copied into OrderVersion.
- Menu composition and production instructions require their own later reviewed
  handoff; OfferVersion is not reused as an operational version.
- One acceptance can create at most one Order, including after that Order is
  cancelled. Order Storno never reopens the accepted Offer. A later commercial
  agreement requires a new Inquiry and new Offer aggregate, or an explicitly
  reviewed exceptional manual command. That exception is not the ordinary
  direct conversion and is not authorised by this V1 contract.

## Lifecycle and conversion constraints

Configurator-only phases are:

```text
Draft → Editing → Preview
```

They are not Core statuses and never create OfferVersion history.

Core OfferVersion lifecycle is:

```text
Prepared
  ├→ Withdrawn
  └→ Sent
       ├→ Accepted → Converted
       ├→ Rejected
       ├→ Withdrawn
       └→ Superseded
```

`Expired` is derived when the current `Europe/Berlin` calendar date is later
than `valid_until` and the sent version has not been accepted, rejected,
withdrawn, or superseded. It is not a stored mutable flag. `Awaiting customer
decision` is the office-facing meaning of an eligible sent version, not an
additional status. `Cancelled` is not an Offer status; Storno belongs to Order.

No lifecycle name above is stored as a mutable general-purpose `status` field.
Core stores immutable OfferVersion content plus append-only
`SentEvidence`, `AcceptanceEvidence`, `RejectionEvidence`,
`WithdrawalEvidence`, and `ConversionLink` facts:

- `Prepared` follows from OfferVersion existence;
- `Sent` follows from SentEvidence;
- `Accepted` follows from AcceptanceEvidence;
- `Converted` follows from ConversionLink;
- `Rejected` and `Withdrawn` follow from their corresponding evidence;
- `Superseded` follows when a newer OfferVersion receives SentEvidence;
- `Expired` follows from `valid_until` and the current business date.

A pure `derive_offer_state` decision is the single source for domain, API, and
UI state labels and transition eligibility.

- Draft editing remains in the configurator and is not Core truth.
- `Prepared` persists an immutable OfferVersion after office review.
- `Sent` records that exact version as presented to the customer.
- `Accepted` binds exact acceptance evidence to one variant.
- `Converted` records the Order created from that acceptance.
- `Rejected` records the customer's decision on that version.
- `Withdrawn` records that the office abandoned a prepared version or rescinded
  a sent version before a customer decision.
- `Superseded` records that a newer OfferVersion was sent. Rejection,
  withdrawal, supersession, or expiry does not prevent preparing a later version
  on the same one-per-Inquiry Offer aggregate.
- Acceptance closes commercial revision: after one variant is accepted, no
  further OfferVersion may be prepared on that Offer aggregate. The accepted
  OfferVersion is immutable and closed forever, including after Order Storno.
- A sent version is never updated; a revision creates the next OfferVersion.
- Only an accepted variant can use the future Offer-to-Order conversion command.
- Acceptance and conversion never bypass existing Inquiry verification,
  rejection, or single-active-Order gates.
- Conversion must be idempotent and atomic with Order plus OrderVersion 1
  creation, Offer conversion linkage, and Inquiry CRM transition.
- Candidate/effective selection, kitchen-print confirmation, `READY_TO_SEND`,
  cancellation, and production publication happen only after Order creation.
- Order changes never flow back into Offer. Order Storno does not reopen,
  unconvert, or alter the accepted OfferVersion.

## Backward compatibility

- Existing direct Inquiry-to-Order conversion remains supported during migration
  and for explicit legacy/manual cases.
- Direct conversion is forbidden while an Inquiry has an active OfferVersion:
  `Prepared` or an eligible `Sent` version. Rejected, withdrawn, superseded, and
  expired versions are inactive; direct conversion after them remains an
  explicitly manual legacy path.
- Once an accepted Offer exists for an Inquiry, direct legacy conversion must
  always refuse to bypass it; `ConvertAcceptedOffer` is then the only conversion
  path for that commercial agreement.
- Preparing a new OfferVersion is forbidden while the Inquiry has an active
  Order.
- Until the Offer runtime slice is deployed, current conversion behavior remains
  unchanged.
- Existing Orders have no implied Offer, accepted variant, price, or payment
  method.
- Existing `core_inquiry_offer_prefill_v1` remains a read-only prefill.
- Existing `proposal_payload_v1` remains a read-only/manual preview contract and
  must not be interpreted as `offer_snapshot_v1`.
- No configurator draft or historical export is migrated automatically.

## Security and transport requirements

Any future transport must preserve:

- the Office Panel as the authenticated human command surface;
- Basic Auth and CSRF for office actions;
- Core Office API bearer authentication in remote mode;
- existing command IDs, idempotency fingerprints, and exact optimistic
  preconditions;
- strict schema, type, enum, size, count, and string-length limits;
- rejection of unknown or duplicate identifiers and inconsistent totals;
- acceptance only of exact `offer_snapshot_v1` envelopes returned by the
  configured configurator backend; the `source` string and snapshot hash provide
  metadata and integrity, not authentication by themselves;
- Core recomputation and storage of `snapshot_hash`, plus immutable storage of
  `calculator_revision`, `catalog_revision`, and `tax_revision`;
- no secrets, credentials, customer payloads, or authoritative snapshots in URL
  query strings or fragments;
- no direct configurator access to `core.db`.

## Explicit non-goals

V1 does not define or authorize:

- database tables, migrations, repositories, routes, or UI;
- direct configurator-to-Core commands;
- automatic customer email, PDF signing, or acceptance portals;
- Invoice, accounting, banking, or payment matching;
- discounts or generic catalog customization rules;
- production groups or structured kitchen execution;
- price, VAT, or Offer fields on OrderVersion;
- removal of the legacy Inquiry-to-Order path.

## Acceptance gate for implementation planning

Before code is planned, reviewers must agree on:

1. the Offer lifecycle and exact transition permissions;
2. the canonical representation and revision identifiers produced by the
   configurator backend;
3. money rounding and VAT treatment confirmed for commercial use;
4. acceptance evidence required for each channel;
5. office-mediated transport, authentication, size limits, idempotency, and
   concurrency behavior;
6. atomic mapping from an accepted variant to OrderVersion 1 and the separate
   payment-reminder context;
7. additive migration and rollback behavior preserving direct Inquiry-to-Order.

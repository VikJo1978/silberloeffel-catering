# COURIER_CASH_HANDOFF_CONTRACT_V1

Status: **FROZEN** for Core issue #202.

Contract version: `courier-cash-handoff-v1`

This pack freezes the smallest cross-repository contract for BAR execution
between Silberlöffel Core/Kiosk and Courier App. It deliberately does not
implement the complete Courier UI or accounting. The implementation consumer
is `courier-app#13`.

## 1. Topology decision

The previous Kiosk order-feed decision said Courier App never talks to Core
directly. Issue #202 revisits that rule only for machine writes.

1. Planning/read direction stays Courier -> private Kiosk
   `GET /api/order-feed`.
2. Cash execution writes go from the Courier backend directly to Core:
   `POST /machine/v1/courier/cash-events`.
3. **Kiosk remains strictly read-only.** It is not a write relay and stores no
   Courier execution state.
4. Core remains source of truth for payment workflow/audit. Courier owns
   assignment UI and its immutable `assignment_id`.

Routing writes through Kiosk was rejected because it would destroy the Kiosk's
strongest safety property: no write surface.

## 2. Kiosk -> Courier projection

The existing order-feed gets one additive order field `cash_handoff`.

- field absent: producer has not rolled out this contract; hide cash actions;
- field present as `null`: contract available, Order is not BAR;
- field present as object: BAR execution context exists.

The object is frozen by `order-feed-cash-handoff.schema.json`:

```json
{
  "contract_version": "courier-cash-handoff-v1",
  "bar_required": true,
  "quittung_status": "PRINTED_CURRENT",
  "order_version_id": "11111111-1111-4111-8111-111111111111",
  "cash_execution_context_id": "22222222-2222-4222-8222-222222222222"
}
```

`PRINTED_CURRENT` means the external Quittung readiness fact belongs to the
current BAR/effective-OrderVersion context. A later effective Order revision,
payment-method change, Quittung reprint or privileged correction makes the old
context stale.

`cash_execution_context_id` is an opaque immutable UUID minted by Core for
one execution-relevant BAR context. It changes when payment method,
effective OrderVersion or Quittung readiness/currentness changes. It does not
change merely because custody advances through the same context.

Courier must not enable customer cash completion while
`quittung_status=NOT_READY`.

No amount, billing, invoice contents, document/PDF, price or accounting data
crosses this projection.

## 3. Courier -> Core command

```http
POST /machine/v1/courier/cash-events
Authorization: Bearer <dedicated service token>
Content-Type: application/json
```

No query parameters. Request exact field set is frozen in
`cash-event-command.schema.json`.

Every event carries contract version, idempotency key, Order identity,
Courier-owned assignment identity, effective OrderVersion identity,
cash execution context identity, actor identity/role and occurred-at time.

`occurred_at` is audit provenance. Server `recorded_at`, transaction order
and state preconditions decide current Core truth. A client timestamp never
wins a race.

## 4. Frozen event types

### BAR_RECEIVED_AND_QUITTUNG_HANDED_TO_CUSTOMER
Actor `DRIVER`. READY -> `DRIVER_CUSTODY`. **Not final payment.**

### BAR_NOT_RECEIVED
Actor `DRIVER` or `CHEF`. Exactly one reason:
`CUSTOMER_NOT_FOUND`, `CUSTOMER_COULD_NOT_PAY`,
`AMOUNT_NOT_ACCEPTABLE`, `OTHER`.

`OTHER` requires a non-empty note. Other reasons require `note=null`.
The reason code `AMOUNT_NOT_ACCEPTABLE` carries no numeric amount.

Result `NOT_RECEIVED`; Core stays unpaid and projects urgent
`Barzahlung klären`.

### BAR_HANDED_TO_CHEF
Actor `DRIVER`. `DRIVER_CUSTODY` ->
`AWAITING_CHEF_CONFIRMATION`. Still not final payment.

### BAR_RECEIVED_FROM_DRIVER_BY_CHEF
Actor `CHEF`. `AWAITING_CHEF_CONFIRMATION` -> `FINAL_PAID`.
This distinct chef confirmation is required for delivery cash.

### BAR_RECEIVED_DIRECT_BY_CHEF_AND_QUITTUNG_HANDED_TO_CUSTOMER
Actor `CHEF`, pickup/direct chef path only.
READY -> `FINAL_PAID` without driver custody.

### BAR_HANDOFF_CORRECTION
Actor `CHEF` or `OFFICE`. Requires
`correction_of_idempotency_key` and mandatory `correction_reason`.
Original event remains immutable/auditable. Current cash state becomes
`MANUAL_REVIEW_REQUIRED`. If the corrected event established final payment,
Core also uses the existing #201 audited payment-completion correction.
Drivers cannot correct/delete events.

Machine transition source: `transition-table.json`.

## 5. Authentication

Dedicated Core service token, separate from Courier user/phone tokens and the
Kiosk pickup-signal token.

Implementation requirements:

- token from mode-0600 service environment file;
- constant-time bearer comparison;
- route returns 404 when no server-side token is configured;
- once configured, missing/malformed/wrong bearer always returns the same
  `401 {"error":"unauthorized"}`;
- authenticate before body/schema validation;
- token never accepted in URL/query/body;
- Authorization and request bodies never logged;
- `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.

LAN/Tailscale is defence in depth, not authentication.

## 6. Replay, ordering and concurrency

- exact version `courier-cash-handoff-v1`;
- exact JSON field sets, unknown fields rejected;
- maximum request body 16 KiB;
- globally unique `idempotency_key`;
- first accepted command stores request fingerprint and exact success response;
- identical replay returns the **same persisted success response**;
- same key with different canonical request -> 409
  `{"error":"idempotency_conflict"}`;
- stale OrderVersion -> 409 `{"error":"stale_order_revision"}`;
- stale cash context -> 409 `{"error":"stale_cash_context"}`;
- out-of-order state -> 409 `{"error":"invalid_transition"}`;
- concurrent commands are serialized transactionally; first valid transition
  wins and every loser is re-evaluated against resulting state.

Stale revision/context conflicts before mutation.

## 7. Responses

Frozen by `cash-event-response.schema.json`.

Success contains only contract version, immutable Core event id, idempotency
key, Order id, resulting cash state and server recorded-at.

Error codes:
- 401 `unauthorized`
- 400 `invalid_request`
- 400 `unsupported_contract_version`
- 409 `idempotency_conflict`
- 409 `stale_order_revision`
- 409 `stale_cash_context`
- 409 `invalid_transition`
- 503 `core_unavailable`

Error bodies do not echo request fields.

## 8. Failure behaviour

Kiosk unavailable: unavailable feed is not an empty day. No cash context is
invented and no cash action is enabled.

Core write unavailable/timeout: Courier must **not** display the event as saved
and must not advance authoritative local cash state. Physical reality may
already have happened, so UI stays explicitly unsaved/retryable and retries
use the same idempotency key.

Courier unavailable: Core keeps current truth and invents no Courier event.

## 9. Rollout and compatibility

1. Merge/freeze this contract pack.
2. Implement Core journal/state machine/machine endpoint dormant until token.
3. Deploy Courier support that tolerates absent `cash_handoff` and hides cash
   actions when absent/unsupported.
4. Add Kiosk `cash_handoff` projection. Existing Courier parser reads named
   fields and ignores unknown top-level order keys, so old Courier remains
   compatible.
5. Configure Core write token/URL.
6. Enable Courier cash UI from `courier-app#13`.

Rollback before step 6 is safe: absent context disables actions. Unknown/stale
context is never guessed current.

## 10. Non-goals

No amount/paid-amount, cents, price, ledger, balance/difference, partial
payment, invoice/receipt/PDF transport/generation, accounting API, automatic
customer communication, customer billing expansion, Kiosk write relay, or
complete Office/Courier UI.

## 11. Shared assets

Both repositories must test the same semantics from this directory:
schemas, transition table and `fixtures.json`. Courier may vendor the fixture
pack verbatim in its implementation PR. Any semantic change requires a new
contract version.

# Order Outbound Send Boundary — design pack V1

Status: **design proposal — product decisions APPROVED FOR V1; Slice B1 implemented locally (EMAIL_MVP_1), not deployed; other slices not authorized except Slice A1 after review**
Evidence baseline: repository audit after Gate **6D-4 PASS** / Gate **6D-5 FAIL**, 2026-07-18, Europe/Berlin
Prerequisite audits: Gate 6D-4 operational smoke, Gate 6D-5 send-boundary audit
Scope owner: **Core operational outbound send** — Order axis only
Placement: active design packs live under `docs/proposals/` (see `docs/README.md` §Documentation rules)

---

## 1. Repository audit (verified facts)

This pack is grounded in the **actual** codebase. Names below are file paths relative to the repository root unless noted.

### 1.1 READY_TO_SEND (derived read, not dispatch)

| Artifact | Path | Verified behaviour |
|---|---|---|
| Gate rule | `src/catering_system/domain/ready_to_send.py` | `evaluate_ready_to_send_from_facts()` — ready only when effective version exists **and** its `kitchen_print_confirmed_at` is set |
| Reason vocabulary | same file | `ready_to_send_order_not_found`, `order_cancelled`, `no_effective_version`, `effective_version_not_resolvable`, `kitchen_print_not_confirmed` |
| Service read | `src/catering_system/services/operational_core_service.py` | `evaluate_ready_to_send()` — pure read, emits nothing |
| Service command | same file | `request_ready_to_send()` — **does not mutate order truth**; emits `OrderReadyToSend` or `OrderReadyToSendBlocked` |
| API command | `src/catering_system/ui/office_api.py` → `cmd_ready` | `POST /office/v1/orders/{id}/ready` — always `200` with `{evaluation}` |
| Events | `src/catering_system/domain/operational_core_events.py` | `OrderReadyToSend`, `OrderReadyToSendBlocked` — dataclass events, not persisted delivery state |
| UI labels | `src/catering_system/ui/office_panel_views.py` | `READY_TO_SEND_BLOCKER_LABELS` — five codes only |
| Operator guide | `docs/user/office-panel.md` §Version and kitchen workflow | Steps 1–6 end at “request/check `READY_TO_SEND`”; **no client send step** |

Frozen pack reference: `docs/archive/packs/OPERATIONAL_CORE_EXECUTION_PACK_V1.md` §6–§10 — READY_TO_SEND stays derived, not stored; gate owned by operational core, not B7–B27 progression.

### 1.2 Offer commercial send (separate axis)

| Artifact | Path | Verified behaviour |
|---|---|---|
| Evidence model | `src/catering_system/domain/offer.py` → `SentEvidence` | Append-only; one row per `offer_version_id` |
| Service | `src/catering_system/services/offer_service.py` → `record_sent_evidence()` | Gates: `Prepared` state, no prior sent evidence, no acceptance/conversion |
| API | `POST /office/v1/offers/{offer_id}/versions/{version_id}/mark-sent` | Manual evidence recording; **no SMTP/API transport** |
| Persistence | `src/catering_system/repositories/sqlite_offer_repository.py` | `offer_sent_evidence` — PK `offer_version_id` |
| Contract | `docs/proposals/offer_contract_v1.md` §Explicit non-goals | “automatic customer email” explicitly out of scope for Offer V1 |

**Gate 6D-5 confirmed:** Offer `SentEvidence` does **not** substitute Order outbound send.

### 1.3 Order / OrderVersion (current operational truth)

| Artifact | Path | Fields |
|---|---|---|
| `Order` | `src/catering_system/domain/order.py` | `order_id`, `source_inquiry_id`, timestamps, `candidate_order_version_id`, `effective_order_version_id`, `cancelled_at` |
| `OrderVersion` | same | event facts + `kitchen_print_confirmed_at` only — **no positions, no money, no recipient** |
| SQLite | `src/catering_system/repositories/sqlite_order_repository.py` | mirrors domain; invariant triggers on version ownership |

No persisted send state, PAUSE, or Attention facts exist on Order today.

### 1.4 API command envelope and idempotency

| Artifact | Path | Verified behaviour |
|---|---|---|
| Transaction owner | `src/catering_system/repositories/core_transaction.py` | `CoreCommandExecutor.run()` — `BEGIN IMMEDIATE` … business write … ledger … `COMMIT`; events flushed post-commit via `DeferredEventSink` |
| Ledger | `src/catering_system/repositories/office_api_ledger.py` | `office_api_commands(command_id PK, fingerprint, result_status, result_body, created_at)` |
| Fingerprint | same | canonical hash over route, path ids, args, expect, client_id |
| Busy | `CoreCommandExecutor` + API | `503 core_busy` + `Retry-After: 1` — HTTP retry only, not business Attention |
| Normative summary | `docs/api/core-office-api.md` | envelope `{command_id, expect, args}`; replay rules |

### 1.5 Attention projections (UI/dashboard — not send enforcement)

| Counter | Derivation | Path |
|---|---|---|
| `druck_fehlt` | active orders with **no** version ever print-confirmed | `office_api.py` → `queue()` |
| `nicht_wirksam` | active orders with `effective_order_version_id IS NULL` | same |
| `versand_blockiert` | active orders where `evaluate_ready_to_send().ready == False` | same |
| `next_action` | print-confirm → effective → null | `office_api_views.py` → `resolve_next_action()` |

Known gap (documented, not fixed here): `PHASE_3_PRINT_ACK_ATTENTION_PACK_V1.md` §2.5 — dashboard can miss a new unconfirmed target version when an older version remains effective and ready.

**Attention counters are not authoritative blocking facts** and are not consulted by any send service (because none exists).

### 1.6 Kitchen print retry (related but separate)

| Artifact | Path | Status |
|---|---|---|
| `KitchenPrintService` | `src/catering_system/services/kitchen_print_service.py` | `request_print`, `reprint`, technical accept/reject — **not wired to Office API** in production |
| `kitchen_print_jobs` table | `src/catering_system/repositories/sqlite_kitchen_print_job_repository.py` | append-only attempt history (Slice 3A code exists) |
| Design pack | `PHASE_3_PRINT_ACK_ATTENTION_PACK_V1.md` | **not started** in production |

Kitchen reprint/retry must **not** be conflated with outbound customer send retry.

### 1.7 Print projection (kitchen/commercial read — not customer outbound doc)

| Artifact | Path | Relevance |
|---|---|---|
| `OrderPrintProjectionService` | `src/catering_system/services/order_print_projection_service.py` | Joins `OrderVersion` event facts + Offer positions via `ConversionLink`; intents `preview` / `final` |
| Scope pack | `docs/proposals/PRINT_PROJECTION_SCOPE_V1.md` | Explicitly excludes payment/READY_TO_SEND changes; Küchenzettel ≠ customer send |
| API read | `GET /office/v1/orders/{id}/print-data?version=` | Returns positions; **commercial totals not exposed** in current JSON slice; watermark `ENTWURF` until effective |

Print projection is **not** sufficient as a silent reuse for V1 customer outbound document (see §10).

### 1.8 Event patterns

Domain events today:

- Emitted synchronously into `DeferredEventSink` during commands
- Flushed **after** successful SQLite `COMMIT`
- **Not** stored in a durable event table unless a downstream sink is configured
- `OrderReadyToSend` carries **no** `order_version_id`, **no** transport metadata

Outbound send needs **persisted** evidence separate from ephemeral events. **`OrderReadyToSend` is not proof of send eligibility at dispatch time.**

### 1.9 Persistence / migrations pattern

- No standalone `migrations/` tree — schema evolves via numbered functions in repository modules + `sqlite_migrations.apply_migrations(connection, namespace, tuples)`
- Examples: `sqlite_order_repository.py`, `sqlite_offer_repository.py`, `office_api_ledger.py`, `sqlite_kitchen_print_job_repository.py`
- `core.db` is single SQLite file on Lenovo (`docs/current-status.md`)

### 1.10 Office Order Detail (current projection surface)

| Read | Path | Send-related fields today |
|---|---|---|
| `GET /office/v1/orders/{id}` | `office_api_views.py` → `order_detail()` | `ready_to_send`, `versions[]`, `payment_reminder`, `next_action` via list row helper |
| Panel | `src/catering_system/ui/office_panel_order_detail.py` | “Versandfreigabe” section; `POST /order/{id}/ready` |

No `send_status`, `send_evidence`, or `outbound_attention` fields exist.

### 1.11 Frozen / status docs

| Document | Relevant constraint |
|---|---|
| `docs/current-status.md` | “no automatic customer sends become Core truth” |
| `docs/decisions/README.md` ADR-004/005/006 | operational facts list does **not** include send evidence |
| `docs/proposals/PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1.md` | Core Office API performs **no outbound HTTP** today |
| `docs/proposals/offer_contract_v1.md` | commercial send ≠ operational send |
| Gate 6D-5 audit | PAUSE: 0 matches; outbound send endpoints: 404 |

### 1.12 Gate 6D-5 confirmed gaps (inputs to this pack)

1. No `OutboundSendService`
2. No outbound transport port/adapter
3. No `OrderSendEvidence`
4. No persisted delivery/send state
5. No safe fake/outbox transport
6. PAUSE completely absent
7. Attention/Retry are projections, not send-boundary enforcement
8. `POST /ready` evaluates gate + emits event only
9. Offer `SentEvidence` ≠ Order outbound send

---

## 2. Business meaning — what is outbound send?

### 2.1 Candidate meanings (must not be mixed)

| Candidate | Axis | Already covered? |
|---|---|---|
| Angebot to customer | Offer commercial | **Yes** — `mark-sent` + `SentEvidence` |
| Küchenzettel / production sheet | Kitchen internal | **Yes** — print projection + `ConfirmKitchenPrint` |
| Buffetschilder | Kitchen display | **Yes** — buffet-cards projection |
| Wochenübersicht / kiosk feed | Kitchen/courier read | **Yes** — effective-only reads |
| **Auftragsbestätigung to customer** | Order operational | **V1 target — not yet implemented** |
| Lieferschein / delivery note | Delivery day / courier | **No** — separate future axis |
| Courier dispatch message | Courier app | **No** — read-only feed exists |
| Invoice / payment reminder | Payment checklist | **Partial** — manual facts only, no send |

### 2.2 V1 use case — **APPROVED**

> After operational `READY_TO_SEND` eligibility is satisfied, the office operator issues an **explicit manual send command** that delivers an **Auftragsbestätigung** (order confirmation document) to the customer by **email**, recording **`OrderSendEvidence`** in Core only after **transport acceptance**.

`READY_TO_SEND` means **derived eligibility to send**, not stored state and **not** automatic dispatch.

### 2.3 Explicit axis separation (frozen in this pack)

```text
A. Offer commercial send
   Prepared OfferVersion
   → manual mark-sent
   → SentEvidence (offer_version_id)
   → no Order involvement

B. Order operational outbound send
   effective OrderVersion + READY_TO_SEND eligibility (+ PAUSE/Attention clear)
   → explicit manual Office send command
   → OutboundSendService (fresh gate evaluation)
   → transport adapter
   → OrderSendEvidence (order_version_id) — only after transport accepted
   → delivery/send projection

These axes MUST NOT share evidence tables, commands, or transport adapters.
```

### 2.4 Approved product decisions — V1

| # | Decision | V1 rule |
|---|---|---|
| 1 | Outbound document | **Auftragsbestätigung** to customer |
| 2 | Channel | **email only** (`channel` fixed to `email` in V1 commands) |
| 3 | `READY_TO_SEND` | **Derived eligibility**; not stored state; **does not trigger send** |
| 4 | Send trigger | **Explicit manual Office command only**; `OutboundSendService` **always** recomputes gate; **never** trusts `OrderReadyToSend` event or prior `POST /ready` |
| 5 | Recipient | Default = **stored customer email**; override requires **`recipient_override_reason`**; **immutable snapshot** of actually used address in Attempt/Evidence; UI projections show **masked** value |
| 6 | Success policy | **One successful send** per effective `OrderVersion` |
| 7 | Resend | **Separate explicit `resend` command** with mandatory **`reason`**; original evidence stays append-only |
| 8 | Delivery semantics | **Transport accepted** = success for V1; delivered/read receipt **out of scope** |
| 9 | PAUSE | **Order-level**; blocks `READY_TO_SEND` and outbound send; **does not** block effective switch; **does not hide** Order from read projections |
| 10 | Blocking Attention | **Unresolved outbound failure**, **manual blocking attention**, **retry exhausted**, **active PAUSE** |
| 11 | Payment / informational | Payment reminders and informational warnings **do not block send** by themselves |

---

## 3. Domain model proposal

Design principles aligned with existing patterns (`SentEvidence`, `KitchenPrintJob`, command ledger):

- **Append-only evidence** for successful sends (after transport acceptance)
- **Separate attempt + outbox rows** for in-flight / failed / reconciled dispatch
- **No secrets or full message bodies** in Core evidence tables
- **OrderVersion-scoped** send evidence
- **Evidence never created in the same transaction as pending outbox** (see §6.4)

### 3.1 `OrderSendEvidence` (append-only success fact)

Created only in **Transaction 2** after transport acceptance.

| Field | Type | Rule |
|---|---|---|
| `send_evidence_id` | UUID4 | PK; minted by Core |
| `order_id` | UUID4 | must exist |
| `order_version_id` | UUID4 | must equal effective version at send time |
| `document_snapshot_id` | UUID4 | FK to frozen `OrderConfirmationDocumentSnapshot` |
| `document_hash` | string | SHA-256 — must match snapshot |
| `document_kind` | enum | V1: `auftragsbestaetigung` only |
| `channel` | enum | V1: **`email` only** |
| `recipient_snapshot` | string | **immutable** address actually used (full value stored; UI masks on read) |
| `recipient_source` | enum | `customer_default` \| `operator_override` |
| `recipient_override_reason` | string \| null | required when `operator_override` |
| `sent_at` | UTC datetime | Core-minted at evidence commit (`transport_accepted_at`) |
| `recorded_at` | UTC datetime | Core write timestamp |
| `recorded_by` | string | authenticated Office API client id |
| `evidence_reference` | string | operator audit token |
| `transport_message_id` | string | stable transport idempotency key |
| `send_attempt_id` | UUID4 | FK to successful attempt |
| `command_id` | UUID4 | originating Office API command |
| `supersedes_send_evidence_id` | UUID4 \| null | present only for explicit resend |

Invariants:

- Append-only — no UPDATE/DELETE
- **At most one “primary” successful evidence per `order_version_id`** (resend adds new row with `supersedes_*`)
- `recorded_at >= sent_at`
- Evidence exists **only if** outbox row is `accepted` for same `transport_message_id`

### 3.2 `OrderSendAttempt`

| Field | Type | Rule |
|---|---|---|
| `send_attempt_id` | UUID4 | PK |
| `order_id` | UUID4 | |
| `order_version_id` | UUID4 | must match effective at enqueue |
| `command_id` | UUID4 | Office API command |
| `status` | enum | `prepared` → `dispatching` → `sent` \| `failed` |
| `failure_code` | string \| null | allowlisted when `failed` |
| `retryable` | bool | set on failure |
| `retry_count` | int | incremented on controlled retry |
| `document_snapshot_id` | UUID4 | frozen snapshot used for this attempt |
| `document_hash` | string | copied from snapshot |
| `channel` | string | V1: `email` |
| `recipient_snapshot` | string | immutable for this attempt |
| `recipient_source` | enum | `customer_default` \| `operator_override` |
| `recipient_override_reason` | string \| null | |
| `transport_message_id` | string | minted in Transaction 1; **stable idempotency key** |
| `transport_accepted_at` | UTC datetime \| null | set in Transaction 2 |
| `created_at` | UTC datetime | |
| `completed_at` | UTC datetime \| null | |

Derived rules:

- At most one attempt in `prepared` or `dispatching` per `(order_id, order_version_id)`
- **`sent` status requires linked `OrderSendEvidence`**
- Failed retryable attempt opens blocking Attention until retry or resolution

### 3.3 `OutboxMessage` (transport persistence — not domain evidence)

| Field | Type | Rule |
|---|---|---|
| `transport_message_id` | string | PK — **idempotency key** for transport + reconciliation |
| `send_attempt_id` | UUID4 | FK |
| `status` | enum | `pending` → `dispatching` → `accepted` \| `failed` |
| `channel` | string | V1: `email` |
| `recipient_snapshot` | string | copy at enqueue |
| `document_hash` | string | |
| `payload_blob` | BLOB | capped (e.g. 512 KiB); test/smoke only retention policy |
| `failure_code` | string \| null | |
| `created_at` | UTC datetime | |
| `dispatched_at` | UTC datetime \| null | |
| `accepted_at` | UTC datetime \| null | transport acceptance timestamp |

**Forbidden:** creating `OrderSendEvidence` in the same transaction that creates `OutboxMessage(status=pending)`.

### 3.4 `OrderConfirmationDocumentSnapshot` (requirement)

Frozen document captured **before** Transaction 1; referenced by attempt and evidence.

Built only from:

- effective `OrderVersion` event facts
- frozen commercial data via `ConversionLink` / Offer snapshot (**not live Catalog**)
- positions, totals, VAT, customer/event fields
- recipient snapshot chosen for this send (default or override)

Requirements:

| Requirement | Rule |
|---|---|
| Source | effective `OrderVersion` + frozen Offer/commercial data only |
| Contents | positions, totals, VAT, customer/event fields, recipient snapshot |
| Catalog | **no live Catalog read** |
| Hash | stable `document_hash` over canonical serialized bytes |
| Kitchen print | **must not** silently reuse `OrderPrintProjectionService` as customer document |
| Watermark | **no** `ENTWURF` on outbound final document |
| Mutability | immutable once snapshot row inserted for an attempt |

Optional read-only builder (Slice B1):

```text
OrderConfirmationDocumentSnapshotService.build_for_send(...) -> Snapshot
```

### 3.5 `OrderOperationalPause`

Order-level operational fact (see §4). PAUSE **does not** remove or hide the Order from Wochenübersicht, kiosk, calendar, or list reads — it only affects release/send eligibility and attention projections.

### 3.6 `OrderOperationalAttention`

Authoritative blocking facts (see §5). Dashboard counters derive from these rows after Slice A2.

### 3.7 Delivery / send projection (derived read)

| Projection field | Source |
|---|---|
| `ready_to_send` | extended evaluator (Slice A3) — derived, not stored |
| `outbound_send.eligible` | `OutboundSendService.evaluate_outbound_send(...)` — fresh computation |
| `outbound_send.latest_evidence` | newest `OrderSendEvidence` for effective version |
| `outbound_send.active_attempt` | `prepared` / `dispatching` / failed-retryable |
| `outbound_send.recipient_display` | masked `recipient_snapshot` |
| `pause.active` | active pause row |
| `blocking_attentions` | active blocking attention rows |

---

## 4. PAUSE contract

### 4.1 Scope — **APPROVED: order-level**

### 4.2 Commands (proposed API)

| Command | Route | Args |
|---|---|---|
| Pause | `POST /office/v1/orders/{id}/pause` | `reason_code`, `note` |
| Resume | `POST /office/v1/orders/{id}/resume` | `resume_note` |

### 4.3 Frozen invariants

```text
active PAUSE
  → evaluate_ready_to_send(...).ready == false   (reason: order_paused)
  → evaluate_outbound_send(...).eligible == false
  → OutboundSendService rejects send at service boundary
```

### 4.4 Interactions — **APPROVED**

| Area | Behaviour under active PAUSE |
|---|---|
| Read projections | Order **remains visible** (lists, detail, Wochenübersicht, kiosk, calendar) |
| `POST /ready` | Allowed; emits `OrderReadyToSendBlocked` including `order_paused` |
| Outbound send | **Rejected** |
| Effective switch | **Allowed** |
| Kitchen print confirm | **Allowed** |
| Cancel (Storno) | Allowed |

---

## 5. Attention / Retry contract

### 5.1 Principle

> Dashboard counters are **not** enforcement.
> `OutboundSendService` re-evaluates all blockers on every send.
> It does **not** trust UI, queue snapshots, `OrderReadyToSend`, or prior `POST /ready`.

### 5.2 Blocking Attention kinds — **APPROVED V1**

These **block** `READY_TO_SEND` and outbound send:

| Kind | Source |
|---|---|
| `order_paused` | active `OrderOperationalPause` |
| `outbound_send_failed_unresolved` | failed attempt + unresolved Attention |
| `outbound_send_retry_exhausted` | retry policy exhausted |
| `manual_blocking_attention` | operator-opened blocking attention |

**Informational only (do not block send by themselves):**

- payment reminder states (`office-panel.md` rule preserved)
- dashboard informational warnings without a blocking attention row
- kitchen print attention counters (`druck_fehlt`) until migrated to authoritative facts in a later pack

### 5.3 Retry semantics

| Retry type | Layer |
|---|---|
| HTTP retry | `503 core_busy` + same `command_id` |
| Business retry | `POST .../send-retry` targeting failed retryable attempt — **controlled**; opens no blind resend |

Retry exhausted → blocking Attention (`outbound_send_retry_exhausted`) until operator resolves.

### 5.4 READY_TO_SEND integration (Slice A3)

Extend `evaluate_ready_to_send_from_facts` (or thin wrapper) to include approved blocking reasons:

```text
existing operational reasons
+ order_paused
+ outbound_send_failed_unresolved
+ outbound_send_retry_exhausted
+ manual_blocking_attention
```

Payment/informational projections **excluded**.

---

## 6. Send service boundary

### 6.1 Application service (proposal)

```python
class OutboundSendService:
    def evaluate_outbound_send(self, order_id: str) -> OutboundSendEvaluation: ...

    def enqueue_send(
        self,
        order_id: str,
        *,
        expected_effective_order_version_id: str,
        recipient_reference: str | None,  # None => customer default
        recipient_override_reason: str | None,
        evidence_reference: str,
        command_id: str,
        recorded_by: str,
    ) -> SendEnqueueResult: ...  # returns attempt_id, transport_message_id; status prepared

    def retry_send(self, order_id: str, *, send_attempt_id: str, ...) -> SendEnqueueResult: ...

    def resend_order(self, order_id: str, *, reason: str, ...) -> SendEnqueueResult: ...
```

**Note:** `enqueue_send` performs Transaction 1 only. Evidence creation happens in dispatcher Transaction 2.

Gate evaluation runs at **enqueue** and again at **dispatch** (defense in depth).

### 6.2 Preconditions — minimum gate stack

Evaluated at enqueue (and re-checked at dispatch):

1. Order exists, not cancelled
2. Effective version matches `expected_effective_order_version_id`
3. Kitchen print confirmed on effective version
4. `READY_TO_SEND` eligibility (extended evaluator) — **computed fresh**
5. No active PAUSE
6. No active blocking Attention (approved kinds)
7. No successful primary `OrderSendEvidence` for version (unless `resend`)
8. No conflicting `prepared`/`dispatching` attempt
9. Recipient resolved: default customer email or valid override + reason
10. `OrderConfirmationDocumentSnapshot` built; hash stable
11. **`OrderReadyToSend` event and prior `POST /ready` are ignored**

V1 channel enforcement: reject non-`email` at API validation layer.

### 6.3 Transport port

```python
class OutboundTransport(Protocol):
    def dispatch(
        self,
        *,
        transport_message_id: str,  # stable idempotency key
        channel: Literal["email"],
        recipient_snapshot: str,
        document_hash: str,
        document_bytes: bytes,
        metadata: Mapping[str, str],
    ) -> TransportDispatchResult: ...
```

| Adapter | Slice |
|---|---|
| `FakeOutboxTransport` + dispatcher | B3 — same lifecycle as real transport |
| `SmtpTransport` | D — future |

### 6.4 Transaction / outbox design — **APPROVED two-phase model**

#### Forbidden model

```text
❌ Single transaction:
     insert Attempt(prepared)
     insert Outbox(pending)
     call transport
     insert OrderSendEvidence
     commit
```

Evidence must **not** exist until transport has **accepted** the message.

#### Approved model

```text
┌─────────────────────────────────────────────────────────────────┐
│ TRANSACTION 1 — enqueue (Office send command)                   │
├─────────────────────────────────────────────────────────────────┤
│  ledger replay check                                            │
│  fresh gate evaluation                                          │
│  build OrderConfirmationDocumentSnapshot (immutable)            │
│  resolve recipient (default or override+reason)                 │
│  mint transport_message_id (stable idempotency key)             │
│  insert OrderSendAttempt(status=prepared)                       │
│  insert OutboxMessage(status=pending)                           │
│  insert office_api_commands ledger → 200 {attempt_id, ...}      │
│ COMMIT                                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ DISPATCHER (sync in FakeOutbox / async worker in real SMTP)     │
├─────────────────────────────────────────────────────────────────┤
│  load Outbox(pending) + Attempt(prepared)                       │
│  re-run gate evaluation (defense in depth)                      │
│  TRANSACTION 1b: Outbox→dispatching, Attempt→dispatching        │
│  transport.dispatch(transport_message_id=...)  ← idempotent     │
│    ├─ accepted → continue                                       │
│    └─ failed → FAILURE PATH                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│ TRANSACTION 2 — success  │    │ FAILURE PATH                 │
├──────────────────────────┤    ├──────────────────────────────┤
│ Attempt → sent           │    │ Attempt → failed             │
│ Outbox → accepted        │    │ Outbox → failed              │
│ append OrderSendEvidence │    │ open blocking Attention      │
│ emit OrderOutboundSent   │    │ retryable per policy         │
│ COMMIT                   │    │ COMMIT                       │
└──────────────────────────┘    └──────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ RECONCILIATION (crash: transport accepted, Transaction 2 missing)│
├─────────────────────────────────────────────────────────────────┤
│  find Outbox(accepted) or transport idempotency record            │
│    without matching OrderSendEvidence                             │
│  complete Transaction 2 from persisted outbox facts               │
│  **never** call transport.dispatch again for same message id      │
└─────────────────────────────────────────────────────────────────┘
```

**FakeOutboxTransport (Slice B3)** must implement the **same** state transitions (`pending` → `dispatching` → `accepted`|`failed`) even though no network is involved. In-process dispatch is allowed **only** after `dispatching` is persisted.

#### Crash matrix

| Crash point | Recovery |
|---|---|
| Before Transaction 1 commit | No attempt/outbox; client retries same `command_id` |
| After Transaction 1, before dispatch | Dispatcher picks up `pending`; idempotent |
| After transport accepted, before Transaction 2 commit | **Reconciliation** completes evidence from outbox/`transport_message_id` |
| After Transaction 2 commit | Client replay returns ledger body; no transport call |

**Never blind resend** on reconciliation — always key on `transport_message_id`.

---

## 7. API proposal (not implemented)

### 7.1 Primary send command — **manual Office action**

```http
POST /office/v1/orders/{order_id}/send
```

```json
{
  "command_id": "<uuid4>",
  "expect": {
    "effective_order_version_id": "<uuid4>"
  },
  "args": {
    "channel": "email",
    "recipient_reference": null,
    "recipient_override_reason": null,
    "evidence_reference": "SMOKE-6D5-OUTBOUND"
  }
}
```

- `recipient_reference: null` → use stored customer email default
- non-null `recipient_reference` → **requires** non-empty `recipient_override_reason`
- Response **`200`** from Transaction 1 returns `{send_attempt_id, transport_message_id, status: "prepared"}` — **not** final evidence
- Final evidence appears after dispatcher Transaction 2 (poll via order detail or async notification in UI — UI detail in later slice)

### 7.2 Additional commands

| Route | Purpose |
|---|---|
| `POST .../send-retry` | controlled retry of failed retryable attempt |
| `POST .../resend` | explicit resend after success; **`reason` required** |
| `POST .../pause` / `.../resume` | PAUSE |
| `POST .../resolve-attention` | resolve manual/exhausted attention |

### 7.3 Response matrix

| Condition | HTTP | `error` |
|---|---|---|
| Enqueue success (Transaction 1) | `200` | `{status: "prepared", ...}` |
| Dispatch+evidence success (sync fake path may return in same HTTP) | `200` | `{status: "sent", send_evidence_id, ...}` |
| Same `command_id` replay | `200` | verbatim ledger |
| Fingerprint conflict | `409` | `command_id_conflict` |
| Stale effective version | `409` | `stale_state` |
| Gate blocked | `422` | `outbound_send_blocked` + `reasons[]` |
| Already sent (primary evidence exists) | `409` | `send_evidence_exists` |
| Active pause | `422` | `order_paused` |
| Blocking attention | `422` | `outbound_attention_active` |
| Override without reason | `422` | `recipient_override_reason_required` |
| Invalid email / channel | `422` | `invalid_recipient` / `invalid_channel` |
| Transport failure (retryable) | `422` | `transport_failed_retryable` |
| Transport failure (final) | `422` | `transport_failed_final` |
| SQLite busy | `503` | `core_busy` |

### 7.4 Read projection

Extend `GET /office/v1/orders/{id}`:

```json
{
  "ready_to_send": { "ready": false, "reasons": ["order_paused"] },
  "outbound_send": {
    "eligible": false,
    "reasons": ["order_paused"],
    "latest_evidence": null,
    "active_attempt": { "status": "prepared", "transport_message_id": "…" },
    "recipient_display": "c***@example.invalid",
    "active_pause": { "reason_code": "manual_hold" },
    "blocking_attentions": []
  }
}
```

---

## 8. FakeOutboxTransport and dispatcher (Slice B3)

### 8.1 Requirements

| Requirement | Design |
|---|---|
| No network | In-process adapter; obeys **same lifecycle** as real transport |
| Persist messages | `OutboxMessage` table in `core.db` |
| Stable idempotency | `transport_message_id` PK; `dispatch()` idempotent on key |
| Failure injection | test hook: `fail_mode: none \| retryable \| final` |
| Smoke safety | recipients must use `@example.invalid` or approved synthetic prefix |
| Restart-safe | reconciliation job keys on `transport_message_id` |

### 8.2 FakeOutbox lifecycle (matches §6.4)

```text
pending   → written in Transaction 1
dispatching → dispatcher marks before calling FakeOutboxTransport.dispatch
accepted  → FakeOutbox returns success → Transaction 2 creates evidence
failed    → FakeOutbox returns failure → Attention + retry path
```

`FakeOutboxTransport.dispatch()` **must not** mutate Core evidence directly — only returns accept/reject to dispatcher.

### 8.3 Storage

**SQLite `outbound_transport_outbox` in `core.db`** via official repository path (restart-safe, same backup domain as Core truth).

Transport outbox ≠ domain evidence — link via `transport_message_id` + `send_attempt_id`.

---

## 9. Idempotency and resend matrix

| # | Scenario | Expected behaviour |
|---|---|---|
| 1 | Same `command_id` replay at enqueue | Verbatim ledger; no second attempt/outbox |
| 2 | Same `transport_message_id` redispatch | Transport returns cached acceptance; **no second send** |
| 3 | New `command_id` after primary evidence | `409 send_evidence_exists` |
| 4 | Explicit `resend` with `reason` | New snapshot/attempt/outbox chain; new evidence; original evidence preserved |
| 5 | Transport fails before acceptance | Attempt/outbox `failed`; blocking Attention; **no evidence** |
| 6 | Transport accepted, Transaction 2 crash | Reconciliation completes evidence; transport **not** called again |
| 7 | Client timeout after Transaction 2 | Same `command_id` replay returns final sent body |

---

## 10. Document snapshot (Slice B1)

See §3.4 `OrderConfirmationDocumentSnapshot`.

Implementation notes:

- Canonical serialization: **JSON** for V1 (PDF rendering optional later)
- Hash: SHA-256 of UTF-8 canonical bytes
- Snapshot row persisted **before** Transaction 1
- Preview route (optional): `GET /office/v1/orders/{id}/outbound-document` — read-only; not a send

---

## 11. Persistence and migration plan (proposal only)

Namespace: `order_outbound_send`.

| Migration order | Table |
|---|---|
| A1 | `order_operational_pauses` |
| A2 | `order_operational_attentions` |
| B1 | `order_confirmation_document_snapshots` |
| B2 | `order_send_attempts`, `order_send_evidence`, `outbound_transport_outbox` |

Key constraints:

```sql
-- one primary successful send per order_version (V1)
CREATE UNIQUE INDEX uq_order_send_evidence_primary
  ON order_send_evidence (order_version_id)
  WHERE supersedes_send_evidence_id IS NULL;

CREATE UNIQUE INDEX uq_outbox_transport_message
  ON outbound_transport_outbox (transport_message_id);

CREATE UNIQUE INDEX uq_attempt_inflight
  ON order_send_attempts (order_id, order_version_id)
  WHERE status IN ('prepared', 'dispatching');
```

---

## 12. Test matrix (minimum)

Add tests for **two-phase** lifecycle:

| Area | Cases |
|---|---|
| Transaction 1 | enqueue creates attempt+outbox pending; **no evidence** |
| Dispatcher | pending→dispatching→accepted; evidence in Transaction 2 |
| FakeOutbox | same lifecycle without network |
| Reconciliation | accepted outbox without evidence → evidence completed; transport called once |
| Recipient | default email; override requires reason; masked projection |
| PAUSE | blocks ready+send; order still in list/Woche reads |
| Blocking Attention | failure, manual, retry exhausted, pause |
| Idempotency | command replay; transport_message_id replay |
| Resend | explicit command; original evidence preserved |
| Payment | does not block send |

---

## 13. Delivery slices — **REVISED ORDER**

| Slice | Scope | GO required |
|---|---|---|
| **A1** | PAUSE domain, pause/resume commands, order detail projection, `order_paused` reason | **Ready for implementation after this pack review** |
| **A2** | Authoritative `OrderOperationalAttention` + resolve command | Separate GO |
| **A3** | Integrate blocking reasons into `READY_TO_SEND` evaluation | Separate GO |
| **B1** | `OrderConfirmationDocumentSnapshot` service + preview read (no send) | **Implemented locally — EMAIL_MVP_1; not deployed** |
| **B2** | Attempt / evidence / outbox persistence + migrations | Separate GO |
| **B3** | FakeOutbox dispatcher + reconciliation (two-phase lifecycle) | Separate GO |
| **B4** | `OutboundSendService` + `POST /send` + order detail projections | Separate GO |
| **C1** | Retry / resend commands + failure Attention wiring | Separate GO |
| **C2** | Gate 6D-5 smoke (`@example.invalid` only) | Separate GO |
| **D** | Real email transport (SMTP/provider) | Separate GO + security review |

**Dependency chain:** A1 → A2 → A3 → B1 → B2 → B3 → B4 → C1 → C2 → (review) → D

**Gate 6D-5 smoke:** only after **B4 + C1 + C2** prerequisites.

---

## 14. Remaining open decisions (non-blocking for A1)

Product decisions **1–11 are APPROVED** (§2.4). Still open for later slices:

| # | Question | Blocks |
|---|---|---|
| 1 | PAUSE/resume RBAC — any office bearer vs restricted role? | A1 implementation detail |
| 2 | Who may `resolve-attention`? | A2 |
| 3 | Max retry count before `retry_exhausted` | C1 |
| 4 | Canonical document format JSON vs PDF bytes | B1 |
| 5 | Stored customer email source of truth (Inquiry vs Offer snapshot vs Contact) | B1/B4 |
| 6 | Sync vs async dispatcher in production API response | B4 UI/UX |
| 7 | Outbox payload retention TTL in production | D |

---

## 15. Unresolved blockers before coding

| Slice | Blocker | Severity |
|---|---|---|
| **A1** | Pack review sign-off | **required for A1 GO** |
| A2+ | Separate GO per slice (§13) | **process** |
| B3+ | Two-phase transaction design approval (§6.4) | **resolved in this revision** |
| C2 | B4 + fake dispatcher + reconciliation landed | **dependency** |
| D | Real SMTP security review | **future** |

**Resolved by this revision:**

- V1 document = Auftragsbestätigung ✓
- Channel = email only ✓
- READY_TO_SEND ≠ auto send ✓
- Manual send + fresh gate ✓
- Recipient snapshot + mask ✓
- One success per version ✓
- Explicit resend ✓
- Transport accepted = V1 delivery ✓
- PAUSE / blocking Attention rules ✓
- Two-phase outbox/evidence model ✓

---

## 16. Related follow-ups (out of scope)

- Fix `smoke_6d4.py` ISO-week check — separate small commit
- Documentation debt: `sent_at >= OfferVersion.created_at`; Offer Detail VAT/linkage audit
- `PHASE_3_PRINT_ACK_ATTENTION_PACK_V1.md` — coordinate vocabularies; do not merge with outbound Attention kinds

---

## 17. Acceptance and coding authorization

### Pack acceptance

Reviewers confirm:

1. Approved product decisions (§2.4)
2. Axis separation Offer vs Order send
3. Two-phase transaction / outbox design (§6.4)
4. `OrderConfirmationDocumentSnapshot` requirement (§3.4)
5. Slice order (§13)
6. FakeOutbox lifecycle parity (§8)

---

### Product decisions: **APPROVED FOR V1**

### Coding authorization:

| Slice | Authorization |
|---|---|
| **A1 — PAUSE** | **Ready for implementation after pack review** |
| **A2 and later** | **Require separate GO** |

**Do not** start Gate 6D-5 smoke until slices **B4 + C1 + C2** are complete.
**Do not** enable real email transport (slice D) until fake path and reconciliation are proven.

---

## Implementation status (local, not deployed)

| Slice | Status |
|---|---|
| **A1 — PAUSE** | **Implemented locally (2026-07-18)** — persistence, commands, projections, tests. **Not deployed.** Production deployment **forbidden** until Slice **A3** (READY_TO_SEND enforcement with `order_paused`). |
| **A2+** | **Not started** |

A1 deliverables present locally:

- append-only `order_operational_pause_events` (+ migration `order_operational_pause` v1)
- `OperationalCoreService.pause_order` / `resume_order`
- `POST /office/v1/orders/{id}/pause` and `/resume`
- Order Detail `operational_pause`; queue `pausiert` / `pausiert_top`
- domain events `OrderOperationalPaused` / `OrderOperationalResumed`

Explicitly **not** in A1 (pending later slices):

- authoritative Attention (A2)
- READY_TO_SEND / outbound send enforcement (A3+)
- OutboundSendService, transport, evidence, outbox (B*)
- `ready_to_send.py` changes

# PHASE_3B_KITCHEN_PRINT_AGENT_V1

Status: **accepted ADR — implementation not started**

Depends on: Slice 3A (`KitchenPrintJob` facts, repository, service) — **frozen**

Related: `PHASE_3_PRINT_ACK_ATTENTION_PACK_V1.md`, `PRINT_PROJECTION_SCOPE_V1.md`

Scope: Core API kitchen-agent contract, claim idempotency, immutable print
document delivery. No agent process, CUPS adapter, or Office UX in this slice.

---

## 1. Purpose

Slice 3B adds the **kitchen print agent API boundary** on top of existing
Phase 3A job facts. It answers:

1. Which job may the agent take?
2. How does the agent obtain an **immutable** print artifact?
3. How does the agent report technical rejection?
4. How does command replay return the same result?

It does **not** change Slice 3A domain facts, SQLite job triggers, or
`acknowledge_print_job()` / `kitchen_print_confirmed_at` semantics.

---

## 2. Layering

```text
Domain
 └── KitchenPrintJob              facts only (Slice 3A, frozen)

Application
 ├── KitchenPrintService          claim / accept / reject orchestration
 ├── KitchenPrintDocument         immutable claim snapshot (DTO)
 └── KitchenPrintDocumentFactory  resolve + render + hash

Infrastructure
 ├── KitchenPrintJobRepository    atomic claim_next_eligible()
 ├── Command ledger               idempotency (reuse office_api pattern)
 └── DocumentStore                persisted artifact by document_ref
```

### 2.1 `KitchenPrintDocument` — application DTO, not domain entity

The frozen print artifact is **not** a domain aggregate and **not** the primary
ledger object. Responsibilities stay separate:

| Concern | Owner |
|---|---|
| Command idempotency | `office_api_ledger` (`command_id`, fingerprint, stored response) |
| Print artifact lifecycle | `KitchenPrintDocument` + `DocumentStore` |

Suggested shape:

```python
@dataclass(frozen=True)
class KitchenPrintDocument:
    document_ref: str          # stable content address, e.g. sha256 hex
    print_job_id: str
    projection_hash: str       # canonical hash of resolved projection JSON
    content_type: str          # e.g. text/html; charset=utf-8
    body: bytes
    created_at: datetime
```

The ledger stores **references** (`document_ref`, job IDs, timestamps) in the
replay response body. Full `body` bytes live in `DocumentStore` keyed by
`document_ref`.

---

## 3. Mandatory invariants

```text
Invariant 1:
  Agent never confirms a business fact.
  Agent must not call acknowledge_print_job() or mutate
  OrderVersion.kitchen_print_confirmed_at.

Invariant 2:
  Every accepted print job has exactly one immutable print document
  once document creation completes.

Invariant 3:
  Replaying a claim command returns identical document_ref and payload
  (via command ledger + DocumentStore lookup).

Invariant 4:
  Kitchen print resolution never selects candidate/effective versions.
  Target is always the job's immutable order_version_id.

Invariant 5:
  OrderVersion.kitchen_print_confirmed_at changes only through
  acknowledge_print_job() (Office/human path).
```

---

## 4. Atomic claim — repository use case

Do **not** implement claim as `list_open_jobs()` followed by
`accept_print_job()`. That introduces a race window.

Add one repository operation:

```text
KitchenPrintJobRepository.claim_next_eligible(now, policy) -> KitchenPrintJob | None

BEGIN IMMEDIATE
  SELECT oldest eligible job
    WHERE acknowledged_at IS NULL
      AND rejected_at IS NULL
      AND superseded_at IS NULL
      AND accepted_at IS NULL
      AND accept_deadline_at > now
    ORDER BY accept_deadline_at ASC, requested_at ASC
    LIMIT 1
  IF none: COMMIT; return None
  UPDATE SET accepted_at = now, ack_deadline_at = now + acknowledgment_timeout
COMMIT
```

Cancellation is checked in the service layer before/after claim (owner Order
`cancelled_at`). Rejected path uses existing `reject_print_job()`.

---

## 5. Idempotency — command ledger only

Reuse the existing Office API pattern:

```text
command_id + command_fingerprint → ledger.get / ledger.record
```

Agent routes (`POST /kitchen/v1/print-jobs/claim-next`,
`POST /kitchen/v1/print-jobs/{id}/reject`) use the same envelope.

Do **not** add `claimed_by` or `agent_id` to `KitchenPrintJob`. Agent identity
is transport/auth (`KITCHEN_PRINT_AGENT_TOKEN`), not a persisted job fact.

Replay flow:

```text
Agent --command_id=abc--> Core API
                              |
                              +-- ledger hit → return stored response
                              +-- ledger miss → claim + document → record → return
```

---

## 6. Print resolution — `PrintIntent.kitchen_job`

Existing intents (`preview`, `change_preview`, `final`) are Office UI semantics.
Kitchen agent needs a distinct contract:

```text
"Production sheet for this exact OrderVersion"
```

```python
OrderPrintProjectionService.resolve(
    order_id,
    order_version_id,
    intent="kitchen_job",
)
```

### 6.1 Must use

- Requested `OrderVersion` event facts (date, time, location, guests, stand #)
- Frozen `OrderCommercialSnapshot` (positions, variant label)
- Order cancellation fact (`order_cancelled_at`) for STORNIERT banner only

### 6.2 Must not use

- Candidate / effective version **selection** (no "print the effective stand")
- UI watermark logic (`ENTWURF`, `VERALTET`, `ÄNDERUNG – NOCH NICHT WIRKSAM`)
- Preview semantics (`is_preview`, stale flags derived from live effective switch)

Implementation: extend `_resolve_flags()` with a `kitchen_job` branch that
returns stable flags for the job-bound version. Only operational safety banners
(e.g. cancelled order) remain.

---

## 7. Immutable document — flags hazard

`PrintFlagsBlock` today depends on **live** Order state. Re-fetching projection
after an effective-version switch can change watermarks for the same
`order_version_id`.

Therefore:

```text
claim-next
  → resolve(intent="kitchen_job")     # once
  → render → bytes                    # once
  → projection_hash + document_ref    # once
  → DocumentStore.save
  → ledger.record(response with refs)
```

Subsequent reads (replay, optional `GET .../document`) load from
`DocumentStore` by `document_ref`. Never re-render from live projection for an
accepted job.

---

## 8. Transaction boundary — MVP (Variant A)

Rendering inside a SQLite `BEGIN IMMEDIATE` is too slow (HTML/PDF generation).

**Slice 3B MVP:**

```text
BEGIN IMMEDIATE
  claim_next_eligible()   # sets accepted_at + ack_deadline_at
COMMIT

resolve(intent="kitchen_job")
render document
DocumentStore.save(document)
ledger.record(full response)
```

### 8.1 Attention state: accepted without document

Between COMMIT and DocumentStore.save, a crash leaves:

```text
accepted_at != null
document_ref == null
```

This is a **derived attention condition** (not a new persisted status column):

```text
derive: document_pending = accepted_at IS NOT NULL AND no DocumentStore entry
```

Office print-attention read (Slice 3C) surfaces this. Agent retry with the
same `command_id` completes idempotently once ledger + store exist.

### 8.2 Deferred (Variant B — later slice)

Explicit artifact lifecycle facts (`document_created_at`, `ready_for_print_at`)
or a separate `KitchenPrintArtifact` table. Not required for 3B MVP.

---

## 9. API contract (Slice 3B)

Auth: `KITCHEN_PRINT_AGENT_TOKEN` bearer. Office token cannot call agent routes.

### 9.1 Claim

```http
POST /kitchen/v1/print-jobs/claim-next
```

Request:

```json
{
  "command_id": "uuid"
}
```

Success response (first call and replay):

```json
{
  "command_id": "uuid",
  "print_job_id": "uuid",
  "order_id": "uuid",
  "order_version_id": "uuid",
  "accepted_at": "2026-08-08T11:00:00+00:00",
  "ack_deadline_at": "2026-08-08T11:05:00+00:00",
  "document_ref": "sha256:…",
  "document": {
    "content_type": "text/html; charset=utf-8",
    "body_base64": "…"
  }
}
```

Empty queue: `204` or structured `{ "job": null }` — pick one in contract tests
and freeze.

Optional later: `GET /kitchen/v1/print-jobs/{id}/document` for crash recovery
without replaying full body in ledger.

### 9.2 Reject

```http
POST /kitchen/v1/print-jobs/{print_job_id}/reject
```

```json
{
  "command_id": "uuid",
  "rejection_code": "printer_unavailable"
}
```

Allowlisted codes unchanged from Slice 3A domain.

### 9.3 ACK — explicitly out of agent scope

```text
Agent → physical print result → reject OR (success, no domain ACK)
Office → human confirmation → POST .../ack → acknowledge_print_job()
       → kitchen_print_confirmed_at
```

---

## 10. Application flow (3B)

```text
POST /kitchen/v1/print-jobs/claim-next
        |
        v
KitchenPrintService
        |
        +-- claim_next_eligible()          [repo, atomic]
        |
        +-- OrderPrintProjectionService
        |         .resolve(..., intent="kitchen_job")
        |
        +-- KitchenPrintDocumentFactory
        |         .create(projection) → KitchenPrintDocument
        |
        +-- DocumentStore.save(document)
        |
        +-- ledger.record(response)
        v
Agent → CUPS / lp adapter (Slice 3D, out of scope here)
```

Renderer for MVP: extract `render_print_sheet()` logic to an application-layer
function callable from Core API (HTML bytes). PDF rendering is a later deployment
slice.

---

## 11. Explicitly out of scope (3B)

- `kitchen_print_agent` systemd process (Slice 3D)
- CUPS / physical printer adapter (Slice 3F)
- Office Panel attention UX (Slice 3C)
- Changes to Slice 3A `KitchenPrintJob` fields or SQLite triggers
- Agent-side domain ACK or `kitchen_print_confirmed_at` mutation
- `claimed_by` / `agent_id` on job rows
- Heartbeat persistence to SQLite (in-process memory only, per Phase 3 pack)

---

## 12. Implementation order (PR: PHASE-3B-PRINT-AGENT-CONTRACT)

0. **Contract tests** — `tests/unit/test_kitchen_print_agent_contract.py` +
   `tests/helpers/kitchen_print_agent_contract.py` (reference boundary; 9 tests)
1. ADR + contract tests green against reference boundary
2. `claim_next_eligible()` on repository (+ in-memory mirror)
3. `PrintIntent.kitchen_job` + tests (no UI watermarks)
4. `KitchenPrintDocument` DTO + `KitchenPrintDocumentFactory` + `DocumentStore`
5. Kitchen-agent HTTP routes wired through command ledger
6. Integration tests: claim → document immutable on replay; accepted-without-
   document attention derivable

Contract helpers delegate to production once each slice lands; until then the
reference boundary encodes ADR invariants and must stay green.

No Slice 3A code changes unless a test-only seam is required.

---

## 13. Test obligations

| Test | Proves |
|---|---|
| `claim_next_eligible` atomic under contention | no double-accept |
| `kitchen_job` intent stable flags | Invariant 4 |
| same `command_id` → same `document_ref` + body | Invariant 3 |
| agent token cannot call office routes / vice versa | capability separation |
| agent cannot reach `acknowledge_print_job` | Invariant 1 |
| replay after crash mid-document-create | idempotent completion |
| `flags` not re-derived on document fetch | §7 immutability |

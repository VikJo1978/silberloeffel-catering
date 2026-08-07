# Delivery Execution Slice 6 V1

Design boundary for converting kitchen-completed orders into delivery execution
work without breaking the live courier feed or re-coupling commercial axes.

Related: [Architecture](../architecture.md) — Delivery execution boundary.

## 1. Scope

**Goal:**

> Start delivery execution from kitchen completion facts using frozen
> operational delivery data, without reading live Offer or Inquiry state.

Slice 6 proves one operational cycle:

```text
KitchenCompletionEvidence → DeliveryQueueProjection → DispatchEvidence → DeliveryCompletionEvidence
```

**Gate decision (variant A — parallel contours):**

Two delivery-related paths coexist:

```text
CURRENT LIVE (unchanged)

OrderVersion (effective)
    |
    v
Wochenübersicht
    |
    v
courier-app order feed (kiosk)


NEW CORE EXECUTION (Slice 6)

KitchenCompletionEvidence
    |
    v
DeliveryQueueProjection
    |
    v
DispatchEvidence
    |
    v
DeliveryCompletionEvidence
```

`READY_TO_SEND` and `KitchenCompletionEvidence` have different semantics:

| Fact | Meaning |
|------|---------|
| `READY_TO_SEND` | Operational release from commercial preparation |
| `KitchenCompletionEvidence` | Kitchen execution stage completed |

Switching the live courier feed to require `KitchenCompletionEvidence` would
change the business workflow (courier visibility would move from print/effective
release to post-kitchen completion). That is out of scope for Slice 6.

Migration of courier visibility to `DeliveryQueueProjection` is a **future
slice**, not part of Slice 6 implementation.

## 2. OrderDeliverySnapshot — operational delivery read model

Delivery execution must not read:

- live `Inquiry` data;
- live `OfferVersion` data;
- `OrderCommercialSnapshot` (commercial positions only).

`OrderCommercialSnapshot` answers **what was sold**. Delivery needs **where and
how to fulfill** — a separate responsibility.

Minimal frozen operational delivery snapshot (to be introduced in PR C):

```text
OrderDeliverySnapshot
---------------------

order_id
order_version_id

fulfillment_mode          -- DELIVERY | PICKUP (frozen at conversion)

delivery_address        -- structured, nullable for PICKUP
delivery_contact        -- optional operational contact hints

time_window_text        -- copied operational fact
location_text           -- copied operational fact

created_from            -- accepted_order_conversion
```

Three projection layers, three responsibilities:

```text
OrderCommercialSnapshot   → what we sell (commercial)
OrderPrintProjection      → what we produce (kitchen)
OrderDeliverySnapshot     → where/how we deliver (delivery)
```

The snapshot is created at offer conversion (or first effective delivery-relevant
version switch) and treated as immutable operational delivery truth for execution
consumers. Live Inquiry edits must not affect delivery queue membership or payload.

## 3. Input contract

Delivery Queue receives:

```text
Order
 └── effective OrderVersion
      └── KitchenCompletionEvidence (handoff gate)
      └── OrderDeliverySnapshot (frozen delivery facts)
      └── OrderVersion operational fields (time, location)
```

**Forbidden dependencies:**

```text
Delivery → OfferRepository
Delivery → Configurator
Delivery → live InquiryRepository reads
Delivery → OrderCommercialSnapshot (commercial positions)
```

## 4. Eligibility rule

`DeliveryQueueProjection` is derived, not stored.

Include an order only when all conditions hold:

- `KitchenCompletionEvidence` exists for the effective `order_version_id`;
- `OrderDeliverySnapshot.fulfillment_mode == DELIVERY` (exclude `PICKUP`);
- the order is not cancelled;
- no operational pause blocks execution (re-evaluate from current facts).

Do **not** persist:

```text
order.in_delivery_queue = true
```

Do **not** use live courier feed gates (`READY_TO_SEND` / Wochenübersicht
membership) as proof of delivery queue eligibility — they are parallel contours.

## 5. Execution facts

Future append-only evidence (PR C):

```python
DispatchEvidence(
    dispatch_evidence_id,
    order_id,
    order_version_id,
    dispatched_at,
    recorded_at,
    recorded_by,
    evidence_reference,
)

DeliveryCompletionEvidence(
    delivery_completion_evidence_id,
    order_id,
    order_version_id,
    completed_at,
    recorded_at,
    recorded_by,
    evidence_reference,
)
```

Rules (same pattern as `KitchenCompletionEvidence`):

- immutable after insert;
- append-only repository;
- one dispatch fact and one completion fact per `(order_id, order_version_id)`;
- idempotent replay for identical payloads;
- does not mutate `OrderVersion`, snapshots, or kitchen evidence.

## 6. Non-goals (Slice 6)

Do not include:

- courier-app rewrite or feed contract change;
- GPS tracking;
- route optimization;
- ETA / SLA;
- customer notifications;
- driver assignment (`DeliveryAssignmentEvidence` — courier-app axis);
- unified gate (variant B) switching live feed to kitchen completion;
- inventory, purchasing, mobile courier app.

## 7. Follow-up slices

| Slice | Deliverable |
|---|---|
| **PR B (tests)** | Contract tests: no kitchen completion → excluded; completion → included; PICKUP excluded; no Offer/Inquiry live reads |
| **PR C (domain)** | `OrderDeliverySnapshot`, `DeliveryQueueProjectionService`, `DispatchEvidence`, `DeliveryCompletionEvidence`, minimal Office API |
| **Future** | Courier feed v2 aligned with `DeliveryQueueProjection` (explicit migration slice) |

### PR B contract tests (planned)

1. **Kitchen not completed** — `READY_TO_SEND` without `KitchenCompletionEvidence` → not in delivery queue.
2. **Kitchen completed** — `KitchenCompletionEvidence` → delivery queue entry from frozen snapshot.
3. **PICKUP exclusion** — `fulfillment_mode=PICKUP` → not in delivery queue.
4. **Boundary guard** — static prohibition of `OfferRepository`, Configurator, live Inquiry access in delivery projection modules.

### End-to-end chain after Slice 6

```text
Offer → Order → READY_TO_SEND → Kitchen Queue → KitchenCompletionEvidence
  → DeliveryQueueProjection → DispatchEvidence → DeliveryCompletionEvidence
```

Each stage: **immutable fact → derived projection → append-only execution evidence**.

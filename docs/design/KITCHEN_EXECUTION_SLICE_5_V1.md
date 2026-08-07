# Kitchen Execution Slice 5 V1

Design boundary for converting released operational orders into kitchen execution
work without introducing new commercial coupling.

Related: [Architecture](../architecture.md) — Kitchen execution boundary.

## 1. Scope

**Goal:**

> Convert released operational orders into kitchen execution work without
> introducing new commercial coupling.

Slice 5 proves one operational cycle:

```text
READY_TO_SEND → Kitchen Queue projection → KitchenCompletionEvidence
```

Kitchen execution is a **consumer** of operational release facts. It is not a
new source of commercial truth and does not redefine Offer, Order, or
READY_TO_SEND semantics established in Slices 1–4.

`ProductionTask` and other orchestration abstractions are **out of scope** for
this slice. Queue membership and completion evidence are sufficient to validate
the first execution boundary.

## 2. Input contract

Kitchen Queue receives operational read data shaped as:

```text
Order
 └── effective OrderVersion
      └── OrderPrintProjection
           └── OrderCommercialSnapshot
```

`OrderPrintProjectionService.resolve()` is the only approved source for kitchen
queue payload (event facts + frozen commercial positions).

**Forbidden dependencies:**

```text
Kitchen → OfferRepository
Kitchen → Configurator
Kitchen → live catalog prices
```

Kitchen execution must not read live `OfferVersion` data or re-derive commercial
content from the Offer write model.

## 3. Eligibility rule

Queue membership is a **derived projection**, not a stored order flag.

Include an order only when all conditions hold:

- `evaluate_ready_to_send().ready` is true;
- an effective `OrderVersion` exists;
- kitchen print is confirmed on the effective version;
- `OrderCommercialSnapshot` exists for the order;
- the order is not cancelled;
- no operational pause blocks execution.

Do **not** persist:

```text
order.ready_to_send = true
```

Eligibility must be re-evaluated from current facts on each queue read. Prior
`OrderReadyToSend` events or `POST /ready` calls are not trusted as queue
membership proof.

## 4. Execution facts

Future append-only evidence (not implemented in Slice 5 docs PR):

```python
KitchenCompletionEvidence(
    order_id,
    order_version_id,
    completed_at,
    recorded_by,
    evidence_reference,
)
```

Rules:

- immutable after insert;
- append-only repository (no update/delete);
- duplicate completion rejected or handled idempotently;
- does not mutate `OrderVersion` or `OrderCommercialSnapshot`;
- does not rewrite historical commercial facts.

Completion records **what happened in kitchen execution**. It does not change
what was accepted commercially or what was released operationally.

## 5. Non-goals (Slice 5)

Do not include in this slice:

- Courier routing or delivery execution;
- ETA or SLA calculations;
- route optimization;
- customer notifications;
- production groups;
- inventory or purchasing;
- kitchen planning algorithms;
- `ProductionTask` entity or workflow engine;
- wiring of `KitchenPrintService` (Slice 3A / print-ACK — separate track);
- redesign of `Wochenuebersicht` (may reuse date filters later, different
  membership semantics).

## 6. Follow-up slices (planned)

| Slice | Deliverable |
|---|---|
| **PR B (tests)** | Contract tests: not-ready excluded; ready included; projection-only render |
| **PR C (domain)** | `KitchenQueueProjectionService`, `KitchenCompletionEvidence`, minimal API |

After Slice 5 is proven:

```text
KitchenCompletionEvidence
        |
        v
Courier / Delivery (next execution layer)
```

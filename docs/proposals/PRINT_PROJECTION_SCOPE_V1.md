# Print Projection Scope V1

Status: **design proposal only — no production code authorized**

Evidence baseline: repository state after slice **6B-1** (Änderung workflow polish), 2026-07-16, Europe/Berlin

Scope owner: shared read layer for **Küchenzettel v2** (6C-1) and **Buffetschilder** (6C-2)

---

## 1. Purpose

Define a single **read-only print projection** that combines:

- **Operational event facts** from a specific `OrderVersion` (what/when/where for this stand)
- **Commercial dish data** from the accepted Offer variant (what to prepare / show on buffet cards)

Print materials are **not operational truth**. They are derived views. The existing lifecycle remains unchanged:

```text
OrderVersion (event facts)
  → kitchen print confirm
  → effective
  → READY_TO_SEND
```

This document fixes the data contract and resolution rules before any renderer or API work in 6C-1 / 6C-2.

---

## 2. Frozen constraints (must not change in 6C)

| Area | Rule |
|---|---|
| `OrderVersion` | No new fields; no positions; no in-place edit |
| Candidate / effective | Existing semantics; candidate = office hint; effective = Küchenstand |
| `READY_TO_SEND` | Unchanged gate |
| Payment reminder | Separate axis; not a print blocker |
| `KitchenPrintJob` (Slice 3A) | Separate workflow; do not merge with Office browser print without explicit later pack |
| Operational truth | Only Order / OrderVersion facts + existing Core commands |

---

## 3. Current state (audit)

### 3.1 What exists today

| Layer | Content |
|---|---|
| `OrderVersion` | `event_date`, `time_window_text`, `location_text`, `guest_count_estimate`, `planning_mode`, `kitchen_print_confirmed_at` |
| `Order` | `candidate_order_version_id`, `effective_order_version_id`, `cancelled_at`, `source_inquiry_id` |
| `Offer` / `OfferVersion` | Immutable commercial snapshot: variants, positions (money + name), event + payment fields, `snapshot_id`, `snapshot_hash` |
| `ConversionLink` | `offer_id`, `offer_version_id`, `variant_id`, `acceptance_id`, `order_id`, `created_at` — one row per Offer, append-only |
| `OfferSnapshotPosition` (transport) | Full customer-visible line: `name`, `description`, `composition`, `notes`, `quantity`, `quantity_mode`, `unit_label`, `catalog_item_id`, money fields |
| Persisted `OfferPosition` | **Subset only:** `name`, money, `kind`, `related_position_id` — **drops** description/composition/notes/quantity |
| Print today | `render_print_sheet()` — event facts only, browser print, any owned `?version=` |

### 3.2 Resolution path (Offer-backed orders)

```text
Order.order_id
  → Order.source_inquiry_id
  → OfferRepository.get_by_source_inquiry_id(inquiry_id)
  → Offer.conversion_link (must exist; order_id must match)
  → OfferVersion(offer_version_id from link)
  → OfferVariant(variant_id from link)
  → positions[]
```

There is **no** `Order → Offer` foreign key on the Order row. The link is commercial (`ConversionLink`), not operational.

### 3.3 Änderung vs menu (critical gap)

`create_relevant_order_change_version` updates **event facts only**. Accepted variant positions stay on the **converted OfferVersion** forever.

Therefore print projection **must join two sources**:

| Print section | Source |
|---|---|
| Header (date, time, place, guests, stand #) | Requested `OrderVersion` |
| Dish list | `ConversionLink` → accepted variant (unchanged by OrderVersion v2+) |

An OrderVersion change without a new commercial Offer does **not** change the menu on printouts. That is correct for V1 and must be documented in UI.

---

## 4. `OrderPrintProjection` — target read model

Pure read type (domain or service layer — no UI). Suggested name: `PrintProjection`.

### 4.1 `event` block

Operational context for the **requested** OrderVersion:

| Field | Source |
|---|---|
| `order_id` | `Order` |
| `order_version_id` | Requested version |
| `version_number` | `OrderVersion.version_number` |
| `event_date` | `OrderVersion.event_date` |
| `time_window_text` | `OrderVersion.time_window_text` |
| `location_text` | `OrderVersion.location_text` |
| `guest_count_estimate` | `OrderVersion.guest_count_estimate` |
| `planning_mode` | `OrderVersion.planning_mode` |
| `kitchen_print_confirmed_at` | `OrderVersion` (nullable) |
| `order_cancelled_at` | `Order.cancelled_at` (nullable) |
| `is_candidate` | `order_version_id == candidate_order_version_id` |
| `is_effective` | `order_version_id == effective_order_version_id` |

### 4.2 `commercial` block

Nullable when no Offer conversion exists.

| Field | Source |
|---|---|
| `source` | `"offer_conversion"` \| `"none"` |
| `offer_id` | `ConversionLink.offer_id` |
| `offer_version_id` | `ConversionLink.offer_version_id` |
| `accepted_variant_id` | `ConversionLink.variant_id` |
| `variant_label` | `OfferVariant.label` |
| `snapshot_id` | `OfferVersion.snapshot_id` |
| `snapshot_hash` | `OfferVersion.snapshot_hash` |
| `positions` | Accepted variant positions (see §6) |
| `conversion_created_at` | `ConversionLink.created_at` |

### 4.3 `print_flags` block

Derived at resolve time; never stored.

| Flag | Meaning |
|---|---|
| `intent` | `preview` \| `final` (caller-selected mode) |
| `is_preview` | `intent == preview` OR (intent final but version not effective — see policy) |
| `is_final_allowed` | Whether this version may be printed as final output |
| `is_stale` | Version is outdated for final guest-facing use |
| `watermark` | `null` \| `"ENTWURF"` \| `"VERALTET"` |
| `footer_technical` | Optional internal line: order id short, stand #, event date |

### 4.4 `PrintPosition` (per dish line)

V1 projection line — not a new persisted entity:

| Field | V1 | Later |
|---|---|---|
| `position_id` | ✓ | |
| `kind` | ✓ (`catalog`, `surcharge`, `fee`, `custom`) | |
| `name` | ✓ required | |
| `quantity_display` | ✓ if persisted | derived from quantity + mode + guests |
| `unit_label` | optional | |
| `description` | optional short text | |
| `composition` | optional (Zutaten / Inhalt) | |
| `notes` | optional (Küchenhinweis per line) | |
| `catalog_item_id` | traceability only; never dereferenced in V1 | |
| `allergens` | — | catalog phase |
| `vegetarian` / `vegan` | — | catalog phase |
| `production_group` | — | catalog phase |

---

## 5. Storage decision (A / B / C)

### Option A — Read Offer aggregate at print time

**Mechanism:** `Order → ConversionLink → OfferVersion → variant.positions`

| Pros | Cons |
|---|---|
| No new tables | Today only `name` + money survive persistence |
| ConversionLink already pins the correct variant | `description` / `composition` / `notes` / quantity **lost** in `_map_position()` and SQLite |
| Offer rows are immutable (SQLite triggers) | Variant `description` from snapshot also dropped |
| Matches commercial truth boundary | Buffetschilder V1 would be name-only without a fix |

**Verdict:** Required as the **read path**, insufficient alone for V1 quality.

### Option B — Immutable commercial snapshot at conversion

**Mechanism:** New persisted envelope at `convert_accepted_offer`, e.g. `order_print_commercial_snapshot_v1`, keyed by `order_id`.

| Pros | Cons |
|---|---|
| Print data frozen even if Offer lookup breaks | **Duplicates** data already on OfferVersion |
| Clear audit trail at conversion instant | New persistence + migration; must define replay/idempotency on convert |
| Could store full snapshot JSON | Second commercial copy to keep in sync with Offer contract |
| | Still not OrderVersion truth — but easy to confuse operationally |

**Verdict:** Overkill while `ConversionLink` + immutable OfferVersion already exist. Revisit only if Offer aggregate is ever purged (not planned).

### Option C — Extend persisted `OfferPosition` (+ variant text)

**Mechanism:** Persist snapshot text fields when `prepare_offer_version` maps `OfferSnapshotPosition → OfferPosition`; extend SQLite `offer_positions` and domain type.

| Pros | Cons |
|---|---|
| Fixes root cause (mapping gap) | Requires migration + backfill policy for existing rows |
| Single commercial source | Immutability triggers allow INSERT only on new OfferVersion — **existing converted offers stay name-only until re-prepare** (impossible after acceptance) |
| Option A read path unchanged | Must extend `_map_position`, repository load/save |
| Aligns with `offer_contract_v1` position semantics | |

**Verdict:** **Recommended persistence fix** for V1. Not a change to OrderVersion.

### Chosen architecture

```text
Read path:     A  (Offer aggregate via ConversionLink)
Persistence:   C  (extend OfferPosition + OfferVariant description at prepare time)
Not chosen:    B  (separate conversion snapshot table)
```

**Important:** Positions remain **commercial** facts on Offer, not on OrderVersion. Print projection **joins** commercial + operational at read time.

---

## 6. Minimum V1 print fields

### 6.1 Küchenzettel v2 (6C-1)

| Field | Required V1 | Notes |
|---|---|---|
| Event facts | ✓ | Already on OrderVersion |
| Stand # / version | ✓ | |
| Order short ref | optional footer | |
| Position `name` | ✓ | Kitchen needs dish list |
| `kind` | ✓ | Filter display (hide `fee`? product decision) |
| `quantity_display` | ✓ when available | Küche needs counts |
| `composition` | strongly recommended | CONFIGURATOR pack gap |
| `notes` | optional | Per-line kitchen hints |
| `description` | optional | Short; lower priority than composition |
| Money fields | **out of scope** | Not kitchen print |
| Allergens / vegan / production group | **defer** | Catalog phase |

### 6.2 Buffetschilder (6C-2)

| Field | Required V1 | Notes |
|---|---|---|
| `name` | ✓ | Guest-facing |
| `description` | ✓ if present | Short guest text |
| `composition` | ✓ if present | Allergen proxy until structured allergens |
| Allergens (structured) | defer | Catalog / snapshot contract extension |
| Vegan / vegetarian markers | defer | Catalog phase |
| `quantity_display` | optional on card | Often omitted on buffet cards |
| Event date on card | ✓ footer | From OrderVersion |
| Stand / Entwurf / Veraltet | ✓ | See §8 |

### 6.3 Catalog phase (explicit non-goals for 6C V1)

- Structured allergen list
- Vegetarian / vegan badges
- Production group / kitchen routing
- Live catalog dereference by `catalog_item_id`
- PDF engine (browser print + CSS remains sufficient)

---

## 7. Conversion boundary

### 7.1 Flow today

```text
Offer accepted (AcceptanceEvidence)
      ↓
convert_accepted_offer
      ↓
Order + OrderVersion v1 (event facts from OfferVersion)
ConversionLink (offer_version_id + variant_id + acceptance_id)
Payment reminder seeded from Offer payment method
Inquiry → Bestätigt / Auftrag
```

**What crosses the boundary:**

| Data | Copied to Order? | Available for print via |
|---|---|---|
| Event facts | ✓ OrderVersion v1 | OrderVersion (any stand) |
| Positions / menu | ✗ | ConversionLink → Offer variant |
| Prices | ✗ | Offer (not needed for kitchen/buffet V1) |
| Payment method | ✓ payment reminder | Not print |

### 7.2 Risks (audited)

| Risk | Current behavior | Print impact |
|---|---|---|
| Angebot changed after conversion | **Impossible** — accepted OfferVersion closed forever; no new OfferVersion while Order active | Safe: ConversionLink pins frozen version |
| Offer deleted | **Impossible** — SQLite immutability; no delete API | Safe |
| OfferVersion unavailable | Offer aggregate load fails | Projection: `commercial.source = none`, positions `[]`, explicit warning |
| ConversionLink / Order mismatch | Domain guards on convert; idempotent replay | Must validate `link.order_id == order_id` on resolve |
| New OrderVersion (Änderung) | Event facts only | Header updates; menu stays at conversion variant |
| Legacy inquiry convert (no Offer) | No ConversionLink | Event-only print; empty commercial block |
| Order Storno | `cancelled_at` set | Print allowed read-only with STORNIERT banner (existing) |

---

## 8. Preview / Final / Stale policy

### 8.1 Version selection

Office passes:

- `order_id`
- `order_version_id` (explicit stand)
- `intent`: `preview` | `final`

Default when opening from Order detail next step: **candidate if set, else highest `version_number`** (same as `resolve_next_action`).

### 8.2 Preview

| Rule | Value |
|---|---|
| Allowed versions | Any owned, non-cancelled OrderVersion |
| Typical use | Candidate / latest stand before effective switch |
| Watermark | **`ENTWURF`** when `order_version_id != effective_order_version_id` |
| Küchenzettel | Allowed — kitchen must print before confirm |
| Buffetschilder | Allowed for office rehearsal; not guest-facing final |

### 8.3 Final

| Rule | Value |
|---|---|
| Allowed versions | **`order_version_id == effective_order_version_id` only** |
| Buffetschilder | Hard gate for final route |
| Küchenzettel | Final reprint of effective stand (reprint allowed, idempotent read) |
| Watermark | None |
| API behavior on violation | `422 print_final_requires_effective` (suggested) |

### 8.4 Stale

A version is **`stale`** when:

- `intent == final` AND `order_version_id != effective_order_version_id`, OR
- A **new** effective stand exists AND user opens an older stand with `intent == final`

UI/API for stale:

| Surface | Behavior |
|---|---|
| Preview route with old stand | Show **`VERALTET`** banner + effective stand number; still allow read |
| Final route with old stand | **Reject** (422) |
| After effective switch | Previous printed buffet set is logically outdated; footer shows current effective stand # |

**Not stale:** candidate preview of a not-yet-effective stand while an older stand is still effective — that is normal Änderung workflow (`ENTWURF`, not `VERALTET`).

### 8.5 Footer marking (V1)

Recommended on every print page:

```text
Auftrag · Stand {n} · {event_date}
[ENTWURF | VERALTET | wirksamer Stand {m}]
```

Optional technical footer (office only, not guest cards): short `order_id` prefix.

---

## 9. Legacy orders

| Case | Commercial block | Küchenzettel V1 | Buffetschilder V1 |
|---|---|---|---|
| Legacy inquiry convert (no Offer) | `source: none`, `positions: []` | Event facts only (as today) | Not available — show explicit «Kein Menü hinterlegt» |
| Offer exists but not converted | No ConversionLink | Same as legacy | N/A (no Order yet) |
| Converted Offer, positions name-only (pre-migration) | Partial | Name list only | Cards with name only + warning «Zusatztexte fehlen» |
| Cancelled order | Event + commercial read still allowed | STORNIERT banner | STORNIERT banner |

No retroactive menu invention. Legacy completeness is a **data gap**, not a projection bug.

---

## 10. Shared service contract

Suggested module: `src/catering_system/services/order_print_projection_service.py`

No UI imports. Pure read service.

```python
PrintIntent = Literal["preview", "final"]

@dataclass(frozen=True)
class PrintProjection:
    event: PrintEventBlock
    commercial: PrintCommercialBlock | None
    flags: PrintFlagsBlock


def resolve_print_projection(
    order_id: str,
    order_version_id: str,
    *,
    intent: PrintIntent,
) -> PrintProjection:
    ...
```

### 10.1 Resolution steps

1. Load `Order`; fail `not_found` if missing.
2. Load `OrderVersion`; fail `not_found` / `version_not_owned`.
3. Build `event` block + `is_candidate` / `is_effective`.
4. Resolve commercial:
   - `offer = offer_repo.get_by_source_inquiry_id(order.source_inquiry_id)`
   - If `offer?.conversion_link?.order_id == order_id`: load variant positions
   - Else: `commercial = None`
5. Compute `flags` from `intent`, effective/candidate/stale rules (§8).
6. If `intent == final` and not `is_final_allowed`: raise `PrintProjectionError` (domain) → API `422`.

### 10.2 Consumers (no shared HTML)

| Consumer | Uses |
|---|---|
| `render_print_sheet` v2 (6C-1) | `event` + positions (kitchen layout) |
| `render_buffet_cards` (6C-2) | `event` + positions (guest layout) + flags/watermark |
| `GET …/print-data` (remote) | JSON shape mirroring `PrintProjection` |
| Future: `GET …/buffet-cards-data` | Same projection, different renderer |

Renderers **must not** reimplement join logic.

### 10.3 Suggested API additions (6C-1 / 6C-2 — not in 6C-0)

| Route | Purpose |
|---|---|
| `GET /office/v1/orders/{id}/print-projection?version=&intent=` | Frozen JSON for remote parity |
| `GET /office/v1/orders/{id}/buffet-cards-data?version=&intent=` | Same projection; renderer-specific view optional |

Panel routes remain read-only GET + browser print.

---

## 11. Dependencies

### 11.1 Before 6C-1 (Küchenzettel v2)

| Step | Slice | Deliverable |
|---|---|---|
| **6C-0** | This document | Frozen scope ✓ |
| **6C-0p** | Offer position persistence | Extend `OfferPosition` + SQLite + `_map_position` with `description`, `composition`, `notes`, `quantity`, `quantity_mode`, `unit_label`; variant `description` |
| **6C-1a** | Projection service | `order_print_projection_service.py` + unit tests |
| **6C-1b** | Renderer + route | Enriched `render_print_sheet`; preview/final flags; optional `print-projection` API |

6C-0p can ship as a small migration slice immediately before 6C-1. It does **not** touch OrderVersion.

### 11.2 Before 6C-2 (Buffetschilder)

| Dependency | Reason |
|---|---|
| 6C-0p persistence | Guest-facing text |
| 6C-1a projection service | Reuse join + flags |
| Final-only gate (§8.3) | Stale prevention |
| CSS print layout (A6/A5) | Separate renderer; same projection |

6C-2 **must not** fork commercial join logic.

### 11.3 Parallel / unchanged

- 6B Änderung workflow (done) — event header changes without menu changes
- KitchenPrintJob 3A — out of scope
- Payment, READY_TO_SEND, effective/candidate commands — unchanged

---

## 12. Explicit non-goals (6C wave)

- New fields on `OrderVersion`
- Positions stored on Order
- Catalog DB or live catalog reads
- Structured allergens / vegan / production groups in V1
- PDF generation library
- KitchenPrintJob integration
- Kiosk write paths
- Retroactive backfill of text fields for already-converted Offers (unless owner accepts one-off migration script — open question)
- In-place edit of effective version

---

## 13. Open questions

1. **Backfill:** Existing converted Offers have name-only positions. Accept degraded V1 print, or run a one-time migration from archived snapshot JSON (if stored externally — **not in Core today**)?
2. **Küchenzettel final gate:** Should Küchenzettel enforce `intent=final` only on effective, or allow print-confirm flow to keep using preview intent until confirm? **Proposal:** keep preview for confirm workflow; add final gate only for Buffetschilder + optional «official reprint».
3. **Position filtering:** Show `fee` / `surcharge` lines on kitchen sheet and buffet cards, or `kind=catalog` only? Needs owner input.
4. **Variant label on print:** Show accepted variant label (e.g. «Buffet Premium») in header?
5. **Guest count on quantity:** Recompute `quantity_display` from `quantity_mode=per_person` using **OrderVersion.guest_count_estimate** (may differ from Offer snapshot guest count after Änderung). **Proposal:** use OrderVersion guest count for display recompute.
6. **API naming:** Single `print-projection` endpoint vs separate print-data extensions — decide in 6C-1 implementation pack.

---

## 14. Summary

| Decision | Choice |
|---|---|
| Architecture | **A + C:** read Offer via ConversionLink; extend Offer persistence for text/quantity |
| Not chosen | B (conversion snapshot table); OrderVersion positions; catalog dereference |
| Join model | OrderVersion (event) + ConversionLink variant (menu) |
| V1 dish minimum | `name` + `quantity_display` + `composition`/`description` where persisted |
| Preview | Any stand; `ENTWURF` when not effective |
| Final | Effective stand only (strict for Buffetschilder) |
| Stale | Old effective after switch; block final, warn on preview |
| Legacy | Event-only print; honest empty menu |
| Shared module | `order_print_projection_service.resolve_print_projection()` |
| Next code slices | **6C-0p** persistence → **6C-1** Küchenzettel → **6C-2** Buffetschilder |

---

## 15. Key files (reference for implementers)

| Area | Path |
|---|---|
| Order domain | `src/catering_system/domain/order.py` |
| Offer domain | `src/catering_system/domain/offer.py` |
| Snapshot transport | `src/catering_system/domain/offer_snapshot.py` |
| Snapshot → Offer map | `src/catering_system/services/offer_service.py` (`_map_position`) |
| Conversion | `src/catering_system/services/offer_service.py` (`convert_accepted_offer`) |
| Offer SQLite | `src/catering_system/repositories/sqlite_offer_repository.py` |
| Current print | `src/catering_system/ui/office_panel_views.py` (`render_print_sheet`) |
| Print API read | `src/catering_system/ui/office_api.py` (`print_data`) |
| Commercial contract | `docs/proposals/offer_contract_v1.md` |
| Configurator gap note | `docs/archive/packs/CONFIGURATOR_EXECUTION_PACK_V1.md` |

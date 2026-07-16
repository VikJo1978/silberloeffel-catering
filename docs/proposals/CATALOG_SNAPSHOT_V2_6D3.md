# 6D-3 — Offer Snapshot V2 + Catalog Adapter (design pack)

Status: **design proposal only — no production code authorized until approved**  
Prerequisite: `CATALOG_SCOPE_V1.md` (6D-0), **6D-1** (`c8662ad`), **6D-2** (`d91c84c Add catalog editing and price history`)  
Scope owner: **Commercial snapshot boundary** — Catalog → OfferPosition freeze at `prepare-offer`  
Next slice: **6E** Buffetschilder allergen badges (print reads snapshotted OfferPosition only)

Delivered in two implementation commits (recommended):

| Sub-slice | Goal |
|---|---|
| **6D-3a** | Core accepts `offer_snapshot_v2`; persist extended OfferPosition; Configurator **Catalog adapter** with `items.json` fallback |
| **6D-3b** | Remove Configurator runtime dependency on `items.json` for catalog lines |

---

## 1. Purpose

Close the gap between **live Stammdaten** (Catalog) and **immutable commercial truth** (Offer / Order / Print):

```text
Today (until 6D-3):

  items.json  ──►  Configurator  ──►  OfferSnapshot v1  ──►  OfferPosition
                                              │
                                              └── catalog_item_id lost on persist

Target (after 6D-3):

  CatalogDish  ──►  Configurator (read API)  ──►  OfferSnapshot v2  ──►  OfferPosition
        │                                              │
        │                                              └── frozen copy at prepare-offer
        └── Büro-owned (6D-2)
```

Goals:

- At **Angebot creation**, copy dish Stammdaten + commercial line fields into an immutable snapshot.
- Persist `catalog_item_id` (Catalog `dish_id`) and allergen codes on `OfferPosition`.
- Keep **all existing Offers, Orders, and Print** unchanged (no backfill, no live Catalog join).
- Migrate Configurator catalog source without breaking Angebot creation during rollout.

Non-goals (6D-3):

- Order / OrderVersion schema or behaviour changes
- Live Catalog lookup from Order detail or Print projection (forbidden — see §2)
- Buffetschilder / Küchenzettel allergen UI (6E — needs snapshotted fields first)
- Retroactive rewrite of legacy OfferPosition rows
- Catalog `create-dish` API or new Büro workflows
- Automatic recalculation of open Offers when Catalog changes

---

## 2. Frozen constraints

| Rule | Rationale |
|---|---|
| **Snapshot at prepare-offer only** | Commercial truth is fixed when Core accepts `prepare-offer` |
| **No Order → Catalog** | Operational event must not dereference live Stammdaten |
| **No Print → Catalog** | Küchenzettel / Buffetschilder read OfferPosition via OrderPrintProjection (6C) |
| **V1 + V2 coexist** | Strict validation per `schema_version`; legacy payloads unchanged |
| **Legacy NULL ≠ empty list** | `allergens = null` means *nicht bekannt*, not *keine Allergene* (§6) |
| **No backfill** | Existing SQLite rows keep NULL new columns; behaviour via read semantics |
| **Price from snapshot** | OfferPosition stores cents copied at ingest; Catalog price changes affect **new** offers only |
| **Allergen codes A–N** | Same dictionary as Catalog; no free text on snapshot |
| **`active=false` gate at compose** | Inactive dishes must not appear in **new** configurator selections (§8) |

### 2.1 Forbidden pattern (never implement)

```text
Order / OrderVersion
        ↓ live JOIN
CatalogDish
        ↓
Allergens on Küchenzettel / Buffetschilder   ❌
```

Example failure mode:

```text
Auftrag 2024: Nudelsalat — Allergen A
Catalog 2026: Nudelsalat — Allergene A, G
```

Live lookup would mutate the legal/commercial document retroactively.

---

## 3. Current implementation baseline

Authoritative as of `d91c84c`:

### 3.1 CatalogDish (Core)

```text
dish_id, name, description, composition, notes
current_unit_net_cents, allergens (A–N), active
created_at, updated_at
```

No `vegan`, `vegetarian`, `vat_rate_percent` on Catalog today.

### 3.2 OfferSnapshot V1 (wire)

- `OfferSnapshotPosition` already accepts optional `catalog_item_id`, `description`, `composition`, `notes` on the wire.
- Validation in `offer_snapshot_validation.py`; hash in `offer_snapshot.py`.

### 3.3 OfferPosition (persisted)

- Stores `description`, `composition`, `notes`, quantity fields (6C-0p).
- Does **not** persist `catalog_item_id`, `allergens`, `vegan`, `vegetarian`.
- `_map_position()` in `offer_service.py` drops `catalog_item_id`.

### 3.4 Configurator (external)

```text
items.json  →  compose  →  calculate  →  OfferSnapshot v1  →  POST prepare-offer
```

Still the runtime catalog source until 6D-3a adapter lands.

---

## 4. Target data flow

### 4.1 Configurator (after 6D-3a)

```text
GET /office/v1/catalog/dishes          (list, active dishes)
GET /office/v1/catalog/dishes/{id}       (detail for compose)
GET /office/v1/catalog/allergen-codes  (labels)

        ↓ user selects dish lines

Catalog Adapter builds position draft from CatalogDish fields

        ↓ calculator (unchanged tax/quantity logic)

OfferSnapshot v2 JSON

        ↓ POST prepare-offer (unchanged command)

Core validate → map → persist OfferPosition (extended)
```

### 4.2 Büro path (unchanged mechanism)

Manual / test `prepare-offer` with v2 snapshot body — same mapping rules as Configurator output.

---

## 5. Sub-slices: 6D-3a vs 6D-3b

### 5.1 6D-3a — Catalog adapter + Core V2 (minimum shippable)

**Core:**

- Accept `schema_version: "offer_snapshot_v2"`.
- Extend validation + `_map_position()` + SQLite `offer_positions` columns.
- V1 path untouched.

**Configurator:**

- Read Catalog via Office API (Bearer token — same as remote panel).
- Build catalog lines from `CatalogDish` fields.
- **Fallback:** if Catalog unreachable or dish missing → use local `items.json` row for that line only (log + metric; do not block entire Angebot).

**Explicitly not in 6D-3a:**

- Deleting `items.json` from repo or deploy bundle
- Requiring Catalog for non-catalog position kinds (`fee`, `custom`, `surcharge`)

### 5.2 6D-3b — Remove items.json runtime (follow-up)

- Configurator catalog UI reads Catalog only.
- `items.json` retained as **migration/seed source** for Core (`seed_catalog_from_items.py`), not compose runtime.
- Fallback removed or reduced to explicit offline-dev flag.

Separate commit; do not mix with 6D-3a Core schema work.

---

## 6. Snapshot V2 — position shape

### 6.1 New / extended fields (catalog lines)

When `kind === "catalog"`:

| Field | Type | Source at compose | Persisted on OfferPosition |
|---|---|---|---|
| `catalog_item_id` | UUID string | **Required** — Catalog `dish_id` | **Yes** (new column) |
| `name` | string | Catalog (+ override rules below) | Yes (existing) |
| `description` | string \| null | Catalog | Yes (existing) |
| `composition` | string \| null | Catalog | Yes (existing) |
| `notes` | string \| null | Catalog or configurator line note | Yes (existing) |
| `unit_net_cents` | int | Catalog `current_unit_net_cents` at compose time¹ | Yes (existing) |
| `quantity`, `quantity_mode`, `unit_label` | — | Configurator calculator | Yes (existing) |
| VAT totals | cents | Configurator calculator | Yes (existing) |
| `allergens` | string[] | Catalog `allergens` (A–N, sorted unique) | **Yes** (new JSON column) |
| `vegan` | bool \| null | See §7.3 | **Yes** (new nullable column) |
| `vegetarian` | bool \| null | See §7.3 | **Yes** (new nullable column) |

¹ Calculator may apply quantity; **unit** price must match Catalog at snapshot build unless explicit override policy is added later (default: **no override** — Catalog unit net is authoritative for catalog lines).

Non-catalog kinds (`fee`, `custom`, `surcharge`): V2 fields optional / omitted; V1 rules unchanged.

### 6.2 Envelope

```json
{
  "schema_version": "offer_snapshot_v2",
  "...": "same top-level keys as v1"
}
```

- Hash algorithm unchanged; canonical JSON includes new position keys when present.
- `calculator.catalog_revision` should reference Catalog snapshot identity (e.g. dish `updated_at` max or fixed `"core-catalog-v1"`) — exact string frozen in 6D-3a implementation docstring.

### 6.3 Validation rules (V2 additions)

- If `kind === "catalog"`: `catalog_item_id` **required**, must be valid UUID.
- If `allergens` present: each code ∈ A–N, sorted unique (match Catalog normalisation).
- If `allergens` omitted on catalog line → treat as validation error in V2 (compose must send explicit list, may be `[]` only when Catalog has empty allergens).
- V1 payloads: allergen keys forbidden / ignored per existing strict key sets.

---

## 7. Semantic decisions (frozen)

### 7.1 Legacy OfferPosition — allergens NULL

```text
allergens IS NULL   →  "nicht bekannt"  (unknown at snapshot time)
allergens = []      →  "keine deklarierten Allergene zum Snapshot-Zeitpunkt"
allergens = ["G"]   →  explicit snapshot fact
```

Print / UI (6E) must **not** render "keine Allergene" for NULL.

### 7.2 Catalog change after Offer exists

```text
CatalogDish.price     850 → 900
Existing OfferPosition     stays 850
New prepare-offer          copies 900
```

Already proven in 6D-2 regression; 6D-3 extends to allergens and text fields.

### 7.3 vegan / vegetarian (deferred detail)

CatalogDish **does not** carry these flags today.

**6D-3a default:**

- Snapshot V2 allows optional `vegan`, `vegetarian` on positions.
- Catalog adapter sets **`null`** for both when sourcing from Catalog.
- Configurator may set explicit bools on **custom** lines; catalog lines stay `null` until Catalog gains fields (future slice, no 6D-3 schema break).

Do **not** invent vegan/vegetarian on Catalog in 6D-3 unless explicitly approved in implementation review.

### 7.4 active=false at compose time

When Configurator loads Catalog list:

- Default list: `active_only=true` (or filter client-side).
- Inactive dish must not be selectable for **new** lines.
- Existing Offers referencing inactive dish via old snapshot: **unchanged** (immutable).

Büro may re-activate dish in Verwaltung; new Angebote then see it again.

---

### 7.5 `catalog_item_id` ownership (frozen)

`OfferPosition.catalog_item_id` is a **traceability anchor** to the Catalog dish that was copied at snapshot time — **not** a live foreign key.

```text
catalog_item_id = dish_id at prepare-offer moment
```

Rules:

| Situation | OfferPosition.catalog_item_id |
|---|---|
| Dish later `active=false` | **Unchanged** — historical Offers keep the id |
| Dish renamed / price changed in Catalog | **Unchanged** — snapshot fields are frozen |
| Dish absent from future Catalog list | **Unchanged** — id may point to row Büro still has in DB |
| Live Order / Print lookup via this id | **Forbidden** — never JOIN Catalog at read time |

Purpose: audit ("which Stammdaten row was snapshotted?"), not runtime composition.

Configurator and Core must set `catalog_item_id` on every V2 `kind=catalog` line. Legacy V1 rows remain `NULL`.

---

## 8. Core changes (6D-3a)

### 8.1 Domain — OfferPosition delta

Add nullable fields:

```python
catalog_item_id: str | None = None
allergens: tuple[AllergenCode, ...] | None = None   # None = legacy unknown
vegan: bool | None = None
vegetarian: bool | None = None
```

Validation:

- When `kind == "catalog"` and any V2 field set: `catalog_item_id` required.
- When `allergens is not None`: validate codes (reuse `validate_allergen_codes`).
- Legacy reconstructed rows: all new fields `None`.

### 8.2 SQLite migration — `offer_positions`

| Column | Type | Notes |
|---|---|---|
| `catalog_item_id` | TEXT NULL | FK logical to `catalog_dishes.dish_id`, no SQLite FK enforce |
| `allergens_json` | TEXT NULL | JSON array or SQL NULL |
| `vegan` | INTEGER NULL | 0/1/NULL |
| `vegetarian` | INTEGER NULL | 0/1/NULL |

**No backfill.** NULL remains NULL.

### 8.3 Services

| Component | Change |
|---|---|
| `offer_snapshot_validation.py` | Branch on `schema_version`; parse V2 position fields |
| `offer_snapshot.py` | `OfferSnapshotV2` type or unified snapshot with version tag |
| `offer_service._map_position()` | Copy new fields snapshot → domain |
| `sqlite_offer_repository` | Read/write new columns |
| `prepare_offer_version` | No business-rule change; stricter validation for v2 |

### 8.4 API

- `POST .../prepare-offer` — unchanged route; accepts v1 or v2 snapshot in `args.snapshot`.
- Optional read enrichment (non-blocking): `GET offer detail` may expose `allergens` on positions when persisted — for office display only.

**No new command.**

---

## 9. Configurator changes (6D-3a, separate repo)

### 9.1 Catalog client

```text
CORE_OFFICE_API_URL + CORE_OFFICE_API_TOKEN
```

Reuse same endpoints as office panel remote mode:

```text
GET /office/v1/catalog/dishes
GET /office/v1/catalog/dishes/{dish_id}
GET /office/v1/catalog/allergen-codes
```

### 9.2 Adapter responsibilities

For each selected catalog line:

1. Resolve `dish_id` from selection.
2. Load `CatalogDish` (from cache or detail endpoint).
3. Copy Stammdaten fields into snapshot position draft.
4. Set `unit_net_cents` from `current_unit_net_cents`.
5. Set `allergens` from Catalog tuple (may be empty list `[]`).
6. Run existing calculator for totals / VAT.

### 9.3 Fallback (6D-3a only)

```text
IF catalog fetch fails OR dish_id unknown:
    use items.json row with matching id/sku
    emit snapshot v1 OR v2 without catalog_item_id guarantee
    log structured warning
```

Policy: **whole Angebot must not fail** because Catalog is down; fallback preserves today's behaviour.

### 9.4 6D-3b

Remove fallback from production path; `items.json` not read at compose runtime.

---

## 10. Print & Order (unchanged in 6D-3)

| Layer | 6D-3 touch |
|---|---|
| `OrderPrintProjectionService` | **No change** |
| `render_print_sheet` / `render_buffet_cards` | **No change** |
| ConversionLink → OfferPosition join | **No change** |

New fields sit on OfferPosition for **future** 6E/6F enrichment. Legacy print identical.

---

## 11. Tests (required before merge)

### 11.1 Core — snapshot ingest

1. **V2 catalog line roundtrip**

```text
CatalogDish (900 cents, allergens [G])
    → OfferSnapshot v2
    → prepare-offer
    → OfferPosition (900, [G], catalog_item_id set)
```

2. **Catalog change isolation**

```text
Prepare offer at Catalog state (900, [G])
Change Catalog to (1000, [G, J])
Reload OfferPosition → still (900, [G])
New prepare-offer → (1000, [G, J])
```

3. **Legacy V1 unchanged**

```text
Existing V1 prepare-offer fixtures still pass
OfferPosition allergens NULL after load
```

4. **NULL semantics**

```text
Legacy row allergens=NULL → API/print helpers treat as "unknown", not []
```

5. **V2 validation**

```text
catalog kind without catalog_item_id → 422
invalid allergen code → 422
```

6. **Regression**

```text
6D-2 test_offer_position_unchanged_after_catalog_price_update still passes
Print projection tests unchanged
```

### 11.2 Configurator (6D-3a)

- Adapter unit test: Catalog mock → snapshot position fields.
- Fallback test: Catalog 503 → items.json row used; Angebot still buildable.
- Integration smoke: end-to-end prepare-offer with v2 against Core test server.

---

## 12. Acceptance criteria

**6D-3a done** when:

1. Core accepts `offer_snapshot_v2` and persists extended OfferPosition columns.
2. V1 snapshots and legacy DB rows behave identically to pre-6D-3.
3. Mandatory tests §11.1 pass; full unit suite green.
4. Configurator can compose from Catalog API with items.json fallback.
5. No Print / Order / live Catalog join introduced.

**6D-3b done** when:

1. Configurator production path uses Catalog only.
2. `items.json` not required at compose runtime (seed script only).

Suggested commit messages:

```text
Add offer snapshot v2 and catalog position fields
Add configurator catalog adapter with items fallback   # 6D-3a configurator repo
Remove configurator items.json runtime dependency     # 6D-3b
```

---

## 13. File plan (Core — 6D-3a)

| Layer | Files |
|---|---|
| Domain | `domain/offer.py`, `domain/offer_snapshot.py` |
| Validation | `services/offer_snapshot_validation.py` |
| Mapping | `services/offer_service.py` |
| Persistence | `repositories/sqlite_offer_repository.py`, migration |
| Tests | `test_offer_snapshot_validation.py`, `test_offer_service.py`, `test_offer_repository.py`, new `test_offer_snapshot_v2_catalog.py` |

**Do not touch:** `order_print_projection_service.py`, `buffet_cards_service.py`, `catalog_dish_write_service.py` (except optional read helpers).

---

## 14. Roadmap after 6D-3

```text
6D-3  Snapshot V2 + Catalog adapter     ← this pack
6E    Buffetschilder allergen badges    (reads OfferPosition.allergens, NULL-safe)
6F    Küchenzettel production hints     (optional production_group — future Catalog field)
```

Full Büro chain:

```text
Verwaltung (Catalog)
    → Angebot (immutable snapshot)
    → Auftrag
    → Küchenzettel / Buffetschilder (snapshot-only)
```

Post-foundation office UX (search, filters, Wochenübersicht polish) proceeds **after** 6D-3b without architectural risk.

---

## 15. Open items (frozen defaults for implementation)

| Item | 6D-3a default |
|---|---|
| VAT rate for catalog lines | Configurator calculator (Catalog has no VAT field) |
| `vegan` / `vegetarian` on catalog lines | `null` until Catalog extended |
| `production_group` | Defer to 6F |
| Offer detail UI showing allergens | Optional read-only; not required for 6D-3a merge |
| Configurator cache TTL | 60s in-memory per process (implementation detail) |
| Strict mode flag | Env `CATALOG_ADAPTER_STRICT=1` disables fallback (dev/staging only) |

---

## 16. References

| Doc | Path |
|---|---|
| Catalog scope (6D-0) | `docs/proposals/CATALOG_SCOPE_V1.md` |
| Catalog read (6D-1) | `docs/proposals/CATALOG_READ_MODEL_6D1.md` |
| Catalog write (6D-2) | `docs/proposals/CATALOG_WRITE_MODEL_6D2.md` |
| Print bundle | `docs/proposals/PRINT_PROJECTION_SCOPE_V1.md` |
| Snapshot V1 | `src/catering_system/domain/offer_snapshot.py` |
| prepare-offer | `src/catering_system/services/offer_service.py` |

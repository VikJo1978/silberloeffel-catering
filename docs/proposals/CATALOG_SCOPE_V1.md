# CATALOG_SCOPE_V1 — frozen scope (6D-0)

Status: **design only — no code, no tables, no UI**  
Scope owner: Catalog / Preise / Allergene  
Prerequisite: Print-Bundle complete (6C-1 Küchenzettel, 6C-2 Buffetschilder)  
Companion audit: `CATALOG_AUDIT_6D0.md` (detailed field inventory)

---

## Frozen rule

```text
Catalog (Stammdaten, office-editable)
        ↓ snapshot at Angebot creation
Offer / OfferPosition (immutable after send)
        ↓ accepted variant via ConversionLink
Order / OrderPrintProjection (read accepted snapshot)
```

**Forbidden:**

```text
Order → Catalog          (live dereference at print or order edit)
OrderVersion → menu      (operational facts only)
```

If Catalog price or allergens change tomorrow, **old Aufträge and old Angebote must not change**. Only new Angebote pick up new Stammdaten.

---

## 1. Current state

### 1.1 Where dishes live today

| Layer | Type | Location | Core truth? |
|---|---|---|---|
| Live catalog | external | `~/fingerfood-app` — `items.json` / future storage | No — mutable |
| Configurator draft | external | fingerfood-app Draft Storage | No |
| Proposal preview | transport | `proposal_payload_v1` → `office_panel_proposal.py` | No |
| Inquiry prefill | transport | `core_inquiry_offer_prefill_v1` | No |
| **OfferSnapshot** | wire contract | `offer_snapshot_v1` — validated at `prepare_offer_version` | At ingest boundary |
| **OfferVariant** | persisted | `domain/offer.py` + SQLite `offer_variants` | Yes — immutable |
| **OfferPosition** | persisted | `domain/offer.py` + SQLite `offer_positions` | Yes — immutable |
| Print projection | read model | `order_print_projection_service.py` via `ConversionLink` | Read-only join |

There is **no `CatalogDish` entity in Core today**.

### 1.2 Dish fields — present vs missing

**Present** (on wire and/or persisted after 6C-0p):

| Field | OfferSnapshotPosition | OfferPosition | Print (6C) |
|---|---|---|---|
| `name` | ✓ | ✓ | ✓ |
| `description` | ✓ | ✓ optional | ✓ |
| `composition` | ✓ | ✓ optional | ✓ |
| `notes` | ✓ | ✓ optional | Küchenzettel |
| `catalog_item_id` | ✓ optional | **✗ not persisted** | ✗ |
| `kind` | ✓ | ✓ | ✓ |
| `quantity`, `quantity_mode`, `unit_label` | ✓ | ✓ optional | Küchenzettel qty |

**Missing** (nowhere in Core or snapshot contract):

| Field | Status |
|---|---|
| `allergens` (structured) | ✗ — deferred; `composition` used as informal proxy |
| `vegan` / `vegetarian` | ✗ |
| `production_group` | ✗ — kitchen routing |
| `price history` | ✗ — only frozen cents on OfferPosition |
| `active` / catalog lifecycle | ✗ — lives only in configurator `items.json` |

**Audit answer (frozen):**

```text
Есть:
  name, description, composition, notes
  (+ money fields, quantity semantics, kind)

Нет:
  allergens, vegan, vegetarian, production_group, price history
  (+ catalog_item_id lost on persist)
```

### 1.3 Where variants live

- **OfferSnapshotVariant:** `variant_id`, `label`, `description`, `positions[]`, `totals` (totals wire-only)
- **OfferVariant (Core):** `variant_id`, `label`, `description?`, `positions[]`
- **AcceptanceEvidence:** pins exactly one `accepted_variant_id`
- **ConversionLink:** pins accepted variant → `Order`

Variant structure is **immutable per OfferVersion** after `prepare_offer_version`.

### 1.4 Configurator boundary today

```text
Configurator (fingerfood-app)
        ↓ calculates + materializes
OfferSnapshot V1
        ↓ POST prepare-offer
Core Offer / OfferPosition
```

Configurator **never writes Core directly** (`CONFIGURATOR_EXECUTION_PACK_V1`).  
Catalog today lives **inside configurator**, not as a first-class Core layer.

---

## 2. Missing fields

Fields required for Verwaltung and future Buffetschilder (allergen badges) that must be designed **before** 6D-1:

| Field | Catalog (source) | OfferSnapshot copy | OfferPosition persist | Print projection |
|---|---|---|---|---|
| `dish_id` / `catalog_item_id` | ✓ PK | ✓ traceability | ✓ **Phase 3** (nullable) | optional trace |
| `allergens[]` | ✓ coded list | ✓ snapshot copy | ✓ **Phase 3** nullable | Buffetschilder **after Phase 3** |
| `vegan`, `vegetarian` | ✓ bool | ✓ snapshot copy | ✓ **Phase 3** nullable | Buffetschilder **after Phase 3** |
| `production_group` | ✓ internal | optional copy | ✓ **Phase 3** optional | Küchenzettel **after Phase 3** |
| `current_unit_net_cents` + VAT | ✓ Stammpreis | → frozen cents | already via money fields | never on guest card |
| `active` | ✓ | n/a | n/a | n/a |
| `PriceHistory` | ✓ audit (6D-2 write) | n/a | n/a | n/a |

**Do not** add allergen/price fields directly to `OfferPosition` in 6D-1.  
Path: **CatalogDish → snapshot (Phase 3) → OfferPosition → Print**. Print-Bundle unchanged until snapshot copy exists.

---

## 3. Catalog model (target)

### 3.1 CatalogDish — proposed Stammdaten entity

```text
CatalogDish
 ├── dish_id              (stable PK, exposed as catalog_item_id on snapshot)
 ├── name
 ├── description          (customer-visible Kurztext)
 ├── composition          (Zutaten / Inhalt — display text, not allergen substitute)
 ├── allergens            (ordered list of EU codes — see §3.2)
 ├── vegan                (bool)
 ├── vegetarian           (bool)
 ├── production_group     (optional internal kitchen routing key)
 ├── vat_rate_percent     (7 | 19 — Stammpreis VAT class)
 ├── current_unit_net_cents   (Stammpreis — mutable by Büro only; see §4.3)
 ├── unit_label               (optional default, e.g. "Stück", "Portion")
 ├── active                   (bool — inactive dishes hidden from new offers)
 ├── created_at / updated_at
 └── PriceHistory[]           (append-only — see §3.4; write path in 6D-2)
```

**Catalog lives in Core** as Stammdaten. Configurator reads Catalog via API; `items.json` becomes migration source, not long-term truth.

### 3.4 PriceHistory — design now, write in 6D-2

Do **not** model price as a bare mutable `Decimal` without audit. Even in 6D-1 (read-only), the schema must reserve:

```text
CatalogPriceHistoryEntry
 ├── entry_id
 ├── dish_id
 ├── old_unit_net_cents      (nullable on first set)
 ├── new_unit_net_cents
 ├── changed_at              (timezone-aware)
 ├── changed_by              (office actor label, e.g. "office-panel")
 └── effective_from          (optional date — for "ab wann gilt der neue Preis")
```

6D-1: table may exist empty or seeded; **read API exposes latest entry only** (optional).  
6D-2: every Stammpreis change appends history **then** updates `CatalogDish.current_unit_net_cents`.

Questions this answers later:

- «Warum war das Angebot im Juni 8,50 € und jetzt 9 €?» → Angebotspreis frozen on Offer; Stammpreis history on Catalog.
- «Wer hat den Preis geändert?» → `changed_by` + `changed_at`.
- «Ab welchem Tag gilt der neue Preis?» → `effective_from` (6D-2).

**Extension path:** Option 3 (Küche schlägt vor → Büro prüft) adds a `PriceChangeProposal` entity later — does **not** require remodelling `PriceHistory`.

### 3.2 Allergen model — structured, not free text

**Forbidden in V1:**

```text
Allergene: "Milch, Gluten?"
```

**Required shape:**

```python
allergens: tuple[AllergenCode, ...]  # e.g. ("A", "G", "C")
```

**Frozen German EU allergen dictionary (codes A–N):**

| Code | Bezeichnung |
|---|---|
| A | Gluten |
| B | Krebstiere |
| C | Eier |
| D | Fisch |
| E | Erdnüsse |
| F | Soja |
| G | Milch |
| H | Schalenfrüchte |
| I | Sellerie |
| J | Senf |
| K | Sesam |
| L | Schwefeldioxid/Sulfite |
| M | Lupinen |
| N | Weichtiere |

Rules:

- Catalog stores **codes only**; UI renders German labels from this frozen dictionary.
- Snapshot copies the code list at offer creation — immutable on OfferPosition.
- Empty list `[]` means "no declared allergens" (distinct from `null` = legacy unknown).
- `composition` remains ingredient text; it does **not** replace structured allergens.

### 3.3 Existing OfferPosition — Option A vs B

| Option | Approach | Verdict |
|---|---|---|
| **A** | Add `allergens nullable` directly to `OfferPosition` only | Rejected as primary model — no Stammdaten home for office edits |
| **B** | `CatalogDish` → copied into OfferSnapshot → OfferPosition | **Accepted** |

Legacy rows:

- Existing `OfferPosition` rows without allergen fields remain valid (`NULL` = unknown / not declared).
- No backfill required at migration time.
- Print-Bundle behaviour unchanged for legacy offers.

New offers:

- Configurator (or office) reads **CatalogDish** → materializes snapshot → Core persists copy on OfferPosition.
- `catalog_item_id` **must be persisted** on OfferPosition when present (closes current traceability gap).

---

## 4. Snapshot rules

### 4.1 Price layers (Stammpreis → Angebotspreis → Auftragspreis)

```text
Stammpreis          CatalogDish.current_unit_net_cents
   ↓ copy + calculate at offer creation
Angebotspreis       OfferPosition.unit_net_cents (+ totals, VAT frozen)
   ↓ acceptance pins variant; conversion does NOT re-copy prices
Auftragspreis       (no separate field) — read accepted OfferPosition via ConversionLink
```

| Layer | Mutable? | Who changes? | Stored where |
|---|---|---|---|
| **Stammpreis** | Yes | Office / authorized role (see §4.3) | CatalogDish (+ price history) |
| **Angebotspreis** | **No** after OfferVersion insert | — | OfferPosition (immutable) |
| **Auftragspreis** | **Never a live price** | — | Implicit: accepted OfferPosition snapshot |

Example (frozen behaviour):

```text
Heute:  Kartoffelsalat  8 €  Allergen: G (Milch)   → Kunde bestellt
Morgen: Kartoffelsalat  9 €  Allergen: G           → neuer Kunde sieht 9 €
        Alter Auftrag druckt weiter 8 € + snapshot allergens
```

Core **never recalculates** OfferPosition from Catalog at print time or order edit time.

### 4.2 Snapshot copy trigger

Copy Catalog → OfferSnapshot happens at:

- `prepare_offer_version` (authoritative path today)
- Future: office manual offer line add (still produces snapshot, never live join)

Each new OfferVersion = new snapshot = new frozen positions.  
Editing Catalog does **not** retroactively change sent OfferVersions.

### 4.3 Price change authority — **frozen: Option 1 (Nur Büro)**

**Decision (2026-07-16):** commercial Stammdaten changes are **Büro-owned**. Küche supplies content; Büro owns commercial truth.

```text
Stammpreis
    |
    v
CatalogDish
    |
    v
OfferSnapshot
    |
    v
OfferPosition
    |
    v
Order / Print
```

Büro already owns the commercial chain:

```text
Anfrage → Angebot → Annahme → Auftrag
```

Küche must **not** directly mutate Catalog commercial fields (price, active, allergens after confirmation).

#### Role: Küche

**May (informally or via future proposal workflow):**

- propose a new Gericht
- suggest Beschreibung / Zutaten changes
- report cost / margin changes

**May not (direct Catalog write):**

- change Stammpreis
- activate / deactivate dishes
- set allergens on Catalog

Workflow for kitchen-originated changes:

```text
Küche: Änderung vorschlagen
        ↓
Büro: Prüfung
        ↓
Büro: aktiviert in Catalog (6D-2 command)
```

No Küche login or Catalog write surface in 6D-1 / 6D-2.

#### Role: Büro

**May (6D-2 commands):**

- change Stammpreis → append `PriceHistory` → update `current_unit_net_cents`
- activate / deactivate dish
- change allergens (after internal confirmation)
- create / edit dish text fields
- manage variants in configurator flow (unchanged — still via OfferSnapshot)

#### Future extension (not closed)

Option 3 (Beide mit Freigabe) can be added **without** schema break:

- new `CatalogChangeProposal` entity (kitchen suggestion, office approval)
- approved proposal → same Büro command path as today
- `PriceHistory.changed_by` distinguishes `"office-panel"` vs `"approved-proposal:{id}"`

**6D-1:** no proposals, no write commands, no role ACL — read-only Verwaltung only.

### 4.4 Snapshot schema evolution

- **V1 (`offer_snapshot_v1`):** current contract — no allergen fields.
- **V2 (future):** extend `OfferSnapshotPosition` with optional `allergens[]`, `vegan`, `vegetarian`, `production_group`; require `catalog_item_id` when `kind=catalog`.
- Core accepts V1 and V2 during transition; validation strict per `schema_version`.
- Print projection reads persisted OfferPosition — **Print-Bundle unchanged** when allergen fields arrive (Buffetschilder allergen badges = later slice).

### 4.5 Configurator target flow

**Today:**

```text
Configurator → OfferSnapshot → Core
```

**Target:**

```text
Configurator → Catalog (read Stammdaten)
        ↓ compose + calculate
OfferSnapshot (frozen copy of dish fields + prices)
        ↓
Core OfferPosition
```

Effects:

- Price update in Catalog → **new Angebote only**
- Allergen update in Catalog → **new Schilder / new offers only**
- Old Angebote / Aufträge → unchanged snapshots

---

## 5. Migration strategy

Phased — no big-bang, no breaking legacy offers or Print-Bundle.

### Phase 0 — 6D-0 (this document)

Audit + frozen scope. No code.

### Phase 1 — 6D-1 Catalog Read Model

- `CatalogDish` + `PriceHistory` schema in Core (history table empty or seed-only).
- Read API + office Verwaltung list/detail (**read-only**).
- One-time seed import from configurator `items.json`.
- **No** Offer/OfferPosition schema change.
- **No** prepare-offer, print, or configurator behaviour change.

See: `CATALOG_READ_MODEL_6D1.md`.

### Phase 2 — 6D-2 Catalog Editing

- Büro-only write command: **update existing dish** (not full CRUD in v1).
- Every price change: `PriceHistory` append → `CatalogDish.current_unit_net_cents`.
- Configurator **unchanged** (`items.json → OfferSnapshot` until 6D-3 migration slice).

See: `CATALOG_WRITE_MODEL_6D2.md`.

### Phase 3 — Snapshot extension (6D-3 or part of 6D-2)

- Extend `offer_snapshot_v2` position shape with allergen/dietary fields.
- Persist `catalog_item_id` + new nullable fields on `OfferPosition` (SQLite migration, **no backfill**).
- `_map_position()` copies all snapshot fields.
- Legacy positions: `allergens = null`, print unchanged.

### Phase 4 — Print enrichment (optional, after Catalog stable)

- Buffetschilder allergen badges from **snapshotted** `OfferPosition.allergens`, not live Catalog.
- Küchenzettel production_group routing — separate slice.

### Non-goals during migration

- Rewriting historical OfferVersions
- Backfilling allergens onto old OfferPosition rows
- Moving menu onto OrderVersion
- Breaking 6C Print-Bundle read path

---

## 6. Office UI boundary

### 6.1 Future Verwaltung surface

```text
Verwaltung
 |
 + Gerichte (6D-1 — read-only list + detail)
 |    ├── Name
 |    ├── Beschreibung / Zutaten
 |    ├── Allergene (coded A–N → labels)
 |    ├── Vegan / Vegetarisch
 |    ├── Stammpreis + MwSt (current only)
 |    └── Aktiv / Inaktiv
 |
 + Preise / Historie     (6D-2 — full audit view; 6D-1 optional „letzte Änderung“ on detail only)
 |
 + Allergene (Referenz)  (6D-1 — static dictionary via API; optional dedicated page)
```

All **writes** target CatalogDish — **6D-2 only**.

### 6.2 Explicitly NOT in office UI

```text
Order bearbeiten → Menü ändern     ✗
OrderVersion → dish lines            ✗
Print screen → live catalog lookup   ✗
Offer detail → edit sent prices      ✗
```

Order detail continues to show:

- Event facts + version history (OrderVersion)
- Link to accepted Offer (commercial read-only)
- Print links (Küchenzettel / Buffetschilder) — read projection

Menu changes for a customer require a **new Angebot** (new OfferVersion via configurator), not order edit.

### 6.3 Relationship to existing flows

| Flow | Catalog role |
|---|---|
| Inquiry → Configurator prefill | Unchanged handoff; configurator reads Catalog |
| prepare-offer | Snapshot copies Catalog dish fields |
| convert accepted offer | Event facts only → Order; menu stays on Offer |
| Print-Bundle | Read OfferPosition via ConversionLink — **no Catalog join** |

---

## 7. Out of scope

### 7.1 Explicitly excluded from Catalog V1 scope

- Order / OrderVersion schema changes
- Menu editing on Order detail
- Live Catalog dereference at print time
- Free-text allergen fields
- Discount / negative price positions
- Automated configurator → Core bridge (still manual prepare-offer)
- Buffetschilder allergen badge rendering (until snapshot fields exist)
- KitchenPrintJob / PDF / production planning
- Multi-tenant or franchise catalog
- Customer-facing online catalog (public site — separate concern)

### 7.2 Deferred slices (after 6D-2)

| Slice | Depends on |
|---|---|
| **6D-1** Catalog Read Model | This scope doc + `CATALOG_READ_MODEL_6D1.md` |
| **6D-2** Catalog Editing | 6D-1 + §4.3 frozen (Nur Büro) |
| **6D-3** Snapshot V2 + OfferPosition persist | 6D-2 + configurator reads Catalog |
| **6E** Buffetschilder allergen badges | Phase 3 snapshotted allergens on OfferPosition |
| **6F** Küchenzettel production groups | Phase 3 snapshotted production_group |

### 7.3 Print-Bundle protection

6D series must **not** refactor:

- `OrderPrintProjectionService`
- `render_print_sheet` / `render_buffet_cards`
- ConversionLink read path

New catalog fields reach print only after they exist on **OfferPosition snapshot**, via existing projection join.

---

## 8. Decision summary

| Decision | Status |
|---|---|
| Catalog → Snapshot → Offer → Order/Print | **Frozen** |
| Order → Catalog forbidden | **Frozen** |
| CatalogDish as Stammdaten source (Option B) | **Frozen** |
| Allergens = EU codes A–N, not free text | **Frozen** |
| Catalog storage in Core DB | **Frozen** |
| Price change authority = **Nur Büro** (Option 1) | **Frozen** — §4.3 |
| PriceHistory append-only audit | **Frozen** — design in 6D-1 schema, write in 6D-2 |
| Legacy OfferPosition untouched | **Frozen** |
| No allergen fields on OfferPosition until Phase 3 | **Frozen** |
| `catalog_item_id` persist on OfferPosition | **Required in Phase 3** |

---

## 9. Next steps

1. ~~Approve 6D-0 scope~~ — **done**.
2. ~~Resolve price authority~~ — **frozen: Nur Büro** (§4.3).
3. **6D-1 Catalog Read Model** — implement per `CATALOG_READ_MODEL_6D1.md` (read-only).
4. **6D-2 Catalog Editing** — Büro write commands + PriceHistory append.
5. **6D-3 Snapshot V2** — configurator emits extended snapshot; nullable OfferPosition columns.
6. **6E / 6F** — print enrichment from snapshotted fields only.

Print-Bundle remains closed until Phase 3 snapshot copy exists.

---

## 10. Reference files

| Area | Path |
|---|---|
| Detailed audit | `docs/proposals/CATALOG_AUDIT_6D0.md` |
| 6D-1 design pack | `docs/proposals/CATALOG_READ_MODEL_6D1.md` |
| Offer snapshot domain | `src/catering_system/domain/offer_snapshot.py` |
| Offer domain | `src/catering_system/domain/offer.py` |
| Snapshot validation | `src/catering_system/services/offer_snapshot_validation.py` |
| Snapshot → Offer map | `src/catering_system/services/offer_service.py` |
| Print projection | `src/catering_system/services/order_print_projection_service.py` |
| Commercial contract | `docs/proposals/offer_contract_v1.md` |
| Print scope | `docs/proposals/PRINT_PROJECTION_SCOPE_V1.md` |
| Configurator boundary | `docs/archive/packs/CONFIGURATOR_EXECUTION_PACK_V1.md` |

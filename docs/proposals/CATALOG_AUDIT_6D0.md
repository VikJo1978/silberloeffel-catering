# 6D-0 — Catalog Audit (design only)

Status: **frozen audit** — no code in this step  
Scope owner: Catalog / Preise / Allergene architecture  
Prerequisite: Print-Bundle complete (6C-1 Küchenzettel, 6C-2 Buffetschilder)

---

## 0. Purpose

Before building **Verwaltung → Gerichte / Preise / Allergene**, freeze where dish data lives today, what is already snapshotted, and what must **never** be copied into `OrderVersion`.

Target architecture (proposed):

```text
Catalog (Stammdaten, office-editable)
        |
        ↓ copy at Angebot creation
OfferSnapshot → OfferPosition (immutable commercial snapshot)
        |
        ↓ read via ConversionLink
OrderPrintProjection → Küchenzettel / Buffetschilder
```

**Order never reads live Catalog.**  
**OrderVersion never stores menu content.**

---

## 1. Where dishes live today

| Layer | Location | Role | Core truth? |
|---|---|---|---|
| **Live catalog** | `~/fingerfood-app` — `items.json` / future catalog storage (separate repo) | Office browsing, configurator composition, price calculation | **No** — mutable Stammdaten |
| **Configurator draft** | fingerfood-app Draft Storage | Pre-offer editing | **No** |
| **Proposal paste** | `proposal_payload_v1` → `office_panel_proposal.py` | Read-only Angebots-Vorschau from pasted JSON | **No** |
| **Inquiry prefill** | `core_inquiry_offer_prefill_v1` → `office_panel_offer_prefill.py` | Handoff Inquiry → configurator URL | **No** |
| **OfferSnapshot (wire)** | `offer_snapshot_v1` validated in `offer_snapshot_validation.py` | Authoritative boundary from configurator backend | **At ingest only** |
| **OfferPosition (persisted)** | `domain/offer.py` + SQLite `offer_positions` | Frozen commercial line per accepted Offer path | **Yes** (immutable after insert) |
| **Print read model** | `order_print_projection_service.py` → positions via `ConversionLink` | Kitchen / guest print | **Read-only join** |

### Key finding

There is **no Catalog entity in Core today**. Dishes exist as:

1. **Live rows** in the configurator repo (outside Core).
2. **Frozen text + money** on `OfferPosition` after `prepare_offer_version`.
3. **Ephemeral preview** in proposal/prefill transports.

The Print-Bundle (6C) correctly reads **accepted `OfferPosition`**, not live catalog and not `OrderVersion`.

---

## 2. Where prices live today

| Layer | Fields | Authority | Mutable after Angebot? |
|---|---|---|---|
| **Configurator backend** | calculation engine | **Authoritative at offer creation** | Yes (for *new* offers) |
| **OfferSnapshotPosition** | `unit_net_cents`, `net_total_cents`, `vat_rate_percent`, `vat_amount_cents`, `gross_total_cents` | Frozen at snapshot ingest | **No** (per OfferVersion) |
| **OfferSnapshotVariant.totals** | variant rollup (7%/19% buckets, gross) | On wire only | **Not persisted in Core** |
| **OfferPosition** | same money fields as snapshot position | Persisted immutable | **No** |
| **Order / OrderVersion** | *(none)* | — | N/A |

### Key findings

- Core **never recalculates** prices from catalog.
- `offer_contract_v1.md`: configurator backend is the calculation authority; Core validates shape + hash, not catalog dereference.
- **Variant totals** are validated on the wire but **dropped** in `_map_variant()` — recomputable from positions if needed.
- Changing a catalog price affects **only future** snapshots, not existing `OfferVersion` rows.

---

## 3. Where variants live today

| Layer | Identity | Contents |
|---|---|---|
| **OfferSnapshotVariant** | `variant_id` (unique within snapshot) | `label`, `description`, `positions[]`, `totals` |
| **OfferVariant (domain)** | `variant_id` + `offer_version_id` | `label`, `description?`, `positions: tuple[OfferPosition]` |
| **SQLite `offer_variants`** | PK `variant_id` | `label`, `description`, `sort_order` |
| **AcceptanceEvidence** | pins `accepted_variant_id` | One variant per accepted OfferVersion |
| **ConversionLink** | pins `variant_id` + `offer_version_id` | Binds accepted commercial menu to `Order` |

### Lifecycle rules (already correct)

- Customer selects **one variant** at acceptance — never a live catalog row.
- `ConversionLink` ensures Order print reads the **same frozen variant** forever.
- New `OrderVersion` changes **event facts only**; menu stays on Offer.

---

## 4. OfferSnapshot V1 — field inventory

Validation: `offer_snapshot_validation.py` + `domain/offer_snapshot.py`  
Contract doc: `docs/proposals/offer_contract_v1.md`  
No separate JSON Schema file — Python strict key sets are the contract.

### Envelope

| Field | Notes |
|---|---|
| `schema_version` | `"offer_snapshot_v1"` |
| `source` | `"fingerfood-configurator-backend"` |
| `source_draft_id` | optional traceability |
| `inquiry_id`, `snapshot_id` | UUID4 |
| `snapshot_hash` | `sha256:<64 hex>` — canonical JSON |
| `snapshot_created_at`, `valid_until` | |
| `currency` | `"EUR"` |
| `recipient`, `event`, `customer_text`, `payment_terms`, `calculator` | see below |
| `variants` | 1–5 variants, 1–100 positions each |

### `recipient`

`company_name`, `contact_name`, `email`, `postal_address`

### `event`

`event_date`, `time_window_text`, `location_text`, `guest_count`, `planning_mode`

### `customer_text`

`title`, `introduction`, `notes`

### `payment_terms`

`method` (`VORKASSE` \| `RECHNUNG` \| `BAR_VOR_ORT`), `customer_visible_text`

### `calculator` (provenance only)

`name`, `calculator_revision`, `catalog_revision`, `tax_revision`

### `variants[]`

| Field | Persisted to Core? |
|---|---|
| `variant_id`, `label`, `description` | ✓ (`OfferVariant`) |
| `positions[]` | ✓ (`OfferPosition`) |
| `totals` | ✗ (wire only) |

### `positions[]`

| Field | On wire | Persisted (`OfferPosition` / SQLite) |
|---|---|---|
| `position_id`, `kind` | ✓ | ✓ |
| `name` | ✓ | ✓ |
| `description`, `composition`, `notes` | ✓ | ✓ (since 6C-0p, nullable for legacy) |
| `quantity`, `quantity_mode`, `unit_label` | ✓ | ✓ (since 6C-0p, nullable for legacy) |
| `unit_net_cents`, `net_total_cents`, `vat_*`, `gross_total_cents` | ✓ | ✓ |
| `related_position_id` | ✓ (surcharge) | ✓ |
| `catalog_item_id` | ✓ optional | **✗ dropped in `_map_position()`** |

### Snapshot fields validated but **not persisted**

- `recipient`, `customer_text`, `calculator` (+ `catalog_revision`)
- `source_draft_id`, `currency`
- Variant `totals`
- Position `catalog_item_id`

---

## 5. Fields needed tomorrow — gap analysis

Proposed future **Catalog Dish** (office-editable Stammdaten):

```text
Dish
 ├── dish_id
 ├── name
 ├── description
 ├── composition
 ├── allergens[]
 ├── vegan
 ├── vegetarian
 ├── active
 └── current_price (+ VAT semantics)
```

### Mapping: Catalog → Snapshot → Print

| Future Catalog field | OfferSnapshotPosition | OfferPosition (today) | Print projection (6C) | Gap |
|---|---|---|---|---|
| `dish_id` | `catalog_item_id` | — | — | **Not persisted** — traceability lost |
| `name` | `name` | `name` | ✓ | OK |
| `description` | `description` | `description` | ✓ | OK (6C-0p) |
| `composition` | `composition` | `composition` | ✓ | OK; temporary allergen proxy |
| `allergens[]` | — | — | — | **Missing everywhere** |
| `vegan` / `vegetarian` | — | — | — | **Missing everywhere** |
| `current_price` | `unit_net_cents` + totals | money fields | intentionally excluded from Buffetschilder | OK at snapshot |
| `notes` (kitchen hint) | `notes` | `notes` | Küchenzettel only | OK |
| `production_group` | — | — | — | **Missing** — kitchen routing |
| `active` | — | — | — | Catalog-only |

### Recommended rule for new fields

| Field class | Belongs in Catalog | Copied to OfferSnapshot | Copied to Order |
|---|---|---|---|
| Customer-visible dish text | ✓ source | ✓ snapshot | ✗ read Offer |
| Allergens / dietary flags | ✓ source | ✓ snapshot at offer time | ✗ read Offer |
| Price / VAT | ✓ current | ✓ frozen cents | ✗ read Offer |
| Production / kitchen routing | ✓ source | optional snapshot copy | ✗ read Offer |
| Event logistics | ✗ | ✓ event block | ✓ OrderVersion only |

**Do not extend `OfferPosition` ad infinitum without a Catalog source.**  
Pattern: Catalog defines editable truth → snapshot copies at `prepare_offer_version` → OfferPosition stores the copy.

---

## 6. What the office should edit (future)

### Editable in Catalog (Stammdaten)

- Dish name, description, composition
- Allergens, vegan, vegetarian
- Current price (and VAT class)
- Active / archived flag
- Production group (internal kitchen logic)
- Possibly: default `unit_label`, default quantity semantics

### Editable in Angebot phase (before send)

- Variant composition (via configurator → new snapshot)
- Event facts, payment terms, customer text
- Per-offer overrides **only by creating a new OfferVersion** (new snapshot)

### Editable in Auftrag phase (operational)

- `OrderVersion` event facts: date, location, guests, planning mode
- **Not** menu lines, prices, allergens

### Never editable after fact

- Sent / accepted / converted OfferVersion content
- Acceptance evidence, conversion link
- Historical print snapshots implied by accepted Offer

---

## 7. Immutable after Angebot — frozen boundary

SQLite immutability triggers protect:

- `offer_versions`, `offer_variants`, `offer_positions`
- All evidence tables: sent, acceptance, rejection, withdrawal, conversion

### Immutable content (per OfferVersion)

| Category | Examples |
|---|---|
| Position lines | name, description, composition, notes, quantity, **all prices/VAT** |
| Variant structure | labels, position set |
| Event + payment on offer | `event_date`, `payment_method`, `valid_until` |
| Provenance | `snapshot_id`, `snapshot_hash` |
| Evidence | sent channel, acceptance variant, conversion link |

### Explicitly **not** copied to Order

On `convert_accepted_offer`, OrderVersion receives **event facts only** from the accepted OfferVersion.  
Menu, prices, allergens stay on Offer — read via `ConversionLink` at print time.

This is the correct split validated by 6C Print-Bundle.

---

## 8. Integration boundaries (today)

```text
Inquiry (Core)
  → prefill URL (core_inquiry_offer_prefill_v1)
  → fingerfood-app configurator

Configurator backend
  → OfferSnapshot V1
  → POST prepare-offer (office API)
  → offer_service.prepare_offer_version()
  → SQLite offer_*

Accepted Offer
  → convert_accepted_offer()
  → Order + ConversionLink
  → OrderPrintProjection (read OfferPosition)
```

| Transport | Schema | Writes Core? |
|---|---|---|
| Inquiry prefill | `core_inquiry_offer_prefill_v1` | No |
| Proposal paste | `proposal_payload_v1` | No (preview only) |
| Authoritative offer | `offer_snapshot_v1` | Yes |

Env: `CONFIGURATOR_URL` — prefill handoff only.  
Configurator **never writes Core directly** (CONFIGURATOR_EXECUTION_PACK_V1).

---

## 9. Risks if Catalog is built wrong

| Anti-pattern | Why it breaks |
|---|---|
| Store menu on `OrderVersion` | Event versions would fork menu; breaks Storno/reconvert semantics |
| Dereference live Catalog at print time | Old Aufträge show new prices/allergens |
| Add allergens only to print projection | No commercial audit trail; Offer history incomplete |
| Infinite `OfferPosition` fields without Catalog | Office edits have no Stammdaten home |
| Persist `catalog_item_id` without Catalog entity | Traceability stub with nothing to point at |

---

## 10. Audit answers (checklist)

| # | Question | Answer |
|---|---|---|
| 1 | Where do dishes live? | **Configurator catalog** (external) + **frozen `OfferPosition`** (Core) + ephemeral proposal/prefill |
| 2 | Where do prices live? | **Configurator calculation** → frozen on **OfferSnapshotPosition / OfferPosition**; not on Order |
| 3 | Where do variants live? | **OfferSnapshotVariant** → **OfferVariant**; pinned by acceptance + conversion link |
| 4 | OfferSnapshot fields? | Full inventory in §4; contract in `offer_contract_v1.md` |
| 5 | Fields to add tomorrow? | **allergens[], vegan, vegetarian, production_group**; persist **catalog_item_id** if Catalog exists |
| 6 | Office-editable? | **Catalog Stammdaten** + new OfferVersions via configurator; **not** historical Offer rows |
| 7 | Immutable after Angebot? | **Entire OfferVersion snapshot** + evidence; Order holds event facts only |

---

## 11. Proposed next step — 6D-1 Catalog Read Model

**Scope:** office-facing read layer only — **no Core truth mutation**.

```text
Verwaltung
 |
 + Gerichte      ← Catalog Dish list/detail (read)
 + Preise        ← current price view per dish (read)
 + Allergene     ← allergen registry view (read)
```

Prerequisites before 6D-1 code:

1. **Decide Catalog storage home** — Core DB vs configurator repo vs hybrid (recommendation: **Catalog in Core** as Stammdaten, configurator reads via API; fingerfood-app `items.json` becomes migration source).
2. **Freeze Dish entity** — fields in §5, versioning strategy for price changes.
3. **Freeze snapshot copy rules** — which Catalog fields copy into `offer_snapshot_v2` (or extended v1 positions).
4. **Persist `catalog_item_id`** on `OfferPosition` when snapshot includes it (small schema migration, no backfill).
5. **Allergen model** — structured list vs coded enum set (EU allergen registry).

6D-1 must **not** change Order, OrderVersion, Offer lifecycle, or Print-Bundle read paths.

---

## 12. Key files (reference)

| Area | Path |
|---|---|
| Snapshot domain | `src/catering_system/domain/offer_snapshot.py` |
| Snapshot validation | `src/catering_system/services/offer_snapshot_validation.py` |
| Offer domain | `src/catering_system/domain/offer.py` |
| Snapshot → Offer map | `src/catering_system/services/offer_service.py` |
| SQLite offers | `src/catering_system/repositories/sqlite_offer_repository.py` |
| Print projection | `src/catering_system/services/order_print_projection_service.py` |
| Commercial contract | `docs/proposals/offer_contract_v1.md` |
| Print scope | `docs/proposals/PRINT_PROJECTION_SCOPE_V1.md` |
| Configurator boundary | `docs/archive/packs/CONFIGURATOR_EXECUTION_PACK_V1.md` |
| Proposal preview | `src/catering_system/ui/office_panel_proposal.py` |
| Inquiry prefill | `src/catering_system/ui/office_panel_offer_prefill.py` |

---

## 13. Decision summary

The Print-Bundle proves the architecture works:

```text
OrderVersion = operative Veranstaltung
OfferPosition = kommerzieller Inhalt (snapshot)
Catalog = editable source (not yet in Core)
```

**6D-0 outcome:** Catalog is a **new Stammdaten layer**, not an extension of Order or OfferPosition.  
Offers snapshot Catalog at creation; Orders read accepted Offers; print reads projection.

Ready for **6D-1 Catalog Read Model** design pack after Catalog storage decision (§11.1).

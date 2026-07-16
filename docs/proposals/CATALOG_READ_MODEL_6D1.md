# 6D-1 — Catalog Read Model (design pack)

Status: **implemented** — `c8662ad Add catalog read model`  
Prerequisite: `CATALOG_SCOPE_V1.md` (6D-0 frozen)  
Scope owner: Catalog Stammdaten — **read-only** office surface  
Next slice: **6D-2 Catalog Editing** — see `CATALOG_WRITE_MODEL_6D2.md`

---

## 1. Purpose

Introduce **CatalogDish** as first-class Stammdaten in Core with a **read-only** office view:

```text
Verwaltung
   |
   + Gerichte
       + Name
       + Stammpreis (current)
       + Allergene (codes → labels)
       + Aktiv / Inaktiv
```

Goals:

- Give Büro visibility into dish master data before editing exists.
- Reserve schema for `PriceHistory` (empty until 6D-2).
- Seed from configurator `items.json` without changing Offer / Order / Print paths.

Non-goals (6D-1):

- Editing dishes or prices
- Price history UI (table may exist, not shown except optional "letzte Änderung")
- Role ACL / Küche proposals
- Configurator switching to Catalog API (6D-2+)
- OfferSnapshot V2 or OfferPosition allergen columns (Phase 3)
- Print-Bundle changes

---

## 2. Frozen constraints

| Area | Rule |
|---|---|
| Order / OrderVersion | **No changes** |
| Offer / OfferPosition | **No changes** |
| prepare-offer / OfferSnapshot V1 | **Unchanged** |
| OrderPrintProjection / 6C print | **No Catalog join** |
| Price authority | **Nur Büro** — no write surface in 6D-1 |
| Allergens | Structured codes A–N only (`CATALOG_SCOPE_V1` §3.2) |
| Catalog → Snapshot → Offer → Print | Long-term path frozen; snapshot extension is Phase 3 |

---

## 3. Domain model

### 3.1 CatalogDish

```python
@dataclass(frozen=True)
class CatalogDish:
    dish_id: str                    # UUID4, stable PK
    name: str
    description: str | None
    composition: str | None         # Zutaten / Inhalt (display text)
    allergens: tuple[AllergenCode, ...]  # empty tuple = none declared
    vegan: bool
    vegetarian: bool
    production_group: str | None    # internal; shown in detail only
    vat_rate_percent: Literal[7, 19]
    current_unit_net_cents: int     # Stammpreis
    unit_label: str | None
    active: bool
    created_at: datetime
    updated_at: datetime
```

`AllergenCode` = single letter `A`–`N` per EU dictionary in `CATALOG_SCOPE_V1`.

Validation:

- `name` required, bounded (match Offer text limits where sensible)
- `current_unit_net_cents` ≥ 0
- `allergens` sorted unique codes at persist boundary
- `dish_id` immutable after insert

### 3.2 CatalogPriceHistoryEntry (schema only in 6D-1)

```python
@dataclass(frozen=True)
class CatalogPriceHistoryEntry:
    entry_id: str
    dish_id: str
    old_unit_net_cents: int | None   # None on initial seed
    new_unit_net_cents: int
    changed_at: datetime
    changed_by: str                  # e.g. "seed-import", "office-panel"
    effective_from: date | None
```

6D-1:

- Table created; may receive seed rows from import (`changed_by="seed-import"`).
- **No append API** until 6D-2.
- Optional read: `latest_price_change(dish_id)` for detail footer.

6D-2 write pattern (specified now, implemented later):

```text
cmd_change_catalog_price
        |
        v
INSERT catalog_price_history
        |
        v
UPDATE catalog_dishes.current_unit_net_cents
```

Atomic in one Core command transaction.

### 3.3 Allergen registry (static)

Not a database table in 6D-1 — frozen Python constant + API shape:

```json
{
  "allergen_codes": [
    {"code": "A", "label": "Gluten"},
    ...
  ]
}
```

Office UI resolves codes → German labels client-side or via API include.

---

## 4. Persistence (Core DB)

New SQLite tables in **core.db** (same connection as offers/orders):

### 4.1 `catalog_dishes`

| Column | Type | Notes |
|---|---|---|
| `dish_id` | TEXT PK | UUID4 |
| `name` | TEXT NOT NULL | |
| `description` | TEXT | nullable |
| `composition` | TEXT | nullable |
| `allergens_json` | TEXT NOT NULL | JSON array of codes, e.g. `["G","A"]` |
| `vegan` | INTEGER NOT NULL | 0/1 |
| `vegetarian` | INTEGER NOT NULL | 0/1 |
| `production_group` | TEXT | nullable |
| `vat_rate_percent` | INTEGER NOT NULL | 7 or 19 |
| `current_unit_net_cents` | INTEGER NOT NULL | |
| `unit_label` | TEXT | nullable |
| `active` | INTEGER NOT NULL | 0/1 |
| `created_at` | TEXT NOT NULL | ISO datetime |
| `updated_at` | TEXT NOT NULL | ISO datetime |

Indexes:

- `idx_catalog_dishes_active_name` on `(active, name)` for list sort

**No immutability triggers** in 6D-1 (nothing mutates except seed script).  
6D-2 adds command-only writes; direct SQL UPDATE discouraged by convention.

### 4.2 `catalog_price_history`

| Column | Type | Notes |
|---|---|---|
| `entry_id` | TEXT PK | UUID4 |
| `dish_id` | TEXT NOT NULL FK | → catalog_dishes |
| `old_unit_net_cents` | INTEGER | nullable |
| `new_unit_net_cents` | INTEGER NOT NULL | |
| `changed_at` | TEXT NOT NULL | |
| `changed_by` | TEXT NOT NULL | |
| `effective_from` | TEXT | nullable ISO date |

Index: `idx_catalog_price_history_dish_changed` on `(dish_id, changed_at DESC)`

Append-only by convention; 6D-2 enforces via service (no UPDATE/DELETE routes).

### 4.3 Migration number

Next migration after existing offer migrations — e.g. `catalog_dishes_v1`.  
Seed script runs **after** migration, idempotent on `dish_id` or external `source_key`.

---

## 5. Seed import (one-time / dev)

Source: configurator `items.json` (path configurable; not bundled in Core repo).

Mapping (best-effort, documented in import script):

| items.json (conceptual) | CatalogDish |
|---|---|
| id / sku | `dish_id` or mapped UUID |
| name | `name` |
| description | `description` |
| ingredients / composition | `composition` |
| price | `current_unit_net_cents` (convert € → cents) |
| vat | `vat_rate_percent` |
| allergens (if present) | parse → codes; else `[]` |
| active | `active` |

Import rules:

- Idempotent: re-run skips existing `dish_id`
- Initial price row: optional `PriceHistory` with `old_unit_net_cents=null`
- Missing allergen data → `allergens=[]`, not free text
- Import is **CLI/admin**, not office panel POST

---

## 6. Read services

### 6.1 CatalogDishService (read-only)

```python
class CatalogDishService:
    def list_dishes(
        self,
        *,
        active_only: bool = False,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CatalogDishListResult: ...

    def get_dish(self, dish_id: str) -> CatalogDish | None: ...

    def list_allergen_codes(self) -> tuple[AllergenCodeDefinition, ...]: ...

    def latest_price_change(self, dish_id: str) -> CatalogPriceHistoryEntry | None: ...
```

No `save`, `update`, or `delete` on this service in 6D-1.

### 6.2 List caps (match office API patterns)

- Default page size: 100
- Max page size: 100
- List response includes `total_count`, `truncated`

Sort: `active DESC`, `name ASC` (active dishes first).

---

## 7. Core Office API (read routes)

Bearer auth; same server as existing `/office/v1/*`.

### 7.1 Routes

| Method | Path | Handler |
|---|---|---|
| GET | `/office/v1/catalog/dishes` | `list_catalog_dishes` |
| GET | `/office/v1/catalog/dishes/{dish_id}` | `catalog_dish_detail` |
| GET | `/office/v1/catalog/allergen-codes` | `list_allergen_codes` |

Query params for list:

- `active_only` (bool, default false)
- `q` (search name, max 200 chars)
- `limit`, `offset`

### 7.2 Response shapes

**List row:**

```json
{
  "dish_id": "...",
  "name": "Kartoffelsalat",
  "current_unit_net_cents": 850,
  "vat_rate_percent": 7,
  "allergens": ["G", "J"],
  "allergen_labels": ["Milch", "Senf"],
  "vegan": false,
  "vegetarian": true,
  "active": true
}
```

**Detail** (extends list row):

```json
{
  "description": "...",
  "composition": "...",
  "unit_label": "Portion",
  "production_group": null,
  "created_at": "...",
  "updated_at": "...",
  "latest_price_change": {
    "old_unit_net_cents": null,
    "new_unit_net_cents": 850,
    "changed_at": "...",
    "changed_by": "seed-import",
    "effective_from": null
  }
}
```

Money display formatting stays in UI; API always emits integer cents.

**Allergen codes reference:**

```json
{
  "allergen_codes": [
    {"code": "A", "label": "Gluten"},
    ...
  ]
}
```

### 7.3 Explicitly no routes in 6D-1

- POST/PATCH/DELETE on dishes
- POST price change
- Bulk import via HTTP

---

## 8. Office Panel UI

### 8.1 Navigation

Add shell section:

```text
Verwaltung → Gerichte     (/verwaltung/gerichte)
```

New `OfficeSection`: `"catalog"` (or `"verwaltung"` with sub-route).

Placement: after Kalender / before Werkzeuge in v2 nav (exact order TBD in implementation).

### 8.2 List page

Read-only table/cards:

| Column | Source |
|---|---|
| Name | `name` |
| Stammpreis | format `current_unit_net_cents` + VAT |
| Allergene | codes as badges or comma-separated labels |
| Status | Aktiv / Inaktiv |

Filters:

- Toggle "Nur aktive"
- Search box → `q` param

No edit buttons. Footer note:

> Stammdaten sind derzeit nur lesbar. Preisänderungen erfolgen durch das Büro (demnächst).

### 8.3 Detail page

`GET /verwaltung/gerichte/{dish_id}` — direct mode or remote API.

Shows:

- Name, Beschreibung, Zutaten (composition)
- Allergene (labels)
- Vegan / Vegetarisch
- Stammpreis + MwSt + Einheit
- Aktiv
- Optional: letzte Preisänderung (from `latest_price_change`)
- **No** Preishistorie table in 6D-1

### 8.4 Remote mode

`RemoteCoreClient` mirrors three GET routes; panel renders identical HTML (parity test like print-data).

### 8.5 UI exclusions

- No forms except search/filter
- No "Neues Gericht" button (6D-2)
- No link from Order detail to edit dish
- No Catalog data on Küchenzettel / Buffetschilder

---

## 9. File plan (implementation guide)

| Layer | New / changed files |
|---|---|
| Domain | `domain/catalog.py` — CatalogDish, AllergenCode, CatalogPriceHistoryEntry |
| Repository | `repositories/catalog_repository.py`, `sqlite_catalog_repository.py` |
| Migration | `repositories/sqlite_migrations.py` — catalog tables |
| Service | `services/catalog_dish_service.py` — read-only |
| API views | `ui/office_api_views.py` — catalog shapes |
| API routes | `ui/office_api.py` — three GET handlers |
| Panel list/detail | `ui/office_panel_catalog_list.py`, `office_panel_catalog_detail.py` |
| HTTP routes | `ui/office_panel_http.py` — `/verwaltung/gerichte` |
| Remote | `ui/remote_core_client.py` — catalog GET parity |
| Seed CLI | `scripts/seed_catalog_from_items.py` (or similar) |
| Tests | `tests/unit/test_catalog_dish_service.py`, `test_office_api_catalog.py`, panel + remote parity |

**Do not touch** in 6D-1:

- `order_print_projection_service.py`
- `offer_service.py` / `_map_position`
- `render_print_sheet` / `render_buffet_cards`

---

## 10. Tests (required before merge)

### 10.1 Domain / repository

- `test_catalog_dish_roundtrip_sqlite`
- `test_allergen_codes_validated_at_persist`
- `test_price_history_append_only_repository` (insert ok; document no update API)

### 10.2 Service

- `test_list_dishes_active_filter`
- `test_list_dishes_search_by_name`
- `test_get_dish_not_found`

### 10.3 API

- `test_list_catalog_dishes_api`
- `test_catalog_dish_detail_api`
- `test_allergen_codes_api`

### 10.4 Panel

- `test_verwaltung_gerichte_list_renders`
- `test_verwaltung_gerichte_detail_renders`
- `test_catalog_direct_remote_parity`

### 10.5 Seed

- `test_seed_import_idempotent` (fixture items.json fragment)

---

## 11. Acceptance criteria

6D-1 is **done** when:

1. Catalog tables exist in core.db with seed data from import script.
2. Three GET API routes return stable JSON shapes.
3. Office panel shows read-only Gerichte list + detail in direct and remote mode.
4. All unit tests pass; no regression in Offer/Order/Print suites.
5. No write commands, no Offer/OfferPosition migration, no print changes.

---

## 12. Relationship to 6D-2 and Phase 3

```text
6D-1  Read Model     ← this pack
6D-2  Büro writes     → PriceHistory append, dish CRUD, active toggle
6D-3  Snapshot V2     → allergens copied to OfferPosition
6E    Print allergens → Buffetschilder reads snapshotted OfferPosition
```

Data flow after full catalog rollout:

```text
CatalogDish (Stammpreis, allergens)
        ↓ snapshot at prepare-offer
OfferPosition (frozen copy)
        ↓ ConversionLink
OrderPrintProjection
        ↓
Küchenzettel / Buffetschilder
```

6D-1 establishes the **top** of this chain only. Print and Offer stay untouched.

---

## 13. Open items (non-blocking for 6D-1 start)

| Item | Default for implementation |
|---|---|
| Nav label "Verwaltung" vs top-level "Gerichte" | Section **Verwaltung → Gerichte** |
| Show inactive dishes default | List shows **all**; filter default off |
| production_group on list | **Detail only** |
| Price display format | German locale `8,50 €` + `inkl. 7 % MwSt.` in UI |

---

## 14. References

| Doc | Path |
|---|---|
| Catalog scope (6D-0) | `docs/proposals/CATALOG_SCOPE_V1.md` |
| Detailed audit | `docs/proposals/CATALOG_AUDIT_6D0.md` |
| Offer contract | `docs/proposals/offer_contract_v1.md` |
| Print bundle | `docs/proposals/PRINT_PROJECTION_SCOPE_V1.md` |
| Configurator boundary | `docs/archive/packs/CONFIGURATOR_EXECUTION_PACK_V1.md` |
| Contact list pattern | `contact_projection_service.py`, `/kontakte` UI |

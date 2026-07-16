# 6D-2 — Catalog Write Model (design pack)

Status: **implemented** — pending commit `Add catalog editing and price history`  
Prerequisite: `CATALOG_SCOPE_V1.md` (6D-0), **6D-1 implemented** (`c8662ad Add catalog read model`)  
Scope owner: Catalog Stammdaten — **Büro write surface + PriceHistory append**  
Next slice: **6D-3 Snapshot V2** (allergens copied to OfferPosition at prepare-offer)

---

## 1. Purpose

Give Büro the first **Verwaltungs-Workflow** for dish Stammdaten:

```text
Verwaltung
   |
   + Gerichte
       + Liste (6D-1)
       + Detail (6D-1)
       + Bearbeiten (6D-2)  ← new
           |
           v
       POST update command
           |
           +--> UPDATE catalog_dishes
           |
           +--> INSERT catalog_price_history   (only when price changes)
```

Goals:

- Edit existing `CatalogDish` rows from the office panel (direct + remote).
- Append **audit-grade** `PriceHistory` when `current_unit_net_cents` changes.
- Preserve optimistic concurrency (`updated_at`) consistent with Inquiry / Order commands.
- Keep commercial snapshots **immutable** — no Offer / Order / Print retroactive updates.

Non-goals (6D-2):

- `POST /catalog/dishes` create-new-dish (seed + future slice; see §13)
- Kitchen proposal workflow (`PriceChangeProposal`)
- Role ACL / per-user auth system
- Configurator switching from `items.json` to Catalog API (6D-3+ migration slice)
- OfferSnapshot V2 / OfferPosition allergen columns (6D-3)
- Print-Bundle changes (6C stays on snapshotted OfferPosition)
- Bulk import re-run that **updates** existing rows (seed remains insert-only skip)

---

## 2. Frozen constraints

| Area | Rule |
|---|---|
| Order / OrderVersion | **No changes** |
| Offer / OfferPosition (existing rows) | **No retroactive price/allergen rewrite** |
| prepare-offer / OfferSnapshot V1 | **Unchanged** |
| OrderPrintProjection / 6C print | **No live Catalog join** |
| Configurator runtime | **Still `items.json → OfferSnapshot`** |
| Price authority | **Nur Büro** — single write command path |
| Allergens | Structured codes A–N only; no free text |
| PriceHistory | **Append-only** — no UPDATE/DELETE API |
| Seed script | **Insert-if-absent only** — no fake history, no update-on-reimport |

### 2.1 Commercial isolation (critical)

After a catalog price change:

```text
Existing OfferPosition.unit_net_cents = 850   → stays 850
Existing OrderPrintProjection                 → unchanged (reads OfferPosition)
New prepare-offer (future, after 6D-3)        → may read Catalog 900
```

6D-2 must include an explicit regression test proving an existing `OfferPosition` is untouched when `CatalogDish.current_unit_net_cents` changes.

---

## 3. Domain model (delta over 6D-1)

6D-1 implementation (authoritative — not the richer draft in early 6D-1 prose):

```python
@dataclass(frozen=True)
class CatalogDish:
    dish_id: str
    name: str
    description: str | None
    composition: str | None
    notes: str | None
    current_unit_net_cents: int
    allergens: tuple[AllergenCode, ...]
    active: bool
    created_at: datetime
    updated_at: datetime
```

```python
@dataclass(frozen=True)
class CatalogPriceHistoryEntry:
    entry_id: str
    dish_id: str
    old_unit_net_cents: int | None
    new_unit_net_cents: int
    changed_at: datetime
    changed_by: str
    effective_from: date | None
```

No new domain types required for 6D-2. Optional helper:

```python
@dataclass(frozen=True)
class CatalogDishUpdate:
    name: str
    description: str | None
    composition: str | None
    notes: str | None
    current_unit_net_cents: int
    allergens: tuple[AllergenCode, ...]
    active: bool
    effective_from: date | None  # required semantics when price changes — see §5
```

---

## 4. Mutable vs immutable fields

### 4.1 Allowed in `update` command

| Field | Notes |
|---|---|
| `name` | Required, bounded (existing `_MAX_NAME_LEN`) |
| `description` | Nullable |
| `composition` | Nullable (Zusammensetzung) |
| `notes` | Nullable (internal Büro notes) |
| `current_unit_net_cents` | ≥ 0 integer cents |
| `allergens` | Sorted unique A–N at persist boundary |
| `active` | Boolean lifecycle |

### 4.2 Forbidden in `update` command

| Field | Reason |
|---|---|
| `dish_id` | Stable PK — path parameter only |
| `created_at` | Audit anchor |
| Offer / Order foreign keys | Catalog has none — must not invent |
| `changed_by` | Server-assigned on history append |

Full-row replace semantics: client sends **complete** editable snapshot (not PATCH-by-field). Omitted optional text fields normalize to `null` when explicitly cleared in the form.

---

### 4.3 Active / inactive semantics (frozen)

`active=false` on a `CatalogDish` means **Stammdaten lifecycle off** — not retroactive commercial invalidation.

```text
CatalogDish deaktiviert (active=false)
        |
        +--> neue Angebote / Configurator-Auswahl   ❌  (6D-3+ when Catalog feeds compose)
        |
        +--> bestehende OfferPositionen             ✅  unchanged
        |
        +--> bestehende Orders / Print              ✅  unchanged
```

Rules:

| Surface | `active=false` effect in 6D-2 |
|---|---|
| Office Gerichte list/detail/edit | Dish visible; Büro may re-activate |
| Seed import | May insert inactive rows; never toggles on re-run |
| prepare-offer / OfferSnapshot | **No change in 6D-2** — enforcement deferred to 6D-3 Configurator + snapshot |
| Order / Print | **No change** — never reads live Catalog |

6D-2 implementation: persist `active` via update command only. **No** filtering of existing offers or orders. Optional list filter `active_only=true` (6D-1) remains a display concern, not a commercial gate.

Re-activating (`active=true`) does not rewrite history or offers — only restores eligibility for **future** composition once Configurator reads Catalog.

---

## 5. PriceHistory rules

### 5.1 When to append

| Change | PriceHistory |
|---|---|
| `current_unit_net_cents` changes (e.g. 850 → 900) | **INSERT** one row |
| Same cents as before | **No row** |
| Text-only change (name, composition, …) | **No row** |
| Allergen / active change without price change | **No row** |
| First office price set on seeded dish (850 → 850) | **No row** (identity) |

### 5.2 Row shape on price change

Example: 8,50 € → 9,00 €

```text
entry_id            = new UUID4
dish_id             = target dish
old_unit_net_cents  = 850
new_unit_net_cents  = 900
changed_at          = command commit time (UTC, aware)
changed_by          = "office"            # v1 constant — see §6
effective_from      = date from args     # default: Berlin today if omitted
```

`old_unit_net_cents` is always the **pre-command** value read under concurrency lock, never client-supplied.

### 5.3 Atomicity

One Core command transaction:

```text
BEGIN
  SELECT catalog_dishes ... FOR UPDATE   (via sqlite immediate txn)
  CHECK expect.updated_at
  IF price changed:
      INSERT catalog_price_history
  UPDATE catalog_dishes SET ... updated_at = now
COMMIT
```

No separate `change-price` command in 6D-2 — price is part of unified `update`.

### 5.4 History read (unchanged from 6D-1)

Detail GET continues to return `price_history[]` (newest first, capped). After 6D-2, detail shows real rows instead of «noch keine».

---

## 6. `changed_by` (v1)

No user-management system exists. Frozen v1:

```text
changed_by = "office"
```

Reserved for 6D-2+ extensions (no schema change):

- `"office-panel"` — if distinguishing panel vs API callers matters later
- `"approved-proposal:{proposal_id}"` — Option 3 kitchen workflow

Do **not** add auth tables or LDAP integration in 6D-2.

---

## 7. Command contract

Follow existing Core Office API **command envelope** (same as `update`, `cancel`, `payment-reminder`):

### 7.1 Route

| Method | Path | Command kind |
|---|---|---|
| POST | `/office/v1/catalog/dishes/{dish_id}/update` | `update` |

**Not** `PUT /catalog/dishes/{id}` — keeps parity with `mark-sent`, `record-acceptance`, `effective`, `cancel`.

### 7.2 Envelope

```json
{
  "command_id": "<uuid4>",
  "expect": {
    "updated_at": "2026-07-16T08:00:00+00:00"
  },
  "args": {
    "name": "Schnitzel",
    "description": "Paniert",
    "composition": "Schwein",
    "notes": null,
    "current_unit_net_cents": 900,
    "allergens": ["A", "C", "G"],
    "active": true,
    "effective_from": "2026-08-01"
  }
}
```

| Key | Required | Notes |
|---|---|---|
| `command_id` | yes | Idempotency via command ledger |
| `expect.updated_at` | yes | Optimistic concurrency |
| `args.name` | yes | |
| `args.current_unit_net_cents` | yes | |
| `args.allergens` | yes | Array (may be empty) |
| `args.active` | yes | |
| `args.description` | no | null clears |
| `args.composition` | no | null clears |
| `args.notes` | no | null clears |
| `args.effective_from` | no | ISO date; **ignored** unless price changes; when price changes and omitted → `berlin_today()` |

### 7.3 Success response (200)

```json
{
  "command_id": "...",
  "dish_id": "...",
  "updated_at": "2026-07-16T09:15:00+00:00",
  "price_changed": true,
  "price_history_entry_id": "..."
}
```

When price unchanged: `price_changed: false`, omit `price_history_entry_id`.

### 7.4 Error responses

| HTTP | Code | When |
|---|---|---|
| 404 | `not_found` | Unknown `dish_id` |
| 409 | `stale_state` | `expect.updated_at` ≠ row |
| 409 | `command_id_conflict` | Ledger fingerprint mismatch |
| 422 | `validation_error` | Domain validation (allergens, negative cents, empty name) |
| 422 | `invalid` | Malformed envelope / types |

Panel maps `stale_state` → German message + reload form with fresh `updated_at` (same pattern as inquiry update).

---

## 8. Service layer

Split write path from read-only 6D-1 service:

```python
class CatalogDishWriteService:
    def update_dish(
        self,
        dish_id: str,
        *,
        update: CatalogDishUpdate,
        expected_updated_at: datetime,
        changed_by: str = "office",
        now: datetime | None = None,
    ) -> CatalogDishUpdateResult: ...
```

`CatalogDishService` (6D-1) stays read-only — no `save()` on the read service.

Write service responsibilities:

1. Load dish; raise `NotFound` if missing.
2. Compare `expected_updated_at` to `dish.updated_at` → `StaleState`.
3. Validate `CatalogDishUpdate` via domain constructors.
4. If `update.current_unit_net_cents != dish.current_unit_net_cents`:
   - append `CatalogPriceHistoryEntry`
   - resolve `effective_from` (arg or Berlin today)
5. Persist updated `CatalogDish` with new `updated_at`.
6. Return result metadata for API response.

---

## 9. Repository (delta)

Extend `CatalogRepository` protocol:

```python
def update_dish(
    self,
    dish: CatalogDish,
    *,
    expected_updated_at: datetime,
) -> None:
    """Raises StaleStateError if updated_at mismatch; DishNotFound if missing."""

def append_price_history(self, entry: CatalogPriceHistoryEntry) -> None:
    """Insert-only."""
```

6D-1 `insert_dish_if_absent` remains **seed-only** — not exposed via office API.

SQLite implementation: single transaction in write service or repository `update_dish_with_optional_history(...)` — implementation choice, but **one command = one transaction**.

---

## 10. Office panel UI

### 10.1 Navigation (delta over 6D-1)

```text
Verwaltung → Gerichte → [Detail] → Bearbeiten
```

| Route | Method | Purpose |
|---|---|---|
| `/gerichte/{dish_id}` | GET | Detail (add «Bearbeiten» link) |
| `/gerichte/{dish_id}/edit` | GET | Edit form |
| `/gerichte/{dish_id}/update` | POST | Submit command (CSRF + command envelope) |

Remote mode: panel POST → Core API command (same as inquiry update).

### 10.2 Edit form fields

```text
Name                    [text]
Beschreibung            [textarea]
Zusammensetzung         [textarea]
Notizen                 [textarea]        (optional, detail-only in 6D-1)

Preis netto             [text]  8,50 €    (display + parse German decimal → cents)

Allergene               [☑ A Gluten] … [☑ N Weichtiere]   (14 checkboxes)

Aktiv                   [☑]

Gültig ab (Preis)       [date]            (shown always; applied only when price changes)

[Speichern]
```

Hidden fields (write envelope):

- `_csrf_token`
- `_command_id`
- `_expect_updated_at` (from detail payload)

### 10.3 Detail history block (after save)

Replace placeholder «noch keine» with formatted audit list:

```text
Preisänderungen:
  8,50 € → 9,00 €   (01.08.2026, office)
```

Use existing `format_catalog_price_eur` for display. HTML-escape all text.

### 10.4 UI exclusions (unchanged)

- No «Neues Gericht» button
- No edit link from Order / Offer / Print pages
- No delete dish

---

## 11. Remote client parity

Add to `RemoteCoreClient`:

```python
def update_catalog_dish(
    self,
    dish_id: str,
    *,
    args: dict[str, object],
    expected_updated_at: datetime,
    command_id: str,
) -> dict[str, object]: ...
```

Validate response keys mirror API success shape. Remote panel edit flow must pass idempotency + concurrency fields through `_Remote*` facade or direct client call (match inquiry pattern).

---

## 12. Persistence

**No schema migration required** — 6D-1 tables already include all columns.

Optional index review only (no change expected):

- `idx_catalog_price_history_dish_changed` already supports history list

---

## 13. Open items (frozen defaults for implementation)

| Item | 6D-2 default |
|---|---|
| Create new dish API | **Deferred** — seed + manual SQL for dev; «Neues Gericht» UI in later slice |
| Delete / archive dish | **Deferred** — use `active=false` |
| `changed_by` value | `"office"` |
| `effective_from` when price unchanged | Ignored; not stored |
| `effective_from` when price changes, field empty | `berlin_today()` |
| Price input parsing | Accept `8,50` / `8.50` / `850` cents in form; API always cents |
| Edit inactive dishes | **Allowed** |
| Max history rows on detail | 20 (existing cap) |
| Notes field on edit form | **Included** (already in DB) |

---

## 14. File plan (implementation guide)

| Layer | New / changed files |
|---|---|
| Domain | `domain/catalog.py` — optional `CatalogDishUpdate`, errors |
| Repository | `catalog_repository.py`, `sqlite_catalog_repository.py` — update + append |
| Service | `catalog_dish_write_service.py` (new) |
| API | `office_api.py` — `cmd_update_catalog_dish`, route registration |
| API views | `office_api_views.py` — unchanged read shapes |
| Panel edit | `office_panel_catalog_edit.py` (new) |
| Panel detail | `office_panel_catalog_detail.py` — Bearbeiten link, history formatting |
| Panel HTTP | `office_panel_http.py` — `/edit`, POST `/update` |
| Panel core | `office_panel.py` — render + command dispatch |
| Remote | `remote_core_client.py` — update command + validation |
| Tests | domain, repository, service, API, panel, remote parity, **Offer regression** |

**Do not touch** in 6D-2:

- `order_print_projection_service.py`
- `buffet_cards_service.py`
- `offer_service.py` position mapping (except regression test fixture)
- Configurator / `items.json` paths
- Seed script update semantics

---

## 15. Tests (required before merge)

### 15.1 Domain / write service

- `test_update_text_fields_no_history`
- `test_update_price_appends_history`
- `test_update_same_price_no_history`
- `test_update_allergens_validates_codes`
- `test_update_stale_updated_at_rejected`

### 15.2 Repository

- `test_sqlite_update_dish_roundtrip`
- `test_sqlite_append_price_history_read_back`
- `test_sqlite_concurrent_update_second_fails`

### 15.3 API

- `test_update_catalog_dish_command_success`
- `test_update_catalog_dish_stale_state_409`
- `test_update_catalog_dish_validation_422`
- `test_update_catalog_dish_idempotent_command_id`

### 15.4 Panel

- `test_gericht_edit_form_renders`
- `test_gericht_update_post_success`
- `test_gericht_detail_shows_price_history`
- `test_catalog_edit_html_escaping`
- `test_gericht_edit_direct_remote_parity`

### 15.5 Regression (commercial isolation)

- `test_offer_position_unchanged_after_catalog_price_update`

Setup: create Offer with `OfferPosition.unit_net_cents=850` linked to a catalog dish id (or parallel fixture). Update catalog dish to 900. Assert stored OfferPosition still 850.

---

## 16. Acceptance criteria

6D-2 is **done** when:

1. Büro can edit an existing dish via panel (direct + remote) with Speichern.
2. Price change appends exactly one `PriceHistory` row and updates `current_unit_net_cents`.
3. Text-only edit does not append history.
4. Optimistic concurrency returns `409 stale_state` on conflict.
5. Detail shows price history list when rows exist.
6. Existing OfferPosition prices unchanged after catalog update (regression test).
7. No changes to Offer prepare path, Print projection, or Configurator runtime.
8. Full unit suite passes.

Suggested commit message (implementation only):

```text
Add catalog dish editing and price history
```

Single commit — do not mix with 6D-3 snapshot work.

---

## 17. Roadmap after 6D-2

```text
6D-2  Catalog Editing + PriceHistory append   ← this pack
6D-3  Snapshot V2 — allergens on OfferPosition at prepare-offer
      Configurator reads Catalog API (migration slice)
6E    Print enrichment — Buffetschilder/Küchenzettel allergen badges from snapshot
```

Data flow target (unchanged from 6D-0):

```text
CatalogDish (live Stammdaten, Büro-owned)
        ↓ snapshot at prepare-offer (6D-3)
OfferPosition (immutable commercial copy)
        ↓ ConversionLink
OrderPrintProjection
        ↓
Küchenzettel / Buffetschilder
```

6D-2 establishes **mutable Catalog** without yet wiring Configurator or snapshots.

---

## 18. References

| Doc | Path |
|---|---|
| Catalog scope (6D-0) | `docs/proposals/CATALOG_SCOPE_V1.md` |
| Catalog read model (6D-1) | `docs/proposals/CATALOG_READ_MODEL_6D1.md` |
| Print bundle (6C) | `docs/proposals/PRINT_PROJECTION_SCOPE_V1.md` |
| Command envelope | `src/catering_system/ui/office_api.py` — `_COMMANDS`, ledger |
| 6D-1 implementation | `c8662ad` — domain, repo, panel read routes |

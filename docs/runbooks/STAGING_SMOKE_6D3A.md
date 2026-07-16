# 6D-3a Staging Smoke Test

Manual runbook for the first **business-critical cross-system path**:

```text
Catalog (Büro)
      ↓ GET
Configurator Adapter
      ↓
OfferSnapshot V2
      ↓ prepare-offer
Core OfferPosition (immutable)
      ↓ ConversionLink
Order
      ↓
Print Projection (Küchenzettel / Buffetschilder)
```

**Purpose:** confirm the vertical slice works in staging with real UI and office workflow — not only unit/e2e tests.

**Prerequisite design:** [CATALOG_SNAPSHOT_V2_6D3.md](../proposals/CATALOG_SNAPSHOT_V2_6D3.md)

**Out of scope for this smoke (later slices):**

- Allergen badges on Küchenzettel / Buffetschilder → **6E**
- Runtime removal of `items.json` → **6D-3b** (only after green smoke here)
- Configurator UI showing Catalog allergens in item cards (snapshot + Offer Detail is authoritative in 6D-3a)

---

## Environment

| Field | Value |
|---|---|
| Date | |
| Tester | |
| Core URL | |
| Configurator URL | |
| Core commit | `silberlöffelcatering` — |
| Configurator commit | `fingerfood-app` — |

### Configurator backend env

```bash
CORE_OFFICE_API_URL=<core-base-url>
CORE_OFFICE_API_TOKEN=<bearer-token>
CATALOG_ADAPTER_STRICT=0   # production-like; fallback allowed
```

### Configurator frontend env

```bash
VITE_API_URL=<configurator-backend-base-url>
```

### API helper (optional)

```bash
export CORE_URL="<core-base-url>"
export TOKEN="<bearer-token>"
export AUTH="Authorization: Bearer $TOKEN"
export CFG_URL="<configurator-backend-base-url>"
```

---

## Recommended test dish

Use a seeded dish that exists in **both** Core Catalog and Configurator `items.json`, so price divergence is easy to spot.

**Option A — price gap (recommended):**

| Field | Value |
|---|---|
| Source id (`items.json`) | `broetchen-mix-1` |
| Catalog `dish_id` | `0aee1cec-c09e-5675-835b-2622af2ddb8a` |
| `items.json` price | 2.30 € (230 Cent) |
| Staging Catalog price (set in Büro) | **12.00 € (1200 Cent)** |
| Allergens (set in Büro) | A, G |
| active | true |

**Option B — Lasagne:**

| Field | Value |
|---|---|
| Source id | `mittagsmenue-m6` |
| Catalog `dish_id` | `728927f2-4265-542b-92d7-cb168e2bc48d` |
| `items.json` price | 16.00 € |
| Staging Catalog price (set in Büro) | **12.00 € (1200 Cent)** |

Fill in the dish used for this run:

```text
Dish name:
Source id:
Catalog dish_id (UUID):
Price (Cent):
Allergens:
Active:
Description:
Composition:
```

Record Offer / Order ids created during this run:

```text
Inquiry id:
Offer A id:          (created at T1)
Offer B id:          (created at T3)
Order id:            (after acceptance, for print)
Order version id:
```

---

# 1. Catalog source

## Setup (Büro)

1. Open Office Panel → **Verwaltung → Gerichte**
2. Open the test dish → **Bearbeiten**
3. Set price **1200 Cent**, allergens **A + G**, `active = true`
4. Fill **description** and **composition** with distinct smoke-test text (e.g. prefix `SMOKE-6D3A-`)

## API check

```bash
curl -s -H "$AUTH" "$CORE_URL/office/v1/catalog/dishes" \
  | jq '.dishes[] | select(.dish_id=="<dish_id>") | {name, current_unit_net_cents, allergens, active}'

curl -s -H "$AUTH" "$CORE_URL/office/v1/catalog/dishes/<dish_id>" \
  | jq '{name, current_unit_net_cents, allergens, allergen_labels, active, description, composition, updated_at}'
```

## Expected

```text
current_unit_net_cents = 1200
allergens              = ["A","G"]   (order may vary)
active                 = true
description/composition = SMOKE-6D3A-… values saved in Büro
```

## Result

- [ ] PASS
- [ ] FAIL

Notes:

---

# 2. Configurator source selection

## UI check

1. Open Configurator
2. Search for the test dish by name
3. Confirm it appears in selection
4. Confirm displayed **unit price = 12.00 €** (Catalog), **not** the stale `items.json` price

## API check

```bash
curl -s "$CFG_URL/api/items?search=<name-fragment>" \
  | jq '.[] | select(.id=="<source_id>") | {id, name, price}'
```

## Inactive gate (optional but recommended)

1. In Büro set test dish `active = false`
2. Reload Configurator — dish must **not** appear in new selections
3. Restore `active = true` before continuing

## Expected

```text
Catalog:     1200 Cent  →  Configurator price 12.00
items.json:  230 or 1600 Cent  →  must NOT win when Catalog is up
inactive dish → excluded from list
```

**Note:** Configurator item cards may still show allergen tokens from `items.json` template. For 6D-3a the authority check is **OfferPosition after prepare-offer** (section 3), not the compose UI allergen display.

## Result

- [ ] PASS
- [ ] FAIL

Notes:

---

# 3. Offer creation

## Büro + Configurator flow

1. Create or open an **Inquiry** in Büro
2. Hand off to Configurator (prefill / Core-Anfrage import — `importedInquiryId` must be set)
3. Add the test dish to the offer draft
4. Click **「Angebot in Core vorbereiten」**
5. Confirm success message with Offer id and Snapshot V2

Alternative: `POST /api/offer/prepare` on Configurator backend (same payload as snapshot build).

## Verify in Büro — Offer Detail

1. Open the new Offer in Office Panel
2. Section **Positionen (Snapshot)** must show:
   - dish name
   - **1200 Cent** (or formatted €)
   - allergen badges **A, G** (or labels Gluten / Milch)
   - description / composition from Catalog snapshot

## API check

```bash
curl -s -H "$AUTH" "$CORE_URL/office/v1/offers/<offer_id>" \
  | jq '.versions[0].variants[0].positions[0] | {
      name, catalog_item_id, unit_net_cents,
      allergens, allergen_labels, allergens_unknown,
      description, composition
    }'
```

## Expected

```text
unit_net_cents   = 1200
catalog_item_id  = <dish_id UUID>
allergens        = ["A","G"]
description      = text from Catalog at prepare-offer time
composition      = text from Catalog at prepare-offer time
schema_version   = 2 (via prepare flow / snapshot)
```

## Result

- [ ] PASS
- [ ] FAIL

Notes:

---

# 4. Price isolation

**Most important test.** Proves Price Authority:

```text
Catalog.current_unit_net_cents → OfferSnapshot → OfferPosition
(not items.json, not live Catalog after snapshot)
```

## Timeline

### T1 — baseline

```text
Catalog:  1200 Cent
Action:   create Offer A via Configurator → Core prepare-offer
Offer A:  unit_net_cents = 1200
```

Record Offer A id: ____________________

### T2 — Catalog price change

In Büro → Gerichte → Bearbeiten → set price to **1500 Cent**.

Confirm via API:

```bash
curl -s -H "$AUTH" "$CORE_URL/office/v1/catalog/dishes/<dish_id>" \
  | jq '.current_unit_net_cents'
# → 1500
```

Check **Preishistorie** on dish detail shows the new entry.

### T3 — new offer

Create **Offer B** with the same dish (new Inquiry or new prepare-offer).

```text
Offer B:  unit_net_cents = 1500
```

### Verification

```bash
# Offer A — must still be 1200
curl -s -H "$AUTH" "$CORE_URL/office/v1/offers/<offer_a_id>" \
  | jq '.versions[0].variants[0].positions[0].unit_net_cents'

# Offer B — must be 1500
curl -s -H "$AUTH" "$CORE_URL/office/v1/offers/<offer_b_id>" \
  | jq '.versions[0].variants[0].positions[0].unit_net_cents'
```

Also re-open Offer A in Büro UI — price unchanged.

## Expected

```text
Offer A = 1200   ✅
Offer B = 1500   ✅
```

**FAIL on this section blocks 6D-3b.**

## Result

- [ ] PASS
- [ ] FAIL

Notes:

---

# 5. Snapshot immutability after Catalog change

After T2/T3, change **non-price** Stammdaten in Catalog:

```text
description  → new text (e.g. SMOKE-6D3A-DESC-v2)
composition  → new text
allergens    → e.g. add C (Ei) or remove G
```

Create **Offer C** (new prepare-offer).

## Verify

| Offer | Expected |
|---|---|
| Offer A (old) | original description, composition, allergens — **unchanged** |
| Offer C (new) | new description, composition, allergens from Catalog at C's prepare-offer |

```bash
curl -s -H "$AUTH" "$CORE_URL/office/v1/offers/<offer_a_id>" \
  | jq '.versions[0].variants[0].positions[0] | {description, composition, allergens}'

curl -s -H "$AUTH" "$CORE_URL/office/v1/offers/<offer_c_id>" \
  | jq '.versions[0].variants[0].positions[0] | {description, composition, allergens}'
```

## Expected

```text
Old offer → frozen snapshot values
New offer → current Catalog values at prepare-offer
```

## Result

- [ ] PASS
- [ ] FAIL

Notes:

---

# 6. Print projection

Proves Print reads **OfferPosition via OrderPrintProjection**, not live Catalog.

## Setup

1. Accept **Offer A** (or any offer with known snapshot texts) → creates Order + ConversionLink
2. Open Order in Büro

## UI check

- **Küchenzettel** (`/order/{order_id}/print?version=…`) — dish **name** matches OfferPosition
- **Buffetschilder** (`/order/{order_id}/buffet-cards?version=…`) — **name, description, composition** match Offer snapshot

Then change Catalog description for the dish and reload Print — **must not change** for the existing Order.

## API check

```bash
curl -s -H "$AUTH" \
  "$CORE_URL/office/v1/orders/<order_id>/print-data?version=<order_version_id>" \
  | jq '.projection.commercial.positions[] | {name, description, composition}'

curl -s -H "$AUTH" \
  "$CORE_URL/office/v1/orders/<order_id>/buffet-cards-data?version=<order_version_id>" \
  | jq '.cards[] | {name, description, composition}'
```

## Expected

```text
Order → ConversionLink → OfferPosition snapshot
NOT Order → live Catalog JOIN

name / description / composition = Offer A snapshot values
```

**Not expected in 6D-3a:** allergen lines on Küchenzettel or Buffetschilder (→ 6E).

## Result

- [ ] PASS
- [ ] FAIL

Notes:

---

# 7. Fallback test

Simulate Catalog unavailable while keeping Configurator up.

## Procedure

1. On Configurator backend, temporarily point to unreachable Core Catalog:

   ```bash
   CORE_OFFICE_API_URL=http://127.0.0.1:1   # or invalid host
   CATALOG_ADAPTER_STRICT=0
   ```

   Restart Configurator backend.

2. Open Configurator — Angebot creation must **still work** using `items.json`.

3. Check backend logs for warning, e.g.:

   ```text
   catalog list failed, using items.json fallback
   catalog adapter warnings: …
   ```

4. Optional API: price should come from `items.json` for the test dish.

5. **Restore** valid `CORE_OFFICE_API_URL` and restart before continuing.

## Expected

```text
Configurator continues
warning logged
source = items_json (or mixed)
whole Angebot not blocked
```

## Result

- [ ] PASS
- [ ] FAIL

Notes:

---

# 8. Strict mode

Proves migration/CI gate — fallback disabled.

## Procedure

1. Set on Configurator backend:

   ```bash
   CATALOG_ADAPTER_STRICT=1
   CORE_OFFICE_API_URL=http://127.0.0.1:1   # Catalog unreachable
   ```

2. Restart backend.

3. Attempt compose / calculate / prepare — must **fail** (no silent fallback).

4. Restore env:

   ```bash
   CATALOG_ADAPTER_STRICT=0
   CORE_OFFICE_API_URL=<valid core url>
   ```

## Expected

```text
offer creation blocked or catalog error surfaced
no silent items.json fallback
```

## Result

- [ ] PASS
- [ ] FAIL

Notes:

---

# 9. Büro workflow (visual)

End-to-end office tool check — turns correct code into a usable backoffice.

Walk through **with eyes on the UI**:

```text
Verwaltung
  → Gerichte
  → dish detail (Allergene, Preis, aktiv)
  → Bearbeiten
  → Preis ändern (1200 → 1500)
  → save
  → dish detail: Preishistorie shows new row
  → Inquiry
  → Configurator handoff
  → compose offer with test dish
  → Angebot in Core vorbereiten
  → Offer Detail: Positionen (Snapshot) + Allergene
  → (optional) acceptance → Order → Küchenzettel / Buffetschilder
```

## Expected

- Navigation under **Verwaltung → Gerichte** works without errors
- Price history visible after edit
- Offer Detail shows snapshotted positions (not live Catalog join)
- No confusing duplicate prices between Configurator list and Offer Detail

## Result

- [ ] PASS
- [ ] FAIL

Notes:

---

## Go / No-Go for 6D-3b

6D-3b (remove runtime `items.json` from Configurator compose path) is allowed only when:

- [ ] **Catalog price authority confirmed** (section 2 + 4)
- [ ] **Snapshot immutability confirmed** (sections 4 + 5)
- [ ] **Print reads snapshot only** (section 6)
- [ ] **Fallback behaviour confirmed** (section 7)
- [ ] **Strict mode confirmed** (section 8)
- [ ] **Büro workflow usable** (section 9)

All critical sections **1–6** must PASS. Sections **7–9** strongly recommended.

### If green

Proceed to **6D-3b** in two phases:

1. **Phase 1:** deprecated warning + metrics when fallback used; monitor staging/prod
2. **Phase 2:** remove fallback loader, JSON price, JSON item selection — Catalog API only (`items.json` remains seed source via `scripts/seed_catalog_from_items.py`)

### If red

Do **not** start 6D-3b. File issues against the failing section; automated coverage:

| Area | Test location |
|---|---|
| Catalog → snapshot → Core | `fingerfood-app/backend/tests/test_prepare_offer_e2e.py` |
| Offer detail allergens | `silberlöffelcatering/tests/unit/test_offer_detail.py` |
| prepare-offer V2 persist | `silberlöffelcatering/tests/unit/test_office_api.py` |
| Catalog adapter / fallback | `fingerfood-app/backend/tests/test_catalog_adapter.py` |

---

## Sign-off

```text
Overall result:  PASS / FAIL
Signed:          ____________________
Date:            ____________________
Follow-up:       ____________________
```

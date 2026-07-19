# OFFICE_CALL_CONTACT_LINKAGE_AUDIT_PACK_V1

**Workstream:** OFFICE_CALL_CONTACT_LINKAGE_V1 — Phase 1 (read-only domain audit and design boundary)
**Date:** 2026-07-19
**Host audited:** `debiancatering` (Lenovo `100.109.6.74`)
**Mode:** read-only — no code, DB, runtime, HubSpot, or service changes

---

## 1. Current-state audit (repository and runtime)

### 1.1 Core (`silberloeffel-catering`)

| Item | Value |
|---|---|
| Path | `/home/viktor/projects/silberloeffel-catering` |
| HEAD / origin/main | `28c0418b1cb37fabe6796026b23a8b5aada1b181` |
| Git status | clean (`main...origin/main`) |
| Primary DB | `/home/viktor/catering-runtime/core.db` (SQLite, shared by API/panel/kiosk/intake) |

**Active services (operational truth entry points):**

| Unit | Bind | Role |
|---|---|---|
| `catering-office-api.service` | `100.109.6.74:8084` | Core Office API (Tailscale, bearer) — **write path for remote panel** |
| `catering-office-panel.service` | `:8081` | Office Panel (LAN, Basic Auth) |
| `catering-kiosk.service` | `:8082` | Kitchen kiosk (read-only) |
| `catering-website-intake.service` | `127.0.0.1:8083` | Website intake |

Config: `/etc/catering/*.env` (values not audited).

### 1.2 Auerswald canonical

| Item | Value |
|---|---|
| Path | `/home/viktor/projects/auerswald-sync-canonical` |
| HEAD / origin/main | `b602988efcf4f2bb466630b56324e868d2230ea3` |
| Git status | clean |
| Active runtime (not git) | `/home/viktor/docker/auerswald-sync` — bind mount, **must not be treated as source of truth for office actions** |
| Container | `auerswald-sync-auerswald-sync-1` — `:8000` |
| Sync | cron `*/5` → locked wrapper → original sync script |

### 1.3 Architectural rules (accepted as binding)

1. Operational truth lives only in Core.
2. Office Panel is controlled entry into Core.
3. A call does **not** create an Order directly.
4. New orders only via **Inquiry → Order**.
5. Phone is an existing `inquiry_source=phone` channel.
6. Calls do **not** directly affect OrderVersion, wirksam, Kitchen Print, READY_TO_SEND, STORNO.
7. Auerswald is a **fact source**, not final operational truth for office actions.
8. HubSpot is a **disabled optional adapter** — no outbound required, not operational truth.
9. No new Contact/Customer/CallRecord entity without proof existing model is insufficient.
10. No parallel CRM beside Core.

---

## 2. Existing Core models (customer / inquiry / order)

### 2.1 Is there a full Customer or Contact entity?

| Concept | Exists? | Notes |
|---|---|---|
| **Customer (CRM aggregate)** | **No** | Only opaque `customer_id` string inside `customer_linkage` |
| **Contact (persisted)** | **No** | |
| **ContactProjection** | **Yes (read-only)** | `domain/contact_projection.py`, `ContactProjectionService` — aggregates Inquiries by derived identity |
| **Order contact fields** | **No** | Order/OrderVersion hold operational event fields only |

### 2.2 What is `customer_linkage`?

**Definition:** `CustomerLinkage` TypedDict in `domain/inquiry.py`:

- Optional keys: `customer_id`, `contact_id`, `placeholder: True`
- Validated by `validate_customer_linkage()` — only allowed keys/types

**Meaning today:**

- **Infrastructure for opaque external references**, not a Core-owned contact record.
- `customer_linkage_indicates_known_client()` (`domain/customer_verification.py`): known if non-empty `customer_id` or `contact_id`; `placeholder` alone ≠ known.
- **All production create paths write `{}`** (office panel, office API, website intake, remote client).
- Office API `update_inquiry` does **not** accept linkage updates.
- `CustomerVerificationService` (B4) exists with `evaluate(phone_matched=..., email_matched=...)` but is **not wired** to intake or Rückruf flow.

**Conclusion:** `customer_linkage` is **not** a contact model — it is an **unused linkage slot** awaiting operational wiring.

### 2.3 Where are Inquiry contact data stored?

- **No structured name/phone/email/company fields** on `Inquiry`.
- Contact hints live in freeform **`intake_message`** (labelled lines: `Telefon:`, `E-Mail:`, `Firma:`, `Name:`) parsed by `parse_intake_contact()` in `intake/intake_contact.py`.
- `intake_subject`, `intake_summary`, `intake_external_ref` — channel metadata, not CRM identity.

### 2.4 Are contact data copied to Order on conversion?

**No.** `OrderService.convert_inquiry_to_order()` copies only operational fields to `OrderVersion` v1. Intake and linkage are explicitly **not** copied (documented in `Inquiry` domain comments). Order title in UI comes from linked Inquiry `intake_subject` via join.

### 2.5 Phone normalization and search

| Capability | Status |
|---|---|
| Normalization | `normalize_phone()` in `intake/intake_contact.py` — digits, `+49`, `00→+`, strip |
| Multiple phones per client | **No model** — one phone line per Inquiry message; projection groups by single derived identity |
| Search by phone (Inquiry list) | **No** — search fields exclude phone |
| Search by phone (Contact list) | **No query API** — full scan + aggregate |
| Merge/deduplication | **Projection-only** via `derive_contact_identity()`; no persisted merge |
| Create client without Inquiry | **No** — only Inquiry create paths |

### 2.6 Identity derivation (`derive_contact_identity`)

Priority (first match wins):

1. `linkage:contact:{contact_id}`
2. `linkage:customer:{customer_id}`
3. `intake:email:{normalized}`
4. `intake:phone:{normalized}`
5. fallback `inquiry:{inquiry_id}`

**Implication:** wiring `customer_linkage` changes projection grouping without a separate Contact table.

### 2.7 Invariants that must not be broken

- Inquiry → Order is the only order creation path.
- `call_verification_required` / `call_verification_status` gate conversion when required.
- OrderVersion / wirksam / READY_TO_SEND / STORNO rules unchanged by telephony slice.
- Remote panel never opens `core.db` directly — all writes via Office API.
- Kiosk remains read-only.

---

## 3. Phone inquiry flow (`inquiry_source=phone`)

### 3.1 Channels

| Source | Entry | Default verification |
|---|---|---|
| `phone` | `intake/phone_adapter.py` → `create_inquiry` | `call_verification_required=True`, status `pending` |
| `phone_by_office` | Office Panel dropdown | user checkbox |
| `missed_call`, `ai_telefonist` | adapter-only labels | not in office dropdown |

Office sources: `manual`, `phone_by_office`, `email`, `website_form`, `configurator`.

### 3.2 Office actions before Inquiry exists

- Rückruf list shows missed calls from Auerswald (when integration works).
- **No Core record** for the call until Inquiry is created.
- Link `GET /inquiry/new?phone=...` is a **UI hint only** — phone is **not** written to Inquiry automatically.

### 3.3 Verification gate

- `inquiry_allows_order_conversion()` blocks if verification required and not `verified`.
- `POST /inquiry/{id}/verify` or API `POST .../verify` → `InquiryService.verify_customer_by_call()` sets status `verified`, emits `CustomerCallVerified`.

### 3.4 Duplicate Inquiry from one call

- **No idempotency** linking Auerswald `call_id` to Inquiry.
- `find_by_source_and_external_ref()` exists on repository but **phone/missed paths do not set** `intake_external_ref` to call key.
- Office can create multiple Inquiries from the same Rückruf row manually.

### 3.5 Link call to existing Inquiry

- **Not implemented.** Resolve on Auerswald side only marks call dismissed in `resolved_missed_calls.json` — no Core linkage.

---

## 4. Auerswald call / CDR contract

### 4.1 Data source

- Files: `app/data/gespr_dat.csv` + `.gz` (30-day filtered snapshot).
- Pipeline: PBX export → full replace gz → csv → `filter_last_30_days.py` → optional Strato scp.
- **Not immutable archive** — rows drop after 30 days; full export replace each sync cycle.

### 4.2 CSV schema (field names only)

TSV, latin1/utf-8. Relevant columns:

| Semantic | Column |
|---|---|
| Vendor row id | `LfdNr` |
| Date / time | `Datum`, `Uhrzeit` |
| Duration | `Dauer` (`HH:MM:SS` → seconds in code) |
| Phone | `Externer Partner` |
| Direction | `Richtung` (`kommend` / `gehend`) |
| Billing / answered | `Abrg.art` (`vergebl` = missed incoming) |
| Extension / participant | `Tn-Nr.real`, `Anschluss-Nr.`, etc. |

### 4.3 Stable call ID

| Mechanism | Used for | Stability |
|---|---|---|
| **`LfdNr`** | Present in every row, unique in snapshot | **Not used in app logic**; may change on full re-export if vendor renumbers |
| **Missed board `call_id`** | `Datum \| Uhrzeit \| normalize_phone(Partner)` | **Composite, no vendor id**; collision if same second + same number |
| **HubSpot task key** | adds `\| Dauer` | **Different** from missed-board key |

**Conclusion:** There is **no adopted stable external call identifier** in operational linkage today.

### 4.4 Resolve / follow-up state (Auerswald-local, not Core)

- `resolved_missed_calls.json`: `{ "resolved_call_ids": [...] }` — append-only set, no TTL.
- Written by `POST /missed/resolve`, `/missed/resolve-bulk`.
- `synced_hubspot_tasks.json`: legacy HubSpot idempotency map — **not used** by missed board or Office Panel.

### 4.5 API surface (port 8000)

Notable routes: `/calls`, `/missed-board`, `/missed/resolve`, `/hubspot/*` (legacy).
**Gap:** Office Panel expects **`GET /missed-board.json`** — **404 on live** `:8000` (integration broken for JSON client).

HubSpot contact on missed board: **stub** (`Unbekannt`, no API call while rendering board).

### 4.6 Retention and mutability

- CDR: rolling 30 days in Auerswald files.
- Resolved IDs may reference calls **evicted** from CDR — resolve state outlives CDR row.
- Core must persist call facts if history beyond 30 days is required post-cutover.

---

## 5. Office Panel integration today

### 5.1 Rückruf count

- `fetch_rueckruf_count()` → `fetch_missed_board()` → `GET {AUERSWALD_SYNC_URL}/missed-board.json?limit=100` (sidebar badge: `None` on error/unconfigured, **`0` when the board is reachable but empty**).
- Count = `len(items)`; **`None`** if misconfigured / error → badge hidden (not zero).
- Dual source in UI v2 contract: (1) Auerswald missed board, (2) Inquiries with `next_action==verify` from intake phone lines.

### 5.2 Server-side integration module

`src/catering_system/integration/auerswald_sync.py`:

- `fetch_missed_board()`, `resolve_missed_call()`, `count_open_missed_calls()`
- Config: `AUERSWALD_SYNC_URL`, `AUERSWALD_SYNC_USER`, `AUERSWALD_SYNC_PASSWORD`

### 5.3 Routes

| Route | Behavior |
|---|---|
| `GET /rueckruf` | Render missed board |
| `POST /rueckruf/resolve` | Proxy to Auerswald `POST /missed/resolve` |
| `GET /inquiry/new?phone=` | Hint for new Inquiry form |

Remote Core mode without `auerswald_url`: Rückruf list unavailable message.

### 5.4 Linkage to Inquiry / customer

- **No automatic linkage.**
- Resolve does **not** write to Core.
- `contact_found` / `contact_name` from Auerswald payload — currently always false / unknown (HubSpot stub).
- Schema mismatch: Panel expects optional **`reason`** field; Auerswald builder omits it.

### 5.5 HubSpot in Panel

- No active HubSpot outbound in Rückruf workflow.
- Legacy HubSpot routes remain in Auerswald app for rollback only.

---

## 6. Violations and gaps

| # | Gap | Severity |
|---|---|---|
| G1 | **`GET /missed-board.json` missing** — Panel client broken on live Auerswald | Critical (current ops) |
| G2 | **No stable call ID adopted** — composite keys differ between subsystems | **Blocks idempotent Core linkage** |
| G3 | **`customer_linkage` always `{}`** — linkage infrastructure unused | High |
| G4 | **Auerswald resolve ≠ Core** — office dismisses call outside operational truth | High |
| G5 | **No phone search / auto-match** on Inquiry create from call | Medium |
| G6 | **B4 verification service unwired** | Medium |
| G7 | **CDR 30d + full replace** — historical calls need Core persistence post-cutover | Medium |
| G8 | **`reason` field / legacy UI text** inconsistencies | Low |
| G9 | **Auerswald :8000** may lack APP_PASSWORD if URL reachable | Security note |

**No violation** of Core Order/inquiry invariants found in current design — problem is **missing linkage layer**, not wrong Order shortcuts.

---

## 7. Minimal architectural options

### Option A — Extend existing models only (recommended if call ID resolved)

**Scope:**

- Add minimal Core fields (e.g. on Inquiry or small side table): `external_call_source`, `external_call_key`, optional `linked_contact_key`.
- Wire `customer_linkage` on confirmed manual match (store opaque ids or `contact_key`).
- Office Panel commands: link call → Inquiry, create `Inquiry(inquiry_source=phone|phone_by_office)`, mark follow-up in Core.
- Auerswald: add JSON board endpoint; after cutover Panel stops writing Auerswald JSON.

| Pros | Cons |
|---|---|
| No parallel CRM | Requires careful idempotency on `external_call_key` |
| Reuses verification + conversion gates | `customer_linkage` semantics must be documented |
| ContactProjection gains real grouping | Migration for new columns |
| Smallest operational truth surface | |

**Operational truth:** Core owns linkage + follow-up; Auerswald owns raw CDR feed.

### Option B — One minimal Core entity: `PhoneCallFact` (or similar)

**Scope:** Immutable fact row: source, external key, normalized phone, timestamps, direction, answered flag; mutable office follow-up fields separate or on Inquiry FK.

| Pros | Cons |
|---|---|
| Clear audit trail beyond 30d CDR | New table + repository + API |
| Idempotent ingest from Auerswald | More migration/testing |
| Multiple Inquiries per call possible (explicit FK) | Risk of scope creep toward CRM |

### Option C — Split immutable event + mutable follow-up

Only if Option A cannot express: (1) one call → many office actions, (2) history after CDR eviction, (3) concurrent office edits — **without** overloading Inquiry.

| Pros | Cons |
|---|---|
| Clean event sourcing boundary | Highest complexity |
| Best for retention/concurrency | Two entities to maintain |

**Recommendation:** **Option A first**, with explicit **`external_call_key`** column(s) and optional promotion to Option B only if retention/concurrency tests fail Option A.

**Do not auto-select Option C.**

---

## 8. Domain boundary (target)

| Layer | Responsibility |
|---|---|
| **Auerswald** | Raw CDR ingest, 30d file, transitional UI, PBX sync, optional read API for Core/Panel backend |
| **Core** | Call fact persistence (minimal), customer/Inquiry linkage, follow-up status, verification, idempotency, long-term history |
| **Office Panel** | Display, controlled Core commands, create phone Inquiry, pick existing contact, no direct Auerswald JSON writes post-cutover |

---

## 9. Matching rules (proposed, post-audit)

Compatible with existing `customer_linkage` **if** linkage stores `contact_key` or opaque ids after office confirmation:

1. Normalize phone (`normalize_phone()` — already in Core).
2. Exact match against parsed phones from open/recent Inquiries and ContactProjection aggregates.
3. **One match** → suggest linkage; apply only after office confirmation command.
4. **Multiple matches** → ambiguous UI; no auto-link.
5. **No match** → unmatched; office creates phone Inquiry with required intake fields.
6. **No fuzzy matching.**
7. **No auto-create customer** from call alone.
8. Manual linkage persisted in Core (`customer_linkage` and/or `external_call_key` on Inquiry).
9. Client phone number changes must not orphan historical calls (immutable `normalized_phone_at_call_time` on fact or Inquiry snapshot).

**`customer_linkage` compatibility:** use `contact_id`/`customer_id` as opaque keys **after** office confirms mapping to a `contact_key`; do not treat empty linkage as identity.

---

## 10. Inquiry integration scenarios

| Scenario | Safe flow |
|---|---|
| Known customer + open Inquiry | Link call to Inquiry + contact_key; optional verify if required |
| Known customer, no Inquiry | Office: **Neue Anfrage anlegen** → `Inquiry(inquiry_source=phone_by_office or phone)` with intake fields |
| Unknown caller | Office enters contact lines in intake_message → standard phone Inquiry create |
| Multiple matches | Manual pick contact/Inquiry before linkage completes |
| Order needed | Only after Inquiry exists and passes conversion gates — **never from call directly** |

**Second Inquiry from same call:** blocked by unique `(external_call_source, external_call_key)` if Option A/B implements idempotency; otherwise explicit office override with audit.

---

## 11. Idempotency and retention

| Topic | Design direction |
|---|---|
| External key | `(source=auerswald, key=<TBD: LfdNr or approved composite>)` |
| Duplicate import | Upsert fact by key; do not duplicate Inquiries |
| Immutable fields | external key, call timestamp, normalized phone at event, direction |
| Mutable fields | office follow-up status, linkage to Inquiry |
| After CDR eviction | Core-retained fact remains; Auerswald row may disappear |
| Core retention | TBD — align with backup/legal; longer than 30d |
| Re-sync | Full CDR replace must not duplicate Core facts if key stable |
| Concurrency | Core commands idempotent; Panel disables double-submit |
| One call → many Inquiries | Discouraged; require explicit break-glass + audit if allowed |

**Prerequisite:** resolve **G2** before implementation.

---

## 12. Privacy and access

| Topic | Direction |
|---|---|
| Storage | Phone numbers in Core DB (Inquiry intake + optional call fact table); Auerswald files remain until cutover |
| Display | Masked in lists where feasible; full number only on detail/actions |
| Audit log | Core command log for linkage/verify/create (no PII in application logs) |
| Roles | Office Panel auth unchanged; API bearer for remote |
| Backup | Auerswald bundles include CDR (PII by design) — already in backup runbook; Core DB in Core backup |
| Export/erase | TBD GDPR process — document in Phase 2 |
| Direct HTTP :8000 | **Do not close in Phase 1**; cutover only after Panel parity + acceptance |

**Future cutover:** users work via Office Panel; backend uses internal Auerswald read API; public :8000 closed after acceptance test.

---

## 13. Migration sequence (high level)

1. **Decision:** adopt call external key (`LfdNr` vs composite) + validate across sync cycles.
2. **Auerswald:** ship `GET /missed-board.json` (+ optional `reason`); no HubSpot on board.
3. **Core schema:** minimal columns or `PhoneCallFact` (per chosen option).
4. **Core API:** commands link-call, create-inquiry-from-call, list unmatched calls (read from Core facts fed by sync job or pull).
5. **Panel:** replace direct Auerswald resolve with Core commands; keep Rückruf UI.
6. **Ingest job:** Core pulls/accepts call facts idempotently (does not replace Order flow).
7. **Cutover:** disable Panel writes to Auerswald JSON; optional close :8000.
8. **Rollback:** Panel flag to use legacy Auerswald resolve; Core facts retained read-only.

---

## 14. Test plan (Phase 2+)

- Unit: `normalize_phone`, external key derivation, idempotent upsert.
- Integration: one call → one Inquiry max; ambiguous match UI command paths.
- Regression: conversion blocked until verify; Order unchanged by call ingest.
- Auerswald: missed-board.json contract tests (no live PBX).
- Panel: Rückruf count None vs 0; remote mode without auerswald_url.
- Security: no PII in logs; API auth on internal routes.

---

## 15. Rollout

1. Deploy Auerswald JSON endpoint (no Core change).
2. Deploy Core linkage behind feature flag.
3. Panel uses Core for resolve/link; parallel read legacy board.
4. Enable ingest + idempotency in production.
5. Monitor duplicate Inquiry rate and Rückruf queue.
6. Cutover write path off Auerswald JSON.

---

## 16. Rollback

- Feature flag → legacy Auerswald resolve.
- Do not delete Core call facts on rollback (read-only archive).
- Timer/sync unchanged during linkage rollback.

---

## 17. Unresolved decisions

| ID | Decision | Owner |
|---|---|---|
| D1 | **External call key:** adopt `LfdNr` vs composite `date|time|phone` vs hybrid | Architecture |
| D2 | Option A vs B for persistence beyond Inquiry | Architecture |
| D3 | Core retention period for call history | Operations / legal |
| D4 | Allow one call → multiple Inquiries (break-glass)? | Product |
| D5 | When to close public :8000 | Operations |
| D6 | Wire `customer_linkage` to `contact_key` convention | Core |
| D7 | Ingest: push from Auerswald vs pull from Core job | Engineering |

---

## 18. Proof of Core rules compliance (target design)

| Rule | How design complies |
|---|---|
| Operational truth in Core | Linkage, follow-up, Inquiry state in Core DB |
| Panel as controlled entry | All writes via Office API / panel POST → Core |
| No Order from call | Commands create/link Inquiry only |
| Inquiry → Order only | Unchanged conversion service |
| Phone as inquiry_source | Reuse `phone` / `phone_by_office` |
| No OrderVersion impact | Call ingest separate from Order commands |
| Auerswald as fact source | CDR ingest only; resolve moves to Core |
| HubSpot disabled | No outbound in linkage slice |
| No parallel CRM | Option A/B extend Inquiry/facts, not new CRM app |

---

## 19. Phase 1 verdict

### **NOT READY — STABLE AUERSWALD CALL ID REQUIRED**

**Primary blocker:** Operational linkage cannot be idempotent until the project **formally adopts** an external call key (`LfdNr` with sync stability proof, or an approved composite with documented collision rules) and persists it in Core.

**Secondary (non-blocking for architecture choice):** **`customer_linkage` wiring decision** — recommend Option A without new Customer entity once D1 is resolved.

**Not selected:** automatic Option B/C without failed Option A proof.

---

### After D1 is resolved

Expected next verdict: **READY FOR MINIMAL OFFICE CALL LINKAGE IMPLEMENTATION** (Option A, Core commands + Panel cutover plan).

---

## Appendix A — Key file references

**Core**

- `src/catering_system/domain/inquiry.py` — Inquiry, CustomerLinkage, verification enums
- `src/catering_system/domain/customer_verification.py` — linkage classification
- `src/catering_system/domain/contact_projection.py` — derive_contact_identity
- `src/catering_system/intake/intake_contact.py` — normalize_phone, parse_intake_contact
- `src/catering_system/intake/phone_adapter.py` — phone channel
- `src/catering_system/services/order_service.py` — convert_inquiry_to_order
- `src/catering_system/integration/auerswald_sync.py` — Rückruf client
- `src/catering_system/ui/office_panel.py` — Rückruf UI, inquiry/new hint
- `src/catering_system/ui/office_api.py` — Core API routes

**Auerswald**

- `app/main.py` — CDR, missed board, resolve, HubSpot legacy routes
- `scripts/sync_auerswald_to_strato.sh` — PBX sync pipeline
- `scripts/filter_last_30_days.py` — retention filter

**Office Panel UI contract (local docs)**

- `office-panel-ui-v2/integration/DATA_CONTRACT.md` — Rückruf dual source, no auto link

---

*End of audit pack — Phase 1 read-only. No production changes performed.*

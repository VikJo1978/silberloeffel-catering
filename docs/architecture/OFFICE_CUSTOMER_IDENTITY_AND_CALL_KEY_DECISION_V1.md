# OFFICE_CUSTOMER_IDENTITY_AND_CALL_KEY_DECISION_V1

**Workstream:** OFFICE_CUSTOMER_IDENTITY_AND_CALL_KEY_DECISION_V1
**Mode:** read-only audit + domain decision + design pack — **no implementation**
**Date:** 2026-07-19
**Host evidence:** `debiancatering` (Lenovo `100.109.6.74`)

**Related prior deliverable:** `OFFICE_CALL_CONTACT_LINKAGE_AUDIT_PACK_V1.md`
- **Location:** `/Users/viktorjohanson/office_panell/docs/OFFICE_CALL_CONTACT_LINKAGE_AUDIT_PACK_V1.md` (workspace deliverable)
- **Not present** in Git repos on Lenovo (`silberloeffel-catering`, `auerswald-sync-canonical`) — out of repo / not committed
- This slice **does not recreate** the audit pack; it extends decisions D1–D2 from that analysis

---

## 1. Current-state evidence

### 1.1 Git repositories (read-only)

| Repo | Path | HEAD | origin/main | Status |
|---|---|---|---|---|
| Core | `/home/viktor/projects/silberloeffel-catering` | `28c0418…` | `28c0418…` | clean |
| Auerswald canonical | `/home/viktor/projects/auerswald-sync-canonical` | `b602988…` | `b602988…` | clean |
| Auerswald runtime | `/home/viktor/docker/auerswald-sync` | — | not git | unchanged |

### 1.2 Runtime paths

| Component | Path |
|---|---|
| Core DB | `/home/viktor/catering-runtime/core.db` |
| Office API | `100.109.6.74:8084` |
| Office Panel | `:8081` |
| Auerswald container | `:8000` |
| Auerswald CDR | `/home/viktor/docker/auerswald-sync/app/data/gespr_dat.csv` (+ `.gz`) |
| Auerswald resolve state | `resolved_missed_calls.json` (7 IDs, legacy composite) |
| Auerswald backup artifacts | `/home/viktor/auerswald-runtime/backups/*.tar.gz` |

### 1.3 Core customer model today (summary)

| Question | Answer |
|---|---|
| Full Customer/Contact entity? | **No** — only `ContactProjection` (read-only aggregate) |
| `customer_linkage` | TypedDict slot; **all 33 production rows = `{}`** (empty JSON object) |
| Structured phone on Inquiry? | **No** — optional `Telefon:` line in `intake_message` (0/33 have it) |
| Phone normalization | `normalize_phone()` exists in `intake/intake_contact.py` |
| Order carries contact? | **No** — operational fields only; title via linked Inquiry |
| B4 verification service | Exists, **not wired** to intake or Rückruf |

### 1.4 Auerswald call identity today

| Mechanism | Used in product? |
|---|---|
| CSV column `LfdNr` | Present (1…N per export), **not used in call_id** |
| Missed `call_id` | `Datum \| Uhrzeit \| normalized_phone` |
| Task `call_id` | above + `Dauer` |
| `GET /missed-board.json` | **Missing (404)** — compatibility defect, separate slice |

### 1.5 Production DB dry-run (aggregate, no PII)

| Metric | Value |
|---|---|
| Total inquiries | 33 |
| `inquiry_source=phone` | 1 |
| `Telefon:` in intake_message | **0** |
| Parseable normalized phone | **0** |
| `customer_linkage` non-empty string | 33 (all `{}`) |
| Duplicate normalized phones across inquiries | 0 |

**Migration implication:** backfill from `intake_message` alone **cannot** bootstrap phone identity; future linkage is **forward-looking** + manual/Auerswald ingest.

---

## 2. Call ID stability evidence (D1 research)

### 2.1 Available snapshots

| Source | Snapshots | Rows | Notes |
|---|---|---:|---|
| Backup tar + live (2026-07-19) | **9** (8 tar + live) | 268 each | **Identical** CSV bytes (`sha256` match) |
| `projects/auerswald-sync/…/gespr_dat.csv` | 1 | 2000 | **Different** export (2026-05-25); **0** fingerprint overlap with live |
| GPG offsite on Lenovo | 2 | encrypted | Not decrypted in this slice |
| VPS remote CSV | 0 | — | hostname unresolved from Lenovo |

**Critical gap:** no two snapshots with **overlapping call fingerprints** at different times → **cannot prove** LfdNr stability across re-export cycles on production data.

### 2.2 Row fingerprint method (no PII)

`fingerprint = sha256(Datum | Uhrzeit | sha256(normalized_phone) | Dauer | Richtung | Abrg.art)`

### 2.3 Findings

| # | Question | Evidence |
|---|---|---|
| 1 | LfdNr stable for same row between exports? | **Unknown** — 0 overlapping fingerprints between generations |
| 2 | LfdNr reuse after new export? | **0 reuse** within each analyzed file; pattern **1…N sequential** |
| 3 | LfdNr global vs local? | **Local file counter** in each export (no gaps 1…N); **not** proven global |
| 4 | PBX renumber old rows? | **Cannot disprove** — no cross-time overlap data |
| 5 | PBX instance ID in CDR? | **No** — only sync host `debiancatering` in backup manifest |
| 6 | Prove stability on available data? | **Only within frozen 268-row snapshot** (100% stable); **not** cross-export |
| 7 | Collision cases | In 2000-row archive: **1 fingerprint → 2 different LfdNr**; live: 268/268 unique both ways |

### 2.4 Resolved ID legacy

- 7 resolved IDs use **3-field** composite (no `Dauer`); **0/7** match current CDR rows by same rule → stale after CDR churn.

---

## 3. D1 options

### D1-A — `auerswald:<pbx_instance_id>:<LfdNr>`

| Criterion | Assessment |
|---|---|
| Idempotency | Good **within one frozen export** |
| Collision risk | Low per file; **reuse across exports unproven** |
| Row mutation | If PBX renumbers, key breaks |
| Re-export | Full replace may reassign LfdNr |
| Legacy migration | Would not map to current resolved composites |
| Rollback | Keep composite resolve sidecar |

**Verdict on D1-A:** **Reject as primary key** — insufficient cross-export stability evidence; 1 fingerprint→2 LfdNr counterexample in historical file.

### D1-B — Content fingerprint hash

**Canonical serialization (normative proposal):**

```
v1|instance=<instance_id>|datum=<DD.MM.YY>|uhrzeit=<HH:MM:SS>|phone=<normalized>|dauer=<HH:MM:SS>|richtung=<raw>|abrg=<raw>
→ call_key = sha256(utf-8 canonical)
```

| Field | Rule |
|---|---|
| `instance_id` | Config `AUERSWALD_INSTANCE_ID`, default `debiancatering` until explicit PBX id exists |
| `datum` / `uhrzeit` | Raw CSV strings (Auerswald locale), not reinterpreted TZ |
| `phone` | `normalize_phone(Externer Partner)` — Core-compatible |
| `dauer` | Raw CSV duration string |
| `richtung`, `abrg` | Raw CSV (direction + billing type) |
| Algorithm | SHA-256 hex |
| Missing field | **Reject row** for Core ingest (fail-closed) |
| Mutable fields | Not part of key; stored separately on fact row |
| Collision | Treat as **same call** (idempotent upsert); log audit event if payload differs |

| Criterion | Assessment |
|---|---|
| Idempotency | Strong for same CDR semantics |
| Collision risk | 1 duplicate fingerprint in 2000-row archive (same second+phone scenario) — accept with audit |
| Re-export | Key stable if PBX row content stable |
| Legacy migration | Map old composite → fingerprint key via parse + rehash |
| Rollback | Dual-read old resolve set |

**Verdict on D1-B:** **Accept as primary call key** (with instance namespace below).

### D1-C — LfdNr + fingerprint verification

| Criterion | Assessment |
|---|---|
| Primary | LfdNr per export |
| Verification | Fingerprint mismatch → quarantine row |
| Problem | Same as D1-A for cross-export; adds complexity |

**Verdict on D1-C:** **Reject as primary**; optional **audit field** `lfdnr_at_ingest` on fact row, not part of key.

---

## 4. D1 decision

### Selected: **D1-B with source namespace (D1-C instance element only)**

**External call reference (Core):**

| Component | Value |
|---|---|
| `call_source` | `auerswald` |
| `call_source_instance` | `debiancatering` (configurable `AUERSWALD_INSTANCE_ID`) |
| `call_key` | `sha256(v1 canonical fingerprint)` per §3 D1-B |
| `call_key_version` | `v1` |
| Optional audit | `lfdnr`, `ingested_at`, raw row hash |

**Namespace string (stored):** `auerswald:debiancatering:v1:<call_key>`

**Collision handling:**

1. Upsert by `(call_source, call_source_instance, call_key)`.
2. If upsert matches but mutable fields differ → update fact, append audit.
3. If same fingerprint hash collision with different normalized inputs (theoretical) → block ingest, manual review queue.

**LfdNr:** **Not** primary key; store for operator debugging only.

**Insufficient LfdNr-only evidence:** documented; **does not block** fingerprint-based decision.

---

## 5. Customer identity audit (D2)

### 5.1 Current identification map

| Data | Where today | Structured? |
|---|---|---|
| Client identity | Derived `contact_key` from linkage/intake/inquiry id | Projection only |
| Name | `intake_message` label `Name:` or subject | Partially parsed |
| Phone | `intake_message` `Telefon:` | Parsed if present (**0 in DB**) |
| Email | `intake_message` `E-Mail:` | Parsed if present |
| Company | `intake_message` `Firma:` | Parsed if present |
| Address | Not modeled | No |
| Multiple phones | Not modeled | No |
| One phone → many clients | Possible via separate inquiries | No enforcement |
| Phone update history | Not modeled | No |
| Inquiry → persistent client | `customer_linkage` unused | No |
| Order → client | Via `source_inquiry_id` only | No `customer_id` on Order |

### 5.2 Answers (D2 questionnaire)

| # | Answer |
|---|---|
| 1 | Client identified ad hoc per Inquiry + projection grouping |
| 2 | Name: intake_message / intake_subject |
| 3 | Phone: intake_message label (sparse) |
| 4 | Email: intake_message label |
| 5 | Company: intake_message label |
| 6 | Address: not stored |
| 7 | Multiple numbers: **not supported** |
| 8 | Shared number across clients: **possible**, undetected |
| 9 | Phone update without history loss: **not supported** |
| 10 | Inquiry should reference stable `customer_id`; Order references Inquiry only |
| 11 | Need **CustomerIdentity** (minimal), not full CRM Contact |
| 12 | Need **PhoneContactPoint** (or equivalent) for exact match |
| 13 | Inquiry retains **snapshot** of contact used at intake time |

---

## 6. D2 options

### Option A — CustomerIdentity + ContactPoint (phone/email)

| Aspect | Assessment |
|---|---|
| Minimality | Medium — email points optional phase 2 |
| Risk | Scope creep toward CRM |
| Migration | New tables + backfill mostly empty |
| Inquiry | `customer_id` FK + snapshot JSON |
| Order | No direct customer FK (via Inquiry) |
| Multi-phone | Supported |
| Merge | Requires merge command + audit |
| GDPR | Retention on customer + points |

### Option B — CustomerIdentity + PhoneContactPoint only

| Aspect | Assessment |
|---|---|
| Minimality | **Highest fit** for call linkage slice |
| Risk | Email remains in intake_message until later |
| Migration | Small schema |
| Inquiry | `customer_id` optional + `contact_snapshot` |
| Order | Unchanged |
| Multi-phone | Supported |
| Dedup | Exact normalized phone match |
| Merge | Explicit office command |

### Option C — Extend `customer_linkage` only

| Aspect | Assessment |
|---|---|
| Minimality | Appears small |
| Risk | **Opaque dict is not Core-owned identity**; no phone history; no query index |
| Migration | Cannot enforce invariants |
| Verdict | **Reject** as sole model |

---

## 7. D2 decision

### Selected: **Option B — CustomerIdentity + PhoneContactPoint**

**Proposed minimal entities (names indicative, finalize in implementation slice):**

#### CustomerIdentity

| Field | Purpose |
|---|---|
| `customer_id` | UUID, Core-owned PK |
| `display_name` | Office display (nullable until set) |
| `company_name` | Optional |
| `status` | `active` \| `merged` \| `anonymized` |
| `created_at` / `updated_at` | Audit |

#### PhoneContactPoint

| Field | Purpose |
|---|---|
| `phone_contact_id` | UUID PK |
| `customer_id` | FK |
| `normalized_phone` | Unique among **active** points (configurable) |
| `display_phone` | Optional formatted |
| `status` | `active` \| `historical` \| `invalid` |
| `valid_from` / `valid_to` | History without losing old calls |
| `verified_at` | Optional office confirmation |

**Not in scope:** marketing fields, deals, HubSpot ids as truth, campaigns.

**`customer_linkage` future role:** store `customer_id` (and optional `phone_contact_id`) after office confirmation — **replace opaque unused dict pattern**.

---

## 8. Inquiry / Order integration

| Rule | Decision |
|---|---|
| Inquiry stores `customer_id`? | **Yes**, optional until linked |
| Inquiry contact snapshot? | **Yes** — immutable JSON at create/update (`name`, `phone`, `email`, `company` used at intake) |
| Order stores `customer_id`? | **No** — only `source_inquiry_id` |
| Frozen at conversion | Operational OrderVersion fields + Inquiry snapshot **remains historical** |
| Call → multiple Inquiries? | **Default no** — unique `(call_source, call_key)` → at most one primary Inquiry link; break-glass requires audit |
| Prevent second Inquiry from same call? | Unique external call link table `call_fact ↔ inquiry_id` |
| Customer merge | Repoint `customer_id` on identities; phone points marked `historical`; audit log; **do not rewrite** Inquiry snapshots or OrderVersion |

**Call fact entity (minimal, separate from customer):**

| Field | Purpose |
|---|---|
| `call_source`, `call_source_instance`, `call_key` | D1 decision |
| `normalized_phone`, timestamps, direction, duration, missed flag | Fact |
| `customer_id` | Optional after match |
| `primary_inquiry_id` | Optional after link |
| `office_follow_up_status` | Core-owned (replaces Auerswald resolve post-cutover) |

---

## 9. Matching rules (normative)

1. Normalize phone with **Core** `normalize_phone()`.
2. Search **active** `PhoneContactPoint.normalized_phone` — **exact match only**.
3. **One** customer match → **suggest** linkage; apply only after **office confirmation** (no silent auto-link).
4. **Multiple** customers with same active phone → **ambiguous** — manual pick (data error until merge).
5. **No match** → unmatched; office may create CustomerIdentity + phone point while creating Inquiry.
6. **No fuzzy** matching.
7. **No auto-create customer** from call alone.
8. Manual linkage → Core command, audit log.
9. Old numbers remain on **historical** phone points; calls retain phone-at-call-time on fact row.
10. **Reassign phone** to another customer → deactivate old point + audit; never silent UPDATE.
11. **Merge customers** → audit trail + repoint active points.
12. **Private/withheld number** → unmatched bucket; no synthetic customer.

**Confirmation required even on single match:** **Yes** — office button «Kunde zuordnen» (prevents wrong auto-link on shared office lines / data errors).

---

## 10. Migration strategy (existing Core data)

### 10.1 Classes (dry-run, no execution)

| Class | Count (current DB) | Action |
|---|---:|---|
| safe exact phone candidate | **0** | N/A today |
| missing phone in intake | **33** | Leave Inquiry unchanged; no backfill |
| malformed | **0** | — |
| ambiguous duplicate phones | **0** | — |
| manual review | **0** | — |
| forward-only | all future phone Inquiries | Create CustomerIdentity at first confirmed intake |

### 10.2 Approach

- **No mass migration** of 33 inquiries.
- New commands create/link customer on **office action**.
- Optional later: parse `E-Mail:` / `Name:` to suggest CustomerIdentity on manual review (separate slice).

---

## 11. Legacy `resolved_missed_calls.json` transition

| Step | Action |
|---|---|
| 1 | Introduce Core `call_follow_up_status` on call fact |
| 2 | Build mapping job: parse legacy `call_id` (3-field) → compute `call_key` v1 if row still in CDR |
| 3 | Unmatched legacy IDs (7 today) → report `legacy_unmapped` (expected after 30d churn) |
| 4 | Dual-read: Core fact resolved OR legacy JSON during transition |
| 5 | Dual-write: stop writing Auerswald JSON after cutover flag |
| 6 | Audit report: old_call_id → new_call_key \| unmapped |
| 7 | Rollback: re-enable Auerswald resolve writes; Core facts read-only |

**Duplicate mapping:** same legacy ID twice → idempotent.

---

## 12. Privacy and security

| Topic | Decision |
|---|---|
| PII fields | `normalized_phone`, display name, company, intake snapshot |
| Storage | Core SQLite (existing backup path) |
| Masked UI | Show last 4 digits in lists where feasible |
| Roles | Office Panel auth unchanged |
| Audit | Core command log (user, action, entity ids — **no phone in log text**) |
| Retention | Call facts **longer than 30d CDR**; phone points follow customer retention policy (TBD legal) |
| Deletion | `anonymized` customer status; redact snapshots per GDPR slice |
| Logs | Structured ids only |
| CDR disappearance | Core fact + linkage **retained** after Auerswald row evicted |
| Auerswald :8000 | **Unchanged this slice** — noted debt: auth not enforced |

---

## 13. Compatibility bug boundary (`/missed-board.json`)

| Principle | Decision |
|---|---|
| Bugfix scope | Add JSON endpoint returning **existing** legacy item shape |
| Must not | Introduce customer identity or new call key in bugfix |
| Must not | Change call_id format without migration |
| HubSpot | **Do not** re-enable lookup in bugfix |
| Timing | **Before** domain implementation — **short standalone slice** |
| Rationale | Restores Panel Rückruf count; independent of Core linkage |

---

## 14. Recommended implementation sequence

1. **Compatibility bugfix** — `GET /missed-board.json` (legacy contract only).
2. **Customer identity foundation** — CustomerIdentity + PhoneContactPoint tables/repos/API read.
3. **Call fact table** — D1 key + ingest idempotency (read from Auerswald CSV/API).
4. **Legacy resolve migration report** — dry-run mapping.
5. **Office Panel read-only** — show Core call facts + match suggestions.
6. **Exact phone matching + manual confirm command**.
7. **Controlled phone Inquiry creation** with snapshot + optional customer link.
8. **Core resolve state** — replace Auerswald JSON writes (feature flag).
9. **Comparison period** — legacy Auerswald board vs Core.
10. **Future** — access cutover; close public :8000 after acceptance.

**Not included:** HubSpot outbound, Order changes, READY_TO_SEND / wirksam changes.

---

## 15. Test strategy

| Layer | Tests |
|---|---|
| Unit | `normalize_phone`, canonical fingerprint, call_key v1 |
| Unit | matching exact / ambiguous / none |
| Integration | idempotent ingest same CSV twice |
| Integration | one call → one Inquiry link enforced |
| Integration | conversion still blocked on verify gate |
| Regression | OrderVersion unchanged by call ingest |
| Contract | missed-board.json schema unchanged in bugfix |
| Migration | legacy resolve mapping dry-run fixtures |

---

## 16. Rollout

- Feature flags: `CORE_CALL_INGEST`, `CORE_CALL_RESOLVE`, `CORE_CUSTOMER_LINKAGE`.
- Deploy identity schema before ingest.
- Enable ingest read-only → office confirm → disable Auerswald resolve writes.
- Monitor duplicate Inquiry attempts and unmapped legacy resolves.

---

## 17. Rollback

- Flags off → Panel uses legacy Auerswald resolve JSON.
- Core tables remain; no drop on rollback.
- Customer commands disabled; inquiries unchanged.

---

## 18. Unresolved blockers (non-blocking for foundation)

| ID | Item | Status |
|---|---|---|
| B1 | Legal retention period for call history | Product/legal |
| B2 | Break-glass: one call → two Inquiries | Product |
| B3 | Email ContactPoint phase 2 | Deferred |
| B4 | Decrypt GPG backup for cross-time LfdNr study | Optional research |
| B5 | Explicit `AUERSWALD_INSTANCE_ID` config | Engineering default OK |

---

## 19. Proof of architectural rules

| Rule | How decision complies |
|---|---|
| Operational truth in Core | Customer, phone points, call facts, resolve state in Core DB |
| Panel controlled entry | Commands via Office API only |
| No Order from call | Link/create Inquiry only |
| Inquiry → Order | Unchanged conversion path |
| phone inquiry_source | Reused |
| Auerswald fact source | Ingest adapter only |
| HubSpot excluded | No HubSpot fields in identity model |
| No parallel CRM | Option B minimal; no deals/marketing |
| OrderVersion sacred | No call fields on Order |

---

## 20. Phase verdict

### **READY FOR CUSTOMER IDENTITY FOUNDATION IMPLEMENTATION**

**Rationale:**

- **D1 decided:** fingerprint-based `call_key` with `auerswald:debiancatering:v1:` namespace — LfdNr **rejected** as primary (insufficient cross-export proof documented).
- **D2 decided:** Option B — CustomerIdentity + PhoneContactPoint; Option C rejected.
- **LfdNr-only path:** **NOT READY** — correctly abandoned in favor of D1-B.
- **Immediate next slice:** customer identity schema + repos (no Auerswald ingest yet), **or** parallel short **`/missed-board.json` bugfix**.

**Not selected:** full CRM (Option A email-heavy), LfdNr primary key (D1-A), HubSpot reactivation.

---

*End of decision pack — read-only; no code, DB, or runtime changes performed.*

---

## 21. Binding architectural commitments (implementation guardrails)

The following rules are **normative** for all follow-on implementation slices (Core identity, Auerswald ingest, Office Panel linkage). They preserve decisions from this pack and the audit pack without reopening CRM or Order shortcuts.

- **HubSpot:** remains a **disabled optional adapter** — no outbound sync, no live contact lookup on the missed board or Rückruf path, and no HubSpot identifiers as operational truth in Core.
- **`AUERSWALD_INSTANCE_ID`:** configurable namespace for Auerswald-sourced call facts; default **`debiancatering`** until an explicit PBX instance identifier exists in CDR exports.
- **Sync hostname:** backup/sync host identity (`debiancatering`) documents **which export pipeline** produced a row; it is **not** a substitute for a PBX serial — instance id stays explicit in config.
- **Fingerprint versioning:** primary external call reference uses **`call_key_version=v1`** SHA-256 over the canonical CSV field serialization; algorithm changes require a **new version**, never silent in-place mutation.
- **`CustomerIdentity`:** Core-owned client aggregate (Option B) with **`PhoneContactPoint`** for normalized numbers — not an extended opaque `customer_linkage` dict alone.
- **Inquiry snapshot:** immutable contact JSON on Inquiry at create/update (`name`, `phone`, `email`, `company` as captured at intake) — historical truth even if phone points change later.
- **Order path:** **no Order from a call** — only **Inquiry → Order** conversion; call ingest may link or suggest Inquiry but must not create OrderVersion directly.
- **Office confirmation:** exact phone match may **suggest** linkage only; applying `customer_id` / phone point to a call or Inquiry requires an explicit office action (e.g. «Kunde zuordnen»), never silent auto-link.

# PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 — Core Office API and the office move

Status: FROZEN — round-3 verdict "conditional freeze approved", all five
round-3 corrections incorporated (§11), 2026-07-13. Implementation follows
this pack; changes to it require a new review round. No code, migration,
deployment, or systemd change accompanies the freeze itself.

## 1. Verified current-state facts (checked 2026-07-13 against working trees)

### 1.1 Office panel routes touching Inquiry / Order / OrderVersion

Verified in `src/catering_system/ui/office_panel_http.py` (HEAD `28d4a0b`):

| Route | Method | Reads | Writes | Core service / repo call |
|---|---|---|---|---|
| `/` | GET | full dashboard (§1.2) | – | repo list reads, `evaluate_ready_to_send`, `WochenuebersichtService`, Auerswald fetch |
| `/rueckruf` (+`/resolve`) | GET/POST | – (Auerswald only) | – (Auerswald) | external phone system, not Core |
| `/anfragen?q=` | GET | Inquiry list/search | – | `list_all`/search |
| `/auftraege?q=` | GET | Order list/search + derived state | – | `list_orders`, versions, READY eval |
| `/inquiry/new` | GET/POST | – | Inquiry create | `InquiryService.create_inquiry` |
| `/inquiry/{id}` | GET | detail + linked orders + prefill | – | `get_by_id`, `list_orders` filter, `offer_prefill_payload` |
| `/inquiry/{id}/update` | POST | Inquiry | update | `InquiryService.update_inquiry` |
| `/inquiry/{id}/verify` | POST | Inquiry | verification | `verify_customer_by_call` (repeat = success) |
| `/inquiry/{id}/convert` | POST | Inquiry | Order + Version 1 | `convert_inquiry_to_order` (gate B5) |
| `/order/{id}` | GET | Order + versions + READY | – | repo reads, `evaluate_ready_to_send` |
| `/order/{id}/version` | POST | Order | new OrderVersion | `create_relevant_order_change_version` — **refuses cancelled orders** (STORNO §3, `order_service.py:91`) |
| `/order/{id}/print?version=` | GET | owned version | – | print sheet |
| `/order/{id}/print-confirm` | POST | Order | print fact | `confirm_kitchen_print` — idempotent repeat = success; **no cancelled-order check in the service today** (the HTML UI simply never offers it on a Storno order) |
| `/order/{id}/effective` | POST | Order | effective pointer | `make_order_version_effective` — gate: confirmed print; any owned printed version valid; **no cancelled-order check in the service today** |
| `/order/{id}/ready` | POST | Order | – | `request_ready_to_send` — unknown order = `200`, `ready=false`, `ready_to_send_order_not_found` |
| `/order/{id}/cancel` | POST | Order | cancellation | `cancel_order` — idempotent repeat = success |
| `/proposal-preview` (+`/prepare`) | GET/POST | – | – | pasted configurator JSON → prefilled Inquiry form |

**Repository orderings (round-2 fact, must be preserved):** inquiries
`ORDER BY event_date, inquiry_id`; orders `ORDER BY order_id`; versions
`ORDER BY version_number`. **Existing constraint:** partial unique index
`uq_inquiries_website_external_ref ON inquiries (inquiry_source,
intake_external_ref) WHERE inquiry_source='website_form' AND
intake_external_ref NOT NULL AND <> ''` (inquiries migration 3, with
fail-closed duplicate pre-check — the §6.2 migration follows this exact
precedent). The repository already raises a typed
`DuplicateExternalReferenceError` (`inquiry_repository.py`) for it — the API
maps that exception, never SQLite error text (§4.5).
`customer_linkage` is validated as keys ⊆ `{customer_id: str, contact_id:
str, placeholder: literal true}`. Re-conversion after Storno is deliberate
(`office_panel.py` ~673). Services raise free-text `ValueError`s, not stable
codes (§4.5).

### 1.2 What the dashboard (`render_queue`) actually computes

Round-2 fact-check, from `office_panel.py:266-455`:

- **Attention counts**: `neue_anfragen` (inquiries with no order at all),
  `druck_fehlt` (active orders with no print-confirmed version),
  `nicht_wirksam` (active orders without effective version),
  `versand_blockiert` (active orders whose READY_TO_SEND is false),
  `storniert` (cancelled orders), plus the external Rückruf count.
- **Current ISO week** via `WochenuebersichtService.get_week_overview`.
- **Top-5 new inquiries** with one action each: `verify` when verification
  is required and not verified, else `convert`.
- **Top-5 blocked orders** with the first READY reason and a next action
  resolved by `_next_step_action`: target version = candidate if it names a
  real owned version else highest `version_number`; action = `print-confirm`
  if its print is unconfirmed, else `effective` if it is not the effective
  one, else none.

### 1.3 Configurator (fingerfood-app, HEAD `a6a3a7d`) local data

File-JSON drafts `backend/app/data/drafts/{uuid}.json`, catalog
`items.json`, FastAPI routes (health, items, `offer/calculate`, drafts
CRUD). No database, no Core access. Prefill arrives client-side as a URL
fragment; proposal export → office is a manual JSON paste.

### 1.4 Services actually running (current-status/runbooks, 2026-07-13)

| Host | Unit | Kind | Binding |
|---|---|---|---|
| Lenovo | `catering-office-panel` | system | `8081` — to be replaced |
| Lenovo | `catering-kiosk` | system | `8082` (+ feed, signal refresher) |
| Lenovo | `catering-website-intake` | system | `127.0.0.1:8083`, bearer |
| Lenovo | `catering-courier-app` | user (Linger) | `8090` |
| Lenovo | `catering-intake-vps-tunnel` | user | reverse SSH → VPS `18083` |
| VPS | `catering-staging-site` | system | `8080` public (fake data) |

Durable VPS intake buffer deferred until launch (`53cdf65`). CRM fully out
of scope (owner decision).

### 1.5 Prefill placement check (round 1)

No active or archived doc places the configurator on the Lenovo; wording is
host-neutral. This pack pins Proxmox going forward; the prefill fragment
travels in the office user's browser, so `CONFIGURATOR_URL` becomes the VM's
Tailscale URL — mechanism unchanged.

## 2. Target architecture

```text
Public form (VPS) → hardened staging intake → reverse-SSH tunnel
    → website-intake receiver (Lenovo, 127.0.0.1:8083, bearer)
    → Core services → core.db                       [exists, unchanged]

Office panel (Proxmox VM, Tailscale only)
    → machine bearer over Tailscale
    → Core Office API (Lenovo, 100.109.6.74:8084)
    → existing Inquiry/Order/OperationalCore services → core.db   [this pack]

Configurator (Proxmox VM, Tailscale only)
    ← read-only prefill fragment via the office user's browser    [exists]
    → local file drafts / future PDFs on Proxmox only
    → NO Core write; confirmed data reaches Core only through an
      explicit office-panel action
```

Placement invariants (owner): Core, `core.db`, kiosk, courier app and all
operational execution stay on the kitchen Lenovo — never VPS/Proxmox. The
Proxmox VM stands in for the future office server (panel, configurator,
Angebot drafts, future PDFs), Tailscale only, no public ports. The VPS stays
public-form staging, future durable intake buffer, off-site backups — never
an office server.

## 3. Boundaries (non-negotiable)

1. Core stays the only operational truth; the API stores nothing beyond the
   in-`core.db` idempotency ledger (§6.1).
2. The office panel remains the only human surface issuing Core commands.
3. The configurator gets no direct Core write — not now, not via this API's
   token; promotion is a separate office-mediated contract (§4.7).
4. No generic CRUD: every endpoint is a named business read or command
   mapping onto existing service methods and gates.
5. JSON contracts only — no Python objects, no SQLite file transfer, no DB
   replication to Proxmox.
6. No automatic sending of Angebote; no CRM features or integrations.
7. Panel, configurator, and Core Office API are never publicly reachable —
   Tailscale only, no port forwarding, never proxied.
8. Boundary evolution stated openly: the frozen kiosk packs' "Core keeps
   exactly one reader: the kiosk" governed *additional consumers*. This API
   **replaces the panel's in-process access**; after cutover the Lenovo
   processes touching `core.db` are exactly: Core Office API (read+command),
   kiosk (read), website-intake receiver (Inquiry create). Archived packs
   stay untouched; the decision register gets the superseding note at freeze.
9. Rückruf/Auerswald is not Core data and gets no proxy route. On Proxmox
   the panel shows `„Rückruf-Liste: nur vor Ort verfügbar“` unless Auerswald
   reachability from the VM is separately proven.
10. **Identical behavior is a contract requirement**: list orderings,
    idempotent-repeat semantics, the `ready`-on-unknown-order response, and
    the next-action resolution rule are specified to match the current panel
    exactly. Any UX change is a separate reviewed decision, never a side
    effect of this migration (round-2 rule).

## 4. API contract — fixed before freeze

Base path `/office/v1/`. Server: stdlib `http.server`, single-threaded
(sqlite3 thread affinity, WORKLOG Entry 048), no outbound HTTP.

### 4.0 Transport rules (all routes)

- Auth first on **every** method including HEAD and OPTIONS:
  `Authorization: Bearer <token>`, constant-time; missing and wrong are the
  same constant `401 {"error":"unauthorized"}` before any routing/parsing.
- Responses: `application/json; charset=utf-8`, correct `Content-Length`,
  `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` — errors too.
- Commands require `Content-Type: application/json` (else `415`), non-empty
  body (`400`), valid `Content-Length` (absent/negative/mismatched → `400`),
  body ≤ 64 KiB (`413`).
- Strictness: unknown or duplicated query parameters → `400`; unknown JSON
  keys anywhere in the envelope and duplicate JSON object keys (detected via
  `object_pairs_hook`) → `400`; exact JSON types, no coercion.
- `GET` rejects any body. Wrong method on a known path → `405
  method_not_allowed`. Unknown path → `404`.
- **HEAD and OPTIONS get explicit handlers** (round-2 fix — the stdlib
  default would answer 501 in HTML without auth, contradicting the rules
  above): `do_HEAD`/`do_OPTIONS` run the same auth check first, then answer
  `405 method_not_allowed` for known paths and `404 not_found` for unknown
  ones, with all security headers; HEAD responses carry the exact headers
  (including the `Content-Length` of the suppressed JSON body) and no body.
- Response size: hard cap 512 KiB, made concrete by the §4.2 pagination and
  the §4.1 embedded-list caps — no response can be constructed above it.
- Error bodies are always `{"error":"<stable-code>"}` — never free text,
  never exception messages.

### 4.1 Shared object shapes (exact, exhaustive)

Timestamps: ISO-8601 UTC with offset. Dates: strict `YYYY-MM-DD`. Enums are
exactly the Core vocabularies; unknown enum values in requests → `400`.

`InquirySummary` (all fields always present):

| field | type |
|---|---|
| `inquiry_id` | string (uuid) |
| `event_date` | date |
| `created_at` / `updated_at` | datetime |
| `inquiry_source` | enum |
| `crm_stage` | enum |
| `time_window_text` | string ≤500 |
| `location_text` | string ≤500 |
| `guest_count_estimate` | int 1…2000 or null |
| `planning_mode` | enum |
| `call_verification_required` | bool |
| `call_verification_status` | enum |

`InquiryListRow` = `InquirySummary` plus (round-2: the list page renders the
Betreff column and the „Auftrag öffnen" link):

| field | type |
|---|---|
| `intake_subject` | string ≤1000 or null |
| `linked_order_id` | string or null — the single **active** (non-cancelled) order's id when one exists, else null (round-3: the list page only renders the „Auftrag öffnen" link, no array needed) |
| `orders_total_count` | int — all orders for this inquiry, cancelled included |

`InquiryDetail` = `InquiryListRow` plus:

| field | type |
|---|---|
| `customer_linkage` | object with keys ⊆ `{customer_id: string, contact_id: string, placeholder: true}` (exact current validation; `placeholder` only ever literal `true`) |
| `intake_message` | string ≤5000 or null |
| `intake_summary` | string ≤2000 or null |
| `intake_external_ref` | string ≤200 or null |
| `allows_conversion` | bool (B5) |
| `orders` | array ≤50 of `{order_id: string, cancelled_at: datetime|null}`, plus `orders_truncated: bool` (detail keeps the full-array view; `orders_total_count` inherited from the list row stays honest) |
| `offer_prefill` | object — exact `core_inquiry_offer_prefill_v1` payload |

`OrderSummary`:

| field | type |
|---|---|
| `order_id` / `source_inquiry_id` | string (uuid) |
| `created_at` / `updated_at` | datetime |
| `candidate_order_version_id` | string or null |
| `effective_order_version_id` | string or null |
| `cancelled_at` | datetime or null |

`NextAction` (the `_next_step_action` resolution, §1.2, exactly):
`{action: "print-confirm"|"effective", order_version_id: string}` or `null`
(no versions, cancelled, or nothing to do).

`OrderListRow` = `OrderSummary` plus (round-2: no N+1 detail calls):

| field | type |
|---|---|
| `ready` | bool |
| `blocker_reason` | string (stable READY reason code) or null |
| `next_action` | `NextAction` |

`OrderVersion`:

| field | type |
|---|---|
| `order_version_id` / `order_id` | string (uuid) |
| `version_number` | int ≥1 |
| `created_at` | datetime |
| `event_date` | date |
| `time_window_text` / `location_text` | string ≤500 |
| `guest_count_estimate` | int 1…2000 or null |
| `planning_mode` | enum |
| `kitchen_print_confirmed_at` | datetime or null |

`OrderDetail` = `OrderSummary` plus `ready_to_send`
(`{ready: bool, reasons: [string]}` — existing stable vocabulary) plus
`versions`: array of `OrderVersion` ascending by `version_number`, capped at
**200** entries, with `versions_total_count: int` and `versions_truncated:
bool` (the cap keeps §4.0's 512 KiB bound concrete; realistic counts are
single digits).

`WeekEntry` (all fields always present):

| field | type |
|---|---|
| `order_id` | string (uuid) |
| `event_date` | date |
| `time_window_text` / `location_text` | string ≤500 |
| `guest_count_estimate` | int 1…2000 or null |

`InquiryTopRow` = exactly the eleven `InquirySummary` fields (§4.1 table,
all present) plus:

| field | type |
|---|---|
| `next_action` | `"verify"` or `"convert"` (§1.2 rule) |

`OrderTopRow` = exactly the seven `OrderSummary` fields (all present) plus:

| field | type |
|---|---|
| `blocker_reason` | string (stable READY reason code) or null |
| `next_action` | `NextAction` |

`QueueView` (round-2: sufficient to reproduce the dashboard without further
calls; Rückruf deliberately absent — not Core data; round-3: exact shapes,
no pseudo-JSON):

| field | type |
|---|---|
| `attention` | object `{neue_anfragen, druck_fehlt, nicht_wirksam, versand_blockiert, storniert}`, all int ≥0 (§1.2 semantics) |
| `week` | object `{iso_year: int, iso_week: int, entries: [WeekEntry] capped at 100, total_count: int, truncated: bool}` |
| `neue_anfragen_top` | array ≤5 of `InquiryTopRow` |
| `auftraege_top` | array ≤5 of `OrderTopRow` |

The operational day and the ISO week are computed in **Europe/Berlin**
(consistent with the courier-app precedent). On any `truncated: true` —
here, in `InquiryDetail.orders`, or in `OrderDetail.versions` — the panel
must render a prominent incompleteness warning (established convention).

### 4.2 Reads — ordering preserved, real pagination

**Ordering is the current repository ordering, unchanged (round-2 blocker):**
inquiries `(event_date, inquiry_id)`, orders `(order_id)`, versions
`(version_number)`. Any re-sorting is a separate UX decision, not this pack.

Pagination on both list routes: optional strict integers `limit` (default
**100**, max **100** — round-3: lowered from 500 so the 512 KiB response
bound is constructively unreachable) and `offset` (default 0, ≥0), each at
most once; non-integer, out-of-range, or unknown parameters → `400`.
`total_count` always carries the unpaginated total.

Search semantics (fixed, matching the current panel): the inquiry `q`
matches inquiry ID, location, event date, CRM stage, source, and intake
subject; the order `q` matches order ID and source inquiry ID.

| Route | Query | 200 response | Errors |
|---|---|---|---|
| `GET /office/v1/queue` | none | `QueueView` | `401` |
| `GET /office/v1/inquiries` | `q` (≤200, once, optional), `limit`, `offset` | `{inquiries: [InquiryListRow], total_count, limit, offset}` | `400`,`401` |
| `GET /office/v1/inquiries/{id}` | none | `InquiryDetail` | `401`,`404` |
| `GET /office/v1/orders` | `q`, `limit`, `offset` as above | `{orders: [OrderListRow], total_count, limit, offset}` | `400`,`401` |
| `GET /office/v1/orders/{id}` | none | `OrderDetail` | `401`,`404` |
| `GET /office/v1/orders/{id}/print-data` | `version=<uuid>` exactly once | `{order: OrderSummary, version: OrderVersion}` | `400`,`401`,`404` (unknown or unowned — no distinction leaked) |

### 4.3 Command envelope

```json
{"command_id": "<uuid4>", "expect": { ... }, "args": { ... }}
```

`command_id` required everywhere; `expect`/`args` must contain exactly the
keys the route defines. Success responses embed `command_id`.

### 4.4 Commands — args, expect, minimal results

Round-2 change: command responses are **minimal and PII-free** — IDs and
timestamps only. The panel issues a normal GET detail afterwards. Exactly
these bodies are what the idempotency ledger records.

| Route | `args` | `expect` | Success (minimal) |
|---|---|---|---|
| `POST /office/v1/inquiries` | `event_date` (date), `inquiry_source` (enum), `time_window_text` (≤500), `location_text` (≤500), `guest_count_estimate` (int 1…2000\|null), `planning_mode` (enum), `call_verification_required` (bool) — all required; `intake_subject` (≤1000), `intake_message` (≤5000), `intake_summary` (≤2000), `intake_external_ref` (≤200) — optional, default `""` | none | `201 {command_id, inquiry_id, updated_at}` |
| `POST /office/v1/inquiries/{id}/update` | editable set as create plus `crm_stage` (enum); minus `inquiry_source`, `call_verification_required` | `updated_at` (req) | `200 {command_id, inquiry_id, updated_at}` |
| `POST /office/v1/inquiries/{id}/verify` | `{}` | none | `200 {command_id, inquiry_id, updated_at}` (repeat = success) |
| `POST /office/v1/inquiries/{id}/convert` | `{}` | none (server-side active-order check in-txn, §6.2) | `201 {command_id, order_id, order_version_id}` |
| `POST /office/v1/orders/{id}/versions` | `event_date`, `time_window_text`, `location_text`, `guest_count_estimate`, `planning_mode` (all req) | `latest_version_number` (req) | `201 {command_id, order_version_id, version_number}` |
| `POST /office/v1/orders/{id}/print-confirm` | `order_version_id` (req) | none | `200 {command_id, order_id, order_version_id, kitchen_print_confirmed_at}` (repeat = success) |
| `POST /office/v1/orders/{id}/effective` | `order_version_id` (req) | `current_effective_order_version_id` (string\|null, req) | `200 {command_id, order_id, effective_order_version_id, updated_at}` |
| `POST /office/v1/orders/{id}/ready` | `{}` | none | `200 {command_id, evaluation: {ready, reasons}}` — unknown order is NOT `404`: `ready=false`, `ready_to_send_order_not_found` (current behavior) |
| `POST /office/v1/orders/{id}/cancel` | `{}` | `updated_at` (req) | `200 {command_id, order_id, cancelled_at, updated_at}` (repeat replays the recorded result, §6.1) |

Command limits are **office-API limits, set here** (1000/5000/2000/200 for
the four intake fields): they are NOT a mirror of the website intake, whose
public `subject` cap is 200 — the office may legitimately hold longer
internal notes (round-2 correction of the earlier wording).

### 4.5 Error map — explicit allowlist, matching today's behavior

Free-text service `ValueError`s never reach the client; mapping is
call-site-based:

| Situation | HTTP | `error` code |
|---|---|---|
| missing/wrong bearer (any method) | `401` | `unauthorized` |
| unknown path / inquiry / order / version in `print-data` | `404` | `not_found` |
| malformed JSON, unknown/duplicate keys or params, type/range violation, bad date, empty body, bad Content-Length, bad `limit`/`offset` | `400` | `invalid_request` |
| wrong Content-Type on command | `415` | `unsupported_media_type` |
| body over 64 KiB | `413` | `body_too_large` |
| wrong method on known path (incl. HEAD/OPTIONS after auth) | `405` | `method_not_allowed` |
| `command_id` replay with different fingerprint (§6.1) | `409` | `command_id_conflict` |
| `expect` mismatch | `409` | `stale_state` |
| convert while a non-cancelled order exists | `409` | `already_converted` |
| create/update raising the existing typed `DuplicateExternalReferenceError` | `409` | `external_ref_conflict` |
| SQLite `database is locked`/`busy` after the busy timeout (§6.4) | `503` + `Retry-After: 1` | `core_busy` |
| convert blocked by verification gate B5 | `422` | `verification_gate_blocked` |
| create-version on a cancelled order (existing STORNO §3 service refusal) | `422` | `order_cancelled` |
| print-confirm / effective on a cancelled order — **API-level pre-check inside the transaction**; the services do not check this today, the HTML panel simply never offers these actions on a Storno order, so the API codifies existing UI-level behavior rather than changing the services | `422` | `order_cancelled` |
| effective on a version without confirmed print | `422` | `kitchen_print_not_confirmed` |
| version not owned by the order (print-confirm/effective) | `422` | `version_not_owned` |
| **not errors** (success, per current services): repeated verify / print-confirm / cancel; `ready` on unknown order | — | — |

Conflict recognition never parses SQLite error text or index names (round-3
correction — SQLite reports columns, not index names): `external_ref_conflict`
comes from the existing typed `DuplicateExternalReferenceError`; an
`IntegrityError` during convert is confirmed by **re-querying the active
order inside the same transaction** — an active order found → `409
already_converted`, otherwise the error is unexplained and stays `500
{"error":"internal"}` with detail in the journal only (no payloads, no
contact data).

### 4.6 Prefill

Unchanged `core_inquiry_offer_prefill_v1`; `InquiryDetail` embeds the
payload; the panel builds the fragment URL locally; the fragment never
leaves the office user's browser.

### 4.7 Future promotion Angebot → OrderVersion

Reuses `POST /orders/{id}/versions` under the office user's authority after
review in the panel; the configurator never calls Core; any richer flow
needs its own pack; CRM stays out entirely.

## 5. Security

- **Exactly one listener: `100.109.6.74:8084`** (Lenovo Tailscale address);
  smoke tests via the Tailscale address; host firewall additionally
  restricts 8084 to tailscale0.
- Bearer mandatory; **token per client** (`OFFICE_API_TOKEN` for the panel;
  a future promotion client gets its own). Secrets only via root-owned
  `EnvironmentFile` mode `600` (`/etc/catering/office-api.env`; panel-side
  counterpart on the VM) — never argv, Git, or logs.
- Constant-time comparison; identical constant `401`; auth before
  everything on every method (§4.0).
- The panel's HTTP client refuses redirects and accepts exactly the §4
  status codes — the bearer never travels to an unconfigured URL.
- Logs (round-3 clarification): the existing Core services already log
  opaque inquiry/order IDs — this is **permitted** in the API process too;
  contacts, addresses, payloads, and tokens remain forbidden. The fixed
  `command committed` line is emitted only **after** a successful `COMMIT`;
  on rollback neither that line nor any domain event may leave the process
  (event dispatch is deferred until post-commit, §6.1).
- Human auth unchanged: panel keeps HTTP Basic + CSRF on the VM; the
  machine bearer is a separate layer.

## 6. Reliability — atomicity is the core requirement

### 6.1 Idempotency ledger inside `core.db`, atomic with the business write

- Ledger table `office_api_commands` lives **in `core.db`** — component
  `office_api`, migration 1 (round-2: named component assignment), via the
  same fail-closed migration runner as every Core component. Columns:
  `command_id` TEXT PK, `fingerprint` TEXT, `result_status` INTEGER,
  `result_body` TEXT, `created_at` TEXT. **No automatic expiry in V1.**
- **Canonical fingerprint (round-2 rework):** SHA-256 over the canonical
  JSON of `{route_template, path_ids, args, expect, client_id}` —
  `client_id` is the identity of the presented token (one panel token today;
  the field exists so a second client can never replay the first client's
  ids). The same `command_id` re-sent to a different route, different order,
  different args or different expect → `409 command_id_conflict`. Same
  `command_id` + same fingerprint → the recorded minimal `result_status`/
  `result_body` (§4.4) is returned verbatim without re-evaluating anything.
- **Ledger stores only the §4.4 minimal bodies** — IDs and timestamps, no
  `InquiryDetail`/`OrderDetail`, no intake texts, no PII (round-2).
- **One SQLite transaction** (`BEGIN IMMEDIATE` … `COMMIT`) wraps, in
  order: entity resolution, `expect` precondition read, business write(s)
  through the existing service, ledger insert. All durable or nothing.
- Requires the **transaction-coordination refactor** (Phase-1 scope):
  repository methods gain an externally-owned transaction mode (the command
  handler owns BEGIN/COMMIT/ROLLBACK on the shared connection; repo methods
  inside it do not auto-commit). Behavior-preserving for all existing
  callers, covered by its own tests. The coordinator also **defers domain
  event emission until after COMMIT** (round-3): services currently `_emit`
  during the call, and an event escaping a rolled-back transaction would
  announce a change that never happened.

### 6.2 Double-convert closure — partial unique index, required migration

As the **next migration of the `orders` component** (round-2: named
component; precedent: `uq_inquiries_website_external_ref` in the inquiries
component):

```sql
CREATE UNIQUE INDEX idx_orders_active_source_inquiry
ON orders (source_inquiry_id) WHERE cancelled_at IS NULL;
```

- Fail-closed pre-migration duplicate check (active orders per inquiry
  > 1 aborts for manual resolution) — same pattern as inquiries migration 3.
- The duplicate check is additionally **mandatory in migration tests and in
  the pre-deploy rehearsal on a database copy**; production copies are never
  fed into regular CI (round-2 rule).
- The convert command checks for an active order inside its transaction →
  `409 already_converted`; the index is the backstop (its `IntegrityError`,
  recognized by name, maps to the same `409`).
- Historical cancelled orders untouched; re-conversion after Storno keeps
  working.

### 6.3 Optimistic concurrency — preconditions inside the same transaction

`expect` evaluation happens inside the §6.1 transaction, immediately before
the service call: `update`/`cancel` → `updated_at`; `versions` →
`latest_version_number`; `effective` → `current_effective_order_version_id`;
`convert` → server-side absence-of-active-order. Mismatch → `409
stale_state`, nothing written.

Transition coexistence: the Lenovo panel is an **emergency fallback only** —
stopped once the Proxmox panel is live; the two panels never write
simultaneously (fallback = start Lenovo panel AND stop the Proxmox one).

### 6.4 SQLite contention (round-3)

The API connection sets `busy_timeout` to **2 seconds** — deliberately below
the panel's 5-second command timeout, so the API answers before the client
gives up. A `database is locked`/`busy` error surviving the timeout maps to
`503 {"error":"core_busy"}` with `Retry-After: 1`; the transaction is rolled
back, nothing is written, and the panel retries with the **same
`command_id`** — safe by §6.1. Acceptance includes a lock → `503` → retry
test (§9).

### 6.5 Degradation

Panel timeouts 3 s reads / 5 s commands; API unreachable → explicit German
failure page («Core nicht erreichbar — nichts wurde gespeichert»), never an
empty queue; no hidden local writes — a command either returned `2xx` or did
not happen; human retry resubmits the same `command_id` (safe by §6.1). The
API performs no outbound HTTP — no blocking-cycle analysis needed.

## 7. Migration plan (E2E strictly before any user switch)

- **Phase 1 — Core Office API on Lenovo, dormant**: both `core.db`
  migrations (§6.1 `office_api`, §6.2 `orders` — verified backup +
  `quick_check` immediately before first start) and the transaction
  refactor. Existing panel unchanged; nothing else restarted.
- **Phase 2 — remote client, dual mode, contract tests**: `RemoteCoreClient`
  behind the panel; `CORE_OFFICE_API_URL` unset = direct mode
  (byte-identical), set = remote; the same behavioral suite must pass in
  both modes — including list ordering, top-5 contents, and next-action
  resolution (§3.10).
- **Phase 3 — Proxmox VM provisioning** (§8); panel + configurator installed
  remote-mode against an **isolated Core copy** (strict rehearsals never on
  live `core.db` — established review rule).
- **Phase 4 — full E2E on the isolated test Core, before any user switch**:
  staging-shaped Inquiry → verify → prefill → configurator draft → manual
  proposal handoff → convert → version → print-confirm → effective → kiosk
  shows it → courier feed shows it → Storno → re-convert. All §9 acceptance
  criteria proven here with invented data.
- **Phase 5 — live deploy and controlled cutover**: point the Proxmox panel
  at the live API, smoke with invented data (status codes + fixed log
  lines), stop `catering-office-panel` on the Lenovo (unit and release
  retained as rollback), office user switches URL. After **14 incident-free
  days** a **separate review verdict** authorizes deleting the direct-DB
  mode and retiring the Lenovo panel unit (round-2: window fixed, deletion
  gated on its own verdict).

## 8. Proxmox VM specification

Debian stable, 2 vCPU, 4 GB RAM, 30–40 GB disk. No port forwarding; ingress
via Tailscale only; host firewall default-deny inbound except tailscale0.
systemd system units (`office-panel`, `configurator-backend`, frontend
serving decided in Phase 3), separate system users and data directories
(`/var/lib/office-panel`, `/var/lib/configurator`). Env-file configuration
(root `600`), no secrets in Git. Proxmox snapshots before each phase change;
draft/PDF directory joins a scheduled backup (mechanism fixed in Phase 3,
Lenovo off-host pattern as template). The VM is a stand-in: the future real
office server is a restore + Tailscale join, not a rebuild.

## 9. Acceptance tests

- **Contract**: every §4 route — happy paths with exact shapes; strict
  `400`s (unknown/duplicate keys and params, types, ranges, dates);
  `415`/`413`/`405`; explicit HEAD/OPTIONS behavior incl. auth-first and
  headers-without-body; pagination (`limit`/`offset` bounds, `total_count`),
  embedded-list caps (`versions` 200 / row `orders` 50) with honest counts;
  512 KiB bound.
- **Dashboard parity**: `QueueView` reproduces `render_queue` exactly on a
  seeded fixture — attention counts, week rows, both top-5 lists including
  next-action resolution order (print-confirm before effective, candidate
  before highest version) and list orderings.
- **Auth negative**: no/wrong token → identical constant `401` on every
  route and method, before parsing.
- **Idempotency**: replay same fingerprint → recorded minimal result, no
  double effect (convert, versions, cancel); same `command_id` with a
  different route/path-id/args/expect → `409 command_id_conflict`;
  crash-window test proving ledger+business atomicity.
- **Double-convert**: second convert → `409` + index backstop; re-convert
  after Storno succeeds; migration duplicate pre-check tested.
- **Preconditions**: stale `updated_at`/`latest_version_number`/
  `current_effective_order_version_id` → `409 stale_state`, no write.
- **Cancelled-order gates**: versions/print-confirm/effective on a Storno
  order → `422 order_cancelled`; `external_ref_conflict` on duplicate
  website ref.
- **Contention**: a held write lock → `503 core_busy` with `Retry-After`,
  rollback proven (no partial write, no ledger row, no event), retry with
  the same `command_id` succeeds exactly once.
- **Timeouts/degradation**: API down → failure page, no local write, no
  empty-queue rendering; truncation warnings render on every `truncated:
  true` surface.
- **Isolation**: the Proxmox host has no path to `core.db`; the configurator
  makes zero Core connections.
- **Cross-system E2E** (Phase 4): full §7 chain; kiosk/Wochenübersicht/
  courier-feed/READY_TO_SEND suites run against the rehearsal Core unchanged.
- **Rollback test**: Phase-5 rollback rehearsed once (Lenovo panel
  re-enabled, Proxmox panel stopped, no writes lost, ledger consistent).

## 10. Deploy / rollback rules

- Verified `core.db` backup (`.backup` + `quick_check`) before every phase
  touching the Lenovo; migrations only after it.
- Phase 1 deploys dormant; kiosk, intake, courier, tunnel services are not
  restarted unless a change targets them.
- Smoke: status codes and fixed log lines only — never customer-data bodies.
- Rollback per phase: 1 — stop/disable the API unit (migrations are additive
  and harmless to direct mode); 2 — unset `CORE_OFFICE_API_URL`; 3 — VM
  snapshot revert; 4 — discard the rehearsal copy; 5 — re-enable the Lenovo
  panel and stop the Proxmox one (never both writing).
- No real customer data before the Phase-5 supervised cutover.

## 11. Review record

**Round 1, 2026-07-13 — changes required; all eight addressed** (ledger into
`core.db` + single transaction + coordinator refactor + no expiry; partial
unique index with pre-check as required migration; full JSON contract before
freeze; error map matched to real idempotent-repeat semantics; atomic
preconditions and fallback-only coexistence; single Tailscale listener;
E2E before user switch; stdlib/8084/per-client tokens/direct-DB deletion/
Auerswald „nur vor Ort"/date fixed).

**Round 2, 2026-07-13 — changes required; all seven addressed:**

1. **Read API completed for the real panel**: `QueueView` with attention
   counts, current-week rows, both top-5 lists with next-action resolution
   (verified against `render_queue`/`_next_step_action`, §1.2);
   `InquiryListRow` gains `intake_subject` + linked orders; `OrderListRow`
   gains `ready`/`blocker_reason`/`next_action` — no N+1 (§4.1, §4.2).
2. **Current orderings preserved verbatim** — inquiries `(event_date,
   inquiry_id)`, orders `(order_id)`, versions `(version_number)`; verified
   against the repositories and made a contract requirement; UX changes only
   as a separate decision (§1.1, §3.10, §4.2).
3. **Idempotency fingerprint covers the whole command** — route template,
   path IDs, args, expect, client identity; foreign-route/foreign-order
   replays → `409`. Ledger stores only minimal PII-free results; command
   responses reduced to IDs/timestamps, the panel re-reads details via GET
   (§4.4, §6.1).
4. **Error map completed**: `422 order_cancelled` for versions (existing
   service refusal) and for print-confirm/effective (honestly labelled as an
   API-level codification of current UI behavior); `409
   external_ref_conflict` for the existing website-ref unique index,
   recognized by index name; unexpected `IntegrityError` stays `500` (§4.5).
5. **HEAD/OPTIONS contradiction resolved**: explicit `do_HEAD`/`do_OPTIONS`,
   auth first, `405`/`404` with full headers, HEAD without body but with the
   suppressed body's `Content-Length`; the stdlib-501 claim removed (§4.0).
6. **Real pagination**: strict `limit` (default 100, max 500) / `offset` on
   both list routes, `total_count` kept; embedded-list caps fixed
   (`versions` ≤200, row `orders` ≤50) with honest totals, making the
   512 KiB rule concrete (§4.1, §4.2).
7. **Types and decisions closed**: `customer_linkage` exact schema
   (`customer_id`/`contact_id` strings, `placeholder` literal `true`);
   intake limits declared as new office-API limits, not an intake mirror
   (public subject cap there is 200); `guest_count_estimate` fixed to
   1…2000|null; transition window fixed at 14 incident-free days with a
   separate deletion verdict; duplicate pre-check mandated in migration
   tests + pre-deploy on a DB copy, production copies never in regular CI;
   index assigned to the `orders` component, ledger to `office_api` (§4.1,
   §4.4, §6.2, §7).

**Round 3, 2026-07-13 — conditional freeze approved; all five corrections
incorporated:**

1. Factual fix: the existing partial index filters on
   `inquiry_source='website_form'`, not `'website'` (§1.1).
2. Conflict recognition without index-name parsing: `external_ref_conflict`
   maps the existing typed `DuplicateExternalReferenceError`; an
   `IntegrityError` during convert is confirmed by re-querying the active
   order inside the transaction; everything else stays `500 internal`
   (§1.1, §4.5).
3. The 512 KiB bound made constructive: list `limit` max lowered to 100;
   `InquiryListRow` carries only `linked_order_id` (single active order) +
   `orders_total_count`, the full capped array (≤50, `orders_truncated`)
   lives only in `InquiryDetail`; `OrderDetail` gains `versions_truncated`;
   `QueueView.week.entries` capped at 100 with `total_count`/`truncated`;
   the panel must render a prominent warning on any truncation (§4.1, §4.2).
4. `QueueView` pseudo-JSON replaced with exact field tables
   (`InquiryTopRow`, `OrderTopRow`, `WeekEntry`); operational day and ISO
   week fixed to Europe/Berlin; search semantics fixed — inquiries by ID,
   location, event date, CRM stage, source, intake subject; orders by order
   ID and source inquiry ID (§4.1, §4.2).
5. SQLite contention handling added (§6.4): `busy_timeout` 2 s (below the
   5 s client command timeout), `database is locked/busy` → `503 core_busy`
   + `Retry-After: 1`, rollback guaranteed, retry with the same
   `command_id`; lock → 503 → safe-retry acceptance test (§9).

Additionally clarified per round 3: opaque Core inquiry/order IDs are
permitted in API logs (the services already emit them); contacts, addresses,
payloads, and tokens stay forbidden; `command committed` only after a
successful COMMIT; domain events never escape a rolled-back transaction —
event dispatch is deferred until post-commit (§5, §6.1).

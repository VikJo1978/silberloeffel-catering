# Architectural decision register

These decisions are current constraints. Change them only through an explicit
review that updates architecture, tests, runbooks, and this register.

| ID | Decision | Reason |
|---|---|---|
| ADR-001 | Lenovo SQLite is operational truth | Office and kitchen must share one authoritative local state |
| ADR-002 | CRM is not order truth | External CRM may sync context but cannot release kitchen work |
| ADR-003 | Inquiry and Order remain separate | Incoming intent and confirmed operational work have different lifecycles |
| ADR-004 | OrderVersions are immutable history | Changes create a new snapshot instead of rewriting past facts |
| ADR-005 | Readiness is derived, not stored | Prevents stale status flags and contradictory truth |
| ADR-006 | Kitchen print precedes effective selection | The effective version must correspond to a confirmed physical handoff |
| ADR-007 | Office panel is private | It is a write surface protected by network boundary, Basic auth, and CSRF |
| ADR-008 | Public intake is narrow | Worker validation and one token-protected receiver route minimize exposure |
| ADR-009 | Staging persistence stays isolated; a narrow test-intake bridge is allowed | Exercise real Inquiry intake before domain/office launch without copying Core or exposing SQLite |
| ADR-010 | Durable intake buffering is deferred but required before real customer traffic | Avoid queue complexity during fake-data testing without accepting lead loss at launch |
| ADR-011 | Core Office API supersedes the panel's in-process Core access | After cutover exactly three Lenovo processes touch `core.db`: Core Office API (read+command), kiosk (read), website-intake receiver (Inquiry create) |
| ADR-012 | Payment method is agreed in the accepted offer; Office tracks reminders only | Keep commercial terms explicit without turning Office or operational Core into accounting software |

## ADR-001 — Core on Lenovo

Production Inquiry, Order, and OrderVersion records live in one SQLite database
on `debiancatering`. Every production service points to that exact file.

Consequences:

- database backup is a critical operational responsibility;
- deployments must not silently create a second database;
- a public VPS must never receive a copy of production Core.

## ADR-004/005/006 — Operational progression

The only stored operational facts are version snapshots, print confirmation,
effective version reference, and cancellation. `READY_TO_SEND` is computed from
those facts. This keeps UI labels, kiosk views, and release checks consistent.

## ADR-008 — Website boundary

The public browser sends no secret. Cloudflare terminates public traffic,
whitelists fields, and adds the upstream token. Lenovo accepts exactly one
receiver route on loopback. The receiver can create an Inquiry but exposes no
office or order action.

## ADR-009 — Staging persistence and test intake

The VPS keeps its own disposable database and never receives a Core copy or a
database credential. The owner approved one explicit exception to complete
form testing before the office and domain are connected: the staging backend
may create fake-data Inquiries through the existing website receiver.

Consequences:

- the browser still receives no secret and never calls Lenovo directly;
- the VPS calls only an exact loopback URL reached through a restricted
  reverse-SSH forward; neither `8083` nor the forwarded port is public;
- every external reference is prefixed `vps-staging-` and retries are
  idempotent;
- a root-owned environment file holds the narrow receiver bearer;
- upstream failure is visible as `502` and is never reported as acceptance;
- disabling either environment variable or the tunnel restores isolated mode;
- only invented data is permitted until HTTPS and the privacy documents exist.

## ADR-010 — Deferred durable intake buffer

The current staging bridge is deliberately synchronous. It forwards a validated
fake submission to Core first, stores the VPS audit copy only after Core returns
its strict `202`, and returns `502` when Core or the tunnel is unavailable. The
browser keeps a stable submission ID, so a visible retry is idempotent, but a
visitor who closes the page after a failure has no server-side delivery
guarantee.

This is accepted only while the endpoint is a fake-data test surface. A durable
buffer is a mandatory launch gate before real customer submissions are allowed.

The launch implementation must:

- persist the validated Inquiry payload in the existing VPS SQLite database
  before returning browser acceptance;
- deliver it asynchronously to the narrow Core receiver and retry safely with
  the existing namespaced submission ID;
- expose pending/delivered/attention state only through the private admin
  surface and never silently discard an exhausted item;
- survive process restart and prove `Core unavailable → accepted locally →
  Core restored → exactly one Inquiry` in an end-to-end test;
- remain an Inquiry-only boundary: no Core copy, Core reads, or Order creation;
- use SQLite for the expected volume; Redis, RabbitMQ, or another broker needs
  a separate scale-driven decision.

Until that gate is implemented, `502` remains the truthful failure response and
must never be changed to a success-looking status.

## ADR-011 — Core Office API boundary supersession

Context and problem: the frozen kiosk packs stated "Core keeps exactly one
reader: the kiosk." That rule governed *additional* consumers of `core.db`. The
office move puts the office panel and configurator on a Proxmox VM that must
never reach `core.db` directly, so the panel can no longer open the database
in-process.

Decision: the Core Office API (`docs/proposals/PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1.md`,
frozen at commit `38930bf`) replaces the panel's in-process database access. It
is a bearer-gated, Tailscale-only service on the Lenovo address `100.109.6.74:8084`
exposing named business reads and commands that map onto the existing Inquiry,
Order, and operational services — no generic CRUD, no SQLite transfer, JSON
contracts only. After the Phase-5 cutover the only Lenovo processes touching
`core.db` are exactly:

- Core Office API — reads and business commands on behalf of the office panel;
- kiosk — read-only;
- website-intake receiver — Inquiry creation only.

The office panel stays the only human surface issuing Core commands (ADR-007);
the configurator never touches Core.

Alternatives rejected:

- keeping the panel's in-process access after the office server moves to Proxmox
  (would require `core.db` on or replicated to a non-kitchen host, violating
  ADR-001);
- a generic CRUD or database-replication bridge (rejected in favour of named
  commands, atomic idempotency, and JSON-only contracts).

Consequences:

- archived kiosk packs stay untouched; their "one reader" wording is scoped to
  additional consumers and is not contradicted by this supersession;
- the API is Tailscale-only, never public, with a per-client bearer;
- command atomicity is enforced by an in-`core.db` idempotency ledger written in
  the same transaction as the business change, with post-commit-only events.

Migration and rollback impact: Phase 1 deploys the API dormant — both `core.db`
migrations (the `office_api` ledger and the `orders` partial UNIQUE index) are
additive and harmless to the existing direct-DB mode, and the office panel is
unchanged. Rollback in Phase 1 is stop/disable the API unit. Direct-DB mode is
retained as an emergency fallback until a separate review verdict authorises its
deletion after 14 incident-free days (pack §7, Phase 5). Full phasing lives in
the pack; implementation landed in commits `d50584d`, `6de69bb`, `8dd3b87`.

## ADR-012 — Agreed payment method and reminder-only finance boundary

Context and problem: payment terms belong to the commercial agreement with the
customer, not to a later office bookkeeping choice. At the same time, this
system must help the office remember external invoicing and payment deadlines
without becoming the accounting system or coupling money state to kitchen
operations.

Decision: `Zahlungsart` is selected in the Angebot as an agreed commercial term
with exactly these initial choices: `Vorkasse`, `Rechnung`, or `Bar vor Ort`.
After the customer accepts the Angebot and the office confirms the Order, the
agreed method is transferred into the Order's future payment-reminder context;
only then does the corresponding reminder workflow start. Existing or manually
created Orders without an accepted Angebot may remain `Zahlungsart noch nicht
gewählt`. Changing the method after Order confirmation changes agreed terms and
therefore requires a separate, deliberate office action rather than an ordinary
metadata edit.

The Office Panel does not create a legally significant invoice. It only reminds
the office to create the invoice in the external accounting program and to
check the payment deadline or confirm cash received. The configurator may still
calculate prices and tax for the Angebot; that does not turn the Angebot or the
Office Panel into the official invoicing system.

Alternatives rejected:

- first choosing the payment method after Order confirmation, because the
  customer would not have agreed that term in the Angebot;
- creating invoices, tax documents, or accounting entries in the Office Panel;
- embedding invoice or payment state in Order, OrderVersion, kitchen-print,
  effective-version, or `READY_TO_SEND` status;
- implementing Invoice, Payment, banking, or accounting integrations before a
  separately reviewed need and contract exist.

Consequences:

- a future accepted-offer handoff must carry the agreed payment method through
  an explicit, reviewed boundary; this ADR does not authorize that code path;
- reminder state remains separate from operational truth and must not block or
  advance kitchen print, effective selection, kiosk visibility, or
  `READY_TO_SEND`;
- legacy and manual Orders need a truthful unselected state instead of an
  invented default;
- post-confirmation changes require an explicit command and auditability in any
  future implementation.

Migration and rollback impact: this is a documentation-only decision. It adds
no schema, API, UI, migration, or runtime behavior. Any implementation requires
its own reviewed slice with additive backward compatibility; absence of future
payment-reminder data must continue to mean `Zahlungsart noch nicht gewählt`.

## How to add a decision

Add the next ADR row and a short section containing:

- context and problem;
- decision;
- alternatives rejected;
- consequences;
- migration and rollback impact.

Link the implementation commit and update affected runbooks.

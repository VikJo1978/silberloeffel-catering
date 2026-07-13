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

## How to add a decision

Add the next ADR row and a short section containing:

- context and problem;
- decision;
- alternatives rejected;
- consequences;
- migration and rollback impact.

Link the implementation commit and update affected runbooks.

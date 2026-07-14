# Core Office API

The office panel's only path to `core.db` once it moves to the Proxmox
office VM. Frozen contract:
[PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1](../proposals/PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1.md)
— this page is the operator summary; the pack is normative.

## Exposure

```text
http://100.109.6.74:8084/office/v1/        (Lenovo Tailscale address only)
```

One listener, never public, never proxied. Bearer
`Authorization: Bearer <OFFICE_API_TOKEN>` is mandatory on **every** method
(HEAD and OPTIONS included) and checked before any routing or parsing;
missing and wrong tokens get the identical constant
`401 {"error":"unauthorized"}`. The token lives only in root-owned
`/etc/catering/office-api.env` (mode `600`).

Phase 1 is **dormant**: the unit may run, but nothing consumes it in
production — the office panel keeps its direct database access until an
explicit Phase 2 configuration/deploy step (not yet done; see below).

## Reads

| Route | Purpose |
|---|---|
| `GET /office/v1/queue` | dashboard `QueueView`: attention counts, Berlin ISO week (≤100 entries + `total_count`/`truncated`), top-5 inquiry/order rows with next actions |
| `GET /office/v1/inquiries?q=&limit=&offset=` | list rows (`intake_subject`, `linked_order_id`, `orders_total_count`); `limit` ≤100, honest `total_count` |
| `GET /office/v1/inquiries/{id}` | full detail incl. `allows_conversion`, capped `orders` array, `offer_prefill` payload |
| `GET /office/v1/orders?q=&limit=&offset=` | rows with `ready`, `blocker_reason`, `next_action` — no N+1 |
| `GET /office/v1/orders/{id}` | detail with versions (≤200, flagged) and `ready_to_send` |
| `GET /office/v1/orders/{id}/print-data?version=` | print-sheet data; unknown and unowned are the same `404` |

Orderings are the repository orderings (inquiries by event date then id,
orders by id, versions by number). Search: inquiries by ID, location, event
date, CRM stage, source, intake subject; orders by order ID and source
inquiry ID.

## Commands

Envelope: `{"command_id": "<uuid4>", "expect": {...}, "args": {...}}` —
exact keys per route, unknown or duplicated JSON keys are `400`. Responses
are minimal (IDs + timestamps, no PII); the panel re-reads details via GET.

| Route | `expect` precondition |
|---|---|
| `POST /office/v1/inquiries` | – |
| `POST /office/v1/inquiries/{id}/update` | `updated_at` |
| `POST /office/v1/inquiries/{id}/verify` | – (repeat = success) |
| `POST /office/v1/inquiries/{id}/convert` | server-side: no active order (`409 already_converted`) |
| `POST /office/v1/orders/{id}/versions` | `latest_version_number` |
| `POST /office/v1/orders/{id}/print-confirm` | – (repeat = success) |
| `POST /office/v1/orders/{id}/effective` | `current_effective_order_version_id` |
| `POST /office/v1/orders/{id}/ready` | – (unknown order: `200`, `ready=false`) |
| `POST /office/v1/orders/{id}/cancel` | `updated_at` (repeat = success) |

Idempotency: every command carries a client `command_id`; precondition,
business write and the ledger record commit in **one** SQLite transaction.
Replaying the same `command_id` with the identical command returns the
recorded result verbatim; any divergence (route, order, args, expect,
client) is `409 command_id_conflict`. Domain events are dispatched only
after COMMIT.

Contention: the API waits up to 2 s on a locked database, then answers
`503 {"error":"core_busy"}` with `Retry-After: 1` and guarantees nothing was
written; the client retries with the **same** `command_id`.

Validation (strict, no coercion): `command_id` and every id/version
reference must be a **uuid4**; `expect` timestamps must be ISO-8601 **UTC
with offset** (naive or non-UTC → `400`); on `update` an omitted intake field
keeps its stored value, an empty string clears it, and an explicit `null` is
`400`. A read whose JSON would exceed the **512 KiB** response cap (e.g. a
long legacy Core text) fails closed with `500 internal` rather than emitting
an oversized body.

Error codes (stable, never free text): `unauthorized`, `not_found`,
`invalid_request`, `unsupported_media_type`, `body_too_large`,
`method_not_allowed`, `command_id_conflict`, `stale_state`,
`already_converted`, `external_ref_conflict`, `verification_gate_blocked`,
`order_cancelled`, `kitchen_print_not_confirmed`, `version_not_owned`,
`core_busy`, `internal`.

## Smoke test (status codes only — never dump bodies)

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  http://100.109.6.74:8084/office/v1/queue          # 401 (no token sent)
journalctl -u catering-office-api --since '5 minutes ago' --no-pager \
  | grep -c 'command committed'                     # authenticated use only
```

The token never enters a command line; the authenticated path is exercised
by `RemoteCoreClient` (Phase 2) and by the test suite.

## Phase 2 client — dual mode (`catering_system.ui.remote_core_client`)

`RemoteCoreClient` is the office panel's only path to this API — implemented,
tested, **not yet deployed** (that is a separate rollout step per the pack's
Phase 5). Direct-mode rendering remains byte-identical. Remote mode consumes
the authoritative `QueueView` for the dashboard and uses repository-shaped
read adapters for the remaining existing views.

- **Mode select**: `CORE_OFFICE_API_URL` unset → direct mode, byte-identical
  to before. Both `CORE_OFFICE_API_URL` and `CORE_OFFICE_API_TOKEN` set →
  remote mode, the panel never opens `core.db`. Exactly one of the two set →
  refuses to start before binding a port or opening any file. The token is
  env-only, never a CLI flag or argv.
- **Transport**: bearer from `CORE_OFFICE_API_TOKEN`; 3 s read / 5 s command
  timeout; redirects refused outright (the bearer never leaves for a second
  host); responses capped at 512 KiB; malformed/non-JSON/wrong-content-type
  bodies are treated as failures, never partially trusted. Successful and
  error responses are checked against the exact frozen field/status contract;
  every command response must echo the submitted `command_id`.
- **No business rules on Proxmox**: the client never re-implements
  `InquiryService`/`OrderService`/`OperationalCoreService`'s write logic (ID
  minting, defaults, timestamps) locally — every write is one of the frozen
  named commands above. The dashboard is rendered from one `QueueView` read,
  so Berlin-day/week selection, attention counts and next actions are not
  recomputed on Proxmox. Other reads (`list_all`, `get_by_id`, `list_orders`,
  `get_order`, `list_order_versions`, `get_order_version`, `print_data`)
  satisfy the same repository shape the panel's rendering code already calls.
- **Honest caps**: `week.truncated`, `orders_truncated` and
  `versions_truncated` are retained and shown prominently. Version creation
  uses `versions_total_count` for its optimistic precondition, including when
  only the first 200 versions are returned.
- **Command completion**: once a command returns its validated minimal result,
  the POST handler redirects from that result and does not perform a second
  Core read. A read outage can therefore no longer turn a committed write into
  the false in-request result “nothing was saved”.
- **Idempotent forms**: every mutating page embeds a hidden `_command_id`
  (minted once per render) plus one `_expect_<field>` per precondition the
  route requires (`updated_at`, `latest_version_number`,
  `current_effective_order_version_id` → form field
  `_expect_effective_version_id`). Resubmitting the same loaded page — a
  double click, or a retry after an indeterminate network failure — always
  sends the identical envelope, so the ledger replays rather than repeats.
- **Degradation**: an unreachable/malformed API response renders the fixed
  page *„Core nicht erreichbar — nichts wurde gespeichert"* (503) — never an
  empty or partially-built dashboard, never a silent local write.
- **Rückruf/Auerswald** stays a separate, local, non-Core integration. When it
  is not reachable/configured from Proxmox, remote mode explicitly shows
  `Rückruf-Liste: nur vor Ort verfügbar` (pack §3.9).

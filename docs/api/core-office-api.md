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

Phase 1 is **dormant**: the unit may run, but nothing consumes it — the
office panel keeps its direct database access until Phase 2 configuration.

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
by the panel itself (Phase 2+) and by the test suite.

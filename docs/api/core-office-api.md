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
| `GET /office/v1/queue` | dashboard `QueueView`: open-inquiry attention count, Berlin ISO week (≤100 entries + `total_count`/`truncated`), top-5 inquiry/order rows with next actions, plus `pausiert` / `pausiert_top`. The compatibility JSON keys remain `neue_anfragen` / `neue_anfragen_top`, but rejected and any already-converted Inquiry are excluded. |
| `GET /office/v1/inquiries?q=&limit=&offset=` | list rows (`intake_subject`, `linked_order_id`, `orders_total_count`); `limit` ≤100, honest `total_count` |
| `GET /office/v1/inquiries/{id}` | full detail incl. `allows_conversion`, capped `orders` array, `offer_prefill` payload, `customer_snapshot`, contact completeness (`contact_completeness`, `missing_contact_fields`, `contact_completion_allowed`), and structured first-Offer eligibility (`offer_preparation_blockers`) |
| `GET /office/v1/orders?q=&limit=&offset=` | rows with `ready`, `blocker_reason`, `next_action`, `operational_pause_active` — no N+1 |
| `GET /office/v1/orders/{id}` | detail with versions (≤200, flagged), `ready_to_send`, derived `operational_pause`, the separately derived `payment_reminder` view, and `confirmation_document` eligibility/snapshot summary |
| `GET /office/v1/orders/{id}/print-data?version=` | print-sheet data; unknown and unowned are the same `404` |
| `GET /office/v1/orders/{id}/confirmation-document` | latest or `?document_snapshot_id=` snapshot summary (`404` when none) |
| `GET /office/v1/orders/{id}/confirmation-document/preview?format=json\|html` | customer-facing preview; default `format=json`, `html` returns rendered document |
| `GET /office/v1/orders/{id}/confirmation-document/send-status` | fake-outbox send state (`not_sent` or evidence summary); always `real_delivery=false`; no full message bodies |
| `GET /office/v1/orders/{id}/confirmation-document/fake-outbox` | Office inspection of the frozen fake-outbox payload (`test_transport=true`, `real_delivery=false`) |

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
| `POST /office/v1/inquiries` | – ; optional structured contact args `contact_email`, `contact_phone`, `contact_name`, `company_name` build the customer snapshot; `website_form`/`configurator` sources require valid email **and** phone (`400 contact_information_required`) |
| `POST /office/v1/inquiries/{id}/update` | `updated_at`; with an active linked Order, only `Bestätigt / Auftrag` is compatible (`422 active_order_crm_stage_conflict`) |
| `POST /office/v1/inquiries/{id}/contact-completion` | `updated_at`; args optional `email` / `phone` (at least one); append-only — fills only missing snapshot contacts, identical resubmission idempotent, replacing a stored value is `409 contact_conflict`, malformed value `400 invalid_contact_value` |
| `POST /office/v1/inquiries/{id}/verify` | – (repeat = success) |
| `POST /office/v1/inquiries/{id}/convert` | server-side: no active order (`409 already_converted`), not rejected (`422 inquiry_rejected`), contacts complete (`422 contact_information_incomplete`), verification satisfied, no blocking Offer (`422 offer_blocks_conversion`); success also sets `Bestätigt / Auftrag` |
| `POST /office/v1/inquiries/{id}/prepare-offer` | `args.snapshot` is a full `offer_snapshot_v1` envelope; Inquiry must not be rejected (`422 inquiry_rejected`), required call verification must be satisfied (`422 inquiry_call_verification_unsatisfied`), contacts must be complete (`422 contact_information_incomplete`), no active Order may exist (`409 active_order_exists`; cancelled historical Orders do not block), and no Offer may exist. Initial success and idempotent command replay return the same canonical `offer_id`; a duplicate request with a different command ID returns `409 {"error":"offer_already_exists","offer_id":"<canonical uuid4>"}` so trusted server-side clients can navigate to the existing Offer without guessing. Snapshot `inquiry_id` must match the path (`422 inquiry_id_mismatch`); invalid envelope or hash (`422 invalid_snapshot`); body cap **256 KiB** (not the global 64 KiB); creates Offer + OfferVersion **1** only |
| `POST /office/v1/offers/{offer_id}/prepare-next-version` | `expect.latest_version_number` (int); `args.snapshot` same envelope as prepare-offer; appends OfferVersion **N+1** on the existing Offer (`201`); stale expect or unique collision → `409 version_conflict`; latest not eligible for revision → `422 prepare_next_blocked`; active order → `409 active_order_exists`; contact incomplete → `422 contact_information_incomplete`; inquiry mismatch → `422 inquiry_id_mismatch`; invalid snapshot → `422 invalid_snapshot`; body cap **256 KiB**; does **not** create a second Offer |
| `POST /office/v1/offers/{offer_id}/versions/{version_id}/mark-sent` | `args.sent_at`, `channel`, `recipient_reference`, `evidence_reference`; version must be `Prepared` (`422 sent_recording_blocked`); duplicate send (`409 sent_evidence_exists`); Core mints `recorded_at` and sets `recorded_by` from the authenticated client |
| `POST /office/v1/offers/{offer_id}/versions/{version_id}/record-acceptance` | `args.accepted_variant_id`, `accepted_at`, `channel`, `evidence_reference`, optional `note`; version must be `Sent` (`422 acceptance_blocked`); a newer Prepared/Sent version blocks acceptance (`422 acceptance_blocked_newer_version_exists`); duplicate acceptance (`409 acceptance_already_exists`); wrong variant (`422 invalid_variant`); Core mints `acceptance_id`, `recorded_at`, and sets `recorded_by` from the authenticated client |
| `POST /office/v1/offers/{offer_id}/versions/{version_id}/convert-accepted` | `args.accepted_variant_id`, `acceptance_id`; version must be `Accepted` with matching acceptance triple (`422 conversion_blocked`); wrong variant or acceptance (`422 invalid_variant` / `422 conversion_blocked`); active order without link (`409 already_converted`); duplicate link with different triple (`409 conversion_already_exists`); success creates Order + ConversionLink, seeds payment reminder, sets inquiry `Bestätigt / Auftrag`; idempotent replay returns the same `order_id` (`200`) |
| `POST /office/v1/orders/{id}/versions` | `latest_version_number` |
| `POST /office/v1/orders/{id}/print-confirm` | – (repeat = success) |
| `POST /office/v1/orders/{id}/effective` | `current_effective_order_version_id` |
| `POST /office/v1/orders/{id}/ready` | – (unknown order: `200`, `ready=false`) |
| `POST /office/v1/orders/{id}/pause` | `operational_pause_active`, `latest_pause_event_id` (nullable uuid4); args `reason_code`, optional `note` / `actor_reference` |
| `POST /office/v1/orders/{id}/resume` | `operational_pause_active`, `current_pause_event_id`, `latest_pause_event_id`; args `reason_code`, optional `note` / `actor_reference` |
| `POST /office/v1/orders/{id}/cancel` | `updated_at` (repeat = success) |
| `POST /office/v1/orders/{id}/payment-reminder` | reminder `updated_at` (nullable before first save); exact manual reminder facts only |
| `POST /office/v1/orders/{id}/confirmation-document` | `current_effective_order_version_id`; `args.created_by`; freezes one Auftragsbestätigung snapshot per effective OrderVersion (`201` first create, `200` replay/idempotent per version); blocked when no effective version, pending candidate, kitchen print missing, or no accepted Offer linkage (`422 confirmation_document_blocked` / `422 pending_order_version_change`) |
| `POST /office/v1/orders/{id}/confirmation-document/send` | `current_effective_order_version_id`; `args.document_snapshot_id`, `args.requested_by`; synchronous fake-outbox test send (`201` first success, ledger replay `200`/`201`); `real_delivery=false`; duplicate snapshot with new `command_id` → `409 confirmation_document_already_sent`; eligibility failures → controlled `404`/`409`/`422` (no SMTP/network) |

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
`already_converted`, `external_ref_conflict`,
`active_order_crm_stage_conflict`, `inquiry_rejected`, `verification_gate_blocked`,
`active_order_exists`, `offer_already_exists`, `inquiry_id_mismatch`,
`invalid_snapshot`, `sent_evidence_exists`, `sent_recording_blocked`,
`invalid_sent_evidence`, `acceptance_already_exists`, `acceptance_blocked`,
`acceptance_blocked_newer_version_exists`, `invalid_acceptance_evidence`,
`prepare_next_blocked`, `version_conflict`,
`conversion_already_exists`, `conversion_blocked`,
`contact_information_required`, `contact_information_incomplete`,
`contact_conflict`, `invalid_contact_value`, `invalid_contact_email`,
`invalid_contact_phone`,
`offer_blocks_conversion`,
`order_cancelled`, `kitchen_print_not_confirmed`, `version_not_owned`,
`invalid_payment_reminder`, `confirmation_document_blocked`,
`commercial_totals_invalid`, `confirmation_document_recipient_missing`,
`confirmation_document_already_sent`, `confirmation_document_not_current`,
`outbound_payload_invalid`, `order_not_ready_to_send`, `order_storniert`,
`order_already_paused`, `order_not_paused`,
`core_busy`, `internal`.

`POST /office/v1/orders/{id}/confirmation-document/send` exposes the fresh
`READY_TO_SEND` blockers when the send boundary returns
`order_not_ready_to_send`:

```json
{
  "error": "order_not_ready_to_send",
  "reasons": [
    "operational_pause"
  ]
}
```

`reasons` is a deterministic array from the same readiness evaluation that
blocked the send. With simultaneous blockers it contains all current reasons,
for example `operational_pause` followed by
`pending_order_version_change`. It contains no exception text or internal
fields.

The local payment-reminder extension records only the chosen method, external
invoice reference/dates, paid date and cash-received flag. Its command uses the
same atomic idempotency ledger as the other Office commands. It neither reads
nor writes operational Order progression fields.

The local Auftragsbestätigung document slice (EMAIL_MVP_1 / outbound pack B1)
adds immutable `order_confirmation_document_snapshots`, a read-only customer
preview, and an Office Panel block. It does **not** send email.

The local fake-outbox slice (EMAIL_MVP_2 / outbound pack B2) adds immutable
`order_confirmation_send_attempts`, `order_confirmation_fake_outbox_messages`,
and `order_confirmation_send_evidence`, plus synchronous test dispatch into a
local inspection sink. Responses always carry `real_delivery=false`.
`SendEvidence` means only “accepted by fake outbox”, not delivered to the
customer. **No SMTP credentials, external mail HTTP, retries, resend, or
background dispatcher.** Before any real SMTP transport, PAUSE/Attention
enforcement and a separate security review are mandatory.

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

# Deployment — manual steps (INTEGRATION_DEPLOYMENT_EXECUTION_PACK_V1)

These are the outside-repo steps. Nothing here changes Core semantics; per the
pack, actually performing them needs the owner's HubSpot account, Cloudflare
account, and the physical kitchen Lenovo.

## 1. Kitchen kiosk on the kitchen Lenovo

```bash
git clone <this-repo> && cd silberlöffelcatering
python3 -m catering_system.ui.kiosk_server --db /var/lib/catering/core.db --port 8080
```

- The SQLite file is the Core operational truth store; keep it on the Lenovo's
  local disk (Core-on-Lenovo is a frozen rule) and in the local backup routine.
- Open `http://<lenovo>:8080/` on the kitchen display; the page refreshes every
  60 s. The kiosk is read-only by construction — no reverse proxy config can
  make it write.
- For autostart, wrap the command in a systemd unit or a login item.

## 2. HubSpot office-facing sync

1. In HubSpot: create a **Private App** with CRM object write scope; copy the
   token.
2. Create the custom deal properties used by the mapping (all single-line
   text): `core_inquiry_id`, `core_crm_stage`, `core_inquiry_source`,
   `core_event_date`, `core_time_window`, `core_location`, `core_guest_count`,
   `core_planning_mode`, `core_call_verification_status`.
3. On the office-side host only:

```bash
export HUBSPOT_PRIVATE_APP_TOKEN=<token>
```

4. Construct `HubSpotOfficeInquiryHttp()` where office automation runs.
   Missing token fails loudly; use `HubSpotOfficeInquiryNoop` where a no-op is
   intended. Pipeline/stage mapping is portal configuration — `crm_stage`
   travels as plain text (`core_crm_stage`).

## 3. Cloudflare Worker (External Secure Intake Layer, Slice A §8)

```bash
cd infra/cloudflare_worker
npx wrangler deploy worker.js --name catering-intake
npx wrangler secret put UPSTREAM_TOKEN
# set UPSTREAM_URL as a plain var in wrangler.toml or the dashboard
```

- Point the Wix form's POST at the worker URL.
- The worker whitelists fields, trims/limits text, requires ISO `event_date`,
  caps body size at 16 KB, and forwards with the server-side bearer token.
  The browser never sees any secret (§8.3), and upstream responses are never
  relayed to the public caller.

## Order of bring-up

1. Kiosk on Lenovo against a fresh SQLite db (verify empty week renders).
2. Office flow writing to the same db (inquiry → order → confirm print →
   effective) — entry appears on the kiosk.
3. HubSpot token + one manual `sync_inquiry_from_core` smoke call.
4. Worker deploy last; flip the Wix form to the worker URL.

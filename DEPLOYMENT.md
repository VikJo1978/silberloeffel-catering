# Deployment — manual steps (INTEGRATION_DEPLOYMENT_EXECUTION_PACK_V1)

These are the outside-repo steps. Nothing here changes Core semantics; per the
pack, actually performing them needs the owner's HubSpot account, Cloudflare
account, and the physical kitchen Lenovo.

## 1. Kitchen kiosk on the kitchen Lenovo

```bash
git clone <this-repo> && cd silberlöffelcatering
PYTHONPATH=src python3 -m catering_system.ui.kiosk_server --db /var/lib/catering/core.db --port 8080
```

The repo uses a `src/` layout, so `PYTHONPATH=src` is required when running from
a clone (verified: without it the module is not found). Alternative if the
Lenovo has network access for build tooling: `pip install -e .` once, then the
plain `python3 -m ...` form works.

- The SQLite file is the Core operational truth store; keep it on the Lenovo's
  local disk (Core-on-Lenovo is a frozen rule) and in the local backup routine.
- Open `http://<lenovo>:8080/` on the kitchen display; the page refreshes every
  60 s. The kiosk is read-only by construction — no reverse proxy config can
  make it write.
- For autostart, wrap the command in a systemd unit or a login item.

## 1a. Office panel on the kitchen Lenovo (LAN-only write surface)

```bash
OFFICE_PANEL_PASSWORD=<office-password> \
PYTHONPATH=src python3 -m catering_system.ui.office_panel --db /var/lib/catering/core.db --port 8081
```

- The panel refuses to start without a password (it is a write surface).
- LAN-only: never expose port 8081 outside the office/kitchen network — no
  port forwarding, no reverse proxy to the internet.
- Office staff log in from office browsers as user `office`.
- Same database file as the kiosk; the kiosk stays read-only on its own port.

## 1b. Autostart via systemd (after the smoke test passed)

Unit templates live in `infra/systemd/`. On the Lenovo:

```bash
# 1. Password file (pick a real password — replace the bring-up test one):
sudo mkdir -p /etc/catering
sudo sh -c 'echo "OFFICE_PANEL_PASSWORD=<strong-password>" > /etc/catering/office-panel.env'
sudo chmod 600 /etc/catering/office-panel.env

# 2. Adjust User= and the /opt/catering paths in both unit files to the real
#    repo path and login user, then:
sudo cp infra/systemd/catering-kiosk.service infra/systemd/catering-office-panel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now catering-kiosk catering-office-panel

# 3. Check:
systemctl status catering-kiosk catering-office-panel
```

Both services restart on failure and start on boot (both servers run 24/7).
Changing the panel password later: edit the env file, then
`sudo systemctl restart catering-office-panel`.

## 1c. Core database backup (both servers run 24/7)

Daily cron on the Lenovo — the SQLite file is the operational truth and is
not re-derivable. Create the target directory once (`mkdir -p
/var/backups/catering`), then:

```cron
15 3 * * * sqlite3 /var/lib/catering/core.db ".backup /var/backups/catering/core-$(date +\%u).db"
```

Copy the backup directory to the office server or an external disk as a second
location. (EspoCRM on the office server needs its own backup — contacts and
communication live only there.)

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

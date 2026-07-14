# Current status

Live deployment last verified: **2026-07-13, Europe/Berlin**.

Local undeployed development last verified: **2026-07-14, Europe/Berlin**.
The reviewed implementation HEAD is `4e42112`; the status-only documentation
commit that follows it does not change application behavior. The Office Panel
UI v2 implementation pack is committed separately at `4507938`. Neither commit
changes the live/deployed baseline below.

## Live/deployed baseline

| Environment | Component | Address/binding | State |
|---|---|---|---|
| Lenovo `debiancatering` | Office panel | LAN/Tailscale, port `8081` | active |
| Lenovo `debiancatering` | Kitchen kiosk | LAN/Tailscale, port `8082` | active |
| Lenovo `debiancatering` | Courier app (test) | LAN/Tailscale, port `8090` | active |
| Lenovo `debiancatering` | Website intake | `127.0.0.1:8083` | active |
| VPS `185.16.60.69` | Form and intake staging | public HTTP, port `8080` | active, Core bridge enabled for fake data |

Production facts:

- Tailscale address: `100.109.6.74`
- SSH user: `viktor`
- repository: `/home/viktor/projects/silberloeffel-catering`
- database: `/home/viktor/catering-runtime/core.db`
- daily backups: `/home/viktor/catering-runtime/backups`
- production checkout: clean fast-forward of `origin/main`, last verified on
  2026-07-13; use `git log -1 --oneline` for the current hash
- kitchen kiosk restarted successfully after the order-feed deployment;
  office panel and website intake were not restarted
- kiosk order feed: read-only `GET /api/order-feed?date=YYYY-MM-DD`, private
  LAN/Tailscale only; deployment smoke checks returned `200`/`400` as expected
- kiosk pickup signal: **active** since 2026-07-13. The kiosk reads the courier
  app over loopback, the authenticated refresher logged its first success, and
  the live process has the expected main thread plus refresher thread
- kiosk signal configuration: `/etc/catering/kiosk.env`, owner `root:root`,
  mode `600`; the bearer is absent from the kiosk process arguments
- courier app test deployment: `/home/viktor/projects/courier-app` at local
  commit `18b3633`, own database `/home/viktor/courier-runtime/courier.db`,
  user unit `catering-courier-app.service`, enabled with `Linger=yes`; the
  checkout and database were clean/healthy and the service had zero restarts
- courier app source: private `VikJo1978/courier-app`, branch `main`; the full
  history, Lenovo unit template, runbook notes, and CI workflow are published.
  Lenovo's dedicated read-only deploy key is registered and a clean fetch of
  `origin/main` was verified
- live integration smoke: kiosk HTML `200`, valid/invalid order feed
  `200`/`400`, unauthenticated/authenticated pickup signal `401`/`200`, and
  exactly one initial `pickup signal refresh succeeded` transition
- `PRAGMA quick_check`: `ok` for both Core and courier databases
- staging-to-Core bridge: **active** since 2026-07-13 for invented test data.
  The VPS backend reaches the loopback-only website-intake receiver through a
  restricted reverse-SSH tunnel; the browser receives neither endpoint nor
  bearer
- bridge E2E proof: two public submissions with the same namespaced retry key
  both returned `202` with `forwarded_to_core: true`, while Core and the VPS
  staging database each contained exactly one row; both databases returned
  `PRAGMA quick_check: ok`
- bridge exposure and secret checks: receiver `127.0.0.1:8083`, VPS tunnel
  `127.0.0.1:18083`, no wildcard tunnel listener, both environment files
  `root:root` mode `600`, handoff consumed, and no bearer in process arguments
- office workflow proof: the live panel is active, requires authentication,
  and reads `/home/viktor/catering-runtime/core.db`; the bridge E2E row appears
  as a new `website_form` Inquiry with required verification still `pending`
  and no linked Order. On a SQLite backup copy, the same row rendered in the
  office queue, remained blocked before verification, then completed the
  `pending → verified → OrderVersion 1` workflow. Production stayed at zero
  linked Orders for the test Inquiry
- daily backup cron: 03:15, 14-day retention, `umask 077`
- manual cron-equivalent backup verified on 2026-07-12: `ok`, mode `600`
- encrypted off-host upload cron: 03:25 to VPS, 30-day retention
- off-host restore drill verified on 2026-07-12: `ok`, row counts `3/1/1`

Form staging facts:

- service user: `catering-staging`
- application: `/opt/catering-staging-site`
- database: `/var/lib/catering-staging/staging.db`
- public preview: [http://185.16.60.69:8080/](http://185.16.60.69:8080/)
- immediate purpose: exercise the already-verified staging-to-Core-to-office
  Inquiry workflow; replacement website work is currently deferred by the owner
- 10-user smoke load: 40/40 requests returned `200`; slowest response was
  approximately `0.153 s`
- staging inquiry viewer: read-only `/admin`, loopback/SSH-tunnel only
- Core forwarding health: `core_forwarding: true`; receiver, reverse tunnel,
  and staging services were all active after the E2E proof
- no domain and no TLS; fake data only
- form UX hardening is live: contact-pair precheck, 12-second timeout, stable
  German errors, and retry-safe preservation of entered values are deployed

Offer workflow development:

- the accepted `Inquiry → Angebot` direction is a read-only prefill into the
  separate configurator; no prices, offer drafts, or automatic customer sends
  become Core truth
- the handoff remains dormant until the configurator is deployed and
  `CONFIGURATOR_URL` is set on the office panel
- ADR-012 fixes the future commercial/payment boundary: `Zahlungsart` is agreed
  in the Angebot (`Vorkasse`, `Rechnung`, or `Bar vor Ort`), transferred only
  after Angebot acceptance and Order confirmation, and then drives an Office
  reminder workflow. The Office Panel remains reminder-only; no invoice,
  accounting, banking, schema, API, or UI implementation exists yet.

## Local undeployed development baseline

- Phase 2 (`RemoteCoreClient` and Office Panel direct/remote dual mode) is
  complete locally but has not been deployed. The live Lenovo Office Panel
  continues to use its existing direct `core.db` mode; no Proxmox cutover has
  occurred.
- Phase 3 design is complete locally in
  `PHASE_3_PRINT_ACK_ATTENTION_PACK_V1.md` (`ce499a2`).
- Phase 3 Slice 3A is complete locally at implementation HEAD `707eb5d`: Core
  kitchen print jobs are an append-only attempt history with additive immutable
  facts, with persisted deadlines, tracked reprints, pure state derivation and
  atomic ACK with the existing OrderVersion confirmation fact.
- Slice 3A adds no Office UI, HTTP API, dashboard integration, kitchen agent,
  printer integration, heartbeat or external Lenovo monitoring. None of these
  Phase 3 capabilities is live on Lenovo or Proxmox.
- The `Truthful open-inquiry queue and conversion gate` slice is committed
  locally at `67e2990`: one pure derivation drives
  direct and remote queue/action behavior; rejected and converted inquiries are
  absent from `Offene Anfragen`; rejected conversion is a Core gate; successful
  conversion sets `Bestätigt / Auftrag` in the same direct/API transaction.
  It adds no call history, notes, follow-up dates, tables or CRM integration.
- Two follow-up Office workflow P0 fixes are committed at `20566dd`: an active
  Order locks its Inquiry to `Bestätigt / Auftrag` in Core and removes
  incompatible UI choices, and `Wirksam machen` appears only after
  kitchen-print confirmation. Direct and remote paths are covered.
- Phase 2, Phase 3 design and Slice 3A, the open-inquiry slice and its P0
  follow-up are present on `origin/main` through `20566dd`, but none is
  deployed.
- The Office Panel UI v2 implementation pack and UI2A foundation/shared shell
  are complete and committed locally. UI2A adds
  repo-owned styling and inline icons, explicit active navigation, and desktop
  plus horizontal mobile navigation that works without JavaScript. Core,
  routes, actions and individual screen layouts are unchanged.
- UI2A has not been pushed or deployed. The Lenovo Office Panel
  remains on its existing deployed UI and direct-`core.db` mode; no Proxmox
  Office Panel contains UI2A.
- UI2B and Phase 3B have not started.

## Local undeployed quality baseline

- Python tests: **643 passed**
- coverage gate: **90% minimum**
- last full-project coverage: **90.4%**
- website intake receiver coverage: **99.2%**
- Ruff: clean; format check reported **101 files already formatted**
- Mypy: clean for **71 source files**
- Office Panel UI2A browser smoke: 1280/820/620/320 px, no body overflow,
  no-JS mobile navigation and table-local scrolling verified
- staging-form browser tests and Cloudflare Worker sanitizer tests: clean
- CI: GitHub Actions on every push and pull request

## Verified recovery controls

Recovery-key protection verified on 2026-07-12:

- working private key remains on the Mac only;
- a separately password-protected AES-256 recovery archive was created and
  restore-tested;
- the owner confirmed an off-device email copy;
- the archive password is stored separately in macOS Keychain and was cleared
  from the clipboard;
- no private key or archive password is present in Git, Lenovo, or VPS.

## Operational risks

### High — the staging form has no HTTPS

The VPS form has only a public IP and plaintext HTTP. Even after the narrow Core
test bridge is enabled it must receive invented data only. Real customer data
waits for the domain, TLS, privacy text, and the final protected public path.

### Accepted for testing — no durable intake buffer yet

The current bridge stores its VPS audit row only after Core accepts the
Inquiry. If Core or the reverse tunnel is unavailable, the browser receives a
truthful `502` and may retry with the same idempotency key, but the VPS does not
promise later delivery. This is acceptable for invented test data only.

Before real customer traffic, implement ADR-010's SQLite-backed durable inbox
and prove outage recovery with exactly-once Core intake.

## Next milestones

No website implementation is active. The owner deferred replacement-site work
on 2026-07-13. When that work resumes:

1. Build the replacement customer website on the proven intake path.
2. Add the ADR-010 durable SQLite intake buffer.
3. Obtain domain control, add TLS/Cloudflare, and perform the launch test.

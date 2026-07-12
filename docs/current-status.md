# Current status

Last verified: **2026-07-12, Europe/Berlin**.

## Live environments

| Environment | Component | Address/binding | State |
|---|---|---|---|
| Lenovo `debiancatering` | Office panel | LAN/Tailscale, port `8081` | active |
| Lenovo `debiancatering` | Kitchen kiosk | LAN/Tailscale, port `8082` | active |
| Lenovo `debiancatering` | Website intake | `127.0.0.1:8083` | active |
| VPS `185.16.60.69` | Temporary staging site | public HTTP, port `8080` | active |

Production facts:

- Tailscale address: `100.109.6.74`
- SSH user: `viktor`
- repository: `/home/viktor/projects/silberloeffel-catering`
- database: `/home/viktor/catering-runtime/core.db`
- deployed production revision verified on 2026-07-12: `ad9bafc`
- `PRAGMA quick_check`: `ok`

Staging facts:

- service user: `catering-staging`
- application: `/opt/catering-staging-site`
- database: `/var/lib/catering-staging/staging.db`
- public preview: [http://185.16.60.69:8080/](http://185.16.60.69:8080/)
- 10-user smoke load: 40/40 requests returned `200`; slowest response was
  approximately `0.153 s`
- no domain and no TLS; fake data only

## Quality baseline

- Python tests: **390 passed**
- coverage gate: **90% minimum**; last local result above the gate
- Ruff: clean
- Mypy: clean
- Cloudflare Worker sanitizer tests: clean
- CI: GitHub Actions on every push and pull request

## Operational risks

### Critical — scheduled backup path is not writable by its cron owner

The `viktor` crontab schedules a daily SQLite backup at 03:15 and 14-day
retention cleanup at 03:30. However, `/var/backups/catering` was observed as
`root:root` with mode `750`; `viktor` could not list it. The backup job is
therefore not considered healthy until ownership is corrected and a file is
created and verified manually.

Resolution and verification are documented in
[Backup and restore](runbooks/backup-restore.md#repair-the-current-backup-permission).

### High — production is not yet connected to the public website

The real Silberlöffel site is still managed externally. The intake receiver is
active on Lenovo, but the final public domain/Cloudflare path is not configured.
The VPS page is a temporary design and form-development environment only.

### Medium — repository systemd templates differ from the live Lenovo units

The kiosk and office templates under `infra/systemd/` use placeholder
`/opt/catering` paths. The live units correctly use `/home/viktor/...`.
Deployments must follow the production runbook and review the rendered unit
before restart.

## Next milestones

1. Repair and prove the automatic production backup.
2. Obtain access to the real Silberlöffel website.
3. Configure a TLS-protected public intake path through Cloudflare.
4. Port the approved staging form into the real site.
5. Perform an end-to-end test from public form to office panel.

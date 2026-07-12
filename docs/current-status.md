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
- daily backups: `/home/viktor/catering-runtime/backups`
- deployed production revision verified on 2026-07-12: `ad9bafc`
- `PRAGMA quick_check`: `ok`
- daily backup cron: 03:15, 14-day retention, `umask 077`
- manual cron-equivalent backup verified on 2026-07-12: `ok`, mode `600`
- encrypted off-host upload cron: 03:25 to VPS, 30-day retention
- off-host restore drill verified on 2026-07-12: `ok`, row counts `3/1/1`

Staging facts:

- service user: `catering-staging`
- application: `/opt/catering-staging-site`
- database: `/var/lib/catering-staging/staging.db`
- public preview: [http://185.16.60.69:8080/](http://185.16.60.69:8080/)
- 10-user smoke load: 40/40 requests returned `200`; slowest response was
  approximately `0.153 s`
- no domain and no TLS; fake data only

## Quality baseline

- Python tests: **395 passed**
- coverage gate: **90% minimum**; last local result above the gate
- Ruff: clean
- Mypy: clean
- Cloudflare Worker sanitizer tests: clean
- CI: GitHub Actions on every push and pull request

## Operational risks

### High — recovery private key needs a second protected copy

Encrypted off-host backup and restore are proven. Its private recovery key is
deliberately present only on the Mac, not Lenovo or VPS. Confirm that
`~/.config/silberloeffel-backup/gnupg` is covered by an encrypted personal
backup; losing that directory would make the VPS copies undecryptable.

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

1. Confirm a protected second copy of the GPG recovery key.
2. Obtain access to the real Silberlöffel website.
3. Configure a TLS-protected public intake path through Cloudflare.
4. Port the approved staging form into the real site.
5. Perform an end-to-end test from public form to office panel.

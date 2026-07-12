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
- production checkout revision verified on 2026-07-12: `ce4d8e3`
- services were not restarted for that checkout sync; their runtime modules
  have not changed since the previously running `ad9bafc`
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

- Python tests: **403 passed**
- coverage gate: **90% minimum**; last local result above the gate
- last full-project coverage: **93.1%**
- website intake receiver coverage: **99.2%**
- Ruff: clean
- Mypy: clean
- Cloudflare Worker sanitizer tests: clean
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

### High — production is not yet connected to the public website

The real Silberlöffel site is still managed externally. The intake receiver is
active on Lenovo, but the final public domain/Cloudflare path is not configured.
The VPS page is a temporary design and form-development environment only.

## Next milestones

1. Obtain access to the real Silberlöffel website.
2. Configure a TLS-protected public intake path through Cloudflare.
3. Port the approved staging form into the real site.
4. Perform an end-to-end test from public form to office panel.

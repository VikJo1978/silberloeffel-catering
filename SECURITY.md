# Security policy

## Supported code

The `main` branch and the currently deployed production revision are supported.
Historical pack documents are not executable security guidance.

## Report a vulnerability

Do not open a public GitHub issue containing credentials, customer information,
production IP access details beyond what is already documented, or an exploit
proof against the live service. Contact the repository owner privately and
include only the minimum information required to reproduce the issue.

## Secrets

Never commit or document values for:

- `OFFICE_PANEL_PASSWORD`
- `WEBSITE_INTAKE_TOKEN`
- `UPSTREAM_TOKEN`
- `AUERSWALD_SYNC_PASSWORD`
- SSH private keys
- Cloudflare, GitHub, CRM, email, or hosting credentials

Production values belong in root-readable environment files or the relevant
provider's secret store. `.env.example` lists names only.

## Network exposure

| Surface | Required exposure |
|---|---|
| Office panel `8081` | private LAN/Tailscale only |
| Kitchen kiosk `8082` | private LAN only |
| Website intake `8083` | Lenovo loopback only |
| VPS staging `8080` | temporary public HTTP; fake data only |

The production public website must reach Lenovo only through the Cloudflare
Worker/Tunnel intake path. Never proxy office or kiosk routes.

## Data handling

- Production `core.db` stays on Lenovo and encrypted off-host backups.
- The off-host GPG private key stays on the Mac only; Lenovo receives its
  public encryption key and VPS stores ciphertext only.
- The Lenovo-to-VPS transport key is restricted by an SSH forced-command
  allowlist and cannot start a shell.
- Do not copy production data to staging, GitHub, test fixtures, or screenshots.
- Redact contact information from logs and issue reports.
- The public Worker never returns the Lenovo response body.
- Staging submissions are disposable and must use fake contact data until TLS
  and a privacy notice are in place.

## Application controls

- Office panel uses HTTP Basic authentication and CSRF tokens for POST actions.
- Public production intake uses field allowlisting, body limits, bearer-token
  authentication between Worker and receiver, and idempotency keys.
- SQLite migrations validate history and fail closed.
- Repository constraints prevent invalid OrderVersion ownership and duplicate
  external website references.
- CI enforces lint, formatting, type checks, tests, and coverage.

## Incident response

1. Remove or block the exposed surface.
2. Preserve relevant journals without customer payloads.
3. Rotate affected credentials.
4. Verify database integrity and backup availability.
5. Patch and test locally/CI.
6. Deploy through the production runbook.
7. Record the incident, impact window, rotation, and verification privately.

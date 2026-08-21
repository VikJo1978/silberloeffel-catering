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
- `OFFICE_API_TOKEN` / `CORE_OFFICE_API_TOKEN`
- employee-introspection service tokens
- Kitchen API / print-agent bearer tokens
- kiosk/courier pickup-signal tokens
- `AUERSWALD_SYNC_PASSWORD`
- SSH or GPG private keys
- Cloudflare, GitHub, CRM, email, hosting, or recovery credentials

The master human recovery store is the password-manager vault
`Bitwarden / Silberloeffel Catering`. Production runtime values belong in
root-readable environment files or the relevant provider's secret store.
`.env.example` lists names only; `docs/operations/secrets-registry.md` records
secret names, consumers and locations without values.

A production host must not be the only recoverable copy of a credential required
to rebuild itself. Conversely, do not copy secrets from the host into GitHub,
issues, logs, screenshots, or chat to create an ad-hoc backup.

## Network exposure

| Surface | Required exposure |
|---|---|
| Office panel `8081` | private LAN/Tailscale only |
| Kitchen kiosk `8082` | private LAN/Tailscale only |
| Website intake `8083` | Lenovo loopback only |
| Core Office API `8084` | Tailscale only |
| Kitchen API `8086` | Lenovo loopback only |
| VPS staging `8080` | temporary public HTTP; fake data only |
| VPS staging intake forward `18083` | VPS loopback only; restricted reverse SSH |

The production public website must reach Lenovo only through the approved
Cloudflare/ingress path. Never proxy office, Core API, Kitchen API or kiosk routes
onto the public Internet.

## Privileged automation

The private `silberloeffel-ops` self-hosted runner runs as unprivileged user
`chatops`. It must never receive unrestricted sudo or be attached to untrusted
pull-request code. Privileged actions are restricted to exact commands exposed by
the root-owned `/usr/local/sbin/catering-ops` wrapper and an explicit sudoers
allowlist.

Automation output must be designed not to print environment values, customer
payloads, private keys or bearer tokens. Revoking the runner must not stop the
application itself.

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
- The optional staging-to-Core test bridge may create namespaced Inquiries only
  through the normal bearer-protected receiver. It has no Core read path and no
  Order capability.

## Application controls

- Office panel uses its configured authentication mode and CSRF tokens for POST
  actions.
- Public production intake uses field allowlisting, body limits, bearer-token
  authentication between Worker and receiver, and idempotency keys.
- Staging forwarding accepts only the exact loopback receiver URL, refuses
  redirects, and treats anything except a valid `202` response as failure.
- SQLite migrations validate history and fail closed.
- Repository constraints prevent invalid OrderVersion ownership and duplicate
  external website references.
- CI enforces lint, formatting, type checks, tests, and coverage.

## Incident response

1. Remove or block the exposed surface.
2. Preserve relevant journals without customer payloads.
3. Rotate affected credentials and update the password-manager recovery record.
4. Verify database integrity and backup availability.
5. Patch and test locally/CI.
6. Deploy through the production runbook.
7. Record the incident, impact window, rotation names (never values), and
   verification privately.

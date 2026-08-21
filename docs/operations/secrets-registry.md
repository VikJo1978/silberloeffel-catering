# Secrets registry

This is an inventory of secret *identifiers and storage locations only*.
Real values must never appear in this repository, GitHub issues, deployment logs,
shell history, screenshots, or chat transcripts.

The target human recovery store is **Bitwarden → `Silberloeffel Catering`**.
Runtime copies remain in root-readable environment files or the provider's own
secret store.

`Master vault record` entries below are naming targets. Populate the actual
Bitwarden records without copying their values into Git.

## Application secrets

| Secret / variable | Consumer | Runtime location | Master vault record | Rotation notes |
|---|---|---|---|---|
| `OFFICE_PANEL_PASSWORD` | Office Panel legacy/basic auth where enabled | `/etc/catering/office-panel.env` | `05 Office Panel` | Rotate when shared access changes; employee auth may supersede it |
| `OFFICE_API_TOKEN` | Core Office API bearer authentication | `/etc/catering/office-api.env` | `06 Core Office API` | Rotate together with every configured client |
| `CORE_OFFICE_API_TOKEN` | Office Panel client of Core API | `/etc/catering/office-panel.env` | `06 Core Office API` | Must match the API-side bearer used for the panel |
| `EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON` | trusted employee-auth service clients | `/etc/catering/office-api.env` | `06 Core Office API / introspection clients` | Use separate random secret per client; revoke individually |
| `WEBSITE_INTAKE_TOKEN` | website intake receiver | `/etc/catering/website-intake.env` | `07 Website Intake` | Rotate with upstream sender/Worker configuration |
| `UPSTREAM_TOKEN` | public Worker/upstream integration where configured | provider secret store | `04 Cloudflare / website upstream` | Never place in local `.env.example` with a real value |
| `PICKUP_SIGNAL_TOKEN` | kiosk client of courier pickup signal | `/etc/catering/kiosk.env` | `08 Kiosk / pickup signal` | Paired with courier-side signal token |
| `KIOSK_SIGNAL_TOKEN` | courier-side pickup signal endpoint | courier runtime env | `10 Courier / kiosk signal` | Rotate as a pair with kiosk consumer |
| `KITCHEN_API_TOKEN` | Kitchen API bearer authentication | `/etc/catering/kitchen-api.env` | `09 Kitchen Print / API token` | Paired with agent token |
| `KITCHEN_PRINT_AGENT_TOKEN` | Kitchen Print Agent client | `/etc/kitchen-print-agent.env` | `09 Kitchen Print / API token` | Must match Kitchen API token unless architecture changes |
| `AUERSWALD_SYNC_PASSWORD` | Auerswald callback/sync integration | integration runtime env | `11 Auerswald` | Rotate at source and runtime together |
| `AUERSWALD_SYNC_USER` | Auerswald integration account name | integration runtime env | `11 Auerswald` | Treat as credential metadata even if not secret alone |
| `HUBSPOT_ACCESS_TOKEN` | Auerswald/HubSpot integration where active | container/runtime secret | `12 External services / HubSpot` | Rotate in HubSpot and runtime; do not expose in logs |

## Infrastructure credentials

| Credential | Runtime location | Master / recovery location | Notes |
|---|---|---|---|
| Lenovo SSH private key(s) used by operators | operator machines, `~/.ssh` | `02 Debian - debiancatering` plus encrypted key backup | Never commit private keys |
| Repository deploy key for `silberloeffel-catering` | Lenovo `~/.ssh` | `01 GitHub / catering deploy key` | GitHub deploy key should remain read-only |
| Courier repository deploy key | Lenovo `/home/viktor/.ssh/courier_app_github` | `01 GitHub / courier deploy key` | GitHub write access disabled |
| GitHub self-hosted runner registration | GitHub + `/home/chatops/actions-runner` | `01 GitHub / ops runner` metadata only | Registration tokens are short-lived; do not archive them as passwords |
| Tailscale account/recovery access | Tailscale provider | `03 Tailscale` | Record owner account and recovery method, not reusable ephemeral auth keys unless deliberately managed |
| Cloudflare account/recovery access | Cloudflare provider | `04 Cloudflare` | Store recovery codes separately under `14 Recovery Codes` |
| Off-host backup GPG private key | operator Mac only | `13 Backup / GPG` encrypted backup | Must not be copied to Lenovo; Lenovo needs only public encryption material |
| Email/SMTP credentials, if configured | provider/runtime secret store | `12 Email / external services` | Document exact consumer when added |

## Non-secret configuration

Do not put ordinary configuration into the password manager just because it is in
an `.env` file. URLs, ports, company PDF text and feature switches belong in Git
or the service inventory when they are not sensitive. `.env.example` remains the
canonical list of application environment-variable names.

## Bitwarden record template

For every production credential create a record with:

```text
Name: <system / purpose>
Username: <if applicable>
Password / token: <secret value, Bitwarden only>
Environment variable: <VARIABLE_NAME>
Runtime path: <path on host/provider>
Consumer: <service/component>
Created: <date>
Last rotated: <date>
Recovery / rotation notes: <short procedure or link to runbook>
```

## Rotation procedure

1. Take a production database backup when the affected service can write Core.
2. Create the replacement secret in Bitwarden/provider first.
3. Update all producer and consumer runtime copies without printing the value.
4. Restart only affected services.
5. Verify authentication succeeds and old credentials fail where feasible.
6. Revoke the previous credential.
7. Record the rotation date here or in the relevant deployment log without
   recording the value.

## Emergency rule

If a real credential is ever committed to Git or posted in an issue, deleting the
text is not sufficient. Treat it as compromised, rotate it immediately, and then
remove/redact the exposed material.

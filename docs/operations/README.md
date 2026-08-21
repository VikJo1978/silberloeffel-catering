# Operations

This directory is the operational entry point for the live Silberlöffel Catering system.
It answers four questions: what is running, where configuration lives, where secret
values are recovered from, and how to rebuild the system when a host fails.

## Start here

1. `../current-status.md` — current verified production state and open drift.
2. `service-inventory.md` — services, ports, runtime paths and ownership.
3. `secrets-registry.md` — names and locations of credentials, never their values.
4. `deployment-log.md` — production deployment evidence and rollback anchors.
5. `disaster-recovery.md` — recovery order for a lost or rebuilt Lenovo host.
6. `../runbooks/lenovo-production.md` — detailed production commands and checks.
7. `../runbooks/backup-restore.md` — database backup and restore procedure.

## Source-of-truth rules

- Git documents configuration structure, paths, commands and recovery procedures.
- A password manager is the master recovery store for human-managed production
  credentials. The target vault is `Bitwarden / Silberloeffel Catering`.
- Runtime copies of secrets live only in root-readable environment files or in the
  provider's own secret store.
- GitHub contains secret *names* only. Never commit, paste into issues, or record
  real secret values.
- `docs/current-status.md` is a snapshot, not a history book. Old deployment facts
  belong in `deployment-log.md`, `CHANGELOG.md`, or `WORKLOG.md`.
- Every production deployment must leave an evidence record containing the target
  commit, database backup path, restarted services and verification result.
- Configuration drift between `/etc/systemd/system` and tracked unit files is an
  explicit operational risk and must be recorded until eliminated.

## Password-manager naming convention

Use one folder/collection named `Silberloeffel Catering`, with records grouped as:

- `01 GitHub`
- `02 Debian - debiancatering`
- `03 Tailscale`
- `04 Cloudflare`
- `05 Office Panel`
- `06 Core Office API`
- `07 Website Intake`
- `08 Kiosk`
- `09 Kitchen Print`
- `10 Courier`
- `11 Auerswald`
- `12 Email / external services`
- `13 Backup / GPG`
- `14 Recovery Codes`

Each record should include the environment-variable name, runtime file path, service,
creation date, last rotation date and a short statement of what consumes the secret.
Do not duplicate a secret into free-form notes when a password field can hold it.

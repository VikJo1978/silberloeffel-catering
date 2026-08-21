# Disaster recovery: rebuild production from zero

Use this when the Lenovo production host is lost, replaced, or too damaged to
repair safely. This is an ordering guide, not a substitute for the detailed
backup and production runbooks.

The recovery objective is to rebuild from versioned code + a verified Core DB
backup + the password-manager vault. No single production host should be the
only copy of a credential required to rebuild itself.

## Recovery inputs

Before starting, obtain:

- access to GitHub repositories;
- access to `Bitwarden / Silberloeffel Catering`;
- Tailscale account/recovery access;
- a verified Core database backup, preferably encrypted off-host;
- the off-host GPG private key from its operator-side encrypted backup;
- SSH/deploy key recovery material where keys are intentionally persistent;
- current service inventory and latest successful deployment record.

If any one of these is missing, record the gap before improvising a replacement.

## Rebuild order

### 1. Base host

- install the supported Debian release;
- create the `viktor` operator account;
- apply OS updates;
- install Git, SQLite, systemd dependencies, Tailscale and the supported Python
  runtime/bootstrap tooling;
- join Tailscale and verify the expected private network reachability.

Do not expose application ports publicly as a shortcut during recovery.

### 2. Application code

Clone `VikJo1978/silberloeffel-catering` to:

```text
/home/viktor/projects/silberloeffel-catering
```

Check out the exact production target commit from the latest approved deployment
record. Build `.venv` from the committed dependency lock according to the Lenovo
runbook. Do not reconstruct Python packages from memory.

### 3. Core database

Restore the selected verified backup to:

```text
/home/viktor/catering-runtime/core.db
```

Set owner/mode according to the backup runbook and run SQLite integrity checks
before starting any writer service.

Never use a stale development or staging database as a production substitute.

### 4. Secrets and configuration

Recreate root-owned environment files from Bitwarden/provider records. Use the
names and paths in `secrets-registry.md` and `.env.example`.

Typical files include:

```text
/etc/catering/office-api.env
/etc/catering/office-panel.env
/etc/catering/website-intake.env
/etc/catering/kiosk.env
/etc/catering/kitchen-api.env
/etc/kitchen-print-agent.env
```

Set restrictive permissions. Do not copy values through GitHub, tickets or chat.
If the vault lacks a required value, rotate/create a new credential at the
provider instead of trying to recover it from logs.

### 5. Install systemd units

Install only reviewed, tracked unit files that match the intended production
revision. Run `systemctl daemon-reload`, enable required units and verify effective
`ExecStart`, `WorkingDirectory`, `EnvironmentFiles` and exposure before starting.

The current Kitchen Print configuration has documented drift from `main`; resolve
that drift before using `main` as the source for Kitchen unit reinstallation.

### 6. Start in dependency order

Suggested order:

1. Core Office API;
2. Office Panel;
3. Website Intake;
4. Kiosk;
5. Courier / pickup-signal components;
6. Kitchen API;
7. Kitchen Print Agent;
8. auxiliary integrations.

Start only the components required for the current recovery scope. A partially
recovered system with clear disabled components is safer than an unverified
full-stack start.

### 7. Verify

At minimum:

- all intended services are `active`;
- listeners match `service-inventory.md`;
- `PRAGMA quick_check`/documented DB verification passes;
- unauthenticated protected endpoints reject access as expected;
- Office Panel reads the restored Core data;
- one safe business-flow smoke test succeeds;
- journals contain no crash loop, traceback or repeated authentication failure.

Do not test recovery by creating real customer data unless the system is already
approved for live traffic.

### 8. Restore automation last

Only after the application is stable:

- restore local and encrypted off-host backup schedules;
- verify a new backup can be created and restored/read;
- install the private GitHub Actions self-hosted runner if remote operations are
  still desired;
- recreate `/usr/local/sbin/catering-ops` and its narrow sudo policy from the
  documented ops design, never by granting the runner unrestricted sudo.

## Loss of GitHub runner only

The runner is not required for application operation. If it fails, production
continues. Reinstall/re-register it from the private `silberloeffel-ops` repository
and verify it runs as unprivileged user `chatops`. Do not solve runner failure by
making it run as root.

## Loss of Bitwarden access

Treat this as an infrastructure incident. Do not dump `/etc/catering/*.env` into
an insecure location to create an emergency vault. Recover Bitwarden access or
rotate credentials provider-by-provider, then rebuild the vault deliberately.

## Recovery completion record

Create a new entry in `deployment-log.md` containing the restored DB backup,
application commit, services started, verification evidence and any credentials
that were rotated (names only, never values).

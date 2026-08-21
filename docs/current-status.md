# Current status

Operational truth last verified: **2026-08-21 08:11 CEST** by a read-only audit
running on the production host `debiancatering` through the restricted private
operations runner.

This page is intentionally short. It describes what is true now. Historical
production detail belongs in `docs/operations/deployment-log.md`, `CHANGELOG.md`
and `WORKLOG.md`.

## Production identity

| Item | Current verified value |
|---|---|
| Host | `debiancatering` |
| Tailscale IPv4 | `100.109.6.74` |
| Application checkout | `/home/viktor/projects/silberloeffel-catering` |
| Production checkout revision | `4eadf014654992619be317c8b3b079c5d8dcd26b` |
| Core database | `/home/viktor/catering-runtime/core.db` |
| Restricted ops wrapper | `/usr/local/sbin/catering-ops` |
| Private ops repository | `VikJo1978/silberloeffel-ops` |
| Actions runner user | `chatops` |

A later documentation-only merge can advance `origin/main` without changing the
application code loaded by running services. Do not equate GitHub HEAD with a
production deployment; use the deployment log and live revision check.

## Live services

Read-only systemd and listener audit on 2026-08-21:

| Component | Enabled | Active | Listener / exposure |
|---|---|---|---|
| `catering-office-panel.service` | yes | yes | `0.0.0.0:8081` |
| `catering-office-api.service` | yes | yes | `100.109.6.74:8084` |
| `catering-kiosk.service` | yes | yes | `0.0.0.0:8082` |
| `catering-website-intake.service` | yes | yes | `127.0.0.1:8083` |
| `kitchen-print-agent.service` | yes | yes | client process, no dedicated HTTP listener |
| `catering-kitchen-api.service` | yes | yes | `127.0.0.1:8086` |
| GitHub Actions runner for `silberloeffel-ops` | n/a | yes | outbound GitHub connection |
| Courier application | not audited in this pass | listener observed | `0.0.0.0:8090` |
| `catering-intake-vps-tunnel.service` | unit not found | no | no `18083` listener observed |

See `docs/operations/service-inventory.md` for exact live `ExecStart`, env-file
paths and known drift.

## Latest production deployment

On **2026-08-21 08:03 CEST**, production was fast-forwarded from
`60f50c8ddd0bb5532bd673290d7d0b248819d4da` to
`4eadf014654992619be317c8b3b079c5d8dcd26b`, deploying PR #145 for the Order
hard-delete foreign-key failure.

Pre-restart database backup:

```text
/home/viktor/catering-runtime/core.db.backup-20260821-080351
```

`catering-office-api.service` restarted successfully and remained active.

At **2026-08-21 08:05:28 CEST**, a real production hard-delete completed with:

```text
command committed route=/office/v1/orders/{id}/delete status=200
```

No new `FOREIGN KEY constraint failed` or
`cannot start a transaction within a transaction` error followed the deployment.
The older occurrences remain in the journal as historical evidence from
2026-08-20.

See `docs/operations/deployment-log.md` for the durable deployment record.

## Production database and backups

| Item | State |
|---|---|
| Core DB path | `/home/viktor/catering-runtime/core.db` |
| Production owner expectation | `viktor:viktor` |
| Production mode expectation | `600` |
| Latest deployment backup verified in this audit trail | `core.db.backup-20260821-080351` |
| Scheduled local/off-host backup jobs | documented in backup runbook, **not re-verified in the 2026-08-21 service audit** |
| Restore procedure | `docs/runbooks/backup-restore.md` |

Do not infer backup health from the existence of an old backup. Scheduled backup
freshness still needs an explicit health check/alerting mechanism.

## Secrets

Real secret values are forbidden in Git. The operational model is:

- master human recovery copy: `Bitwarden / Silberloeffel Catering`;
- runtime copies: root-readable env files such as `/etc/catering/*.env` and
  `/etc/kitchen-print-agent.env`, or provider-managed secret stores;
- Git: variable names, paths, consumers and rotation procedures only.

See `docs/operations/secrets-registry.md` and `SECURITY.md`.

## Remote operations / ChatOps

A private self-hosted GitHub Actions runner is installed on `debiancatering`:

```text
runner repo: VikJo1978/silberloeffel-ops
runner name: debiancatering
runner labels: self-hosted, Linux, X64, catering-prod
runner OS user: chatops
runner home: /home/chatops/actions-runner
```

`chatops` does not have general access to Viktor's project directory and does not
have unrestricted sudo. Privileged production operations are restricted to the
root-owned wrapper `/usr/local/sbin/catering-ops` through
`/etc/sudoers.d/chatops-catering`.

The private ops repository must remain private. Do not attach this privileged
runner to pull-request workflows from the public/main application repository.

## Known configuration drift

### Kitchen Print Phase 3B

The live host currently runs `kitchen-print-agent.service` and
`catering-kitchen-api.service`, but the exact source changes used to activate
those services are not on `main`.

They were preserved before the 2026-08-21 production fast-forward on branch:

```text
wip/kitchen-print-lenovo-phase3b
```

Observed live Kitchen Print Agent uses the project checkout and `.venv`, while
tracked `main` still describes the older `/opt/kitchen-print-agent` runtime.
`catering-kitchen-api.service` is also absent from `main` at this snapshot.

**Operational rule:** do not reinstall Kitchen systemd units from `main` until
that branch is reviewed and reconciled.

## Open operational risks

1. Kitchen systemd/source drift described above.
2. Scheduled backup freshness and off-host backup alerting were not re-verified
   in the 2026-08-21 audit.
3. Port `8090` is listening, but the courier user-service ownership/state was not
   re-audited by the system-level runner pass.
4. The current restricted deploy wrapper creates the SQLite backup after the Git
   fast-forward but before service restart. This keeps the running process on the
   old loaded code until the backup exists, but the wrapper should eventually be
   tightened so backup creation precedes any checkout mutation.
5. One-off recovery commands added to the ops wrapper during the 2026-08-21
   migration should be removed when no longer needed.

## Next operational actions

1. Populate the Bitwarden `Silberloeffel Catering` vault from the secret registry.
2. Reconcile and review `wip/kitchen-print-lenovo-phase3b` into a tracked source
   of truth or deliberately replace it.
3. Verify local and encrypted off-host backup schedules and add stale-backup
   detection.
4. Remove one-off ops permissions after the Kitchen/deployment cleanup.
5. Keep future deployment evidence in `docs/operations/deployment-log.md`.

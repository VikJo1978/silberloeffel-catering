# Current status

Operational truth last updated: **2026-09-08**.

This file is a current operational snapshot, not a deployment diary. Historical details
remain available in Git history, merged pull requests, issue history and the runbooks
under `docs/runbooks/`.

Repository state and production state are deliberately separate. A commit on
`origin/main` is not production until the relevant service has loaded it and the
post-deploy checks have been recorded.

## Current repository state

| Item | Value |
|---|---|
| `origin/main` at the start of this operational-truth update | `a314b51c2f7d942e815bcbf133ec72bb47ddb668` (`a314b51`) |
| Latest deployed application change | `fix(print): require verified IPP completion within ACK deadline (#241)` |
| Working release flow | branch → PR → green CI → merge → production fast-forward |
| Active pre-launch validation | issue #218, coherent end-to-end operational validation |

The kitchen-print observability/runtime-truth cleanup is being prepared separately from
production. Documentation or branch commits must not be interpreted as a production
deployment and must not trigger a service restart by themselves.

## Production state

Production host: `debiancatering`.

| Item | Value |
|---|---|
| Application repository | `/home/viktor/projects/silberloeffel-catering` |
| Core DB | `/home/viktor/catering-runtime/core.db` |
| Deployed application commit | `a314b51c2f7d942e815bcbf133ec72bb47ddb668` (`a314b51`) |
| Kitchen Print Agent | `active/running`; PID `1173322` at 2026-09-08 verification; `NRestarts=0` |
| Kitchen API | loopback `127.0.0.1:8086` |
| Office API | `active` on `100.109.6.74:8084` |
| CUPS | active; queue `Brother_L2710DN_LAN` enabled and idle after E2E |
| Kitchen Print Agent environment | tracked checkout + project `.venv`, no systemd drop-in |

The effective production Kitchen Print Agent unit at verification time was:

```text
WorkingDirectory=/home/viktor/projects/silberloeffel-catering
Environment=PYTHONPATH=/home/viktor/projects/silberloeffel-catering/infra
EnvironmentFile=/etc/kitchen-print-agent.env
ExecStart=/home/viktor/projects/silberloeffel-catering/.venv/bin/python3 -m kitchen_print_agent
Restart=always
RestartSec=5
```

No production database migration was part of the Kitchen Print completion-verification
rollout.

## Kitchen Print completion verification

The 2026-09-08 rollout closed the critical false-ACK risk in the kitchen print path.
The agent now waits for the exact local CUPS job to reach a verified successful IPP
terminal state before acknowledging Core. Canceled, aborted or unverifiable states fail
closed and do not produce an ACK.

Production evidence recorded during the rollout:

- previous production commit before the rollout:
  `1626d616b842f54749c82d769d86dd7b2c080db8`;
- deployed commit: `a314b51c2f7d942e815bcbf133ec72bb47ddb668`;
- production worktree was clean after the fast-forward and restart;
- `kitchen-print-agent` restarted successfully at 2026-09-08 09:26:43 CEST;
- no subsequent automatic service restart was observed (`NRestarts=0`);
- real historical CUPS job `Brother_L2710DN_LAN-17` parsed as IPP state `9`
  (successful completion);
- real historical CUPS job `Brother_L2710DN_LAN-18` parsed as IPP state `7`
  (canceled), proving that the new parser distinguishes success from cancellation;
- a controlled synthetic E2E used a consistent disposable copy of `core.db`, a
  synthetic PDF containing no customer data, the real Kitchen Print Agent code, local
  CUPS and the real Brother queue;
- that E2E created `Brother_L2710DN_LAN-19` at 2026-09-08 09:39:33 CEST;
- the test print job was accepted at `2026-09-08T07:39:33.656371+00:00` and
  acknowledged at `2026-09-08T07:39:56.025896+00:00` with no rejection;
- the test concluded with `E2E_ACK_SUCCESS`;
- the disposable test database was removed after verification;
- the production Core database was not mutated by the synthetic E2E.

The recorded evidence proves the software path through Core/Kitchen API → agent → local
CUPS → verified IPP completion → ACK. Physical paper output should only be claimed as a
separate assurance when an operator explicitly records seeing the expected sheet; that
physical observation is not promoted as independently recorded fact in this status
snapshot.

## Kitchen Print runtime truth and observability follow-up

Audit after the rollout found an operational-truth mismatch: the tracked
`infra/systemd/kitchen-print-agent.service` still described the obsolete `/opt` +
`/usr/bin/python3` layout even though the live Lenovo unit uses the repository checkout
and `.venv`. The cleanup branch aligns the tracked unit with the effective production
unit and adds lifecycle logging for opaque print-job IDs, CUPS job IDs, successful
completion, rejection codes and ACKs. Logs must never contain bearer tokens, customer
data or document bodies.

The cleanup is a repository change only until separately approved for production.
Do not install the unit or restart `kitchen-print-agent` merely because the cleanup PR
merges.

## Runtime / release controls

The established production deployment discipline remains:

1. exact target commit has green CI;
2. production worktree must be clean;
3. DB-affecting deploys require a consistent backup and integrity verification;
4. production updates use `git merge --ff-only origin/main`, never an ad-hoc force
   update;
5. restart only services that must load changed code;
6. verify effective systemd properties, service state, journals and relevant HTTP/CUPS
   behavior after restart;
7. update this operational-truth snapshot after a verified production deploy;
8. documentation-only changes do not constitute an application deployment.

## Known operational risks

### High — branch protection is not independently verified

The GitHub integration available to prior audits could not independently verify the
branch-protection endpoint. The desired server-side state remains PR-required `main`,
green CI required before merge, force push disabled, and direct push prevented or
tightly controlled. Until owner/admin verification proves that state, release discipline
remains partly a process control.

### High — no backup health / stale-backup alerting

The repository contains `docs/proposals/BACKUP_HEALTH_AND_ALERTING_V1.md`, but automated
failure/staleness notification is not recorded as implemented. Backups must not be
considered healthy merely because a schedule exists.

### Medium — Kitchen Print alerting is not implemented

The Kitchen Print Agent now has service-level visibility and the cleanup branch adds
useful lifecycle logs, but automatic notification for repeated restart, Kitchen API
unavailability, `printer_unavailable` or repeated `spool_rejected` remains separate
future operational work.

### Accepted — first real BAR cash E2E still depends on a real BAR order

Do not create synthetic production customer/order data solely to force the Courier cash
handoff E2E. Exercise that path on the first real `BAR_VOR_ORT` order and verify the
receipt/handoff/final-paid facts truthfully.

## Recovery controls

Production DB changes require a pre-deploy backup when migrations or other data risk are
involved. Code rollback and database restore remain separate decisions. For Kitchen Print
completion-verification, the 2026-09-08 pre-rollout commit
`1626d616b842f54749c82d769d86dd7b2c080db8` is historical evidence for that deployment,
not a permanent rollback target for future deployments.

Use the current runbooks under `docs/runbooks/` and record the known-good commit separately
for every deployment.

## Next actions

1. Complete the Kitchen Print runtime-truth/observability cleanup PR and require green CI.
2. Do **not** deploy that cleanup to production without a separate explicit deployment
   decision and a fresh preflight.
3. Continue issue #218 with clearly synthetic pre-launch data across the remaining
   application boundaries.
4. Exercise the Courier cash handoff on the first real `BAR_VOR_ORT` order.

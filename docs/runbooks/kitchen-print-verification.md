# Kitchen print completion verification

The production Lenovo checkout is `/home/viktor/projects/silberloeffel-catering`.
The kitchen print agent runs from that checkout with the project virtual environment:

```text
WorkingDirectory=/home/viktor/projects/silberloeffel-catering
PYTHONPATH=/home/viktor/projects/silberloeffel-catering/infra
ExecStart=/home/viktor/projects/silberloeffel-catering/.venv/bin/python3 -m kitchen_print_agent
EnvironmentFile=/etc/kitchen-print-agent.env
```

Always compare the tracked unit with the effective production unit before changing
systemd:

```bash
systemctl cat kitchen-print-agent
systemctl show kitchen-print-agent \
  -p FragmentPath -p DropInPaths -p WorkingDirectory -p EnvironmentFiles -p ExecStart
```

Do not print or paste the environment-file contents.

## Completion contract

The adapter submits to **local CUPS at localhost:631** and queries the returned
numeric job ID on that same server. A `CUPS_SERVER` environment variable or user
`client.conf` cannot redirect submission to a different server.

Deploy `cups-client` and `cups-ipp-utils` (Debian/Ubuntu packages), including `lp`
and `ipptool`. The packaged
`infra/kitchen_print_agent/get-job-state.test` file is required. The service user
must be allowed to submit to the configured queue and read its job attributes over
local TCP CUPS. CUPS job history must remain available for at least the ACK polling
window.

The agent acknowledges only the matching job with IPP `job-state=9` and an
unambiguous `job-completed-successfully` reason. Canceled (7), aborted (8),
unknown/missing state, warnings/errors, and `queued-in-device` never produce an
ACK. A missing utility or inaccessible server also fails closed. Submission,
status commands and polling share the existing ACK deadline; the adapter does not
resubmit while waiting.

## Read-only diagnosis

```bash
SYSTEMD_PAGER=cat systemctl show kitchen-print-agent \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p Result

lpstat -r
lpstat -p Brother_L2710DN_LAN
lpstat -h localhost:631 -W all -o Brother_L2710DN_LAN | tail -n 20

journalctl -u kitchen-print-agent --since '30 minutes ago' --no-pager
```

Operational logs intentionally contain opaque Core `print_job_id` values, CUPS job
IDs, printer queue names and rejection codes only. They must not contain bearer
tokens, customer data or document bodies. A normal successful lifecycle is visible as:

```text
claimed kitchen print job print_job_id=...
submitted kitchen print to CUPS cups_job_id=Brother_L2710DN_LAN-N printer=Brother_L2710DN_LAN
completed kitchen print in CUPS cups_job_id=Brother_L2710DN_LAN-N printer=Brother_L2710DN_LAN
acknowledged kitchen print job print_job_id=...
```

A technical failure is visible as a rejected lifecycle with the allowlisted rejection
code, for example `printer_unavailable` or `spool_rejected`.

## Controlled verification

Query an existing job with the packaged IPP test file:

```bash
cd /home/viktor/projects/silberloeffel-catering
ipptool -X \
  ipp://localhost:631/jobs/JOB_ID \
  infra/kitchen_print_agent/get-job-state.test
```

For a rollout that changes completion semantics, verify both branches with controlled
jobs: one successful completion and one held/canceled job. The canceled job must not
produce an ACK or `kitchen_print_confirmed_at`. For the final positive E2E, use clearly
synthetic test data or a disposable database copy rather than mutating a real customer
order merely to exercise printing.

CUPS success is a spooler observation. Physical paper output still depends on the
deployed printer/backend reporting correctly; when physical-output assurance is part of
the rollout, verify the actual Brother output separately and record that evidence
explicitly.

## Rollback

Do not hardcode one historical SHA as a permanent rollback target. Before every deploy,
record the exact parent or other known-good commit for that deployment and confirm the
production worktree is clean.

For a code-only kitchen-print rollback with no incompatible schema change:

```bash
cd /home/viktor/projects/silberloeffel-catering
git status --short
# identify the recorded known-good commit for this deployment
# move back only under the repository's approved rollback procedure
sudo systemctl restart kitchen-print-agent
SYSTEMD_PAGER=cat systemctl show kitchen-print-agent \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p Result
journalctl -u kitchen-print-agent --since '5 minutes ago' --no-pager
```

Prefer the release/deployment runbooks for the exact Git operation. Never restore the
Core database for a print-agent-only code rollback unless a separate data-recovery
reason independently requires it.

For the 2026-09-08 rollout of `a314b51c2f7d942e815bcbf133ec72bb47ddb668`,
the recorded pre-rollout production commit was
`1626d616b842f54749c82d769d86dd7b2c080db8`. This is historical deployment evidence,
not a universal rollback target.

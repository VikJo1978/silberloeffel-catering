# Kitchen print agent operations

Operational runbook for the Phase 3B kitchen print edge on Lenovo. This
documents **runtime troubleshooting only** — not Core domain logic, Office
ACK workflow design, or Kitchen API contract changes.

Related: `infra/systemd/kitchen-print-agent.service`,
`infra/systemd/kitchen-print-agent.env.example`,
`docs/decisions/PHASE_3B_KITCHEN_PRINT_AGENT_V1.md`.

## Architecture boundary (do not blur in incidents)

```text
Core (KitchenPrintJob, document, API, ledger)
        |
        | HTTP + command_id
        v
kitchen_print_agent (stateless)
        |
        | PrinterAdapter
        v
CUPS / lp → physical printer
```

The agent must **not** call `acknowledge_print_job()` or mutate
`kitchen_print_confirmed_at`. Successful physical print is a technical delivery
only; human ACK remains an Office action.

If production behaviour is wrong after Lenovo testing, fix deployment first:

```text
infra/kitchen_print_agent/
infra/systemd/
/etc/kitchen-print-agent.env
```

Only escalate to Core when the Kitchen API contract or job facts are incorrect.

## Inventory (planned Lenovo layout)

| Fact | Typical value |
|---|---|
| Agent package | `/opt/kitchen-print-agent/infra/kitchen_print_agent/` |
| systemd unit | `kitchen-print-agent.service` |
| Environment file | `/etc/kitchen-print-agent.env` (mode `600`, root-owned) |
| Run user | `viktor` (member of `lp` or `lpadmin` for CUPS) |
| Kitchen API | loopback or Tailscale — URL in `KITCHEN_PRINT_API_URL` |
| CUPS queue | `KITCHEN_PRINT_PRINTER_NAME` must match `lpstat -p` |

Never paste `/etc/kitchen-print-agent.env` contents into chat, tickets, or logs.

## Check agent state

Unit name: `kitchen-print-agent.service` (see
`infra/systemd/kitchen-print-agent.service`).

```bash
systemctl status kitchen-print-agent
journalctl -u kitchen-print-agent -f
journalctl -u kitchen-print-agent -n 100 --no-pager
```

Expected when healthy:

- `Active: active (running)`
- periodic log lines showing agent alive / claim polls
- no repeated tracebacks on `urllib` or `lp`

## Check CUPS

```bash
lpstat -p
lpstat -a
lpstat -t
```

Manual print (before trusting the agent):

```bash
echo "kitchen print smoke test" | lp -d <QUEUE_NAME>
```

Confirm the job appears in the queue and paper output is correct.

## Restart

```bash
sudo systemctl restart kitchen-print-agent
sudo systemctl restart cups
```

Restart order when debugging printer issues:

1. Fix physical printer / USB / network
2. `systemctl restart cups`
3. manual `lp` smoke test
4. `systemctl restart kitchen-print-agent`

## Symptom → where to look

| Symptom | First check | Likely layer |
|---|---|---|
| Job never leaves queue in Office | Core `KitchenPrintJob` rows; print request exists | Core / Office |
| Agent never claims | Kitchen API reachability; Bearer token; `journalctl` agent | API / network / auth |
| Claim succeeds, nothing prints | `journalctl` agent; `lpstat -p`; user in `lp` group | Agent / CUPS |
| `lp` fails manually | CUPS logs (`/var/log/cups/error_log`); queue name; driver | CUPS / hardware |
| Print on paper, no Office ACK | **Expected** — ACK is manual via Office attention | Office workflow |
| Duplicate print after agent restart | Kitchen API ledger replay (same `command_id`) | API / agent client |
| Job rejected in Core | `rejection_code` on job; agent `reject()` path | Agent / printer |

## Technical reject codes (Core allowlist)

Core accepts only these `rejection_code` values (`KITCHEN_PRINT_REJECTION_CODES`):

| Code | Set by | Typical cause |
|---|---|---|
| `render_failed` | Core | document render failed before agent delivery |
| `spool_rejected` | Agent | spooler rejected the document |
| `printer_unavailable` | Agent / Core | queue missing, CUPS down, connection failure |
| `invalid_printer_configuration` | Agent | unsupported document format for queue |
| `order_cancelled` | Core | order cancelled after claim eligibility |

The agent must send **only** agent-side codes from this list:

```text
spool_rejected
printer_unavailable
invalid_printer_configuration
```

Do not invent codes such as `internal`, `timeout`, or `network_error` until Core
explicitly adds them to the allowlist.

## Fault injection (pre-production)

Run once before relying on kitchen print in service:

```bash
# 1. Normal path
systemctl start kitchen-print-agent
# trigger print request from Office → expect paper output

# 2. CUPS stopped
sudo systemctl stop cups
# trigger print request → expect Core reject, NOT kitchen_print_confirmed_at
sudo systemctl start cups

# 3. Printer offline / USB removed
# trigger print request → expect technical reject in Core
```

After each fault test, confirm in Office:

- job shows attention / rejection as designed
- `kitchen_print_confirmed_at` remains unset until human ACK

## First production-like end-to-end scenario

Complete once after merge of Phase 3B stack (#102–#105):

1. Create or use a real order in Office.
2. Request kitchen print (Core creates `KitchenPrintJob`).
3. Agent claims via `POST /kitchen/v1/print-jobs/claim-next`.
4. Agent receives immutable document bytes.
5. `CupsPrinterAdapter` prints on Lenovo.
6. Repeat with printer fault → verify technical `reject` only.
7. Human ACK through Office (separate from agent success).

Record date, queue name, and outcome in the deployment log — not in this file.

## Install reference (summary)

```bash
sudo cp infra/systemd/kitchen-print-agent.service /etc/systemd/system/
sudo cp infra/systemd/kitchen-print-agent.env.example /etc/kitchen-print-agent.env
# edit /etc/kitchen-print-agent.env — API URL, token, queue name
sudo chmod 600 /etc/kitchen-print-agent.env
sudo systemctl daemon-reload
sudo systemctl enable --now kitchen-print-agent
```

Ensure `PYTHONPATH` in the unit points at the directory containing
`kitchen_print_agent/` (see service file).

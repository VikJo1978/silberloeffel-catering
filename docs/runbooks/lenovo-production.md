# Lenovo production runbook

Use this runbook for the production host only. The Core database is not
reconstructable from CRM or staging; protect it before every deployment.

## Inventory

| Fact | Value |
|---|---|
| Hostname | `debiancatering` |
| Tailscale IP | `100.109.6.74` |
| SSH user | `viktor` |
| Repository | `/home/viktor/projects/silberloeffel-catering` |
| Core database | `/home/viktor/catering-runtime/core.db` |
| Daily backups | `/home/viktor/catering-runtime/backups` |
| Off-host sender | `/home/viktor/catering-runtime/bin/catering-offsite-backup.sh` |
| Environment files | `/etc/catering/*.env` |

| Service | Port | Exposure | Writes Core |
|---|---:|---|---|
| `catering-office-panel` | 8081 | LAN/Tailscale | yes |
| `catering-kiosk` | 8082 | LAN/Tailscale | no |
| `catering-website-intake` | 8083 | loopback only | Inquiry only |

## Connect and inspect

```bash
ssh -i ~/.ssh/id_ed25519 viktor@100.109.6.74
systemctl is-active \
  catering-kiosk \
  catering-office-panel \
  catering-website-intake
```

Expected: three lines containing `active`.

Useful read-only checks:

```bash
cd /home/viktor/projects/silberloeffel-catering
git status --short
git log -1 --oneline
sqlite3 /home/viktor/catering-runtime/core.db 'PRAGMA quick_check;'
ss -ltn
journalctl -u catering-office-panel -n 100 --no-pager
```

Never paste `/etc/catering/*.env` contents into chat, tickets, documentation,
or logs.

## Courier app and kiosk pickup signal

The courier app test instance runs as the enabled user unit
`catering-courier-app.service` on port `8090`. Its checkout is
`/home/viktor/projects/courier-app`; state and the mode-`600` environment file
live under `/home/viktor/courier-runtime`. `Linger=yes` keeps the user manager
alive across logout and starts the enabled unit after reboot. Verify it with:

```bash
systemctl --user is-enabled catering-courier-app
systemctl --user is-active catering-courier-app
loginctl show-user viktor -p Linger
curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8090/api/overdue-pickups  # 401 without bearer
```

Never print, paste, or pass `/home/viktor/courier-runtime/courier.env` in
argv. The chef password and signal bearer are intentionally generated and
stored only on the Lenovo.

Source is published in the private `VikJo1978/courier-app` repository. Lenovo
uses the dedicated key `/home/viktor/.ssh/courier_app_github` for read-only
deploy access. Its public half is registered as a GitHub deploy key with write
access disabled. The repository-local `core.sshCommand` pins that identity so
updates do not depend on a personal account key.

The kiosk displays open equipment returns read from the courier app (current
contract: `docs/api/kiosk-pickup-signal.md`; frozen implementation record:
`docs/archive/packs/KIOSK_PICKUP_SIGNAL_PACK_V1.md`). It is active in
production. The paired configuration lives in the root-owned, mode-`600`
`/etc/catering/kiosk.env`; without both variables the feature remains dormant,
and a half-filled configuration is rejected at startup.

The recommended path is the tracked one-shot script. It backs up the current
unit and env, installs the paired secret without printing it, restarts only the
kiosk, requires the fixed refresh-success log plus `200`/`401` smoke codes, and
rolls back automatically if any gate fails:

```bash
cd /home/viktor/projects/silberloeffel-catering
sudo infra/deploy/activate-kiosk-pickup-signal.sh
```

The production activation completed on 2026-07-13 with
`ACTIVATION_OK kiosk=200 signal_unauth=401`. Re-running the script is reserved
for deliberate credential rotation or recovery because it replaces the paired
kiosk environment and restarts the kiosk.

The equivalent manual steps are retained below for recovery and audit:

1. Create the kiosk environment file — root-owned, mode `600`, loopback URL,
   and a token paired with the courier app's `KIOSK_SIGNAL_TOKEN`. The token
   value must never appear in argv, shell history, documentation, or logs.
   Copy it directly between files without printing it:

   ```bash
   sudo /bin/sh -c '
     set -eu
     umask 077
     token=$(sed -n "s/^KIOSK_SIGNAL_TOKEN=//p" \
       /home/viktor/courier-runtime/courier.env)
     test -n "$token"
     printf "PICKUP_SIGNAL_URL=http://127.0.0.1:8090/api/overdue-pickups\nPICKUP_SIGNAL_TOKEN=%s\n" \
       "$token" > /etc/catering/kiosk.env
   '
   sudo chown root:root /etc/catering/kiosk.env
   sudo chmod 600 /etc/catering/kiosk.env
   ```

   A half-filled file (URL without token or vice versa) is a startup error
   by design — the kiosk refuses to run the feature unauthenticated.

2. The repository unit template references the file
   (`EnvironmentFile=-/etc/catering/kiosk.env`). Before activation, compare
   it with the effective live unit and install the template if needed, then
   reload systemd:

   ```bash
   systemctl cat catering-kiosk
   sudo install -m 644 infra/systemd/catering-kiosk.service \
     /etc/systemd/system/catering-kiosk.service
   sudo systemctl daemon-reload
   ```

3. Restart only the kiosk and smoke-test by status codes and the fixed
   success log line — never by dumping response bodies:

   ```bash
   sudo systemctl restart catering-kiosk
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8082/   # 200
   curl -s -o /dev/null -w '%{http_code}\n' \
     http://127.0.0.1:8090/api/overdue-pickups                       # 401 (no token sent)
   journalctl -u catering-kiosk --since '5 minutes ago' --no-pager \
     | grep -c 'pickup signal refresh succeeded'                     # >= 1
   ```

   The kiosk's own refresher is the authenticated test client; an error-free
   journal alone proves nothing — the success line must actually appear.

## Python dependencies (`uv`)

`pyproject.toml` declares the dependencies; `uv.lock` pins the exact resolved
versions, including transitive ones. `uv` is the only supported way to build
the environment — `pip install` reproduces neither the transitive pins nor the
runtime/development split.

Install the **runtime** set (`reportlab` and its transitive dependencies only —
no test or lint tooling):

```bash
cd /home/viktor/projects/silberloeffel-catering
uv sync --no-dev
```

Install the **development** set as well (adds `pytest`, `mypy`, `ruff`,
`coverage`, `pypdf`):

```bash
uv sync --dev
```

Both commands create or update `.venv` in the repository directory from
`uv.lock`. `.venv` is disposable and git-ignored: deleting and re-syncing it is
always safe.

Verify the PDF dependency is importable by the interpreter that actually serves
requests:

```bash
.venv/bin/python -c "import reportlab; print(reportlab.Version)"   # 5.0.0
```

> **Not yet applied to production.** The live host currently reaches `.venv`
> through an untracked `systemd` drop-in override, and its `.venv` still
> contains development tooling installed by hand. Aligning the tracked unit
> files and rebuilding the production environment from `uv.lock` is a separate,
> later slice (`PDF_RUNTIME_VENV_AND_SYSTEMD_V1`, slices B and D). Until that
> slice runs, do **not** execute `uv sync --no-dev` on Lenovo: it would remove
> the `pytest` and `mypy` that step 4 of the deployment below currently relies
> on.

## PDF runtime verification (read-only)

`infra/deploy/verify_pdf_runtime.py` cross-checks the PDF runtime and systemd
alignment without changing anything: no package installation, no `uv sync`, no
unit installation, no `daemon-reload`, no service restart, no override edit or
removal, no application code change, no database write. It only reads
git-tracked files, runs `uv lock --check`, queries systemd with `systemctl
show`/`systemctl cat`, and reads `/proc/<pid>/cmdline` and `/proc/<pid>/
environ` (variable **names** only — values are never printed).

Two modes; one must be given explicitly:

```bash
# No systemd or production access needed — safe in CI or any checkout.
uv run python infra/deploy/verify_pdf_runtime.py --repository-only

# Real venv, reportlab, systemd and process checks. Run on Lenovo itself.
python infra/deploy/verify_pdf_runtime.py --host-runtime
```

Add `--json` for machine-readable output alongside the human-readable report.

Run `--host-runtime`:

- **before** the Slice D migration below, to confirm the tracked units,
  the venv, and `reportlab` are actually ready — a successful pre-migration
  result may legitimately report `READY_WITH_COMPATIBLE_OVERRIDE` (the
  existing drop-in override still applies and its resulting command matches
  the tracked target);
- **after** installing the tracked units and removing the overrides, to
  confirm the migration landed — a successful post-migration result should
  report `READY_WITHOUT_OVERRIDE` instead.

`MISMATCHED_OVERRIDE`, `TRACKED_UNIT_MISMATCH`, `RUNTIME_INTERPRETER_MISSING`,
`REPORTLAB_MISSING`, `REPORTLAB_VERSION_MISMATCH`, `PDF_CONFIG_MISSING`, and
`LOCK_OUT_OF_DATE` are all failures (non-zero exit) and mean the runtime is
not ready for that step of the migration — investigate before proceeding, do
not work around them by installing anything by hand.

`uv` is not installed on Lenovo as of this writing, so `--host-runtime` there
will currently report `LOCK_OUT_OF_DATE` for the repository-state check (it
cannot verify `uv.lock` without the `uv` binary); this is expected until a
later slice installs `uv` on the host and is not itself a blocker for reading
the rest of the report.

## Safe deployment

### 1. Record the starting point

```bash
cd /home/viktor/projects/silberloeffel-catering
git status --short
git rev-parse --short HEAD
```

Stop if tracked local modifications exist. Untracked operator-owned files must
be understood and preserved.

### 2. Take and verify a pre-deploy backup

```bash
mkdir -p /home/viktor/catering-runtime/predeploy-backups
stamp=$(date +%Y%m%d-%H%M%S)
backup="/home/viktor/catering-runtime/predeploy-backups/core-predeploy-$stamp.db"
sqlite3 /home/viktor/catering-runtime/core.db ".backup $backup"
test -s "$backup"
sqlite3 "$backup" 'PRAGMA quick_check;'
```

### 3. Fetch and fast-forward only

```bash
git fetch origin
git merge --ff-only origin/main
```

Do not use `git reset --hard` on production. If fast-forward is impossible,
stop and investigate the divergence.

### 4. Validate before restart

```bash
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src/catering_system
```

If development dependencies are not installed on Lenovo, rely on the successful
CI run for the exact commit and at least run `compileall` locally on the host.

### 5. Restart and verify

```bash
sudo systemctl restart \
  catering-office-panel \
  catering-kiosk \
  catering-website-intake
systemctl is-active \
  catering-office-panel \
  catering-kiosk \
  catering-website-intake
sqlite3 /home/viktor/catering-runtime/core.db 'PRAGMA quick_check;'
```

Then verify:

- office login and dashboard over the private network;
- kiosk week view;
- unauthenticated intake request is rejected;
- recent service journals contain no traceback or repeated restart.

```bash
curl -i http://127.0.0.1:8083/intake/website-form
journalctl -u catering-office-panel -u catering-kiosk \
  -u catering-website-intake --since '10 minutes ago' --no-pager
```

The intake smoke request should return `405`, not `200`.

## PDF configuration (Offer/Confirmation documents)

Office API and direct-mode Office Panel both require the `OFFICE_PDF_*`
environment contract (issue #41) — see `.env.example` for the full list of
required and optional variables. On Lenovo these live in the root-owned,
mode-`600` `/etc/catering/office-api.env` and `/etc/catering/office-panel.env`
— never print, paste, or `cat` those files. Both services validate this
configuration before opening `core.db`: a missing or blank required variable,
or an unreadable `OFFICE_PDF_LOGO_PATH`, refuses to start with no database
side effect.

**Verify presence without printing values** — list variable *names* only,
never their contents:

```bash
sudo grep -o '^OFFICE_PDF_[A-Z_]*=' /etc/catering/office-panel.env
```

**Preflight verification** — proves the configuration actually loads,
without ever echoing a value. A missing/blank required variable prints the
variable name and exits non-zero; success prints nothing and exits `0`:

```bash
cd /home/viktor/projects/silberloeffel-catering
sudo -u viktor env -i $(sudo grep -v '^#' /etc/catering/office-panel.env) \
  PYTHONPATH=src python3 -c \
  'from catering_system.ui.offer_pdf_static_content_env import offer_pdf_static_content_from_env as f; f()'
echo "exit code: $?"
```

**PDF smoke test without emailing a customer** — download the PDF for an
already-existing offer/confirmation via the authenticated, read-only Office
Panel/API endpoint (a `GET`, never a "send" endpoint) and confirm it is a
well-formed PDF, without composing or sending anything:

```bash
curl -s -u office:$OFFICE_PANEL_PASSWORD \
  http://127.0.0.1:8081/offers/<offer_id>/document.pdf -o /tmp/pdf-smoke.pdf
file /tmp/pdf-smoke.pdf   # expect: PDF document
rm -f /tmp/pdf-smoke.pdf
```

**Rollback for this slice** — this is a pure code change: no schema change,
no change to the `OFFICE_PDF_*` values already configured on production.
Rollback is the standard [code-only rollback](#code-only-rollback) below
(revert the commit, restart `catering-office-panel` only, re-run the smoke
checks) — no database restore and no environment-file change is ever needed
for this slice.

Systemd `ExecStart`/interpreter and dependency-installation changes are
tracked separately (`PDF_RUNTIME_VENV_AND_SYSTEMD_V1`) and are not part of
this procedure.

## Unit files

The live units are in `/etc/systemd/system/`. Always inspect the effective unit
before changing it:

```bash
systemctl cat catering-office-panel
systemctl cat catering-kiosk
systemctl cat catering-website-intake
```

After editing or installing a unit:

```bash
sudo systemctl daemon-reload
sudo systemctl restart <service>
systemctl status <service> --no-pager -l
```

## Rollback

Code rollback and data rollback are different operations.

### Code-only rollback

Use only when the database schema remains compatible with the known-good code:

1. identify the last known-good commit;
2. switch the production checkout to that exact commit without deleting local
   operator files;
3. restart the affected services;
4. run the smoke checks above.

### Database restore

Restoring the database discards later production writes. Use it only after the
owner explicitly accepts that data loss window. Follow the stop-copy-verify
procedure in [Backup and restore](backup-restore.md#restore-production).

## Common failures

| Symptom | Check | Typical cause |
|---|---|---|
| service restart loop | `journalctl -u <service>` | invalid env, migration failure, wrong path |
| office returns 401 | environment file and username `office` | password mismatch |
| kiosk empty | selected week and DB path | wrong week or unit points at wrong DB |
| intake returns 401 | token pairing | Worker and receiver tokens differ |
| intake unreachable externally | loopback is intentional | Cloudflare Tunnel not configured |
| SQLite startup error | migration history and backup | incompatible or damaged database |

## Exposure rules

- Never publish `8081` or `8082` to the internet.
- Keep `8083` on `127.0.0.1`; publish only through the narrow Cloudflare path.
- Never reuse the office password as the intake token.
- Do not copy production `core.db` to the public VPS.

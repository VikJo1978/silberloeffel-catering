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

## Kiosk pickup signal (dormant until activated)

The kiosk can display open equipment returns read from the courier app
(`docs/proposals/KIOSK_PICKUP_SIGNAL_PACK_V1.md`). The feature is **dormant
by default**: deploying the kiosk without `/etc/catering/kiosk.env` (or with
both variables empty) changes nothing — no request is made and the page is
byte-identical to the pre-feature output. Deploy first, activate later.

Activation (only once the courier app runs on this host):

1. Create the kiosk environment file — root-owned, mode `600`, loopback URL,
   and a token paired with the courier app's `KIOSK_SIGNAL_TOKEN`. The token
   value must never appear in argv, shell history, documentation, or logs;
   write it into the two env files directly with an editor:

   ```bash
   sudo touch /etc/catering/kiosk.env
   sudo chown root:root /etc/catering/kiosk.env
   sudo chmod 600 /etc/catering/kiosk.env
   sudoedit /etc/catering/kiosk.env
   # PICKUP_SIGNAL_URL=http://127.0.0.1:8090/api/overdue-pickups
   # PICKUP_SIGNAL_TOKEN=<same value as the courier app's KIOSK_SIGNAL_TOKEN>
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

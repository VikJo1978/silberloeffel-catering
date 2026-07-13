# VPS staging runbook

The VPS is the form-development and intake-test host. The current priority is
proving reliable Inquiry acceptance before the office and replacement website
are connected. Access to the old website is not required. This is not yet a
production customer channel.

## Inventory

| Fact | Value |
|---|---|
| Public URL | [http://185.16.60.69:8080/](http://185.16.60.69:8080/) |
| SSH | `root@185.16.60.69` |
| Service | `catering-staging-site` |
| Runtime user | `catering-staging` |
| Application | `/opt/catering-staging-site` |
| Database | `/var/lib/catering-staging/staging.db` |
| systemd unit | `/etc/systemd/system/catering-staging-site.service` |
| Core-forward env | `/etc/catering/staging-site.env` (`root:root`, `600`) |
| Forwarded receiver | `127.0.0.1:18083` on VPS → `127.0.0.1:8083` on Lenovo |
| Tunnel user unit | Lenovo `catering-intake-vps-tunnel.service` |

## Safety boundary

- No domain and no HTTPS are configured.
- Use invented names, emails, phone numbers, and event details only.
- In isolated mode the staging process has no Lenovo connection. In forwarding
  mode it holds only the narrow Inquiry-receiver bearer and reaches only the
  loopback SSH forward.
- The public API does not expose a list of saved submissions.
- The database is disposable test data.

## Status and health

```bash
ssh -i ~/.ssh/id_ed25519 root@185.16.60.69
systemctl is-active catering-staging-site
curl -fsS http://127.0.0.1:8080/healthz
ss -ltnp 'sport = :8080'
journalctl -u catering-staging-site -n 100 --no-pager
```

Expected health response:

```json
{"status": "ok", "environment": "staging", "core_forwarding": false}
```

`core_forwarding` becomes `true` only when both environment values are present.
A half-configured pair is a startup error.

## Deploy an update

From the repository on the Mac:

```bash
scp -i ~/.ssh/id_ed25519 \
  src/catering_system/ui/staging_site.py \
  root@185.16.60.69:/opt/catering-staging-site/staging_site.py

scp -i ~/.ssh/id_ed25519 -r \
  src/catering_system/ui/staging_site_assets \
  root@185.16.60.69:/opt/catering-staging-site/

scp -i ~/.ssh/id_ed25519 \
  infra/systemd/catering-staging-site.service \
  root@185.16.60.69:/etc/systemd/system/catering-staging-site.service
```

On the VPS:

```bash
chown -R root:root /opt/catering-staging-site
find /opt/catering-staging-site -type d -exec chmod 755 {} +
find /opt/catering-staging-site -type f -exec chmod 644 {} +
python3 -m py_compile /opt/catering-staging-site/staging_site.py
systemctl daemon-reload
systemctl restart catering-staging-site
systemctl is-active catering-staging-site
curl -fsS http://127.0.0.1:8080/healthz
```

Verify the public URL from a different machine after local health succeeds.

## Optional Core intake bridge

This bridge is for marked fake test requests only. It does not expose Lenovo
port `8083`, does not grant VPS access to SQLite, and cannot create Orders.

### 1. Restricted reverse tunnel account and key

Generate the dedicated key on Lenovo without printing private material:

```bash
ssh-keygen -t ed25519 -N '' \
  -f /home/viktor/.ssh/catering_intake_vps \
  -C 'lenovo-staging-intake-tunnel'
chmod 600 /home/viktor/.ssh/catering_intake_vps
```

Create the dedicated `catering-intake` account on the VPS and install only the
public half with these `authorized_keys` restrictions:

```text
restrict,port-forwarding,permitlisten="127.0.0.1:18083" ssh-ed25519 <public-key> lenovo-staging-intake-tunnel
```

The account needs no sudo rights and no application-file access. The reverse
listener must bind only `127.0.0.1:18083`; verify that `0.0.0.0:18083` and
`[::]:18083` do not exist.

Install and start the tracked tunnel as Viktor's user service on Lenovo:

```bash
install -Dm644 infra/systemd/catering-intake-vps-tunnel.service \
  ~/.config/systemd/user/catering-intake-vps-tunnel.service
systemctl --user daemon-reload
systemctl --user enable --now catering-intake-vps-tunnel
systemctl --user is-active catering-intake-vps-tunnel
```

### 2. Paired bearer without shell-history exposure

Generate one token into owner-only temporary files on the Mac. Never print it:

```bash
umask 077
token_file=$(mktemp)
env_file=$(mktemp)
openssl rand -hex 32 > "$token_file"
printf 'STAGING_CORE_INTAKE_URL=http://127.0.0.1:18083/intake/website-form\nSTAGING_CORE_INTAKE_TOKEN=' > "$env_file"
cat "$token_file" >> "$env_file"
scp "$env_file" root@185.16.60.69:/etc/catering/staging-site.env
scp "$token_file" viktor@100.109.6.74:/home/viktor/catering-runtime/staging-core-intake.token
rm -f "$token_file" "$env_file"
```

On the VPS enforce `root:root` and mode `600`. On Lenovo the handoff file must
be owned by `viktor`, mode `600`; then run the tracked rollback-safe activation:

```bash
sudo infra/deploy/activate-staging-core-intake.sh
```

Expected: `ACTIVATION_OK receiver_unauth=401`. The script backs up the previous
receiver environment, rotates the bearer, restarts only the website-intake
receiver, verifies fail-closed auth, and consumes the handoff file. It restores
the previous environment automatically on failure.

### 3. Activate staging forwarding

Install the tracked staging unit, restart only the staging site, and verify
status codes without printing response bodies:

```bash
chown root:root /etc/catering/staging-site.env
chmod 600 /etc/catering/staging-site.env
install -m 644 infra/systemd/catering-staging-site.service \
  /etc/systemd/system/catering-staging-site.service
systemctl daemon-reload
systemctl restart catering-staging-site
curl -fsS http://127.0.0.1:8080/healthz
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST -H 'Content-Type: application/json' --data '{}' \
  http://127.0.0.1:18083/intake/website-form  # 401
```

### 4. End-to-end proof

Submit one clearly marked fake request through `:8080/api/inquiries`. Expect
`202` and `forwarded_to_core: true`. On Lenovo verify by namespaced external
reference and count only; do not print contact payloads. Repeating the same
browser retry key must return success while the Core count remains exactly one.

Rollback is immediate: remove both values from the VPS environment (or remove
the file) and restart staging for isolated mode; stop the tunnel user service;
restore the saved Lenovo receiver environment only if the bearer itself must be
rolled back.

## Browser smoke test

1. Open the public URL with explicit `http://`.
2. Check desktop and mobile layouts.
3. Submit one clearly labelled fake request.
4. Confirm a green `Gespeichert` message and a test ID.
5. Verify service health again.

## Private inquiry viewer

The read-only `/admin` page is intentionally loopback-only. A public request
must receive `404`; do not add Basic Auth over the current plaintext HTTP
connection.

Open an SSH tunnel from the Mac:

```bash
ssh -i ~/.ssh/id_ed25519 -N \
  -L 18080:127.0.0.1:8080 root@185.16.60.69
```

While that command is running, open:

[http://127.0.0.1:18080/admin](http://127.0.0.1:18080/admin)

The page shows the latest 100 staging submissions and escapes every stored
field before rendering. It has no delete or production-forward action.

Verify the public denial separately:

```bash
curl -o /dev/null -sS -w '%{http_code}\n' \
  http://185.16.60.69:8080/admin
```

Expected: `404`.

## Concurrency regression

The server uses `ThreadingHTTPServer`. A stalled browser connection must not
block other visitors; this is covered by an automated regression test.

A lightweight ten-visitor asset check from a trusted machine:

```bash
seq 1 10 | xargs -P10 -I{} sh -c \
  'for path in / /styles.css /app.js /healthz; do
     curl -fsS --connect-timeout 3 --max-time 10 \
       -o /dev/null "http://185.16.60.69:8080$path"
   done'
```

Do not run sustained load tests without first setting traffic and resource
limits. This small smoke test is not a capacity benchmark.

## Inspect test data

```bash
python3 -c '
import sqlite3
c = sqlite3.connect("/var/lib/catering-staging/staging.db")
print(c.execute("PRAGMA quick_check").fetchone())
print(c.execute("SELECT COUNT(*) FROM staging_inquiries").fetchone())
'
```

Do not print full rows if anyone may have entered real contact data by mistake.

## Troubleshooting

| Symptom | Action |
|---|---|
| blank page that never completes | check service; confirm the threading fix is deployed |
| connection refused | inspect service and provider firewall |
| CSS missing | verify `staging_site_assets/` beside `staging_site.py` |
| form returns 429 | wait for the one-minute per-IP rate window |
| form returns 400 | validate date, name, contact method, and guest count |
| service cannot write DB | verify owner `catering-staging` on `/var/lib/catering-staging` |
| admin returns 404 locally | open it through the SSH tunnel, not the public IP |

## Later replacement website and domain launch

After the replacement site and protected intake path are ready:

1. obtain DNS control of the existing domain;
2. configure TLS and the final Cloudflare/public-intake path;
3. deploy the reviewed site build without staging data or staging labels;
4. perform an end-to-end request test through the domain;
5. export or discard staging data according to the owner's decision;
6. close public port `8080` when it is no longer needed.

Do not delete the staging environment until the domain launch has passed its
end-to-end test and rollback is no longer needed.

# Backup and restore

The production SQLite database is the operational truth. A backup is valid only
when it exists, is non-empty, and passes `PRAGMA quick_check`.

## Current schedule

The `viktor` crontab on Lenovo contains:

```cron
15 3 * * * umask 077 && sqlite3 /home/viktor/catering-runtime/core.db ".backup /home/viktor/catering-runtime/backups/core-$(date +\%F).db"
30 3 * * * find /home/viktor/catering-runtime/backups -name 'core-*.db' -mtime +14 -delete
```

This creates a daily online SQLite backup with owner-only file permissions and
retains 14 days.

## Verified state

On 2026-07-12 the original `/var/backups/catering` destination was found
unwritable by the `viktor` cron owner. Sudo required a password, so the cron was
moved to the private user-owned runtime directory instead of widening a system
directory's permissions.

Verified proof:

- backup: `/home/viktor/catering-runtime/backups/core-2026-07-12.db`
- owner/mode: `viktor:viktor`, `600`
- size at verification: 57,344 bytes
- source `quick_check`: `ok`
- backup `quick_check`: `ok`
- source/backup row counts: 3 inquiries, 1 order, 1 order version
- all three production services remained active
- previous crontab: `/home/viktor/catering-runtime/crontab-before-backup-fix-20260712.txt`

Check the newest scheduled backup:

```bash
backup=/home/viktor/catering-runtime/backups/core-$(date +%F).db
test -s "$backup"
stat -c '%U:%G %a %s %y %n' "$backup"
sqlite3 "$backup" 'PRAGMA quick_check;'
```

## Pre-deploy backup

Scheduled backups do not replace a pre-deploy backup:

```bash
mkdir -p /home/viktor/catering-runtime/predeploy-backups
stamp=$(date +%Y%m%d-%H%M%S)
target="/home/viktor/catering-runtime/predeploy-backups/core-predeploy-$stamp.db"
sqlite3 /home/viktor/catering-runtime/core.db ".backup $target"
test -s "$target"
sqlite3 "$target" 'PRAGMA quick_check;'
```

Record the backup filename and deployed Git commit together.

## Off-host copy

A backup on the same Lenovo does not protect against disk loss. The off-host
pipeline encrypts the verified local copy before sending it to the VPS.

### Design

| Component | Location | Contains |
|---|---|---|
| recovery private key | Mac `~/.config/silberloeffel-backup/gnupg` | decrypt capability |
| encryption public key | Lenovo `~/.gnupg-catering-backup` | encrypt capability only |
| transport private key | Lenovo `~/.ssh/catering_backup_vps` | forced backup commands only |
| encrypted local cache | Lenovo `~/catering-runtime/offsite-encrypted` | `.db.gpg`, 14 days |
| encrypted off-host files | VPS `/var/lib/catering-backup/files` | `.db.gpg`, 30 days |

Recovery key fingerprint:

```text
4B5A 450E DBA6 8B78 D9E5 19C2 A5C4 DE7E 0D83 6610
```

The VPS account `catering-backup` uses an SSH forced command. Its key may only:

- upload a correctly named encrypted file;
- return that file's SHA-256 checksum;
- prune encrypted files older than 30 days.

An attempted shell command must fail with exit status `64`. The receiver also
caps each upload at 256 MiB; a truncated upload cannot pass checksum validation.

### Schedule

```cron
25 3 * * * /home/viktor/catering-runtime/bin/catering-offsite-backup.sh >> /home/viktor/catering-runtime/offsite-backup.log 2>&1
```

The sender checks the local SQLite backup, encrypts it with GPG, uploads it,
compares local and remote SHA-256, and only then reports success.

### Verified restore drill

On 2026-07-12 an encrypted file was uploaded to the VPS, downloaded back to the
Mac, decrypted with the dedicated recovery key, and opened with SQLite:

- encrypted VPS owner/mode: `catering-backup:catering-backup`, `600`;
- `PRAGMA quick_check`: `ok`;
- row counts: 3 inquiries, 1 order, 1 order version;
- temporary plaintext on Mac removed after verification;
- all Lenovo production services remained active.

### Recovery-key protection

The private key must never be copied to Lenovo, VPS, GitHub, or ordinary cloud
storage. Ensure the entire Mac directory below has a second encrypted backup:

```text
/Users/viktorjohanson/.config/silberloeffel-backup/gnupg
```

Without it the encrypted off-host database cannot be recovered.

Verified on 2026-07-12: an AES-256 recovery archive was created, decrypted into
a temporary isolated keyring, and matched to fingerprint
`4B5A450EDBA68B78D9E519C2A5C4DE7E0D836610`. The owner confirmed an off-device
email copy. Its independent random password is stored in macOS Keychain under
`Silberloeffel Recovery Archive 2026-07-12`; the password is not stored in the
email, repository, Lenovo, or VPS.

### Manual off-host run

```bash
/home/viktor/catering-runtime/bin/catering-offsite-backup.sh
tail -20 /home/viktor/catering-runtime/offsite-backup.log
```

The command must end with `off-site backup verified` and a SHA-256 value.

### Restore from VPS on the Mac

Use a temporary private directory, retrieve the selected `.gpg` file through
the administrator SSH account, decrypt, verify, and remove the plaintext after
the drill:

```bash
restore_dir=$(mktemp -d /tmp/catering-offsite-restore.XXXXXX)
scp root@185.16.60.69:/var/lib/catering-backup/files/core-YYYY-MM-DD.db.gpg \
  "$restore_dir/backup.db.gpg"
GNUPGHOME="$HOME/.config/silberloeffel-backup/gnupg" \
  gpg --output "$restore_dir/restored.db" \
  --decrypt "$restore_dir/backup.db.gpg"
sqlite3 "$restore_dir/restored.db" 'PRAGMA quick_check;'
find "$restore_dir" -type f -delete
rmdir "$restore_dir"
```

For a real production restore, continue with
[Restore production](#restore-production). Do not upload or commit the decrypted
file.

Minimum weekly check:

- newest local backup age;
- newest off-host encrypted backup age;
- non-zero size;
- a periodic decrypt-and-`quick_check` drill;
- restore procedure still understood by two people or documented access.

## Restore production

> **Destructive operation:** restoring discards writes made after the selected
> backup. Confirm the accepted data-loss window before starting.

### 1. Select and verify the backup

```bash
backup=/absolute/path/to/selected-backup.db
test -s "$backup"
sqlite3 "$backup" 'PRAGMA quick_check;'
```

### 2. Stop all database users

```bash
sudo systemctl stop \
  catering-office-panel \
  catering-kiosk \
  catering-website-intake
```

### 3. Preserve the failed database and restore

```bash
db=/home/viktor/catering-runtime/core.db
sudo cp "$db" "$db.before-restore-$(date +%Y%m%d-%H%M%S)"
sudo cp "$backup" "$db"
sudo chown viktor:viktor "$db"
sqlite3 "$db" 'PRAGMA quick_check;'
```

### 4. Start and smoke test

```bash
sudo systemctl start \
  catering-office-panel \
  catering-kiosk \
  catering-website-intake
systemctl is-active \
  catering-office-panel \
  catering-kiosk \
  catering-website-intake
journalctl -u catering-office-panel -u catering-kiosk \
  -u catering-website-intake --since '5 minutes ago' --no-pager
```

Verify office and kiosk data before resuming normal work.

## Incident record

For every restore, record:

- reason and decision owner;
- failed database copy;
- restored backup filename and timestamp;
- expected data-loss interval;
- Git commit running after restore;
- `quick_check` result;
- office/kiosk smoke-test result.

### Courier artifacts (shared VPS receiver)

Canonical receiver source:

```text
infra/backup/catering-backup-receive.sh
```

Live VPS path:

```text
/usr/local/sbin/catering-backup-receive
```

The receiver still serves the Core contract unchanged. It additionally accepts
Courier encrypted bundle names:

```text
courier-YYYYMMDDTHHMMSSZ.tar.gz.gpg
courier-YYYYMMDDTHHMMSSZ.tar.gz.gpg.sha256
```

Storage boundary remains `/var/lib/catering-backup/files` with mode `600` files
owned by `catering-backup`. Retention is pattern-specific:

| Pattern family | Retention behavior |
|---|---|
| `core-YYYY-MM-DD.db.gpg` | delete after 30 days |
| `courier-…tar.gz.gpg` | delete after 30 days except newest matching artifact |
| `courier-…tar.gz.gpg.sha256` | delete after 30 days except sidecar for newest gpg |
| unknown filenames | never deleted by `prune` |

Courier scheduling and restore drills are documented in the courier repo runbook.

#!/bin/sh
# Encrypt the current local SQLite backup and send it to the restricted VPS user.

set -eu

config=${CATERING_BACKUP_CONFIG:-/home/viktor/.config/catering-offsite-backup.env}
if [ -r "$config" ]; then
    # shellcheck disable=SC1090 -- operator-owned absolute config path
    . "$config"
fi

: "${CATERING_BACKUP_GPG_RECIPIENT:?missing GPG recipient fingerprint}"

database=${CATERING_BACKUP_DATABASE:-/home/viktor/catering-runtime/core.db}
backup_dir=${CATERING_BACKUP_LOCAL_DIR:-/home/viktor/catering-runtime/backups}
encrypted_dir=${CATERING_BACKUP_ENCRYPTED_DIR:-/home/viktor/catering-runtime/offsite-encrypted}
gnupg_home=${CATERING_BACKUP_GNUPGHOME:-/home/viktor/.gnupg-catering-backup}
ssh_key=${CATERING_BACKUP_SSH_KEY:-/home/viktor/.ssh/catering_backup_vps}
remote_user=${CATERING_BACKUP_REMOTE_USER:-catering-backup}
remote_host=${CATERING_BACKUP_REMOTE_HOST:-185.16.60.69}

umask 077
mkdir -p "$backup_dir" "$encrypted_dir"

stamp=$(date +%F)
plain="$backup_dir/core-$stamp.db"
name="core-$stamp.db.gpg"
encrypted="$encrypted_dir/$name"
temporary="$encrypted.tmp.$$"
trap 'rm -f "$temporary"' EXIT HUP INT TERM

if [ ! -s "$plain" ]; then
    sqlite3 "$database" ".backup $plain"
fi

test "$(sqlite3 "$plain" 'PRAGMA quick_check;')" = "ok"

gpg --homedir "$gnupg_home" \
    --batch \
    --yes \
    --trust-model always \
    --recipient "$CATERING_BACKUP_GPG_RECIPIENT" \
    --output "$temporary" \
    --encrypt "$plain"

test -s "$temporary"
mv "$temporary" "$encrypted"
trap - EXIT HUP INT TERM

ssh_target="$remote_user@$remote_host"
ssh -i "$ssh_key" -o BatchMode=yes "$ssh_target" "put $name" < "$encrypted"

local_sum=$(sha256sum "$encrypted" | cut -d ' ' -f 1)
remote_sum=$(ssh -i "$ssh_key" -o BatchMode=yes "$ssh_target" "sha256 $name")
test "$local_sum" = "$remote_sum"

ssh -i "$ssh_key" -o BatchMode=yes "$ssh_target" prune
find "$encrypted_dir" -type f -name 'core-????-??-??.db.gpg' -mtime +14 -delete

printf 'off-site backup verified: %s sha256=%s\n' "$name" "$local_sum"

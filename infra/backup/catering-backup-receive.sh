#!/bin/sh
# Forced-command receiver for encrypted catering backups on the VPS.

set -eu

storage=/var/lib/catering-backup/files
requested=${SSH_ORIGINAL_COMMAND:-}

valid_name() {
    case "$1" in
        core-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].db.gpg) return 0 ;;
        *) return 1 ;;
    esac
}

case "$requested" in
    "put "*)
        name=${requested#put }
        valid_name "$name" || exit 64
        umask 077
        temporary="$storage/.$name.$$"
        trap 'rm -f "$temporary"' EXIT HUP INT TERM
        # Cap a compromised sender at 256 MiB per upload. A truncated upload
        # cannot pass the sender's end-to-end SHA-256 comparison.
        dd of="$temporary" bs=1048576 count=256 2>/dev/null
        test -s "$temporary"
        mv "$temporary" "$storage/$name"
        trap - EXIT HUP INT TERM
        ;;
    "sha256 "*)
        name=${requested#sha256 }
        valid_name "$name" || exit 64
        test -f "$storage/$name"
        sha256sum "$storage/$name" | cut -d ' ' -f 1
        ;;
    prune)
        find "$storage" -type f -name 'core-????-??-??.db.gpg' -mtime +30 -delete
        ;;
    *)
        echo "backup command denied" >&2
        exit 64
        ;;
esac

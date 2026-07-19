#!/bin/sh
# Forced-command receiver for encrypted catering backups on the VPS.

set -eu

storage=${CATERING_BACKUP_RECEIVE_STORAGE:-/var/lib/catering-backup/files}
requested=${SSH_ORIGINAL_COMMAND:-}

valid_name() {
    case "$1" in
        core-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].db.gpg) return 0 ;;
        courier-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.tar.gz.gpg) return 0 ;;
        courier-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.tar.gz.gpg.sha256) return 0 ;;
        fingerfood-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.tar.gz.gpg) return 0 ;;
        fingerfood-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.tar.gz.gpg.sha256) return 0 ;;
        auerswald-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.tar.gz.gpg) return 0 ;;
        auerswald-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.tar.gz.gpg.sha256) return 0 ;;
        *) return 1 ;;
    esac
}

validate_name() {
    name=$1
    cleaned=

    case "$name" in
        ""|*/*|*\\*|*..*) return 1 ;;
    esac

    cleaned=$(printf '%s' "$name" | tr -cd '[:alnum:].-')
    if [ "$cleaned" != "$name" ]; then
        return 1
    fi

    valid_name "$name"
}

prune_courier_family() {
    suffix=$1
    newest=
    for path in $(find "$storage" -maxdepth 1 -type f -name "courier-????????T??????Z.tar.gz.gpg${suffix}" | LC_ALL=C sort); do
        newest=$path
    done

    for path in $(find "$storage" -maxdepth 1 -type f -name "courier-????????T??????Z.tar.gz.gpg${suffix}" -mtime +30 | LC_ALL=C sort); do
        if [ -n "$newest" ] && [ "$path" = "$newest" ]; then
            continue
        fi
        rm -f "$path"
    done
}

prune_auerswald_family() {
    suffix=$1
    newest=
    for path in $(find "$storage" -maxdepth 1 -type f -name "auerswald-????????T??????Z.tar.gz.gpg${suffix}" | LC_ALL=C sort); do
        newest=$path
    done

    for path in $(find "$storage" -maxdepth 1 -type f -name "auerswald-????????T??????Z.tar.gz.gpg${suffix}" -mtime +30 | LC_ALL=C sort); do
        if [ -n "$newest" ] && [ "$path" = "$newest" ]; then
            continue
        fi
        rm -f "$path"
    done
}

prune_fingerfood_family() {
    suffix=$1
    newest=
    for path in $(find "$storage" -maxdepth 1 -type f -name "fingerfood-????????T??????Z.tar.gz.gpg${suffix}" | LC_ALL=C sort); do
        newest=$path
    done

    for path in $(find "$storage" -maxdepth 1 -type f -name "fingerfood-????????T??????Z.tar.gz.gpg${suffix}" -mtime +30 | LC_ALL=C sort); do
        if [ -n "$newest" ] && [ "$path" = "$newest" ]; then
            continue
        fi
        rm -f "$path"
    done
}

case "$requested" in
    "put "*)
        name=${requested#put }
        validate_name "$name" || exit 64
        final="$storage/$name"
        if [ -e "$final" ]; then
            exit 64
        fi
        umask 077
        temporary="$storage/.$name.$$"
        trap 'rm -f "$temporary"' EXIT HUP INT TERM
        # Cap a compromised sender at 256 MiB per upload. A truncated upload
        # cannot pass the sender's end-to-end SHA-256 comparison.
        dd of="$temporary" bs=1048576 count=256 2>/dev/null
        test -s "$temporary"
        mv "$temporary" "$final"
        chmod 600 "$final"
        trap - EXIT HUP INT TERM
        ;;
    "sha256 "*)
        name=${requested#sha256 }
        validate_name "$name" || exit 64
        test -f "$storage/$name"
        sha256sum "$storage/$name" | cut -d ' ' -f 1
        ;;
    prune)
        find "$storage" -maxdepth 1 -type f -name 'core-????-??-??.db.gpg' -mtime +30 -delete
        prune_courier_family ""
        prune_courier_family ".sha256"
        prune_fingerfood_family ""
        prune_fingerfood_family ".sha256"
        prune_auerswald_family ""
        prune_auerswald_family ".sha256"
        ;;
    *)
        echo "backup command denied" >&2
        exit 64
        ;;
esac

#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

image=ghcr.io/dragoncrafted87/alpine-backup-cron
./build.sh

work=$(mktemp -d)
cleanup() {
    rm -rf "$work"
}
trap cleanup EXIT

mkdir -p "$work/source/nested" "$work/source/empty" "$work/backups"
printf 'known-line\n' >"$work/source/known.txt"
printf 'nested-line\n' >"$work/source/nested/inside.txt"
printf 'space name\n' >"$work/source/nested/space name.txt"
ln -s inside.txt "$work/source/nested/link.txt"

docker run --rm \
    --env BACKUP_NAME=fixture \
    --env TZ=UTC \
    --volume "$work/source:/mnt/source:ro" \
    --volume "$work/backups:/mnt/backups" \
    "$image"

mapfile -t archives < <(find "$work/backups" -type f -name 'fixture-*.tar.xz' | sort)
if [ "${#archives[@]}" -ne 1 ]; then
    printf 'expected one archive, found %s\n' "${#archives[@]}" >&2
    exit 1
fi

archive=${archives[0]}
name=$(basename "$archive")
if [[ ! "$name" =~ ^fixture-[0-9]{4}-W[0-9]{2}-[1-7]-[0-9]{2}-[0-9]{2}-[0-9]{2}\.tar\.xz$ ]]; then
    printf 'unexpected archive name %s\n' "$name" >&2
    exit 1
fi

extract="$work/extract"
expected="$work/expected"
mkdir -p "$extract" "$expected"
cp -R -L "$work/source/." "$expected/"
tar -C "$extract" -xJf "$archive"
diff -rq "$expected" "$extract"
printf 'backup archive %s matches the fixture\n' "$name"

#!/usr/bin/env bash
# cspell:disable
# Runs auth-keys.sh as Alpine ash against fixtures. No cluster and no SSH server.
set -euo pipefail

cd "$(dirname "$0")"
script="$(pwd)/root/usr/local/bin/auth-keys.sh"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

bin="${work}/bin"
mkdir -p "$bin"
keep='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey dragon@test'
other='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOtherKey dragon@other'
local_only='ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQLocalOnly local@router'

cat >"${bin}/curl" <<'EOF'
#!/bin/sh
out=""
while [ $# -gt 0 ]; do
    case "$1" in
        -o)
            out="$2"
            shift 2
            ;;
        -o*)
            out="${1#-o}"
            shift
            ;;
        *) shift ;;
    esac
done
case "${FETCH_MODE:-ok}" in
    ok) printf '%s\n' 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey dragon@test' >"$out" ;;
    extra)
        printf '%s\n' \
            'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey dragon@test' \
            'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOtherKey dragon@other' >"$out"
        ;;
    empty) : >"$out" ;;
    bad) printf '%s\n' 'not-a-key' >"$out" ;;
    fail) exit 1 ;;
    *) printf 'bad FETCH_MODE %s\n' "${FETCH_MODE}" >&2; exit 1 ;;
esac
EOF

cat >"${bin}/ssh" <<'EOF'
#!/bin/sh
host=""
cmd=""
for arg in "$@"; do
    cmd="$arg"
    case "$arg" in
        *@*) host="${arg##*@}" ;;
    esac
done
printf '%s\n' "$cmd" >>"${SSH_LOG}"
case "$host" in
    down.example) exit 255 ;;
esac
remote="${REMOTE_DIR}/${host}"
case "$cmd" in
    *"cat >"*)
        cat >"$remote"
        exit 0
        ;;
esac
if [ ! -e "$remote" ]; then
    exit 2
fi
cat "$remote"
exit 0
EOF
chmod 755 "${bin}/curl" "${bin}/ssh"

published="${work}/published"
push_list="${work}/push-list"
known="${work}/known_hosts"
ident="${work}/id"
remotes="${work}/remotes"
log="${work}/ssh.log"
mkdir -p "$remotes"
printf 'key\n' >"$ident"
printf 'down.example ssh-ed25519 AAAAhost1\nok.example ssh-ed25519 AAAAhost2\nsecond.example ssh-ed25519 AAAAhost3\ndrop.example ssh-ed25519 AAAAhost4\n' >"$known"

run_sync() {
    local mode="$1"
    local fetch="$2"
    : >"$log"
    docker run --rm --network none \
        --user "$(id -u):$(id -g)" \
        -e FETCH_MODE="$fetch" \
        -e SSH_LOG=/work/ssh.log \
        -e REMOTE_DIR=/work/remotes \
        -e PATH=/work/bin:/usr/bin:/bin \
        -e AUTH_KEYS_SINK=file \
        -e AUTH_KEYS_FILE=/work/published \
        -e AUTH_KEYS_PUSH_LIST=/work/push-list \
        -e AUTH_KEYS_KNOWN_HOSTS=/work/known_hosts \
        -e AUTH_KEYS_IDENTITY=/work/id \
        -e KEYS_URL=https://github.com/DragonCrafted87.keys \
        -v "$script":/usr/local/bin/auth-keys.sh:ro \
        -v "$work":/work \
        alpine:3.24 \
        /bin/sh /usr/local/bin/auth-keys.sh "$mode"
}

reset_published() {
    printf '%s\n' "$1" >"$published"
    : >"$push_list"
    rm -rf "$remotes"
    mkdir -p "$remotes"
    : >"$log"
}

expect_published() {
    local label="$1"
    local want="$2"
    [[ "$(cat "$published")" == "$want" ]] || {
        printf '%s changed the published file:\n%s\n' "$label" "$(cat "$published")" >&2
        exit 1
    }
}

reset_published "$keep"
set +e
fail_out="$(run_sync run fail 2>&1)"
fail_rc=$?
set -e
[[ "$fail_rc" -ne 0 ]]
printf '%s\n' "$fail_out" | grep -q 'failed to fetch'
expect_published 'fetch failure' "$keep"
[[ ! -s "$log" ]]

reset_published "$keep"
set +e
empty_out="$(run_sync run empty 2>&1)"
empty_rc=$?
set -e
[[ "$empty_rc" -ne 0 ]]
printf '%s\n' "$empty_out" | grep -q 'did not contain any SSH public keys'
expect_published 'empty body' "$keep"

reset_published "$keep"
set +e
bad_out="$(run_sync run bad 2>&1)"
bad_rc=$?
set -e
[[ "$bad_rc" -ne 0 ]]
printf '%s\n' "$bad_out" | grep -q 'did not contain any SSH public keys'
expect_published 'non-key body' "$keep"

reset_published "$local_only"
set +e
drop_out="$(run_sync run ok 2>&1)"
drop_rc=$?
set -e
[[ "$drop_rc" -ne 0 ]]
printf '%s\n' "$drop_out" | grep -q 'drop every key'
expect_published 'no overlap' "$local_only"
[[ ! -s "$log" ]]

reset_published "$keep"
ok_out="$(run_sync run extra)"
grep -q 'AAAAC3NzaC1lZDI1NTE5AAAAITestKey' "$published"
grep -q 'AAAAC3NzaC1lZDI1NTE5AAAAIOtherKey' "$published"
grep -q '^# synced from https://github.com/DragonCrafted87.keys at ' "$published"
printf '%s\n' "$ok_out" | grep -q 'published file'

reset_published "$keep"
printf '%s\n' 'down.example root /oem/authorized_keys' >"$push_list"
before="$(cat "$published")"
set +e
down_out="$(run_sync run extra 2>&1)"
down_rc=$?
set -e
[[ "$down_rc" -ne 0 ]]
printf '%s\n' "$down_out" | grep -q 'failed to read'
grep -q 'AAAAC3NzaC1lZDI1NTE5AAAAIOtherKey' "$published"
[[ "$(cat "$published")" != "$before" ]]

reset_published "$keep"
printf '%s\n' "$local_only" >"${remotes}/drop.example"
printf '%s\n' 'drop.example root /oem/authorized_keys' >"$push_list"
set +e
nover_out="$(run_sync run ok 2>&1)"
nover_rc=$?
set -e
[[ "$nover_rc" -ne 0 ]]
printf '%s\n' "$nover_out" | grep -q 'push would drop every key'
[[ "$(cat "${remotes}/drop.example")" == "$local_only" ]]
grep -q 'AAAAC3NzaC1lZDI1NTE5AAAAITestKey' "$published"

reset_published "$keep"
printf '%s\n' "$keep" >"${remotes}/second.example"
printf '%s\n' \
    'down.example root /oem/authorized_keys' \
    'second.example root /oem/authorized_keys' >"$push_list"
set +e
two_out="$(run_sync run extra 2>&1)"
two_rc=$?
set -e
[[ "$two_rc" -ne 0 ]]
printf '%s\n' "$two_out" | grep -q 'failed to read'
grep -q 'AAAAC3NzaC1lZDI1NTE5AAAAIOtherKey' "${remotes}/second.example"
grep -q 'AAAAC3NzaC1lZDI1NTE5AAAAITestKey' "${remotes}/second.example"
if grep -q 'LocalOnly' "${remotes}/second.example"; then
    printf 'second target kept a key outside the fetch\n' >&2
    exit 1
fi

printf 'auth-keys prove ok\n'

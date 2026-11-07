#!/bin/sh
# Fetch GitHub's authorized_keys, publish the body, then push it to
# hosts that cannot fetch it. Fails closed: a bad fetch, an empty
# fetch, or a body that shares no key with the current file leaves
# that file alone and does not push. One push target failing does
# not roll back the published file and does not skip the later
# targets. The process exits non-zero if any target failed.
#
#   auth-keys.sh run

set -eu
set -o pipefail

KEYS_URL="${KEYS_URL:-https://github.com/DragonCrafted87.keys}"
SINK="${AUTH_KEYS_SINK:-file}"
PUBLISHED="${AUTH_KEYS_FILE:-/www/authorized_keys}"
PUSH_LIST="${AUTH_KEYS_PUSH_LIST:-/etc/auth-keys/push-list}"
KNOWN_HOSTS="${AUTH_KEYS_KNOWN_HOSTS:-/etc/auth-keys/known_hosts}"
IDENTITY="${AUTH_KEYS_IDENTITY:-/etc/auth-keys/id_ed25519}"
NS="${AUTH_KEYS_NAMESPACE:-iot}"
CM="${AUTH_KEYS_CONFIGMAP:-auth-keys}"
key_re='^[A-Za-z0-9._+-]+(@openssh\.com)? [A-Za-z0-9+/=]+'

die() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT INT HUP TERM

load_published() {
    if [ "$SINK" = "file" ]; then
        if [ -f "$PUBLISHED" ]; then
            cat "$PUBLISHED"
        fi
        return 0
    fi
    if [ "$SINK" != "configmap" ]; then
        die "unknown AUTH_KEYS_SINK $SINK"
    fi
    token="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
    ca="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    api="https://kubernetes.default.svc/api/v1/namespaces/${NS}/configmaps/${CM}"
    curl -fsS --cacert "$ca" -H "Authorization: Bearer ${token}" "$api" \
        | jq -r '.data.authorized_keys // empty'
}

store_published() {
    local src tmp body token ca api
    src="$1"
    if [ "$SINK" = "file" ]; then
        tmp="${work}/store"
        cat "$src" >"$tmp"
        mv "$tmp" "$PUBLISHED"
        return 0
    fi
    token="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
    ca="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    api="https://kubernetes.default.svc/api/v1/namespaces/${NS}/configmaps/${CM}"
    body="$(jq -n --rawfile keys "$src" '{data:{authorized_keys:$keys}}')"
    curl -fsS --cacert "$ca" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/strategic-merge-patch+json" \
        -X PATCH \
        --data "$body" \
        "$api" >/dev/null
}

has_overlap() {
    local current="$1"
    local fetched="$2"
    local line blob
    if [ ! -f "$current" ] || ! grep -qE "$key_re" "$current"; then
        return 0
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        blob="$(printf '%s\n' "$line" | awk '{print $2}')"
        [ -n "$blob" ] || continue
        if grep -qF "$blob" "$fetched"; then
            return 0
        fi
    done <"$current"
    return 1
}

publish() {
    command -v curl >/dev/null 2>&1 || die "no https fetch tool"
    local fetched current out
    fetched="${work}/fetched"
    current="${work}/current"
    out="${work}/out"
    if ! curl -fsSL --max-time 20 "$KEYS_URL" -o "$fetched"; then
        die "failed to fetch $KEYS_URL"
    fi
    if ! grep -qE "$key_re" "$fetched"; then
        die "$KEYS_URL did not contain any SSH public keys"
    fi
    load_published >"$current"
    if ! has_overlap "$current" "$fetched"; then
        die "fetch would drop every key in the published file"
    fi
    {
        printf '# synced from %s at %s\n' "$KEYS_URL" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        grep -E "$key_re" "$fetched"
    } >"$out"
    store_published "$out"
    printf 'published %s from %s\n' "$SINK" "$KEYS_URL"
}

push_one() {
    local host user path probe remote remote_rc install_cmd
    host="$1"
    user="$2"
    path="$3"
    if ! awk -v host="$host" '$1 == host { found = 1 } END { exit !found }' "$KNOWN_HOSTS"; then
        printf 'error: no host key pin for %s\n' "$host" >&2
        return 1
    fi
    if [ ! -r "$IDENTITY" ]; then
        printf 'error: cannot read %s\n' "$IDENTITY" >&2
        return 1
    fi
    probe="if [ -f '${path}' ]; then cat '${path}'; exit \$?; fi; exit 2"
    remote="${work}/remote"
    set +e
    ssh -i "$IDENTITY" \
        -o BatchMode=yes \
        -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=yes \
        -o UserKnownHostsFile="$KNOWN_HOSTS" \
        -o ConnectTimeout=10 \
        "${user}@${host}" "$probe" >"$remote" 2>/dev/null
    remote_rc=$?
    set -e
    if [ "$remote_rc" -eq 2 ]; then
        : >"$remote"
    elif [ "$remote_rc" -ne 0 ]; then
        rm -f "$remote"
        printf 'error: failed to read %s on %s\n' "$path" "$host" >&2
        return 1
    fi
    if ! has_overlap "$remote" "$PUBLISHED"; then
        rm -f "$remote"
        printf 'error: push would drop every key in %s on %s\n' "$path" "$host" >&2
        return 1
    fi
    rm -f "$remote"
    install_cmd="umask 077; cat > '${path}.tmp' && chmod 600 '${path}.tmp' && mv '${path}.tmp' '${path}'"
    if ! ssh -i "$IDENTITY" \
        -o BatchMode=yes \
        -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=yes \
        -o UserKnownHostsFile="$KNOWN_HOSTS" \
        -o ConnectTimeout=10 \
        "${user}@${host}" "$install_cmd" <"$PUBLISHED"; then
        printf 'error: failed to install %s on %s\n' "$path" "$host" >&2
        return 1
    fi
    printf 'updated %s on %s\n' "$path" "$host"
}

push_all() {
    local line host user path fail
    [ -f "$PUBLISHED" ] || die "published file is missing"
    [ -f "$PUSH_LIST" ] || return 0
    fail=0
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            "" | "#"*) continue ;;
        esac
        # shellcheck disable=SC2086
        set -- $line
        host="$1"
        user="${2:-}"
        path="${3:-}"
        if [ -z "$host" ] || [ -z "$user" ] || [ -z "$path" ]; then
            printf 'error: bad push target %s\n' "$line" >&2
            fail=1
            continue
        fi
        if ! push_one "$host" "$user" "$path"; then
            fail=1
        fi
    done <"$PUSH_LIST"
    [ "$fail" -eq 0 ]
}

mode="${1:-run}"
case "$mode" in
    publish) publish ;;
    push) push_all ;;
    run)
        publish
        if [ "$SINK" = "configmap" ]; then
            load_published >"$PUBLISHED"
        fi
        push_all
        ;;
    *) die "unknown mode $mode" ;;
esac

#!/usr/bin/env bash
# Fixture cases for host-status.sh. This does not publish and does not
# touch a host.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
script=$here/root/usr/local/bin/host-status.sh
fake=$(mktemp -d)
trap 'rm -rf "$fake"' EXIT
printf '#!/bin/sh\nprintf "mosquitto_pub called\\n" >&2\nexit 99\n' >"$fake/mosquitto_pub"
chmod +x "$fake/mosquitto_pub"
export PATH="$fake:$PATH"

dev_line() {
    printf '  %s: %s 0 0 0 0 0 0 0 %s 0 0 0 0 0 0 0\n' "$1" "$2" "$3"
}

write_dev() {
    dir=$1
    shift
    {
        printf 'Inter-|   Receive                                                |  Transmit\n'
        printf ' face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n'
        while [ "$#" -gt 0 ]; do
            dev_line "$1" "$2" "$3"
            shift 3
        done
    } >"$dir"
}

write_common_net() {
    root=$1
    mkdir -p "$root/proc/net" "$root/sys/class/thermal/thermal_zone0" \
        "$root/sys/class/thermal/thermal_zone1" \
        "$root/sys/class/thermal/thermal_zone2" \
        "$root/sys/class/thermal/thermal_zone3"
    write_dev "$root/proc/net/dev.1" \
        eth0 1000 2000 \
        veth0 9 9 \
        lo 1 1 \
        br-other 4 4 \
        eth1 50 60 \
        br-lan 100 200
    write_dev "$root/proc/net/dev.2" \
        eth0 5000 4000 \
        veth0 9 9 \
        lo 1 1 \
        br-other 4 4 \
        eth1 50 60 \
        br-lan 110 220
    printf 'Iface Destination Gateway Flags RefCnt Use Metric Mask\neth0 00000000 0100000A 0003 0 0 100 00000000\neth1 00000000 0100000A 0003 0 0 300 00000000\n' >"$root/proc/net/route"
    printf '30000\n' >"$root/sys/class/thermal/thermal_zone0/temp"
    printf '47000\n' >"$root/sys/class/thermal/thermal_zone1/temp"
    printf '0\n' >"$root/sys/class/thermal/thermal_zone2/temp"
    printf '200000\n' >"$root/sys/class/thermal/thermal_zone3/temp"
}

write_cpu() {
    printf 'cpu  %s\n' "$2" >"$1/proc/stat.1"
    printf 'cpu  %s\n' "$3" >"$1/proc/stat.2"
}

run_script() {
    env \
        HOST_STATUS_ROOT="$1" \
        HOST_STATUS_HOST=fixture \
        HOST_STATUS_BROKER= \
        HOST_STATUS_ONCE=1 \
        HOST_STATUS_INTERVAL="$2" \
        "$script"
}

assert_json() {
    python3 - "$1" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
names = [item["name"] for item in data["net"]]
assert data["cpu_percent"] == 25.0, data
assert data["memory_percent"] == 40.0, data
assert data["temperature_c"] == 47.0, data
assert data["primary"] == "eth0", data
assert data["rx_bps"] == 4000, data
assert data["tx_bps"] == 2000, data
assert names == ["eth0", "eth1", "br-lan"], names
assert data["disks"] == []
br = data["net"][2]
assert br["rx_bps"] == 10 and br["tx_bps"] == 20, br
PY
}

base=$(mktemp -d)
trap 'rm -rf "$fake" "$base"' EXIT
mkdir -p "$base/proc"
write_common_net "$base"
write_cpu "$base" "100 0 0 900 0 0 0 0 0 0" "350 0 0 1650 0 0 0 0 0 0"
printf 'MemTotal: 1000000 kB\nMemFree: 100000 kB\nMemAvailable: 600000 kB\nBuffers: 0 kB\nCached: 0 kB\n' >"$base/proc/meminfo"
payload=$(run_script "$base" 1)
assert_json "$payload"
printf 'included eth0\n'
printf 'included eth1\n'
printf 'included br-lan\n'
printf 'excluded lo\n'
printf 'excluded veth0\n'
printf 'excluded br-other\n'
printf 'memory available\n'
printf 'temperature hottest\n'
printf 'temperature ignored 0\n'
printf 'temperature ignored above 150\n'

fallback=$(mktemp -d)
trap 'rm -rf "$fake" "$base" "$fallback"' EXIT
mkdir -p "$fallback/proc"
write_common_net "$fallback"
write_cpu "$fallback" "100 0 0 900 0 0 0 0 0 0" "350 0 0 1650 0 0 0 0 0 0"
printf 'MemTotal: 1000000 kB\nMemFree: 200000 kB\nBuffers: 100000 kB\nCached: 100000 kB\n' >"$fallback/proc/meminfo"
fallback_payload=$(run_script "$fallback" 1)
python3 - "$fallback_payload" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
assert data["memory_percent"] == 60.0, data
assert data["temperature_c"] == 47.0
PY
printf 'memory fallback\n'

cold=$(mktemp -d)
trap 'rm -rf "$fake" "$base" "$fallback" "$cold"' EXIT
mkdir -p "$cold/proc/net"
write_cpu "$cold" "100 0 0 900 0 0 0 0 0 0" "350 0 0 1650 0 0 0 0 0 0"
printf 'MemTotal: 1000000 kB\nMemAvailable: 600000 kB\n' >"$cold/proc/meminfo"
write_dev "$cold/proc/net/dev.1" eth0 1000 2000
write_dev "$cold/proc/net/dev.2" eth0 5000 4000
printf 'Iface Destination Gateway Flags RefCnt Use Metric Mask\neth0 00000000 0100000A 0003 0 0 100 00000000\n' >"$cold/proc/net/route"
cold_payload=$(run_script "$cold" 1)
python3 - "$cold_payload" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
assert data["temperature_c"] is None, data
PY
printf 'temperature null\n'

quiet=$(mktemp -d)
trap 'rm -rf "$fake" "$base" "$fallback" "$cold" "$quiet"' EXIT
mkdir -p "$quiet/proc"
write_cpu "$quiet" "100 0 0 900 0 0 0 0 0 0" "100 0 0 900 0 0 0 0 0 0"
printf 'MemTotal: 1000000 kB\nMemAvailable: 600000 kB\n' >"$quiet/proc/meminfo"
quiet_payload=$(run_script "$quiet" 0)
if [ -n "$quiet_payload" ]; then
    printf 'zero cpu delta produced %s\n' "$quiet_payload" >&2
    exit 1
fi
printf 'zero cpu delta\n'

early=$(mktemp -d)
trap 'rm -rf "$fake" "$base" "$fallback" "$cold" "$quiet" "$early"' EXIT
mkdir -p "$early/proc"
write_cpu "$early" "100 0 0 900 0 0 0 0 0 0" "350 0 0 1650 0 0 0 0 0 0"
printf 'MemTotal: 1000000 kB\nMemAvailable: 600000 kB\n' >"$early/proc/meminfo"
early_out=$(mktemp)
env \
    HOST_STATUS_ROOT="$early" \
    HOST_STATUS_HOST=fixture \
    HOST_STATUS_BROKER= \
    HOST_STATUS_ONCE=1 \
    HOST_STATUS_INTERVAL=3 \
    "$script" >"$early_out" &
early_pid=$!
sleep 0.3
if ! kill -0 "$early_pid" 2>/dev/null; then
    printf 'script exited before the first interval\n' >&2
    wait "$early_pid" || true
    exit 1
fi
kill "$early_pid"
wait "$early_pid" 2>/dev/null || true
if [ -s "$early_out" ]; then
    printf 'first sample produced output\n' >&2
    exit 1
fi
printf 'first sample\n'

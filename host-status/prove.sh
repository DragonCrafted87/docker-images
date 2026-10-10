#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

image=ghcr.io/dragoncrafted87/alpine-host-status
./build.sh

network=images-prove-host-status
mqtt=images-prove-host-status-mqtt
app=images-prove-host-status-app
conf=$(mktemp)
work=$(mktemp -d)
cleanup() {
    docker rm -f "$app" "$mqtt" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    rm -rf "$work"
    rm -f "$conf"
}
trap cleanup EXIT

mkdir -p "$work/proc/net" "$work/sys/class/thermal/thermal_zone0"
printf 'cpu  100 0 0 900 0 0 0 0 0 0\n' >"$work/proc/stat.1"
printf 'cpu  350 0 0 1650 0 0 0 0 0 0\n' >"$work/proc/stat.2"
printf 'MemTotal: 1000000 kB\nMemAvailable: 600000 kB\n' >"$work/proc/meminfo"
printf 'Inter-|   Receive                                                |  Transmit\n' >"$work/proc/net/dev.1"
printf ' face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n' >>"$work/proc/net/dev.1"
printf '  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n' >>"$work/proc/net/dev.1"
{
    printf 'Inter-|   Receive                                                |  Transmit\n'
    printf ' face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n'
    printf '  eth0: 5000 0 0 0 0 0 0 0 4000 0 0 0 0 0 0 0\n'
} >"$work/proc/net/dev.2"
printf 'Iface Destination Gateway Flags RefCnt Use Metric Mask\neth0 00000000 0100000A 0003 0 0 100 00000000\n' >"$work/proc/net/route"
printf '47000\n' >"$work/sys/class/thermal/thermal_zone0/temp"

cat >"$conf" <<'EOF'
listener 1883
allow_anonymous true
EOF

docker network create "$network"
docker run -d --name "$mqtt" --network "$network" \
    --volume "$conf:/mosquitto/config/mosquitto.conf:ro" \
    eclipse-mosquitto:2

ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if docker exec "$mqtt" mosquitto_pub -t health -m up; then
        ready=1
        break
    fi
    sleep 0.5
done
if [ "$ready" -ne 1 ]; then
    docker logs "$mqtt" >&2 || true
    exit 1
fi

docker run -d --name "$app" --network "$network" \
    --env HOST_STATUS_ROOT=/host \
    --env HOST_STATUS_HOST=fixture \
    --env HOST_STATUS_BROKER="$mqtt" \
    --env HOST_STATUS_INTERVAL=1 \
    --env HOST_STATUS_ONCE=1 \
    --volume "$work:/host:ro" \
    "$image"

status=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if [ "$(docker inspect -f '{{.State.Status}}' "$app")" = "exited" ]; then
        status=$(docker inspect -f '{{.State.ExitCode}}' "$app")
        break
    fi
    sleep 0.5
done
if [ "$(docker inspect -f '{{.State.Status}}' "$app")" != "exited" ]; then
    docker logs "$app" >&2 || true
    printf 'host-status did not exit\n' >&2
    exit 1
fi
if [ "$status" -ne 0 ]; then
    docker logs "$app" >&2 || true
    printf 'host-status exited %s\n' "$status" >&2
    exit 1
fi

message=$(docker exec "$mqtt" mosquitto_sub -t 'homelab/status/fixture' -C 1 -W 5)
python3 - "$message" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
for key in ("cpu_percent", "memory_percent", "rx_bps", "tx_bps"):
    if not isinstance(data[key], (int, float)):
        raise SystemExit(f"{key} is not numeric: {data[key]!r}")
if data["cpu_percent"] != 25.0 or data["memory_percent"] != 40.0:
    raise SystemExit(data)
if data["rx_bps"] != 4000 or data["tx_bps"] != 2000:
    raise SystemExit(data)
PY
printf 'host-status published a retained payload\n'

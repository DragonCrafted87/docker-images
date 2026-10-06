#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

image=ghcr.io/dragoncrafted87/alpine-speedtest-mqtt-publisher
./build.sh

network=images-prove-speedtest
mqtt=images-prove-speedtest-mqtt
app=images-prove-speedtest-app
conf=$(mktemp)
cleanup() {
    docker rm -f "$app" "$mqtt" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    rm -f "$conf"
}
trap cleanup EXIT

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
    --cap-add NET_RAW \
    --env TZ=UTC \
    --env MQTT_SERVER="$mqtt" \
    --env MQTT_SERVER_PORT=1883 \
    --env PING_COUNT=2 \
    --env DOWNLOAD_ITERATIONS=1 \
    --env UPLOAD_ITERATIONS=1 \
    "$image"

ready=0
for _ in $(seq 1 90); do
    state=$(docker inspect --format '{{.State.Status}}' "$app")
    if [ "$state" = "exited" ]; then
        ready=1
        break
    fi
    sleep 2
done
if [ "$ready" -ne 1 ]; then
    docker logs "$app" >&2 || true
    printf 'speedtest did not exit\n' >&2
    exit 1
fi

status=$(docker inspect --format '{{.State.ExitCode}}' "$app")
logs=$(docker logs "$app" 2>&1)
if [ "$status" -ne 0 ]; then
    printf '%s\n' "$logs" >&2
    printf 'speedtest exited %s\n' "$status" >&2
    exit 1
fi

printf '%s\n' "$logs" | grep -F 'MQTT speedtest payload'
printf '%s\n' "$logs" | grep -F 'MQTT speedtest/attributes payload'

messages=$(docker exec "$mqtt" mosquitto_sub -t 'speedtest/#' -C 1 -W 5 -v)
printf '%s\n' "$messages" | grep -F 'speedtest/attributes'
messages=$(docker exec "$mqtt" mosquitto_sub -t 'speedtest' -C 1 -W 5 -v)
printf '%s\n' "$messages" | grep -F 'speedtest '
printf 'speedtest published a result to the broker\n'

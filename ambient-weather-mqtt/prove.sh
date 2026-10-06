#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

image=ghcr.io/dragoncrafted87/alpine-ambient-weather-mqtt-publisher
./build.sh

network=images-prove-weather
mqtt=images-prove-weather-mqtt
app=images-prove-weather-app
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
    --env TZ=UTC \
    --env MQTT_SERVER="$mqtt" \
    --env MQTT_SERVER_PORT=1883 \
    --publish 127.0.0.1:18080:80 \
    "$image"

ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 1 "http://127.0.0.1:18080/ready" || true)
    if [ "$code" = "400" ] || [ "$code" = "200" ]; then
        ready=1
        break
    fi
    sleep 0.5
done
if [ "$ready" -ne 1 ]; then
    docker logs "$app" >&2 || true
    exit 1
fi

code=$(
    curl -s -o /dev/null -w '%{http_code}' -m 5 \
        "http://127.0.0.1:18080/AMBWeather/dateutc=2024-01-02%2003:04:05&tempf=70.1"
)
if [ "$code" != "200" ]; then
    docker logs "$app" >&2 || true
    printf 'weather returned %s\n' "$code" >&2
    exit 1
fi

logs=$(docker logs "$app" 2>&1)
printf '%s\n' "$logs" | grep -F 'MQTT weather payload'
printf '%s\n' "$logs" | grep -F 'MQTT weather/attributes payload'

messages=$(docker exec "$mqtt" mosquitto_sub -t '#' -C 2 -W 5 -v)
printf '%s\n' "$messages" | grep -F 'weather '
printf '%s\n' "$messages" | grep -F 'weather/attributes'
printf 'weather published a station update to the broker\n'

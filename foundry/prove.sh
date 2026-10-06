#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

image=ghcr.io/dragoncrafted87/alpine-foundry-vtt-runner
./build.sh

entrypoint=$(docker inspect --format '{{json .Config.Entrypoint}}' "$image")
expected='["node","server/resources/app/main.js","--headless","--dataPath=/home/docker/data"]'
if [ "$entrypoint" != "$expected" ]; then
    printf 'entrypoint is %s\n' "$entrypoint" >&2
    exit 1
fi

user=$(docker inspect --format '{{.Config.User}}' "$image")
if [ "$user" != "docker" ]; then
    printf 'user is %s\n' "$user" >&2
    exit 1
fi

docker run --rm --entrypoint node "$image" --version

set +e
output=$(docker run --rm "$image" 2>&1)
status=$?
set -e
if [ "$status" -eq 0 ]; then
    printf 'foundry started without its server tree\n%s\n' "$output" >&2
    exit 1
fi
printf '%s\n' "$output" | grep -F 'server/resources/app/main.js'
printf 'foundry entrypoint is the node runner\n'

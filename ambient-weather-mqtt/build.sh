#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

docker build \
    --tag ghcr.io/dragoncrafted87/alpine:3.24 \
    ../base

docker build \
    --build-arg BASE_IMAGE=ghcr.io/dragoncrafted87/alpine:3.24 \
    --tag ghcr.io/dragoncrafted87/alpine-ambient-weather-mqtt-publisher \
    .

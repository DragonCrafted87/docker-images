#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

docker build \
    --tag ghcr.io/dragoncrafted87/alpine-minecraft \
    .

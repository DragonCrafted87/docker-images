#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

docker build \
    --tag ghcr.io/dragoncrafted87/etsy-oauth-broker:1.0.0 \
    .

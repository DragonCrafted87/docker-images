#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

image=ghcr.io/dragoncrafted87/hermes-agent:v0.22.2-screen
./build.sh

version=$(docker run --rm --user 10000:10000 --entrypoint /usr/local/bin/pass-cli "$image" --version)
printf '%s\n' "$version"
case "$version" in
    "Proton Pass CLI 2.5.1 "*) ;;
    *)
        printf 'unexpected pass-cli version: %s\n' "$version" >&2
        exit 1
        ;;
esac

docker run --rm --user 10000:10000 --entrypoint /bin/sh "$image" -c '
    command -v Xtigervnc
    command -v vncserver
    command -v xfce4-terminal
    command -v xfwm4
    command -v xfdesktop
    command -v xfce4-panel
'

printf 'hermes screen tools ok\n'

# syntax=docker/dockerfile:1
# Foundry 9 calls util.isDate. Node 24 removed that function.
FROM node:20-alpine

RUN <<eot ash
    set -e

    apk upgrade
    apk add --no-cache --update \
        tzdata

    rm -rf /tmp/*
    rm -rf /var/cache/apk/*
eot

ARG USER=docker
ARG UID=1000
ARG GID=1000

RUN ash <<eot
    set -e

    # node:20-alpine already owns uid 1000. Foundry's data is owned by that uid.
    deluser node
    addgroup \
        --gid "$GID" \
        --system "$USER"

    adduser \
        --disabled-password \
        --gecos "" \
        --ingroup "$USER" \
        --uid "$UID" \
        "$USER"
eot

USER docker

WORKDIR /home/docker

ENTRYPOINT ["node", "server/resources/app/main.js", "--headless", "--dataPath=/home/docker/data"]

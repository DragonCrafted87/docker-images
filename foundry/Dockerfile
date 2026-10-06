# syntax=docker/dockerfile:1
FROM alpine:3.24

RUN <<eot ash
    set -e

    apk upgrade
    apk add --no-cache --update \
        nodejs \
        tzdata

    rm -rf /tmp/*
    rm -rf /var/cache/apk/*
eot

ARG USER=docker
ARG UID=1000
ARG GID=1000

RUN ash <<eot
    set -e

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

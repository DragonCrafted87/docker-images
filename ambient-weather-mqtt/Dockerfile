# syntax=docker/dockerfile:1
ARG BASE_IMAGE=ghcr.io/dragoncrafted87/alpine:3.24
FROM ${BASE_IMAGE}

COPY root/. /

RUN <<eot ash
    set -e

    apk upgrade

    pip3 --no-cache-dir \
        install \
            --break-system-packages \
            paho-mqtt

    rm -rf /tmp/*
    rm -rf /var/cache/apk/*
    chmod +x -R /scripts/*
eot

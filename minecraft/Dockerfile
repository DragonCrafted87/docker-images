# syntax=docker/dockerfile:1
ARG BASE_IMAGE=ghcr.io/dragoncrafted87/alpine:3.24
FROM ${BASE_IMAGE}

COPY root/. /

RUN <<eot ash
    set -e

    apk upgrade
    apk add --no-cache --update \
        git \
        openjdk17-jre-headless

    pip3 --no-cache-dir \
        install \
            --break-system-packages \
            dirsync \
            mcrcon \
            python-dateutil \
            requests \
            xmltodict

    rm -rf /tmp/*
    rm -rf /var/cache/apk/*
    chmod +x -R /scripts/*
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

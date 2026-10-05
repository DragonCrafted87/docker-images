# syntax=docker/dockerfile:1
FROM alpine:3.24

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION
LABEL org.label-schema.build-date=$BUILD_DATE \
      org.label-schema.name="DragonCrafted87 Alpine Minecraft" \
      org.label-schema.description="Alpine Image with OpenJDK to run a minecraft server." \
      org.label-schema.vcs-ref=$VCS_REF \
      org.label-schema.vcs-url="https://github.com/DragonCrafted87/docker-images" \
      org.label-schema.version=$VERSION \
      org.label-schema.schema-version="1.0"

COPY root/. /

RUN <<eot ash
    set -e

    apk upgrade
    apk add --no-cache --update \
        git \
        openjdk17-jre-headless \
        py3-pip \
        python3 \
        tini \
        tzdata

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

ENTRYPOINT ["/scripts/finalize"]

# syntax=docker/dockerfile:1
FROM alpine:3.24

COPY root/. /

RUN <<eot ash
    set -e

    apk upgrade
    apk add --no-cache --update \
        py3-pip \
        python3 \
        tzdata

    chmod +x /docker_service_init
    chmod +x -R /scripts/*
    rm -rf /tmp/*
    rm -rf /var/cache/apk/*
eot

ENV PYTHONPATH=/scripts:/scripts/includes

ENTRYPOINT ["/docker_service_init"]

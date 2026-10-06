# syntax=docker/dockerfile:1
FROM alpine:3.24

COPY root/. /

RUN <<eot ash
    set -e

    apk upgrade
    apk add --no-cache --update \
        tzdata \
        xz

    chmod +x /usr/local/bin/backup
    rm -rf /tmp/*
    rm -rf /var/cache/apk/*
eot

ENTRYPOINT ["/usr/local/bin/backup"]
